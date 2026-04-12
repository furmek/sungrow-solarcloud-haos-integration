"""Data update coordinators for Sungrow integration.

Two independent coordinators run at different intervals:
  - SungrowApiCoordinator: polls iSolarCloud API every ~5 minutes
  - SungrowModbusCoordinator: polls inverter via Modbus every ~30 seconds

The __init__.py merges their data and exposes it to sensor entities.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api_client import APIError, AuthError, ISolarCloudAPI
from .ihm_client import IHMClient, IHMError
from .modbus_client import ModbusError, SungrowModbusClient

_LOGGER = logging.getLogger(__name__)


class SungrowApiCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator that polls the iSolarCloud API."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: ISolarCloudAPI,
        update_interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="Sungrow API",
            update_interval=timedelta(seconds=update_interval),
        )
        self._api = api
        self._last_good_data: dict[str, Any] | None = None
        self._consecutive_errors = 0

    async def _async_update_data(self) -> dict[str, Any]:
        start = time.monotonic()
        try:
            data = await self._api.async_get_data()
        except (AuthError, APIError, Exception) as exc:
            self._consecutive_errors += 1
            label = "Auth" if isinstance(exc, AuthError) else "API"
            if self._consecutive_errors <= 3:
                _LOGGER.warning(
                    "iSolarCloud %s error (%d consecutive): %s",
                    label, self._consecutive_errors, exc,
                )
            elif self._consecutive_errors == 4:
                _LOGGER.error(
                    "iSolarCloud %s failed %d times — suppressing further warnings",
                    label, self._consecutive_errors,
                )

            # Return last good data so sensors stay available with stale values
            if self._last_good_data is not None:
                _LOGGER.debug("Returning last good API data (stale)")
                return self._last_good_data

            raise UpdateFailed(f"{label} error: {exc}") from exc

        if self._consecutive_errors > 0:
            _LOGGER.info(
                "API poll recovered after %d error(s)", self._consecutive_errors
            )
        self._consecutive_errors = 0

        elapsed = time.monotonic() - start

        # Flatten all plant fields into a single dict for easy entity access
        flat: dict[str, Any] = {}
        for plant in data.get("plants", {}).values():
            flat.update(plant.get("fields", {}))

        # Always inject last-poll timestamp into flat dict (datetime object for HA TIMESTAMP class)
        flat["api_last_poll"] = datetime.now(timezone.utc)

        n_fields = len(flat)
        _LOGGER.info(
            "API poll complete in %.1fs — %d plant(s), %d field(s)",
            elapsed,
            len(data.get("plants", {})),
            n_fields,
        )

        # Store both flat fields and raw structure
        result = {
            "flat": flat,
            "raw": data,
        }
        self._last_good_data = result
        return result


class SungrowModbusCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator that polls the inverter via Modbus TCP."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: SungrowModbusClient,
        update_interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="Sungrow Modbus",
            update_interval=timedelta(seconds=update_interval),
        )
        self._client = client
        self._consecutive_errors = 0
        self._last_good_data: dict[str, Any] | None = None

    async def _async_update_data(self) -> dict[str, Any]:
        start = time.monotonic()
        try:
            data = await self._client.async_get_data()
        except (ModbusError, Exception) as exc:
            self._consecutive_errors += 1
            if self._consecutive_errors <= 3:
                _LOGGER.warning(
                    "Modbus poll failed (%d consecutive): %s",
                    self._consecutive_errors, exc,
                )
            elif self._consecutive_errors == 4:
                _LOGGER.error(
                    "Modbus poll failed %d times — suppressing further warnings. "
                    "Check inverter connectivity.",
                    self._consecutive_errors,
                )

            # Return last good data so sensors stay available with stale values
            if self._last_good_data is not None:
                _LOGGER.debug("Returning last good Modbus data (stale)")
                return self._last_good_data

            raise UpdateFailed(f"Modbus error: {exc}") from exc

        if self._consecutive_errors > 0:
            _LOGGER.info(
                "Modbus poll recovered after %d error(s)", self._consecutive_errors
            )
        self._consecutive_errors = 0

        # Inject last-poll timestamp (datetime object for HA TIMESTAMP class)
        data["modbus_last_poll"] = datetime.now(timezone.utc)

        elapsed = time.monotonic() - start
        _LOGGER.debug(
            "Modbus poll complete in %.1fs — %d register(s)",
            elapsed, len(data),
        )

        result = {"flat": data}
        self._last_good_data = result
        return result


class SungrowIHMCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator that polls the iHomeManager via Modbus TCP."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: IHMClient,
        update_interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="Sungrow iHM",
            update_interval=timedelta(seconds=update_interval),
        )
        self._client = client
        self._consecutive_errors = 0
        self._last_good_data: dict[str, Any] | None = None

    async def _async_update_data(self) -> dict[str, Any]:
        start = time.monotonic()
        try:
            data = await self._client.async_get_data()
        except (IHMError, Exception) as exc:
            self._consecutive_errors += 1
            if self._consecutive_errors <= 3:
                _LOGGER.warning(
                    "iHM poll failed (%d consecutive): %s",
                    self._consecutive_errors, exc,
                )
            elif self._consecutive_errors == 4:
                _LOGGER.error(
                    "iHM poll failed %d times — suppressing further warnings. "
                    "Check iHM connectivity.",
                    self._consecutive_errors,
                )

            if self._last_good_data is not None:
                _LOGGER.debug("Returning last good iHM data (stale)")
                return self._last_good_data

            raise UpdateFailed(f"iHM error: {exc}") from exc

        if self._consecutive_errors > 0:
            _LOGGER.info(
                "iHM poll recovered after %d error(s)", self._consecutive_errors
            )
        self._consecutive_errors = 0

        data["ihm_last_poll"] = datetime.now(timezone.utc)

        elapsed = time.monotonic() - start
        _LOGGER.debug(
            "iHM poll complete in %.1fs — %d register(s)",
            elapsed, len(data),
        )

        result = {"flat": data}
        self._last_good_data = result
        return result
