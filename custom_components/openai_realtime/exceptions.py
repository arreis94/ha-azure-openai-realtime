"""Exceptions for OpenAI Realtime integration."""


class OpenAIRealtimeError(Exception):
    """Base exception for OpenAI Realtime."""


class ConnectionError(OpenAIRealtimeError):
    """Connection to OpenAI failed."""


class AuthenticationError(OpenAIRealtimeError):
    """Authentication with OpenAI failed."""


class AudioStreamError(OpenAIRealtimeError):
    """Error with audio streaming."""
