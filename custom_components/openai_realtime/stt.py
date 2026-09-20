"""Support for OpenAI Realtime speech-to-text."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable
import logging

from homeassistant.components.stt import (
    AudioBitRates,
    AudioChannels,
    AudioCodecs,
    AudioFormats,
    AudioSampleRates,
    Provider,
    SpeechMetadata,
    SpeechResult,
    SpeechResultState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import AUDIO_CHANNELS, AUDIO_SAMPLE_RATE, DOMAIN
from .realtime_client import OpenAIRealtimeClient

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(
    hass: HomeAssistant,
    config: dict,
    async_add_entities,
    discovery_info: dict | None = None,
) -> None:
    """Set up OpenAI Realtime STT platform."""
    # For config entry-based setup, we need discovery_info
    if discovery_info is None:
        return
    
    entry_id = discovery_info.get("entry_id")
    if not entry_id or entry_id not in hass.data.get(DOMAIN, {}):
        return
    
    client: OpenAIRealtimeClient = hass.data[DOMAIN][entry_id]["client"]
    async_add_entities([OpenAIRealtimeSTTProvider(client)])


async def async_get_engine(
    hass: HomeAssistant,
    config: dict,
    discovery_info: dict | None = None,
) -> Provider | None:
    """Set up OpenAI Realtime STT provider (legacy method)."""
    # Get the first available entry
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        return None
    
    entry = entries[0]
    if entry.entry_id not in hass.data.get(DOMAIN, {}):
        return None
    
    client: OpenAIRealtimeClient = hass.data[DOMAIN][entry.entry_id]["client"]
    return OpenAIRealtimeSTTProvider(client)


class OpenAIRealtimeSTTProvider(Provider):
    """OpenAI Realtime speech-to-text provider."""

    def __init__(self, client: OpenAIRealtimeClient) -> None:
        """Initialize the provider."""
        self.client = client
        self._transcript_queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._name = "OpenAI Realtime STT"

    @property
    def name(self) -> str:
        """Return the name of the provider."""
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        """Set the name of the provider (Home Assistant may override)."""
        # Keep our custom name even if HA tries to set it to domain name
        if value and not value.startswith("openai_"):
            self._name = value
        # Otherwise keep "OpenAI Realtime STT"

    @property
    def supported_languages(self) -> list[str]:
        """Return a list of supported languages."""
        return ["en", "es", "fr", "de", "it", "pt", "nl", "pl", "ru", "ja", "ko", "zh"]

    @property
    def supported_formats(self) -> list[AudioFormats]:
        """Return a list of supported formats."""
        return [AudioFormats.WAV]

    @property
    def supported_codecs(self) -> list[AudioCodecs]:
        """Return a list of supported codecs."""
        return [AudioCodecs.PCM]

    @property
    def supported_bit_rates(self) -> list[AudioBitRates]:
        """Return a list of supported bitrates."""
        return [AudioBitRates.BITRATE_16]

    @property
    def supported_sample_rates(self) -> list[AudioSampleRates]:
        """Return a list of supported sample rates."""
        # OpenAI Realtime API uses 24kHz internally, but we accept 16kHz and 22kHz
        # Audio will be resampled if needed
        return [AudioSampleRates.SAMPLERATE_16000, AudioSampleRates.SAMPLERATE_22000]

    @property
    def supported_channels(self) -> list[AudioChannels]:
        """Return a list of supported channels."""
        return [AudioChannels.CHANNEL_MONO]

    async def async_process_audio_stream(
        self, metadata: SpeechMetadata, stream: AsyncIterable[bytes]
    ) -> SpeechResult:
        """Process an audio stream to text."""
        
        # Ensure connected
        if not self.client.connected:
            try:
                await self.client.connect()
            except Exception as err:
                _LOGGER.error("Failed to connect to Azure OpenAI: %s", err)
                return SpeechResult(
                    text="",
                    result=SpeechResultState.ERROR,
                )

        # Audio is sent over the WebRTC media track; tell the client the PCM
        # rate HA is delivering so it can be resampled to the track's rate.
        self.client.set_input_sample_rate(int(metadata.sample_rate))

        # Drop any stale signals from a previous request
        while not self._transcript_queue.empty():
            self._transcript_queue.get_nowait()

        # Set up transcript callback
        transcript_parts = []
        
        def transcript_callback(text: str) -> None:
            transcript_parts.append(text)
            self._transcript_queue.put_nowait(text)
        
        def response_done_callback() -> None:
            self._transcript_queue.put_nowait(None)  # Signal completion
        
        self.client.set_transcript_callback(transcript_callback)
        self.client.set_response_done_callback(response_done_callback)

        try:
            # Stream audio to OpenAI
            async for chunk in stream:
                if chunk:
                    await self.client.send_audio(chunk)
            
            # Commit audio buffer to trigger processing
            await self.client.commit_audio()
            
            # Wait for transcript completion
            while True:
                text = await asyncio.wait_for(
                    self._transcript_queue.get(), timeout=30.0
                )
                if text is None:  # Done signal
                    break
            
            full_transcript = "".join(transcript_parts)
            
            return SpeechResult(
                text=full_transcript,
                result=SpeechResultState.SUCCESS,
            )

        except asyncio.TimeoutError:
            _LOGGER.error("Timeout waiting for transcription")
            return SpeechResult(
                text="",
                result=SpeechResultState.ERROR,
            )
        except Exception as err:
            _LOGGER.error("Error processing audio: %s", err)
            return SpeechResult(
                text="",
                result=SpeechResultState.ERROR,
            )
