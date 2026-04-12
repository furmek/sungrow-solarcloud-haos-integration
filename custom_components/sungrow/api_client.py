"""iSolarCloud OAuth2 API client wrapping pysolarcloud.

Handles OAuth2 authorization, token refresh, and data retrieval for
plants and devices from Sungrow's iSolarCloud platform.

Dependencies: pysolarcloud >= 0.4.0 (lazy-imported to avoid hard failure
if pysolarcloud is not installed and user only uses Modbus mode).
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import aiohttp

from .const import DEVICE_TYPE_NAMES, SERVERS

_LOGGER = logging.getLogger(__name__)


class APIError(Exception):
    """Raised when the iSolarCloud API returns an error."""


class AuthError(Exception):
    """Raised on authentication/authorization failure."""


class ISolarCloudAPI:
    """OAuth2 client for iSolarCloud."""

    def __init__(
        self,
        server: str,
        app_key: str,
        app_secret: str,
        application_id: str,
        redirect_uri: str,
        access_token: str | None = None,
        refresh_token: str | None = None,
        token_expires_at: float | None = None,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._server_name = server
        self._server_url = SERVERS.get(server, SERVERS["Europe"])
        self._app_key = app_key
        self._app_secret = app_secret
        self._application_id = application_id
        self._redirect_uri = redirect_uri
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._token_expires_at = int(token_expires_at) if token_expires_at else 0
        self._session = session
        self._auth = None
        self._plants_api = None

    # ------------------------------------------------------------------
    # Lazy initialization (avoids import error if pysolarcloud missing)
    # ------------------------------------------------------------------

    def _ensure_pysolarcloud(self) -> None:
        """Lazy-import pysolarcloud and build Auth + Plants objects."""
        if self._auth is not None:
            return

        try:
            from pysolarcloud import Auth, Server
            from pysolarcloud.plants import Plants
        except ImportError as exc:
            raise APIError(
                "pysolarcloud is not installed. "
                "Install pysolarcloud>=0.4.0 to use iSolarCloud API mode."
            ) from exc

        server_map = {
            "Europe": Server.Europe,
            "China": Server.China,
            "International": Server.International,
            "Australia": Server.Australia,
        }
        server_enum = server_map.get(self._server_name, Server.Europe)

        self._auth = Auth(
            server_enum,
            self._app_key,
            self._app_secret,
            self._application_id,
            websession=self._session,
        )

        # Restore persisted tokens
        if self._access_token and self._refresh_token:
            self._auth.tokens = {
                "access_token": self._access_token,
                "refresh_token": self._refresh_token,
                "expires_at": self._token_expires_at or (int(time.time()) + 3600),
            }
            _LOGGER.debug(
                "Restored OAuth tokens (expires_at=%s)", self._token_expires_at
            )

        self._plants_api = Plants(self._auth)

    # ------------------------------------------------------------------
    # OAuth2 flow
    # ------------------------------------------------------------------

    def get_authorization_url(self) -> str:
        """Get the URL the user must visit to authorize the app."""
        self._ensure_pysolarcloud()
        url = self._auth.auth_url(self._redirect_uri)
        _LOGGER.debug("Generated authorization URL")
        return url

    async def async_authorize_with_code(self, code: str) -> dict[str, Any]:
        """Exchange authorization code for access/refresh tokens."""
        self._ensure_pysolarcloud()
        try:
            await self._auth.async_authorize(code, self._redirect_uri)
        except Exception as exc:
            _LOGGER.error("OAuth authorization failed: %s", exc)
            raise AuthError(f"Authorization failed: {exc}") from exc

        if not self._auth.tokens:
            raise AuthError("Authorization returned no tokens — code may be expired")

        token_data = {
            "access_token": self._auth.tokens.get("access_token"),
            "refresh_token": self._auth.tokens.get("refresh_token"),
            "expires_at": self._auth.tokens.get("expires_at"),
        }
        self._access_token = token_data["access_token"]
        self._refresh_token = token_data["refresh_token"]
        self._token_expires_at = token_data["expires_at"]
        _LOGGER.info("OAuth authorization successful")
        return token_data

    def get_token_data(self) -> dict[str, Any]:
        """Return current token data for config entry persistence."""
        if self._auth and self._auth.tokens:
            return {
                "access_token": self._auth.tokens.get("access_token"),
                "refresh_token": self._auth.tokens.get("refresh_token"),
                "expires_at": self._auth.tokens.get("expires_at"),
            }
        return {
            "access_token": self._access_token,
            "refresh_token": self._refresh_token,
            "expires_at": self._token_expires_at,
        }

    # ------------------------------------------------------------------
    # Data retrieval
    # ------------------------------------------------------------------

    @staticmethod
    def _flatten_realtime(rt_data: dict) -> dict[str, Any]:
        """Flatten pysolarcloud realtime response to {code: value}."""
        flat: dict[str, Any] = {}
        for code, entry in rt_data.items():
            if isinstance(entry, dict):
                value = entry.get("value")
                if value is not None:
                    flat[code] = value
        return flat

    async def async_get_data(self) -> dict[str, Any]:
        """Fetch all plant + device data.

        Returns:
            {
                "plants": {
                    "<ps_id>": {"name": str, "fields": {key: value, ...}},
                },
                "devices": {
                    "<sn>": {"name": str, "model": str, "type": str, "fields": {...}},
                },
                "timestamp": int,
            }
        """
        self._ensure_pysolarcloud()

        all_data: dict[str, Any] = {
            "plants": {},
            "devices": {},
            "timestamp": int(time.time()),
        }

        try:
            plant_list = await self._plants_api.async_get_plants()
        except Exception as exc:
            raise APIError(f"Failed to get plant list: {exc}") from exc

        if not plant_list:
            _LOGGER.warning("No plants found in iSolarCloud account")
            return all_data

        plant_ids = [str(p["ps_id"]) for p in plant_list]
        _LOGGER.debug("Found %d plant(s): %s", len(plant_ids), plant_ids)

        # Fetch details and realtime in parallel
        details_by_id: dict[str, dict] = {}
        realtime: dict[str, dict] = {}

        try:
            detail_result, rt_result = await asyncio.gather(
                self._plants_api.async_get_plant_details(plant_ids),
                self._plants_api.async_get_realtime_data(plant_ids),
                return_exceptions=True,
            )
            if isinstance(detail_result, Exception):
                _LOGGER.warning("Failed to get plant details: %s", detail_result)
            else:
                details_by_id = {str(p["ps_id"]): p for p in (detail_result or [])}

            if isinstance(rt_result, Exception):
                _LOGGER.warning("Failed to get realtime data: %s", rt_result)
            else:
                realtime = rt_result or {}
        except Exception as exc:
            _LOGGER.warning("Error fetching plant data: %s", exc)

        for plant in plant_list:
            ps_id = str(plant["ps_id"])
            ps_name = plant.get("ps_name", f"Plant {ps_id}")

            detail = details_by_id.get(ps_id, {})
            rt_flat = self._flatten_realtime(realtime.get(ps_id, {}))

            # Merge: detail overrides info, realtime overrides both
            merged: dict[str, Any] = {}
            for d in (plant, detail, rt_flat):
                if isinstance(d, dict):
                    for k, v in d.items():
                        if v is not None:
                            merged[k] = v

            all_data["plants"][ps_id] = {
                "name": ps_name,
                "fields": merged,
            }

            # Note: device list (async_get_plant_devices) is skipped during
            # regular polling — we only need plant-level realtime data for sensors.
            # This saves 1 API call per plant per poll cycle.

        _LOGGER.debug(
            "API returned %d plant(s), %d device(s)",
            len(all_data["plants"]),
            len(all_data["devices"]),
        )
        return all_data

    async def async_test_connection(self) -> bool:
        """Test that the credentials work by fetching plant list."""
        try:
            self._ensure_pysolarcloud()
            plants = await self._plants_api.async_get_plants()
            ok = plants is not None
            _LOGGER.debug("API connection test: %s", "OK" if ok else "FAILED")
            return ok
        except Exception as exc:
            _LOGGER.error("API connection test failed: %s", exc)
            return False

    async def async_close(self) -> None:
        """Clean up (pysolarcloud manages its own session)."""
        pass
