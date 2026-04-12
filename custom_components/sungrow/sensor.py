"""Sensor platform for the Sungrow integration.

Creates native HA sensor entities for both API and Modbus data sources.
Each source gets its own HA device for clear separation in the UI.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_IHM_HOST,
    CONF_MODE,
    CONF_MODBUS_HOST,
    CONF_SERVER,
    DOMAIN,
    MODE_API,
    MODE_BOTH,
    MODE_MODBUS,
)
from .coordinator import SungrowApiCoordinator, SungrowIHMCoordinator, SungrowModbusCoordinator
from .sensor_types import (
    API_SENSORS,
    IHM_SENSORS,
    MODBUS_SENSORS,
    SungrowSensorDescription,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Sungrow sensors from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    mode = entry.data.get(CONF_MODE, MODE_BOTH)

    api_coordinator: SungrowApiCoordinator | None = data.get("api_coordinator")
    modbus_coordinator: SungrowModbusCoordinator | None = data.get("modbus_coordinator")
    ihm_coordinator: SungrowIHMCoordinator | None = data.get("ihm_coordinator")

    entities: list[SungrowSensor] = []

    if mode in (MODE_API, MODE_BOTH) and api_coordinator is not None:
        for desc in API_SENSORS:
            entities.append(
                SungrowSensor(
                    coordinator=api_coordinator,
                    description=desc,
                    entry=entry,
                    source="api",
                )
            )
        _LOGGER.debug("Registered %d API sensor entities", len(API_SENSORS))

    if mode in (MODE_MODBUS, MODE_BOTH) and modbus_coordinator is not None:
        for desc in MODBUS_SENSORS:
            entities.append(
                SungrowSensor(
                    coordinator=modbus_coordinator,
                    description=desc,
                    entry=entry,
                    source="modbus",
                )
            )
        _LOGGER.debug("Registered %d Modbus sensor entities", len(MODBUS_SENSORS))

    if ihm_coordinator is not None:
        for desc in IHM_SENSORS:
            entities.append(
                SungrowSensor(
                    coordinator=ihm_coordinator,
                    description=desc,
                    entry=entry,
                    source="ihm",
                )
            )
        _LOGGER.debug("Registered %d iHM sensor entities", len(IHM_SENSORS))

    if entities:
        async_add_entities(entities)
        _LOGGER.info("Added %d Sungrow sensor entities (mode=%s)", len(entities), mode)
    else:
        _LOGGER.warning("No sensor entities created — check configuration mode")


class SungrowSensor(CoordinatorEntity, SensorEntity):
    """A Sungrow sensor entity backed by a coordinator."""

    entity_description: SungrowSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SungrowApiCoordinator | SungrowModbusCoordinator,
        description: SungrowSensorDescription,
        entry: ConfigEntry,
        source: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry
        self._source = source
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info — separate device per source."""
        if self._source == "api":
            return DeviceInfo(
                identifiers={(DOMAIN, f"{self._entry.entry_id}_api")},
                name="Sungrow iSolarCloud",
                manufacturer="Sungrow",
                model=f"iSolarCloud API ({self._entry.data.get(CONF_SERVER, 'Europe')})",
            )
        if self._source == "ihm":
            ihm_host = self._entry.options.get(
                CONF_IHM_HOST, self._entry.data.get(CONF_IHM_HOST, "unknown")
            )
            return DeviceInfo(
                identifiers={(DOMAIN, f"{self._entry.entry_id}_ihm")},
                name="Sungrow iHomeManager",
                manufacturer="Sungrow",
                model=f"iHM @ {ihm_host}",
            )
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry.entry_id}_modbus")},
            name="Sungrow Inverter (Modbus)",
            manufacturer="Sungrow",
            model=f"SH15T @ {self._entry.data.get(CONF_MODBUS_HOST, 'unknown')}",
        )

    @property
    def available(self) -> bool:
        """Entity is available when coordinator has successfully polled."""
        if not self.coordinator.last_update_success:
            return False
        if self.coordinator.data is None:
            return False
        return True

    @property
    def native_value(self) -> Any:
        """Return the sensor value from the coordinator's flat data."""
        if self.coordinator.data is None:
            return None
        flat = self.coordinator.data.get("flat", {})
        value = flat.get(self.entity_description.key)
        if value is None:
            return None
        if self.entity_description.convert is not None:
            value = self.entity_description.convert(value)
        return value
