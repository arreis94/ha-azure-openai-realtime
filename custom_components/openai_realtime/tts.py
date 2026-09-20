"""Support for OpenAI Realtime text-to-speech."""
from __future__ import annotations

import asyncio
import io
import logging
import wave

from homeassistant.components.tts import Provider, Voice, TtsAudioType
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
    """Set up OpenAI Realtime TTS platform."""
    # For config entry-based setup, we need discovery_info
    if discovery_info is None:
        return
    
    entry_id = discovery_info.get("entry_id")
    if not entry_id or entry_id not in hass.data.get(DOMAIN, {}):
        return
    
    client: OpenAIRealtimeClient = hass.data[DOMAIN][entry_id]["client"]
    async_add_entities([OpenAIRealtimeTTSProvider(hass, client)])


async def async_get_engine(
    hass: HomeAssistant,
    config: dict,
    discovery_info: dict | None = None,
) -> Provider | None:
    """Set up OpenAI Realtime TTS provider (legacy method)."""
    # Get the first available entry
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        return None
    
    entry = entries[0]
    if entry.entry_id not in hass.data.get(DOMAIN, {}):
        return None
    
    client: OpenAIRealtimeClient = hass.data[DOMAIN][entry.entry_id]["client"]
    return OpenAIRealtimeTTSProvider(hass, client)


class OpenAIRealtimeTTSProvider(Provider):
    """OpenAI Realtime text-to-speech provider."""

    def __init__(self, hass: HomeAssistant, client: OpenAIRealtimeClient) -> None:
        """Initialize the provider."""
        self.hass = hass
        self.client = client
        self._audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._name = "OpenAI Realtime TTS"

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
        # Otherwise keep "OpenAI Realtime TTS"

    @property
    def supported_languages(self) -> list[str]:
        """Return a list of supported languages."""
        return ["en", "es", "fr", "de", "it", "pt", "nl", "pl", "ru", "ja", "ko", "zh"]

    @property
    def default_language(self) -> str:
        """Return the default language."""
        return "en"

    @property
    def supported_options(self) -> list[str]:
        """Return a list of supported options."""
        return ["voice"]

    async def async_get_supported_voices(self, language: str) -> list[Voice]:
        """Return a list of supported voices for a language."""
        return [
            Voice("alloy", "Alloy"),
            Voice("echo", "Echo"),
            Voice("shimmer", "Shimmer"),
        ]

    def _create_wav_header(self, data_size: int) -> bytes:
        """Create WAV file header."""
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, "wb") as wav_file:
            wav_file.setnchannels(AUDIO_CHANNELS)
            wav_file.setsampwidth(2)  # 16-bit = 2 bytes
            wav_file.setframerate(AUDIO_SAMPLE_RATE)
            wav_file.writeframes(b"\x00" * data_size)
        
        return wav_buffer.getvalue()

    async def async_get_tts_audio(
        self, message: str, language: str, options: dict | None = None
    ) -> TtsAudioType:
        """Convert text to speech."""
        
        # Ensure connected
        if not self.client.connected:
            try:
                await self.client.connect()
            except Exception as err:
                _LOGGER.error("Failed to connect to Azure OpenAI: %s", err)
                return None, None

        # Drop any stale signals from a previous request
        while not self._audio_queue.empty():
            self._audio_queue.get_nowait()

        # Set up audio callback
        audio_chunks = []
        
        def audio_callback(audio_data: bytes) -> None:
            _LOGGER.debug("TTS: Received audio chunk of %d bytes", len(audio_data))
            audio_chunks.append(audio_data)
            self._audio_queue.put_nowait(audio_data)
        
        def audio_done_callback() -> None:
            _LOGGER.info("TTS: Audio complete, collected %d chunks", len(audio_chunks))
            self._audio_queue.put_nowait(None)  # Signal completion
        
        self.client.set_audio_callback(audio_callback)
        # With WebRTC the model audio streams in real time over the media
        # track; output_audio_buffer.stopped (not response.done) marks the
        # end of the audio.
        self.client.set_audio_done_callback(audio_done_callback)

        try:
            # Send text message
            _LOGGER.info("TTS: Sending text message: %s", message)
            await self.client.send_text(message)
            
            # Collect audio chunks
            _LOGGER.debug("TTS: Waiting for audio chunks...")
            while True:
                chunk = await asyncio.wait_for(
                    self._audio_queue.get(), timeout=30.0
                )
                if chunk is None:  # Done signal
                    _LOGGER.debug("TTS: Received completion signal")
                    break
            
            # Combine all audio chunks
            full_audio = b"".join(audio_chunks)
            _LOGGER.info("TTS: Collected %d bytes of audio", len(full_audio))
            
            if not full_audio:
                _LOGGER.error("No audio data received")
                return None, None
            
            # Create WAV file
            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, "wb") as wav_file:
                wav_file.setnchannels(AUDIO_CHANNELS)
                wav_file.setsampwidth(2)  # 16-bit PCM
                wav_file.setframerate(AUDIO_SAMPLE_RATE)
                wav_file.writeframes(full_audio)
            
            return "wav", wav_buffer.getvalue()

        except asyncio.TimeoutError:
            _LOGGER.error("Timeout waiting for audio")
            return None, None
        except Exception as err:
            _LOGGER.error("Error generating speech: %s", err)
            return None, None
