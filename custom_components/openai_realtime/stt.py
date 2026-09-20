"""Support for Azure OpenAI Realtime speech-to-text."""
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
    SpeechMetadata,
    SpeechResult,
    SpeechResultState,
    SpeechToTextEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .realtime_client import OpenAIRealtimeClient

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Azure OpenAI Realtime STT from a config entry."""
    client: OpenAIRealtimeClient = hass.data[DOMAIN][config_entry.entry_id]["client"]
    async_add_entities([OpenAIRealtimeSTTEntity(config_entry, client)])


class OpenAIRealtimeSTTEntity(SpeechToTextEntity):
    """Azure OpenAI Realtime speech-to-text entity."""

    _attr_name = "Azure OpenAI Realtime STT"

    def __init__(self, config_entry: ConfigEntry, client: OpenAIRealtimeClient) -> None:
        """Initialize the entity."""
        self._attr_unique_id = f"{config_entry.entry_id}-stt"
        self.client = client
        self._transcript_queue: asyncio.Queue[str | None] = asyncio.Queue()

    @property
    def supported_languages(self) -> list[str]:
        """Return a list of supported languages."""
        return ["en", "es", "fr", "de", "it", "pt", "nl", "pl", "ru", "ja", "ko", "zh", "hu"]

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
        # Input is resampled to the WebRTC track's 24kHz before transmission
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
            # Stream audio to Azure OpenAI
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
