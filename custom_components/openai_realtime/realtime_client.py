"""Azure OpenAI Realtime API WebRTC client.

Connection flow (GA protocol):
1. POST the session config to /openai/v1/realtime/client_secrets with the
   Azure API key to obtain an ephemeral client secret.
2. Create an aiortc RTCPeerConnection with an outgoing microphone track and
   a "realtime-channel" data channel, then POST the SDP offer to
   /openai/v1/realtime/calls authenticated with the ephemeral secret.
3. Audio flows over the WebRTC media tracks (Opus on the wire); Realtime API
   events flow as JSON over the data channel.
"""
from __future__ import annotations

import asyncio
import fractions
import json
import logging
import time
from typing import Any, Callable

import aiohttp
import av
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import MediaStreamError, MediaStreamTrack

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    AUDIO_SAMPLE_RATE,
    AZURE_CLIENT_SECRETS_PATH,
    AZURE_WEBRTC_CALLS_PATH,
    CONF_ENDPOINT,
    CONF_INSTRUCTIONS,
    CONF_MODEL,
    CONF_VOICE,
    DATA_CHANNEL_NAME,
    DEFAULT_INSTRUCTIONS,
    DEFAULT_MODEL,
    DEFAULT_VOICE,
    EVENT_INPUT_AUDIO_TRANSCRIPTION_COMPLETED,
    EVENT_INPUT_AUDIO_TRANSCRIPTION_FAILED,
    EVENT_OUTPUT_AUDIO_BUFFER_STARTED,
    EVENT_OUTPUT_AUDIO_BUFFER_STOPPED,
    EVENT_RESPONSE_CREATED,
    EVENT_RESPONSE_OUTPUT_ITEM_DONE,
    EVENT_TYPE_CONVERSATION_ITEM_CREATE,
    EVENT_TYPE_INPUT_AUDIO_BUFFER_CLEAR,
    EVENT_TYPE_INPUT_AUDIO_BUFFER_COMMIT,
    EVENT_TYPE_INPUT_AUDIO_BUFFER_SPEECH_STARTED,
    EVENT_TYPE_INPUT_AUDIO_BUFFER_SPEECH_STOPPED,
    EVENT_TYPE_OUTPUT_AUDIO_BUFFER_CLEAR,
    EVENT_TYPE_RESPONSE_AUDIO_TRANSCRIPT_DELTA,
    EVENT_TYPE_RESPONSE_CANCEL,
    EVENT_TYPE_RESPONSE_CREATE,
    EVENT_TYPE_RESPONSE_DONE,
    EVENT_TYPE_RESPONSE_TEXT_DELTA,
    EVENT_TYPE_SESSION_UPDATE,
    INPUT_TRANSCRIPTION_MODEL,
    SESSION_TURN_DETECTION_TYPE,
)
from .exceptions import AuthenticationError, ConnectionError as RealtimeConnectionError

_LOGGER = logging.getLogger(__name__)

# 20 ms frames, the native Opus frame duration
FRAME_DURATION = 0.02
CONNECT_TIMEOUT = 30
DATA_CHANNEL_OPEN_TIMEOUT = 15
DRAIN_TIMEOUT = 60


def frame_to_pcm(frame: av.AudioFrame) -> bytes:
    """Extract the valid PCM16 mono bytes from a frame.

    The plane buffer is larger than the audio it holds (FFmpeg alignment
    padding); reading it whole injects garbage between chunks, which is
    audible as clicks/distortion. Only the first samples * 2 bytes are valid.
    """
    return bytes(frame.planes[0])[: frame.samples * 2]


class MicrophoneStreamTrack(MediaStreamTrack):
    """Outgoing audio track fed with PCM16 mono chunks from Home Assistant.

    Produces paced 20 ms frames; emits silence while no input is buffered so
    the media stream (and server-side VAD) keeps running between requests.

    The frames handed to aiortc always use a fixed sample rate: the Opus
    encoder's internal resampler binds to the first frame's format and raises
    on changes, so input at other rates is resampled here in write().
    """

    kind = "audio"

    def __init__(self, sample_rate: int = AUDIO_SAMPLE_RATE) -> None:
        """Initialize the track."""
        super().__init__()
        self._sample_rate = sample_rate
        self._input_rate = sample_rate
        self._resampler: av.AudioResampler | None = None
        self._input_pts = 0
        self._buffer = bytearray()
        self._drained = asyncio.Event()
        self._drained.set()
        self._timestamp = 0
        self._start: float | None = None

    def set_sample_rate(self, sample_rate: int) -> None:
        """Set the PCM sample rate of subsequent write() calls."""
        if sample_rate == self._input_rate:
            return
        _LOGGER.debug("Input sample rate set to %d Hz", sample_rate)
        self._input_rate = sample_rate
        # PyAV resamplers bind to the input format on first use
        self._resampler = None
        self._input_pts = 0

    def write(self, data: bytes) -> None:
        """Queue PCM16 mono audio for transmission."""
        if not data:
            return
        if self._input_rate != self._sample_rate:
            data = self._resample(data)
        self._buffer.extend(data)
        if self._buffer:
            self._drained.clear()

    def _resample(self, data: bytes) -> bytes:
        """Resample PCM16 mono input to the track's fixed sample rate."""
        if self._resampler is None:
            self._resampler = av.AudioResampler(
                format="s16", layout="mono", rate=self._sample_rate
            )
        samples = len(data) // 2
        frame = av.AudioFrame(format="s16", layout="mono", samples=samples)
        frame.planes[0].update(data[: samples * 2])
        frame.sample_rate = self._input_rate
        frame.pts = self._input_pts
        frame.time_base = fractions.Fraction(1, self._input_rate)
        self._input_pts += samples

        out = bytearray()
        resampled = self._resampler.resample(frame)
        if not isinstance(resampled, list):
            resampled = [resampled]
        for out_frame in resampled:
            if out_frame is not None:
                out.extend(frame_to_pcm(out_frame))
        return bytes(out)

    async def wait_drained(self, timeout: float = DRAIN_TIMEOUT) -> None:
        """Wait until all queued audio has been transmitted."""
        await asyncio.wait_for(self._drained.wait(), timeout=timeout)

    async def recv(self) -> av.AudioFrame:
        """Return the next 20 ms audio frame, real-time paced."""
        if self.readyState != "live":
            raise MediaStreamError

        samples = int(self._sample_rate * FRAME_DURATION)
        frame_bytes = samples * 2  # 16-bit mono

        if self._start is None:
            self._start = time.monotonic()
        else:
            wait = (
                self._start
                + (self._timestamp / self._sample_rate)
                - time.monotonic()
            )
            if wait > 0:
                await asyncio.sleep(wait)

        if len(self._buffer) >= frame_bytes:
            chunk = bytes(self._buffer[:frame_bytes])
            del self._buffer[:frame_bytes]
        elif self._buffer:
            # Trailing partial frame: pad with silence
            chunk = bytes(self._buffer).ljust(frame_bytes, b"\x00")
            self._buffer.clear()
        else:
            chunk = b"\x00" * frame_bytes
        if not self._buffer:
            self._drained.set()

        frame = av.AudioFrame(format="s16", layout="mono", samples=samples)
        frame.planes[0].update(chunk)
        frame.sample_rate = self._sample_rate
        frame.pts = self._timestamp
        frame.time_base = fractions.Fraction(1, self._sample_rate)
        self._timestamp += samples
        return frame


class OpenAIRealtimeClient:
    """WebRTC client for the Azure OpenAI Realtime API."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize the client."""
        self.hass = hass
        self.config_entry = config_entry
        self._pc: RTCPeerConnection | None = None
        self._channel: Any = None
        self._channel_open = asyncio.Event()
        self._mic_track: MicrophoneStreamTrack | None = None
        self._audio_receiver_task: asyncio.Task | None = None
        self._connected = False
        self._call_id: str | None = None

        self._audio_callback: Callable[[bytes], None] | None = None
        self._audio_done_callback: Callable[[], None] | None = None
        self._transcript_callback: Callable[[str], None] | None = None
        self._input_transcript_callback: Callable[[str], None] | None = None
        self._function_call_callback: Callable[[dict[str, Any]], None] | None = None
        self._response_done_callback: Callable[[], None] | None = None
        self._speech_started_callback: Callable[[], None] | None = None
        self._speech_stopped_callback: Callable[[], None] | None = None

        self._is_speaking = False
        self._has_active_response = False
        self._output_audio_active = False

    @property
    def connected(self) -> bool:
        """Return if connected with an open data channel."""
        return (
            self._connected
            and self._channel is not None
            and self._channel.readyState == "open"
        )

    async def connect(self) -> None:
        """Establish the WebRTC session with Azure OpenAI."""
        if self.connected:
            return
        # Drop any half-open previous session before reconnecting
        await self.disconnect()

        endpoint = self.config_entry.data[CONF_ENDPOINT].rstrip("/")
        api_key = self.config_entry.data[CONF_API_KEY]

        try:
            ephemeral_key = await self._create_client_secret(endpoint, api_key)

            pc = RTCPeerConnection()
            self._pc = pc
            self._channel_open = asyncio.Event()

            self._mic_track = MicrophoneStreamTrack()
            pc.addTrack(self._mic_track)

            @pc.on("track")
            def on_track(track: MediaStreamTrack) -> None:
                if track.kind == "audio":
                    _LOGGER.debug("Remote audio track received")
                    self._audio_receiver_task = asyncio.create_task(
                        self._consume_remote_audio(track)
                    )

            @pc.on("connectionstatechange")
            def on_connection_state_change() -> None:
                _LOGGER.debug("WebRTC connection state: %s", pc.connectionState)
                if pc.connectionState in ("failed", "closed"):
                    self._connected = False

            channel = pc.createDataChannel(DATA_CHANNEL_NAME)
            self._channel = channel

            @channel.on("open")
            def on_open() -> None:
                _LOGGER.debug("Data channel open")
                self._channel_open.set()

            @channel.on("message")
            def on_message(message: str) -> None:
                self._handle_event(message)

            @channel.on("close")
            def on_close() -> None:
                _LOGGER.debug("Data channel closed")
                self._connected = False

            offer = await pc.createOffer()
            await pc.setLocalDescription(offer)

            answer_sdp = await self._exchange_sdp(
                endpoint, ephemeral_key, pc.localDescription.sdp
            )
            await pc.setRemoteDescription(
                RTCSessionDescription(sdp=answer_sdp, type="answer")
            )

            await asyncio.wait_for(
                self._channel_open.wait(), timeout=DATA_CHANNEL_OPEN_TIMEOUT
            )
            self._connected = True
            _LOGGER.info(
                "Connected to Azure OpenAI Realtime API via WebRTC (call %s)",
                self._call_id,
            )

        except Exception as err:
            _LOGGER.error("Failed to connect to Azure OpenAI Realtime API: %s", err)
            await self.disconnect()
            raise

    async def _create_client_secret(self, endpoint: str, api_key: str) -> str:
        """Request an ephemeral client secret, applying the session config."""
        options = self.config_entry.options
        session_config = {
            "session": {
                "type": "realtime",
                "model": options.get(CONF_MODEL, DEFAULT_MODEL),
                "instructions": options.get(CONF_INSTRUCTIONS, DEFAULT_INSTRUCTIONS),
                "audio": {
                    "input": {
                        # STT results come from server-side transcription of
                        # the user's speech, not from a model response
                        "transcription": {"model": INPUT_TRANSCRIPTION_MODEL},
                        # The conversation agent triggers responses
                        # explicitly; VAD must not auto-respond during STT
                        "turn_detection": {
                            "type": SESSION_TURN_DETECTION_TYPE,
                            "create_response": False,
                        },
                    },
                    "output": {
                        "voice": options.get(CONF_VOICE, DEFAULT_VOICE),
                    },
                },
            },
        }

        session = async_get_clientsession(self.hass)
        url = f"{endpoint}{AZURE_CLIENT_SECRETS_PATH}"
        _LOGGER.debug("Requesting ephemeral client secret: %s", url)
        response = await session.post(
            url,
            json=session_config,
            headers={"api-key": api_key},
            timeout=aiohttp.ClientTimeout(total=CONNECT_TIMEOUT),
        )
        if response.status in (401, 403):
            body = await response.text()
            raise AuthenticationError(
                f"Authentication failed ({response.status}): {body}"
            )
        if response.status != 200:
            body = await response.text()
            raise RealtimeConnectionError(
                f"Failed to create client secret ({response.status}): {body}"
            )

        data = await response.json()
        ephemeral_key = data.get("value")
        if not ephemeral_key:
            raise RealtimeConnectionError(
                f"No ephemeral client secret in response: {data}"
            )
        return ephemeral_key

    async def _exchange_sdp(
        self, endpoint: str, ephemeral_key: str, offer_sdp: str
    ) -> str:
        """POST the SDP offer and return the SDP answer."""
        session = async_get_clientsession(self.hass)
        url = f"{endpoint}{AZURE_WEBRTC_CALLS_PATH}"
        _LOGGER.debug("Sending SDP offer: %s", url)
        response = await session.post(
            url,
            data=offer_sdp,
            headers={
                "Authorization": f"Bearer {ephemeral_key}",
                "Content-Type": "application/sdp",
            },
            timeout=aiohttp.ClientTimeout(total=CONNECT_TIMEOUT),
        )
        if response.status not in (200, 201):
            body = await response.text()
            raise RealtimeConnectionError(
                f"SDP exchange failed ({response.status}): {body}"
            )

        location = response.headers.get("Location", "")
        self._call_id = location.rsplit("/", 1)[-1] if location else None
        return await response.text()

    async def disconnect(self) -> None:
        """Tear down the WebRTC session."""
        self._connected = False

        if self._audio_receiver_task:
            self._audio_receiver_task.cancel()
            try:
                await self._audio_receiver_task
            except (asyncio.CancelledError, Exception):
                pass
            self._audio_receiver_task = None

        if self._mic_track:
            self._mic_track.stop()
            self._mic_track = None

        if self._channel:
            self._channel.close()
            self._channel = None

        if self._pc:
            await self._pc.close()
            self._pc = None
            _LOGGER.info("Disconnected from Azure OpenAI Realtime API")

        self._channel_open = asyncio.Event()
        self._call_id = None
        self._has_active_response = False
        self._output_audio_active = False

    async def _consume_remote_audio(self, track: MediaStreamTrack) -> None:
        """Read the model's audio track and forward PCM16/24kHz mono chunks."""
        resampler = av.AudioResampler(
            format="s16", layout="mono", rate=AUDIO_SAMPLE_RATE
        )
        try:
            while True:
                frame = await track.recv()
                # The remote track streams continuously (silence between
                # responses); only forward audio while a response is playing.
                if not self._output_audio_active or not self._audio_callback:
                    continue
                resampled = resampler.resample(frame)
                if not isinstance(resampled, list):
                    resampled = [resampled]
                for out_frame in resampled:
                    if out_frame is None:
                        continue
                    self._audio_callback(frame_to_pcm(out_frame))
        except MediaStreamError:
            _LOGGER.debug("Remote audio track ended")
        except asyncio.CancelledError:
            raise
        except Exception as err:
            _LOGGER.error("Error reading remote audio: %s", err)

    def _send_event(self, event: dict[str, Any]) -> None:
        """Send an event over the data channel."""
        if not self._channel or self._channel.readyState != "open":
            _LOGGER.error("Data channel not open, cannot send %s", event.get("type"))
            return
        try:
            self._channel.send(json.dumps(event))
            _LOGGER.debug("Sent event: %s", event.get("type"))
        except Exception as err:
            _LOGGER.error("Error sending event: %s", err)

    def _handle_event(self, message: str) -> None:
        """Handle an incoming data channel event."""
        try:
            data = json.loads(message)
        except json.JSONDecodeError as err:
            _LOGGER.error("Failed to decode data channel message: %s", err)
            return
        if not isinstance(data, dict):
            _LOGGER.warning("Unexpected data channel message: %s", message)
            return

        try:
            event_type = data.get("type")
            _LOGGER.debug("Received event: %s", event_type)

            if event_type == EVENT_RESPONSE_CREATED:
                self._has_active_response = True

            elif event_type == EVENT_OUTPUT_AUDIO_BUFFER_STARTED:
                # Model audio playout started on the media track
                self._output_audio_active = True

            elif event_type == EVENT_OUTPUT_AUDIO_BUFFER_STOPPED:
                self._output_audio_active = False
                if self._audio_done_callback:
                    self._audio_done_callback()

            elif event_type == EVENT_TYPE_RESPONSE_AUDIO_TRANSCRIPT_DELTA:
                transcript = data.get("delta", "")
                if transcript and self._transcript_callback:
                    self._transcript_callback(transcript)

            elif event_type == EVENT_TYPE_RESPONSE_TEXT_DELTA:
                # Text-modality responses deliver text deltas instead of an
                # audio transcript
                text = data.get("delta", "")
                if text and self._transcript_callback:
                    self._transcript_callback(text)

            elif event_type == EVENT_INPUT_AUDIO_TRANSCRIPTION_COMPLETED:
                # Server-side transcription of what the user said (STT)
                transcript = data.get("transcript", "")
                _LOGGER.debug("Input transcription completed: %s", transcript)
                if self._input_transcript_callback:
                    self._input_transcript_callback(transcript)

            elif event_type == EVENT_INPUT_AUDIO_TRANSCRIPTION_FAILED:
                _LOGGER.error(
                    "Input transcription failed: %s", data.get("error", {})
                )
                if self._input_transcript_callback:
                    self._input_transcript_callback("")

            elif event_type == EVENT_RESPONSE_OUTPUT_ITEM_DONE:
                # The model requested a function/tool call
                item = data.get("item") or {}
                if (
                    item.get("type") == "function_call"
                    and self._function_call_callback
                ):
                    _LOGGER.debug(
                        "Function call requested: %s(%s)",
                        item.get("name"),
                        item.get("arguments"),
                    )
                    self._function_call_callback(
                        {
                            "name": item.get("name"),
                            "call_id": item.get("call_id"),
                            "arguments": item.get("arguments"),
                        }
                    )

            elif event_type == EVENT_TYPE_RESPONSE_DONE:
                self._has_active_response = False
                if self._response_done_callback:
                    self._response_done_callback()
                # Text-only or failed responses never start audio playout;
                # release audio waiters in that case.
                if not self._output_audio_active and self._audio_done_callback:
                    self._audio_done_callback()

            elif event_type == EVENT_TYPE_INPUT_AUDIO_BUFFER_SPEECH_STARTED:
                _LOGGER.debug("User started speaking")
                self._is_speaking = True
                if self._speech_started_callback:
                    self._speech_started_callback()
                if self._has_active_response or self._output_audio_active:
                    _LOGGER.debug("Cancelling active response (barge-in)")
                    self._cancel_response_events()

            elif event_type == EVENT_TYPE_INPUT_AUDIO_BUFFER_SPEECH_STOPPED:
                _LOGGER.debug("User stopped speaking")
                self._is_speaking = False
                if self._speech_stopped_callback:
                    self._speech_stopped_callback()

            elif event_type == "error":
                error = data.get("error", {})
                error_code = error.get("code")
                if error_code in (
                    "response_cancel_not_active",
                    "conversation_already_has_active_response",
                    "input_audio_buffer_commit_empty",
                ):
                    _LOGGER.debug("Azure OpenAI API notice: %s", error.get("message"))
                else:
                    _LOGGER.error("Azure OpenAI API error: %s", error)

        except Exception as err:
            _LOGGER.error("Error handling event: %s", err)

    def set_input_sample_rate(self, sample_rate: int) -> None:
        """Set the PCM sample rate of the audio passed to send_audio."""
        if self._mic_track:
            self._mic_track.set_sample_rate(sample_rate)

    async def send_audio(self, audio_data: bytes) -> None:
        """Queue microphone audio for transmission over the media track."""
        if not self.connected or not self._mic_track:
            _LOGGER.warning("Cannot send audio: not connected")
            return
        self._mic_track.write(audio_data)

    async def commit_audio(self) -> None:
        """Commit the input audio buffer so it gets transcribed.

        Does NOT request a model response: STT only needs the input
        transcription; responses are created by the conversation agent
        (send_text) or TTS (send_tts_text).
        """
        if not self.connected:
            return

        # The media track transmits in real time; wait for the queued audio
        # to actually reach the server before committing.
        if self._mic_track:
            try:
                await self._mic_track.wait_drained()
            except asyncio.TimeoutError:
                _LOGGER.warning("Timed out draining microphone audio")

        self._send_event({"type": EVENT_TYPE_INPUT_AUDIO_BUFFER_COMMIT})

    def _cancel_response_events(self) -> None:
        """Send the events that stop the current response and its audio."""
        if self._has_active_response:
            self._send_event({"type": EVENT_TYPE_RESPONSE_CANCEL})
            self._has_active_response = False
        # Stop the audio already buffered for playout on the media track
        self._send_event({"type": EVENT_TYPE_OUTPUT_AUDIO_BUFFER_CLEAR})
        self._send_event({"type": EVENT_TYPE_INPUT_AUDIO_BUFFER_CLEAR})

    async def cancel_response(self) -> None:
        """Cancel the current AI response (for interruption)."""
        if not self.connected:
            return
        self._cancel_response_events()

    async def update_session(self, session: dict[str, Any]) -> None:
        """Update the live session config (instructions, tools, ...)."""
        if not self.connected:
            return
        self._send_event(
            {
                "type": EVENT_TYPE_SESSION_UPDATE,
                "session": {"type": "realtime", **session},
            }
        )

    async def create_response(self) -> None:
        """Request a model response for the current conversation state."""
        if not self.connected:
            return
        self._send_event({"type": EVENT_TYPE_RESPONSE_CREATE})
        self._has_active_response = True

    async def send_function_result(self, call_id: str, output: str) -> None:
        """Send the result of a function/tool call back to the model."""
        if not self.connected:
            _LOGGER.warning("Cannot send function result: not connected")
            return
        self._send_event(
            {
                "type": EVENT_TYPE_CONVERSATION_ITEM_CREATE,
                "item": {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": output,
                },
            }
        )

    async def send_text(self, text: str) -> None:
        """Send a text message to the conversation and request a response."""
        if not self.connected:
            _LOGGER.warning("Cannot send text: not connected")
            return

        self._send_event(
            {
                "type": EVENT_TYPE_CONVERSATION_ITEM_CREATE,
                "item": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": text}],
                },
            }
        )

        if not self._has_active_response:
            self._send_event({"type": EVENT_TYPE_RESPONSE_CREATE})
            self._has_active_response = True

    async def send_tts_text(self, text: str) -> None:
        """Speak the given text verbatim (for TTS).

        Uses an out-of-band response (conversation: "none") so the spoken
        text neither responds to nor pollutes the conversation history.
        """
        if not self.connected:
            _LOGGER.warning("Cannot send TTS text: not connected")
            return

        self._send_event(
            {
                "type": EVENT_TYPE_RESPONSE_CREATE,
                "response": {
                    "conversation": "none",
                    "output_modalities": ["audio"],
                    "tool_choice": "none",
                    "instructions": (
                        "Repeat the following message verbatim, exactly as "
                        "written, in the same language, without adding, "
                        "changing or omitting anything:\n\n" + text
                    ),
                },
            }
        )
        self._has_active_response = True

    def set_audio_callback(self, callback: Callable[[bytes], None]) -> None:
        """Set callback for received audio."""
        self._audio_callback = callback

    def set_audio_done_callback(self, callback: Callable[[], None]) -> None:
        """Set callback for completion of the response audio playout."""
        self._audio_done_callback = callback

    def set_transcript_callback(self, callback: Callable[[str], None]) -> None:
        """Set callback for received transcript."""
        self._transcript_callback = callback

    def set_input_transcript_callback(self, callback: Callable[[str], None]) -> None:
        """Set callback for the transcription of the user's speech (STT)."""
        self._input_transcript_callback = callback

    def set_function_call_callback(
        self, callback: Callable[[dict[str, Any]], None]
    ) -> None:
        """Set callback for function/tool call requests from the model."""
        self._function_call_callback = callback

    def set_response_done_callback(self, callback: Callable[[], None]) -> None:
        """Set callback for response completion."""
        self._response_done_callback = callback

    def set_speech_started_callback(self, callback: Callable[[], None]) -> None:
        """Set callback for when user starts speaking."""
        self._speech_started_callback = callback

    def set_speech_stopped_callback(self, callback: Callable[[], None]) -> None:
        """Set callback for when user stops speaking."""
        self._speech_stopped_callback = callback
