"""Config flow for Sungrow integration.

Supports three setup modes:
  1. API only    — iSolarCloud OAuth2 credentials
  2. Modbus only — inverter IP, port, optional SSL
  3. Both        — API + Modbus (recommended)

The flow adapts its steps based on the chosen mode:
  Mode selection → [API credentials → OAuth authorize] → [Modbus settings] → Done
"""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api_client import APIError, AuthError, ISolarCloudAPI
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_API_ENABLED,
    CONF_API_SCAN_INTERVAL,
    CONF_APP_KEY,
    CONF_APP_SECRET,
    CONF_APPLICATION_ID,
    CONF_AUTH_CODE,
    CONF_IHM_ENABLED,
    CONF_IHM_HOST,
    CONF_IHM_PORT,
    CONF_IHM_SCAN_INTERVAL,
    CONF_IHM_SLAVE_ID,
    CONF_MODBUS_ENABLED,
    CONF_MODE,
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
    CONNECTION_TCP,
    DEFAULT_API_SCAN_INTERVAL,
    DEFAULT_IHM_PORT,
    DEFAULT_IHM_SCAN_INTERVAL,
    DEFAULT_IHM_SLAVE_ID,
    DEFAULT_MODBUS_PORT_TCP,
    DEFAULT_MODBUS_SCAN_INTERVAL,
    DEFAULT_MODBUS_SLAVE_ID,
    DEFAULT_SERVER,
    DOMAIN,
    MODE_API,
    MODE_BOTH,
    MODE_MODBUS,
    MODBUS_CONNECTIONS,
    SERVERS,
)
from .ihm_client import IHMClient
from .modbus_client import ModbusError, SungrowModbusClient

_LOGGER = logging.getLogger(__name__)

MODE_OPTIONS = {
    MODE_BOTH: "Both — API + Modbus (recommended)",
    MODE_API: "API only — iSolarCloud cloud",
    MODE_MODBUS: "Modbus only — local inverter",
}


class SungrowConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Sungrow integration."""

    VERSION = 1

    def __init__(self) -> None:
        self._mode: str = MODE_BOTH
        self._api_data: dict[str, Any] = {}
        self._modbus_data: dict[str, Any] = {}
        self._ihm_data: dict[str, Any] = {}
        self._token_data: dict[str, Any] = {}
        self._auth_url: str = ""
        self._api: ISolarCloudAPI | None = None

    # ------------------------------------------------------------------
    # Step 1: Choose connection mode
    # ------------------------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 1: Choose connection mode."""
        if user_input is not None:
            self._mode = user_input[CONF_MODE]
            _LOGGER.debug("User selected mode: %s", self._mode)

            if self._mode in (MODE_API, MODE_BOTH):
                return await self.async_step_api_credentials()
            else:
                return await self.async_step_modbus()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_MODE, default=MODE_BOTH): vol.In(MODE_OPTIONS),
            }),
        )

    # ------------------------------------------------------------------
    # Step 2a: API credentials
    # ------------------------------------------------------------------

    async def async_step_api_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Collect iSolarCloud OAuth2 app credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._api_data = user_input
            try:
                session = async_get_clientsession(self.hass)
                self._api = ISolarCloudAPI(
                    server=user_input[CONF_SERVER],
                    app_key=user_input[CONF_APP_KEY],
                    app_secret=user_input[CONF_APP_SECRET],
                    application_id=user_input[CONF_APPLICATION_ID],
                    redirect_uri=user_input[CONF_REDIRECT_URI],
                    session=session,
                )
                self._auth_url = self._api.get_authorization_url()
                _LOGGER.debug("Generated OAuth authorization URL")
                return await self.async_step_api_authorize()
            except APIError as exc:
                _LOGGER.error("Failed to build auth URL: %s", exc)
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error building auth URL")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="api_credentials",
            data_schema=vol.Schema({
                vol.Required(CONF_SERVER, default=DEFAULT_SERVER): vol.In(
                    list(SERVERS.keys())
                ),
                vol.Required(CONF_APP_KEY): str,
                vol.Required(CONF_APP_SECRET): str,
                vol.Required(CONF_APPLICATION_ID): str,
                vol.Required(
                    CONF_REDIRECT_URI,
                    default="http://homeassistant.local:8123/auth/external/callback",
                ): str,
                vol.Optional(
                    CONF_API_SCAN_INTERVAL, default=DEFAULT_API_SCAN_INTERVAL
                ): vol.All(int, vol.Range(min=60, max=3600)),
            }),
            errors=errors,
            description_placeholders={
                "portal_url": "https://developer-api.isolarcloud.com/",
            },
        )

    # ------------------------------------------------------------------
    # Step 2b: OAuth authorization
    # ------------------------------------------------------------------

    async def async_step_api_authorize(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """User authorizes via OAuth URL and pastes the code."""
        errors: dict[str, str] = {}

        if user_input is not None and user_input.get(CONF_AUTH_CODE):
            code = user_input[CONF_AUTH_CODE].strip()
            try:
                self._token_data = await self._api.async_authorize_with_code(code)
                ok = await self._api.async_test_connection()
                if ok:
                    _LOGGER.info("OAuth authorization successful")
                    if self._mode == MODE_BOTH:
                        return await self.async_step_modbus()
                    else:
                        return await self._create_entry()
                else:
                    errors["base"] = "invalid_auth"
            except AuthError as exc:
                _LOGGER.error("Authorization failed: %s", exc)
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected error during OAuth authorization")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="api_authorize",
            data_schema=vol.Schema({
                vol.Required(CONF_AUTH_CODE): str,
            }),
            errors=errors,
            description_placeholders={
                "auth_url": self._auth_url,
            },
        )

    # ------------------------------------------------------------------
    # Step 3: Modbus settings
    # ------------------------------------------------------------------

    async def async_step_modbus(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Configure Modbus connection to the inverter."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._modbus_data = user_input

            # Test connection if host provided
            host = user_input.get(CONF_MODBUS_HOST, "")
            if host:
                _LOGGER.debug("Testing Modbus connection to %s", host)
                client = SungrowModbusClient(
                    host=host,
                    connection=user_input.get(CONF_MODBUS_CONNECTION, CONNECTION_TCP),
                    port=user_input.get(CONF_MODBUS_PORT, DEFAULT_MODBUS_PORT_TCP),
                    slave_id=user_input.get(CONF_MODBUS_SLAVE_ID, DEFAULT_MODBUS_SLAVE_ID),
                    use_ssl=user_input.get(CONF_MODBUS_USE_SSL, False),
                    verify_ssl=user_input.get(CONF_MODBUS_VERIFY_SSL, False),
                    ssl_certfile=user_input.get(CONF_MODBUS_SSL_CERTFILE) or None,
                    username=user_input.get(CONF_MODBUS_USERNAME) or None,
                    password=user_input.get(CONF_MODBUS_PASSWORD) or None,
                )
                ok, msg = await client.async_test_connection()
                if ok:
                    _LOGGER.info("Modbus test: %s", msg)
                    return await self.async_step_ihm()
                else:
                    _LOGGER.warning("Modbus test failed: %s", msg)
                    errors["base"] = "cannot_connect"
            else:
                errors[CONF_MODBUS_HOST] = "missing_host"

        return self.async_show_form(
            step_id="modbus",
            data_schema=vol.Schema({
                vol.Required(CONF_MODBUS_HOST): str,
                vol.Optional(
                    CONF_MODBUS_CONNECTION, default=CONNECTION_TCP
                ): vol.In(MODBUS_CONNECTIONS),
                vol.Optional(
                    CONF_MODBUS_PORT, default=DEFAULT_MODBUS_PORT_TCP
                ): vol.All(int, vol.Range(min=1, max=65535)),
                vol.Optional(
                    CONF_MODBUS_SLAVE_ID, default=DEFAULT_MODBUS_SLAVE_ID
                ): vol.All(int, vol.Range(min=1, max=247)),
                vol.Optional(CONF_MODBUS_USERNAME, default=""): str,
                vol.Optional(CONF_MODBUS_PASSWORD, default=""): str,
                vol.Optional(CONF_MODBUS_USE_SSL, default=False): bool,
                vol.Optional(CONF_MODBUS_VERIFY_SSL, default=False): bool,
                vol.Optional(CONF_MODBUS_SSL_CERTFILE, default=""): str,
                vol.Optional(
                    CONF_MODBUS_SCAN_INTERVAL, default=DEFAULT_MODBUS_SCAN_INTERVAL
                ): vol.All(int, vol.Range(min=10, max=300)),
            }),
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Step 4: iHomeManager (optional)
    # ------------------------------------------------------------------

    async def async_step_ihm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Configure optional iHomeManager connection."""
        errors: dict[str, str] = {}

        if user_input is not None:
            if user_input.get(CONF_IHM_ENABLED):
                host = user_input.get(CONF_IHM_HOST, "")
                if host:
                    _LOGGER.debug("Testing iHM connection to %s", host)
                    client = IHMClient(
                        host=host,
                        port=user_input.get(CONF_IHM_PORT, DEFAULT_IHM_PORT),
                        slave_id=user_input.get(CONF_IHM_SLAVE_ID, DEFAULT_IHM_SLAVE_ID),
                    )
                    ok, msg = await client.async_test_connection()
                    if ok:
                        _LOGGER.info("iHM test: %s", msg)
                        self._ihm_data = user_input
                        return await self._create_entry()
                    else:
                        _LOGGER.warning("iHM test failed: %s", msg)
                        errors["base"] = "cannot_connect"
                else:
                    errors[CONF_IHM_HOST] = "missing_host"
            else:
                # iHM not enabled — skip
                self._ihm_data = user_input
                return await self._create_entry()

        return self.async_show_form(
            step_id="ihm",
            data_schema=vol.Schema({
                vol.Optional(CONF_IHM_ENABLED, default=False): bool,
                vol.Optional(CONF_IHM_HOST, default=""): str,
                vol.Optional(
                    CONF_IHM_PORT, default=DEFAULT_IHM_PORT
                ): vol.All(int, vol.Range(min=1, max=65535)),
                vol.Optional(
                    CONF_IHM_SLAVE_ID, default=DEFAULT_IHM_SLAVE_ID
                ): vol.All(int, vol.Range(min=1, max=247)),
                vol.Optional(
                    CONF_IHM_SCAN_INTERVAL, default=DEFAULT_IHM_SCAN_INTERVAL
                ): vol.All(int, vol.Range(min=10, max=300)),
            }),
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Create entry
    # ------------------------------------------------------------------

    async def _create_entry(self) -> config_entries.ConfigFlowResult:
        """Merge all collected data and create the config entry."""
        data: dict[str, Any] = {CONF_MODE: self._mode}

        # API data
        if self._api_data:
            data.update(self._api_data)
            data[CONF_ACCESS_TOKEN] = self._token_data.get("access_token")
            data[CONF_REFRESH_TOKEN] = self._token_data.get("refresh_token")
            data[CONF_TOKEN_EXPIRES_AT] = self._token_data.get("expires_at")

        # Modbus data
        if self._modbus_data:
            data.update(self._modbus_data)

        # iHM data
        if self._ihm_data:
            data.update(self._ihm_data)

        # Generate unique ID
        if self._mode in (MODE_API, MODE_BOTH):
            unique = f"sungrow_{data.get(CONF_APP_KEY, 'unknown')}"
        else:
            unique = f"sungrow_mb_{data.get(CONF_MODBUS_HOST, 'unknown')}"

        await self.async_set_unique_id(unique)
        self._abort_if_unique_id_configured()

        # Build title
        parts = []
        if self._mode in (MODE_API, MODE_BOTH):
            parts.append(data.get(CONF_SERVER, "API"))
        if self._mode in (MODE_MODBUS, MODE_BOTH):
            parts.append(data.get(CONF_MODBUS_HOST, "Modbus"))
        title = f"Sungrow ({' + '.join(parts)})"

        _LOGGER.info("Creating config entry: %s (mode=%s)", title, self._mode)
        return self.async_create_entry(title=title, data=data)

    # ------------------------------------------------------------------
    # Options flow
    # ------------------------------------------------------------------

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> SungrowOptionsFlow:
        return SungrowOptionsFlow()


class SungrowOptionsFlow(config_entries.OptionsFlow):
    """Options flow to adjust scan intervals and Modbus settings."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        mode = self.config_entry.data.get(CONF_MODE, MODE_BOTH)

        def cur(key: str, default: Any) -> Any:
            return self.config_entry.options.get(
                key, self.config_entry.data.get(key, default)
            )

        schema_dict: dict[Any, Any] = {}

        # API toggle — only show if initial setup included API credentials
        if mode in (MODE_API, MODE_BOTH):
            schema_dict[vol.Optional(
                CONF_API_ENABLED,
                default=cur(CONF_API_ENABLED, True),
            )] = bool
            schema_dict[vol.Optional(
                CONF_API_SCAN_INTERVAL,
                default=cur(CONF_API_SCAN_INTERVAL, DEFAULT_API_SCAN_INTERVAL),
            )] = vol.All(int, vol.Range(min=60, max=3600))

        # Modbus toggle — only show if initial setup included Modbus
        if mode in (MODE_MODBUS, MODE_BOTH):
            schema_dict[vol.Optional(
                CONF_MODBUS_ENABLED,
                default=cur(CONF_MODBUS_ENABLED, True),
            )] = bool
            schema_dict[vol.Optional(
                CONF_MODBUS_SCAN_INTERVAL,
                default=cur(CONF_MODBUS_SCAN_INTERVAL, DEFAULT_MODBUS_SCAN_INTERVAL),
            )] = vol.All(int, vol.Range(min=10, max=300))
            schema_dict[vol.Optional(
                CONF_MODBUS_USE_SSL,
                default=cur(CONF_MODBUS_USE_SSL, False),
            )] = bool
            schema_dict[vol.Optional(
                CONF_MODBUS_VERIFY_SSL,
                default=cur(CONF_MODBUS_VERIFY_SSL, False),
            )] = bool
            schema_dict[vol.Optional(
                CONF_MODBUS_SSL_CERTFILE,
                default=cur(CONF_MODBUS_SSL_CERTFILE, ""),
            )] = str

        # iHM settings — always shown in options (can be enabled later)
        schema_dict[vol.Optional(
            CONF_IHM_ENABLED,
            default=cur(CONF_IHM_ENABLED, False),
        )] = bool
        schema_dict[vol.Optional(
            CONF_IHM_HOST,
            default=cur(CONF_IHM_HOST, ""),
        )] = str
        schema_dict[vol.Optional(
            CONF_IHM_PORT,
            default=cur(CONF_IHM_PORT, DEFAULT_IHM_PORT),
        )] = vol.All(int, vol.Range(min=1, max=65535))
        schema_dict[vol.Optional(
            CONF_IHM_SLAVE_ID,
            default=cur(CONF_IHM_SLAVE_ID, DEFAULT_IHM_SLAVE_ID),
        )] = vol.All(int, vol.Range(min=1, max=247))
        schema_dict[vol.Optional(
            CONF_IHM_SCAN_INTERVAL,
            default=cur(CONF_IHM_SCAN_INTERVAL, DEFAULT_IHM_SCAN_INTERVAL),
        )] = vol.All(int, vol.Range(min=10, max=300))

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema_dict),
        )
