"""Support for the Azure OpenAI Realtime conversation agent."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Literal

from homeassistant.components import conversation
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import MATCH_ALL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import intent, llm
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_INSTRUCTIONS, DEFAULT_INSTRUCTIONS, DOMAIN
from .realtime_client import OpenAIRealtimeClient

_LOGGER = logging.getLogger(__name__)

RESPONSE_TIMEOUT = 60.0
MAX_TOOL_ITERATIONS = 5

try:
    from voluptuous_openapi import convert as _convert_schema
except ImportError:  # future HA versions migrate to probatio
    from probatio import to_openapi as _convert_schema


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Azure OpenAI Realtime conversation agent from a config entry."""
    client: OpenAIRealtimeClient = hass.data[DOMAIN][config_entry.entry_id]["client"]
    async_add_entities([OpenAIRealtimeConversationEntity(config_entry, client)])


def _serialize_tool_result(result: Any) -> str:
    """Serialize a tool result to a JSON string for the model."""
    if isinstance(result, (dict, list, str, int, float, bool)) or result is None:
        return json.dumps(result, default=str)
    # Newer HA versions wrap results in a ToolResult-like object
    for attr in ("data", "result", "content"):
        if hasattr(result, attr):
            return json.dumps(getattr(result, attr), default=str)
    return json.dumps(str(result))


class OpenAIRealtimeConversationEntity(conversation.ConversationEntity):
    """Azure OpenAI Realtime conversation agent.

    Sends the user's text into the realtime session and returns the model's
    reply. Home Assistant control is provided through the Assist LLM API:
    its tools are registered on the realtime session and function calls are
    routed back to HA. Conversation history lives server-side in the realtime
    session, so multi-turn context is kept while the WebRTC call is up.
    """

    _attr_name = "Azure OpenAI Realtime"
    _attr_supported_features = conversation.ConversationEntityFeature.CONTROL

    def __init__(self, config_entry: ConfigEntry, client: OpenAIRealtimeClient) -> None:
        """Initialize the entity."""
        self._attr_unique_id = f"{config_entry.entry_id}-conversation"
        self.config_entry = config_entry
        self.client = client
        self._done_queue: asyncio.Queue[None] = asyncio.Queue()

    @property
    def supported_languages(self) -> list[str] | Literal["*"]:
        """Return a list of supported languages."""
        return MATCH_ALL

    async def _async_prepare_llm_api(
        self, user_input: conversation.ConversationInput
    ) -> llm.APIInstance | None:
        """Fetch the Assist LLM API and register its tools on the session."""
        llm_context = llm.LLMContext(
            platform=DOMAIN,
            context=user_input.context,
            language=user_input.language,
            assistant=conversation.DOMAIN,
            device_id=user_input.device_id,
        )
        try:
            llm_api = await llm.async_get_api(
                self.hass, llm.LLM_API_ASSIST, llm_context
            )
        except HomeAssistantError as err:
            _LOGGER.warning(
                "Assist LLM API unavailable, continuing without HA control: %s", err
            )
            return None

        tools: list[dict[str, Any]] = []
        for tool in llm_api.tools:
            try:
                parameters = _convert_schema(
                    tool.parameters, custom_serializer=llm_api.custom_serializer
                )
            except Exception as err:
                _LOGGER.warning(
                    "Skipping tool %s (unserializable parameters): %s",
                    tool.name,
                    err,
                )
                continue
            tools.append(
                {
                    "type": "function",
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": parameters,
                }
            )

        instructions = self.config_entry.options.get(
            CONF_INSTRUCTIONS, DEFAULT_INSTRUCTIONS
        )
        await self.client.update_session(
            {
                "instructions": f"{instructions}\n\n{llm_api.api_prompt}",
                "tools": tools,
                "tool_choice": "auto",
            }
        )
        _LOGGER.debug("Registered %d Assist tools on the session", len(tools))
        return llm_api

    async def _async_run_tool(
        self, llm_api: llm.APIInstance | None, call: dict[str, Any]
    ) -> str:
        """Execute one tool call and return the serialized result."""
        if llm_api is None:
            return json.dumps({"error": "Home Assistant control is unavailable"})
        try:
            tool_args = json.loads(call.get("arguments") or "{}")
        except json.JSONDecodeError as err:
            return json.dumps({"error": f"Invalid tool arguments: {err}"})
        try:
            result = await llm_api.async_call_tool(
                llm.ToolInput(tool_name=call["name"], tool_args=tool_args)
            )
        except Exception as err:
            _LOGGER.warning("Tool %s failed: %s", call.get("name"), err)
            return json.dumps({"error": str(err)})
        return _serialize_tool_result(result)

    async def async_process(
        self, user_input: conversation.ConversationInput
    ) -> conversation.ConversationResult:
        """Process a sentence and return the model's reply."""
        intent_response = intent.IntentResponse(language=user_input.language)

        # Ensure connected
        if not self.client.connected:
            try:
                await self.client.connect()
            except Exception as err:
                _LOGGER.error("Failed to connect to Azure OpenAI: %s", err)
                intent_response.async_set_error(
                    intent.IntentResponseErrorCode.UNKNOWN,
                    f"Failed to connect to Azure OpenAI: {err}",
                )
                return conversation.ConversationResult(
                    response=intent_response,
                    conversation_id=user_input.conversation_id,
                )

        llm_api = await self._async_prepare_llm_api(user_input)

        # Drop any stale signals from a previous request
        while not self._done_queue.empty():
            self._done_queue.get_nowait()

        reply_parts: list[str] = []
        pending_calls: list[dict[str, Any]] = []

        self.client.set_transcript_callback(reply_parts.append)
        self.client.set_function_call_callback(pending_calls.append)
        self.client.set_response_done_callback(
            lambda: self._done_queue.put_nowait(None)
        )

        try:
            _LOGGER.debug("Conversation: sending user text: %s", user_input.text)
            await self.client.send_text(user_input.text)

            for _ in range(MAX_TOOL_ITERATIONS):
                await asyncio.wait_for(
                    self._done_queue.get(), timeout=RESPONSE_TIMEOUT
                )
                if not pending_calls:
                    break

                # Execute the requested tools, return the results, and ask
                # the model to continue.
                calls = pending_calls.copy()
                pending_calls.clear()
                reply_parts.clear()
                for call in calls:
                    output = await self._async_run_tool(llm_api, call)
                    _LOGGER.debug(
                        "Tool %s result: %s", call.get("name"), output
                    )
                    await self.client.send_function_result(
                        call.get("call_id", ""), output
                    )
                await self.client.create_response()
            else:
                _LOGGER.warning(
                    "Stopped after %d tool iterations", MAX_TOOL_ITERATIONS
                )

            reply = "".join(reply_parts).strip()
            _LOGGER.debug("Conversation: model reply: %s", reply)

            if not reply:
                intent_response.async_set_error(
                    intent.IntentResponseErrorCode.UNKNOWN,
                    "The model returned an empty response",
                )
            else:
                intent_response.async_set_speech(reply)

        except asyncio.TimeoutError:
            _LOGGER.error("Timeout waiting for the model's response")
            intent_response.async_set_error(
                intent.IntentResponseErrorCode.UNKNOWN,
                "Timeout waiting for the model's response",
            )
        except Exception as err:
            _LOGGER.error("Error processing conversation: %s", err)
            intent_response.async_set_error(
                intent.IntentResponseErrorCode.UNKNOWN,
                f"Error talking to Azure OpenAI: {err}",
            )

        return conversation.ConversationResult(
            response=intent_response,
            conversation_id=user_input.conversation_id,
        )
