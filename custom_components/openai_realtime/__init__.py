"""The Azure OpenAI Realtime Voice Assistant integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_ENDPOINT, DOMAIN
from .realtime_client import OpenAIRealtimeClient

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.CONVERSATION, Platform.STT, Platform.TTS]


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old config entries.

    Version 1 entries targeted the OpenAI WebSocket API and have no Azure
    endpoint, so they can't be migrated automatically - the integration must
    be removed and set up again with the Azure resource details.
    """
    if entry.version == 1:
        _LOGGER.error(
            "Config entry %s was created for the OpenAI WebSocket API and "
            "cannot be migrated to Azure OpenAI WebRTC. Remove the "
            "integration and set it up again with your Azure OpenAI "
            "endpoint, API key and model deployment name",
            entry.title,
        )
        return False
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Azure OpenAI Realtime Voice Assistant from a config entry."""
    if CONF_ENDPOINT not in entry.data:
        _LOGGER.error(
            "Config entry is missing the Azure OpenAI endpoint; remove and "
            "re-add the integration"
        )
        return False

    hass.data.setdefault(DOMAIN, {})

    client = OpenAIRealtimeClient(hass, entry)
    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id)
        client: OpenAIRealtimeClient = data["client"]
        await client.disconnect()

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
