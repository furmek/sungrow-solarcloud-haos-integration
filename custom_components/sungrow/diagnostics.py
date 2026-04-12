"""Diagnostics support for Sungrow integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ACCESS_TOKEN,
    CONF_APP_SECRET,
    CONF_REFRESH_TOKEN,
    CONF_TOKEN_EXPIRES_AT,
    DOMAIN,
)

REDACT_KEYS = {
    CONF_APP_SECRET,
    CONF_ACCESS_TOKEN,
    CONF_REFRESH_TOKEN,
    CONF_TOKEN_EXPIRES_AT,
    "password",
    "app_secret",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})

    diag: dict[str, Any] = {
        "config_entry": async_redact_data(dict(entry.data), REDACT_KEYS),
        "options": async_redact_data(dict(entry.options), REDACT_KEYS),
    }

    # API coordinator state
    api_coord = data.get("api_coordinator")
    if api_coord is not None:
        api_data = api_coord.data or {}
        diag["api"] = {
            "last_update_success": api_coord.last_update_success,
            "last_exception": str(api_coord.last_exception) if api_coord.last_exception else None,
            "field_count": len(api_data.get("flat", {})),
            "plant_count": len(api_data.get("raw", {}).get("plants", {})),
            "device_count": len(api_data.get("raw", {}).get("devices", {})),
        }

    # Modbus coordinator state
    modbus_coord = data.get("modbus_coordinator")
    if modbus_coord is not None:
        mb_data = modbus_coord.data or {}
        diag["modbus"] = {
            "last_update_success": modbus_coord.last_update_success,
            "last_exception": str(modbus_coord.last_exception) if modbus_coord.last_exception else None,
            "register_count": len(mb_data.get("flat", {})),
        }

    # iHM coordinator state
    ihm_coord = data.get("ihm_coordinator")
    if ihm_coord is not None:
        ihm_data = ihm_coord.data or {}
        diag["ihm"] = {
            "last_update_success": ihm_coord.last_update_success,
            "last_exception": str(ihm_coord.last_exception) if ihm_coord.last_exception else None,
            "register_count": len(ihm_data.get("flat", {})),
        }

    return diag
