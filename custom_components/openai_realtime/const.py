"""Constants for the Azure OpenAI Realtime integration."""

DOMAIN = "openai_realtime"

# Configuration keys
CONF_API_KEY = "api_key"
CONF_ENDPOINT = "endpoint"
CONF_MODEL = "model"  # Azure model deployment name
CONF_VOICE = "voice"
CONF_INSTRUCTIONS = "instructions"
CONF_LANGUAGE = "language"
CONF_MODALITIES = "modalities"

# Default values
DEFAULT_MODEL = "gpt-realtime"
DEFAULT_VOICE = "alloy"
DEFAULT_INSTRUCTIONS = (
    "You are a helpful voice assistant integrated with Home Assistant. "
    "You can help users control their smart home devices and answer questions. "
    "Be concise and natural in your responses."
)
DEFAULT_LANGUAGE = "en"
DEFAULT_MODALITIES = ["text", "audio"]

SUPPORTED_VOICES = [
    "alloy",
    "ash",
    "ballad",
    "cedar",
    "coral",
    "echo",
    "marin",
    "sage",
    "shimmer",
    "verse",
]

SUPPORTED_LANGUAGES = {
    "en": "English",
    "hu": "Hungarian"
}

SUPPORTED_MODALITIES = ["text", "audio"]

# Azure OpenAI GA Realtime API (WebRTC) paths, relative to the resource
# endpoint (https://<resource>.openai.azure.com)
AZURE_CLIENT_SECRETS_PATH = "/openai/v1/realtime/client_secrets"
AZURE_WEBRTC_CALLS_PATH = "/openai/v1/realtime/calls"

# Audio Configuration (PCM exchanged with Home Assistant; WebRTC media is
# Opus on the wire, resampled at the edges)
AUDIO_FORMAT = "pcm16"
AUDIO_SAMPLE_RATE = 24000
AUDIO_CHANNELS = 1

# WebRTC data channel name for Realtime API events
DATA_CHANNEL_NAME = "realtime-channel"

# Session Configuration
SESSION_TURN_DETECTION_TYPE = "semantic_vad"

# WebSocket Events - Outgoing (sent over the WebRTC data channel)
EVENT_TYPE_SESSION_UPDATE = "session.update"
EVENT_TYPE_INPUT_AUDIO_BUFFER_COMMIT = "input_audio_buffer.commit"
EVENT_TYPE_INPUT_AUDIO_BUFFER_CLEAR = "input_audio_buffer.clear"
EVENT_TYPE_OUTPUT_AUDIO_BUFFER_CLEAR = "output_audio_buffer.clear"
EVENT_TYPE_RESPONSE_CREATE = "response.create"
EVENT_TYPE_RESPONSE_CANCEL = "response.cancel"
EVENT_TYPE_CONVERSATION_ITEM_CREATE = "conversation.item.create"

# WebSocket Events - Incoming (received over the WebRTC data channel)
EVENT_SESSION_CREATED = "session.created"
EVENT_SESSION_UPDATED = "session.updated"
EVENT_INPUT_AUDIO_BUFFER_COMMITTED = "input_audio_buffer.committed"
EVENT_INPUT_AUDIO_BUFFER_CLEARED = "input_audio_buffer.cleared"
EVENT_RESPONSE_CREATED = "response.created"
EVENT_TYPE_RESPONSE_DONE = "response.done"
EVENT_TYPE_RESPONSE_AUDIO_TRANSCRIPT_DELTA = "response.output_audio_transcript.delta"
EVENT_RESPONSE_AUDIO_TRANSCRIPT_DONE = "response.output_audio_transcript.done"
EVENT_TYPE_RESPONSE_TEXT_DELTA = "response.output_text.delta"
EVENT_TYPE_INPUT_AUDIO_BUFFER_SPEECH_STARTED = "input_audio_buffer.speech_started"
EVENT_TYPE_INPUT_AUDIO_BUFFER_SPEECH_STOPPED = "input_audio_buffer.speech_stopped"
# WebRTC-specific: playout of the response audio track started/stopped
EVENT_OUTPUT_AUDIO_BUFFER_STARTED = "output_audio_buffer.started"
EVENT_OUTPUT_AUDIO_BUFFER_STOPPED = "output_audio_buffer.stopped"
EVENT_ERROR = "error"

# Error codes
ERROR_INVALID_API_KEY = "invalid_api_key"
ERROR_CONNECTION_FAILED = "connection_failed"
ERROR_AUDIO_PROCESSING = "audio_processing_error"
ERROR_UNKNOWN = "unknown_error"
