"""Config flow for Azure OpenAI Realtime integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_API_KEY,
    CONF_ENDPOINT,
    CONF_INSTRUCTIONS,
    CONF_LANGUAGE,
    CONF_MODEL,
    CONF_VOICE,
    DEFAULT_INSTRUCTIONS,
    DEFAULT_LANGUAGE,
    DEFAULT_MODEL,
    DEFAULT_VOICE,
    DOMAIN,
    SUPPORTED_LANGUAGES,
    SUPPORTED_VOICES,
)

_LOGGER = logging.getLogger(__name__)


def normalize_endpoint(value: str) -> str:
    """Normalize the Azure endpoint input to a full base URL.

    Accepts a bare resource name ("myresource"), a host
    ("myresource.openai.azure.com") or a full URL.
    """
    value = value.strip().rstrip("/")
    if not value:
        return ""
    if not value.startswith(("http://", "https://")):
        if "." not in value:
            value = f"{value}.openai.azure.com"
        value = f"https://{value}"
    return value


class OpenAIRealtimeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Azure OpenAI Realtime."""

    VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            endpoint = normalize_endpoint(user_input[CONF_ENDPOINT])

            if not endpoint:
                errors[CONF_ENDPOINT] = "invalid_endpoint"
            elif not api_key:
                errors[CONF_API_KEY] = "invalid_api_key"
            else:
                return self.async_create_entry(
                    title="Azure OpenAI Realtime",
                    data={
                        CONF_API_KEY: api_key,
                        CONF_ENDPOINT: endpoint,
                    },
                    options={
                        CONF_MODEL: user_input.get(CONF_MODEL, DEFAULT_MODEL),
                        CONF_VOICE: user_input.get(CONF_VOICE, DEFAULT_VOICE),
                        CONF_INSTRUCTIONS: user_input.get(
                            CONF_INSTRUCTIONS, DEFAULT_INSTRUCTIONS
                        ),
                        CONF_LANGUAGE: user_input.get(CONF_LANGUAGE, DEFAULT_LANGUAGE),
                    },
                )

        data_schema = vol.Schema(
            {
                vol.Required(CONF_ENDPOINT): str,
                vol.Required(CONF_API_KEY): str,
                vol.Optional(CONF_MODEL, default=DEFAULT_MODEL): str,
                vol.Optional(CONF_VOICE, default=DEFAULT_VOICE): vol.In(
                    SUPPORTED_VOICES
                ),
                vol.Optional(
                    CONF_INSTRUCTIONS, default=DEFAULT_INSTRUCTIONS
                ): str,
                vol.Optional(CONF_LANGUAGE, default=DEFAULT_LANGUAGE): vol.In(
                    SUPPORTED_LANGUAGES
                ),
            }
        )

        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OptionsFlowHandler:
        """Get the options flow for this handler."""
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Azure OpenAI Realtime."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        # Don't set self.config_entry explicitly - it's handled by parent class
        super().__init__()

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        # Get current options with defaults
        current_options = self.config_entry.options

        data_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_MODEL,
                    default=current_options.get(CONF_MODEL, DEFAULT_MODEL),
                ): str,
                vol.Optional(
                    CONF_VOICE,
                    default=current_options.get(CONF_VOICE, DEFAULT_VOICE),
                ): vol.In(SUPPORTED_VOICES),
                vol.Optional(
                    CONF_INSTRUCTIONS,
                    default=current_options.get(CONF_INSTRUCTIONS, DEFAULT_INSTRUCTIONS),
                ): str,
                vol.Optional(
                    CONF_LANGUAGE,
                    default=current_options.get(CONF_LANGUAGE, DEFAULT_LANGUAGE),
                ): vol.In(SUPPORTED_LANGUAGES),
            }
        )

        return self.async_show_form(step_id="init", data_schema=data_schema)
