"""Sungrow Inverter integration for Home Assistant.

Supports three connection modes:
  - api:    iSolarCloud OAuth2 API only (cloud, ~5 min latency)
  - modbus: Direct Modbus TCP only (local, ~30s, supports SSL/TLS)
  - both:   API + Modbus combined (recommended — best of both worlds)

Data from both sources is exposed as native HA sensor entities.
No MQTT broker required.
"""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api_client import ISolarCloudAPI
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_API_ENABLED,
    CONF_API_SCAN_INTERVAL,
    CONF_APP_KEY,
    CONF_APP_SECRET,
    CONF_APPLICATION_ID,
    CONF_IHM_ENABLED,
    CONF_IHM_HOST,
    CONF_IHM_PORT,
    CONF_IHM_SCAN_INTERVAL,
    CONF_IHM_SLAVE_ID,
    CONF_MODE,
    CONF_MODBUS_ENABLED,
    CONF_MODBUS_CONNECTION,
    CONF_MODBUS_HOST,
    CONF_MODBUS_PORT,
    CONF_MODBUS_SCAN_INTERVAL,
    CONF_MODBUS_SLAVE_ID,
    CONF_MODBUS_PASSWORD,
    CONF_MODBUS_SSL_CERTFILE,
    CONF_MODBUS_USE_SSL,
    CONF_MODBUS_USERNAME,
    CONF_MODBUS_VERIFY_SSL,
    CONF_REDIRECT_URI,
    CONF_REFRESH_TOKEN,
    CONF_SERVER,
    CONF_TOKEN_EXPIRES_AT,
    DEFAULT_API_SCAN_INTERVAL,
    DEFAULT_IHM_PORT,
    DEFAULT_IHM_SCAN_INTERVAL,
    DEFAULT_IHM_SLAVE_ID,
    DEFAULT_MODBUS_PORT_TCP,
    DEFAULT_MODBUS_SCAN_INTERVAL,
    DEFAULT_MODBUS_SLAVE_ID,
    DOMAIN,
    MODE_API,
    MODE_BOTH,
    MODE_MODBUS,
    PLATFORMS,
)
from .coordinator import SungrowApiCoordinator, SungrowIHMCoordinator, SungrowModbusCoordinator
from .ihm_client import IHMClient
from .modbus_client import SungrowModbusClient

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Sungrow from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    mode = entry.data.get(CONF_MODE, MODE_BOTH)
    entry_data: dict[str, Any] = {}

    _LOGGER.info("Setting up Sungrow integration (mode=%s)", mode)

    # ---- API coordinator ----
    api_enabled = entry.options.get(CONF_API_ENABLED, True)
    if mode in (MODE_API, MODE_BOTH) and api_enabled:
        # Force IPv4 to avoid "Network unreachable" on broken IPv6 setups
        connector = aiohttp.TCPConnector(family=2)  # 2 = AF_INET (IPv4 only)
        session = async_get_clientsession(hass)
        try:
            # Try to create an IPv4-only session; fall back to default if it fails
            ipv4_session = aiohttp.ClientSession(connector=connector)
        except Exception:
            ipv4_session = session
        api = ISolarCloudAPI(
            server=entry.data[CONF_SERVER],
            app_key=entry.data[CONF_APP_KEY],
            app_secret=entry.data[CONF_APP_SECRET],
            application_id=entry.data[CONF_APPLICATION_ID],
            redirect_uri=entry.data[CONF_REDIRECT_URI],
            access_token=entry.data.get(CONF_ACCESS_TOKEN),
            refresh_token=entry.data.get(CONF_REFRESH_TOKEN),
            token_expires_at=entry.data.get(CONF_TOKEN_EXPIRES_AT),
            session=ipv4_session,
        )
        api_interval = entry.options.get(
            CONF_API_SCAN_INTERVAL,
            entry.data.get(CONF_API_SCAN_INTERVAL, DEFAULT_API_SCAN_INTERVAL),
        )
        api_coordinator = SungrowApiCoordinator(hass, api, api_interval)
        await api_coordinator.async_config_entry_first_refresh()
        entry_data["api"] = api
        entry_data["api_coordinator"] = api_coordinator
        entry_data["ipv4_session"] = ipv4_session
        _LOGGER.info(
            "API coordinator started (server=%s, interval=%ds)",
            entry.data[CONF_SERVER], api_interval,
        )

    # ---- Modbus coordinator ----
    modbus_enabled = entry.options.get(CONF_MODBUS_ENABLED, True)
    if mode in (MODE_MODBUS, MODE_BOTH) and modbus_enabled:
        modbus_host = entry.data.get(CONF_MODBUS_HOST, "")
        if not modbus_host:
            _LOGGER.error("Modbus mode enabled but no host configured")
        else:
            modbus_client = SungrowModbusClient(
                host=modbus_host,
                connection=entry.data.get(CONF_MODBUS_CONNECTION, "tcp"),
                port=entry.data.get(CONF_MODBUS_PORT, DEFAULT_MODBUS_PORT_TCP),
                slave_id=entry.data.get(CONF_MODBUS_SLAVE_ID, DEFAULT_MODBUS_SLAVE_ID),
                use_ssl=entry.data.get(CONF_MODBUS_USE_SSL, False),
                verify_ssl=entry.data.get(CONF_MODBUS_VERIFY_SSL, False),
                ssl_certfile=entry.data.get(CONF_MODBUS_SSL_CERTFILE),
                username=entry.data.get(CONF_MODBUS_USERNAME) or None,
                password=entry.data.get(CONF_MODBUS_PASSWORD) or None,
            )
            modbus_interval = entry.options.get(
                CONF_MODBUS_SCAN_INTERVAL,
                entry.data.get(CONF_MODBUS_SCAN_INTERVAL, DEFAULT_MODBUS_SCAN_INTERVAL),
            )
            modbus_coordinator = SungrowModbusCoordinator(
                hass, modbus_client, modbus_interval
            )
            await modbus_coordinator.async_config_entry_first_refresh()
            entry_data["modbus_client"] = modbus_client
            entry_data["modbus_coordinator"] = modbus_coordinator
            _LOGGER.info(
                "Modbus coordinator started (host=%s, port=%s, ssl=%s, interval=%ds)",
                modbus_host,
                entry.data.get(CONF_MODBUS_PORT, DEFAULT_MODBUS_PORT_TCP),
                entry.data.get(CONF_MODBUS_USE_SSL, False),
                modbus_interval,
            )

    # ---- iHomeManager coordinator (optional, non-fatal) ----
    def _ihm_enabled() -> bool:
        return (
            entry.options.get(CONF_IHM_ENABLED, entry.data.get(CONF_IHM_ENABLED, False))
            and entry.options.get(CONF_IHM_HOST, entry.data.get(CONF_IHM_HOST, ""))
        )

    if _ihm_enabled():
        ihm_host = entry.options.get(CONF_IHM_HOST, entry.data.get(CONF_IHM_HOST, ""))
        ihm_port = entry.options.get(CONF_IHM_PORT, entry.data.get(CONF_IHM_PORT, DEFAULT_IHM_PORT))
        ihm_slave = entry.options.get(CONF_IHM_SLAVE_ID, entry.data.get(CONF_IHM_SLAVE_ID, DEFAULT_IHM_SLAVE_ID))
        ihm_interval = entry.options.get(
            CONF_IHM_SCAN_INTERVAL,
            entry.data.get(CONF_IHM_SCAN_INTERVAL, DEFAULT_IHM_SCAN_INTERVAL),
        )

        ihm_client = IHMClient(
            host=ihm_host,
            port=ihm_port,
            slave_id=ihm_slave,
        )
        ihm_coordinator = SungrowIHMCoordinator(hass, ihm_client, ihm_interval)
        try:
            await ihm_coordinator.async_config_entry_first_refresh()
        except Exception as exc:
            # iHM failure is non-fatal — log and continue without iHM data
            _LOGGER.warning("iHM initial poll failed (non-fatal): %s", exc)

        entry_data["ihm_client"] = ihm_client
        entry_data["ihm_coordinator"] = ihm_coordinator
        _LOGGER.info(
            "iHM coordinator started (host=%s, port=%s, slave=%d, interval=%ds)",
            ihm_host, ihm_port, ihm_slave, ihm_interval,
        )

    # Register a no-op listener on each coordinator BEFORE forwarding to
    # the sensor platform.  The coordinator's periodic scheduler only runs
    # while at least one listener is subscribed.  Without this, there is a
    # race: first_refresh succeeds, but the scheduler hasn't started yet
    # because entity setup (which adds real listeners) happens later in
    # async_forward_entry_setups.  The dummy listener guarantees the
    # scheduler is alive from the start and keeps running even if entity
    # setup is delayed.
    @callback
    def _noop() -> None:
        """Keep coordinator scheduler alive."""

    for coord_key in ("api_coordinator", "modbus_coordinator", "ihm_coordinator"):
        coord = entry_data.get(coord_key)
        if coord is not None:
            entry.async_on_unload(coord.async_add_listener(_noop))
            _LOGGER.debug("Registered keepalive listener on %s", coord_key)

    hass.data[DOMAIN][entry.entry_id] = entry_data

    # Forward to sensor platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Persist refreshed OAuth tokens on HA shutdown (not during polling —
    # that would trigger the update listener and cause a reload loop).
    if "api" in entry_data:
        async def _persist_tokens_on_stop(event: Event) -> None:
            """Save refreshed tokens to config entry on shutdown."""
            api_obj: ISolarCloudAPI = entry_data["api"]
            tokens = api_obj.get_token_data()
            if tokens.get("access_token"):
                new_data = dict(entry.data)
                new_data[CONF_ACCESS_TOKEN] = tokens["access_token"]
                new_data[CONF_REFRESH_TOKEN] = tokens.get("refresh_token", "")
                new_data[CONF_TOKEN_EXPIRES_AT] = tokens.get("expires_at", 0)
                hass.config_entries.async_update_entry(entry, data=new_data)
                _LOGGER.info("Persisted refreshed OAuth tokens on shutdown")

        entry.async_on_unload(
            hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _persist_tokens_on_stop)
        )

    # Reload on options change
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    _LOGGER.info("Sungrow integration setup complete (mode=%s)", mode)
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload integration when options change."""
    _LOGGER.debug("Options updated, reloading Sungrow integration")
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id, {})
        api = data.get("api")
        if api:
            await api.async_close()
        # Close our IPv4-only session if we created one
        ipv4_sess = data.get("ipv4_session")
        if ipv4_sess and not ipv4_sess.closed:
            await ipv4_sess.close()
        _LOGGER.info("Sungrow integration unloaded")
    return unload_ok
