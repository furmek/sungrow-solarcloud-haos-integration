"""Sensor type definitions for API and Modbus data points.

Each SungrowSensorDescription defines how a raw data field maps to a
Home Assistant sensor entity: name, unit, device class, state class,
data source, and optional value conversion.

Source precedence for overlapping values:
  - Real-time power → prefer Modbus (live, <30s)
  - Cumulative energy → prefer API (server-side calculation, higher accuracy)
  - Battery SOC → prefer Modbus when available, API fallback
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
    PERCENTAGE,
)


# Source constants
SOURCE_API = "api"
SOURCE_MODBUS = "modbus"
SOURCE_IHM = "ihm"
SOURCE_BOTH = "both"  # available from both, entity picks freshest


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------

def _wh_to_kwh(v: Any) -> Any:
    """Convert Wh to kWh."""
    try:
        return round(float(v) / 1000.0, 3)
    except (TypeError, ValueError):
        return v


def _ratio_to_percent(v: Any) -> Any:
    """Convert 0-1 ratio to 0-100 percentage."""
    try:
        return round(float(v) * 100.0, 2)
    except (TypeError, ValueError):
        return v



# ---------------------------------------------------------------------------
# Extended sensor description
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True)
class SungrowSensorDescription(SensorEntityDescription):
    """Extended sensor description with source and conversion info."""

    source: str = SOURCE_API
    convert: Callable[[Any], Any] | None = None
    # For "both" source sensors: which key to look up in each source
    api_key: str | None = None
    modbus_key: str | None = None


# ---------------------------------------------------------------------------
# API-only sensors (iSolarCloud)
# ---------------------------------------------------------------------------

API_SENSORS: tuple[SungrowSensorDescription, ...] = (
    # --- Power (instantaneous) ---
    SungrowSensorDescription(
        key="power",
        name="PV Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_API,
    ),
    SungrowSensorDescription(
        key="load_power",
        name="Load Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_API,
    ),
    SungrowSensorDescription(
        key="total_active_power_of_pv",
        name="Total PV Active Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_API,
    ),
    SungrowSensorDescription(
        key="pcs_total_active_power",
        name="Inverter Total Active Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_API,
    ),
    SungrowSensorDescription(
        key="grid_active_power",
        name="Grid Active Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_API,
    ),
    SungrowSensorDescription(
        key="total_field_energy_storage_active_power",
        name="Battery Active Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_API,
    ),
    SungrowSensorDescription(
        key="meter_ac_power",
        name="Meter AC Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_API,
    ),
    SungrowSensorDescription(
        key="inverter_ac_power",
        name="Inverter AC Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_API,
    ),

    # --- Energy (cumulative, source Wh → converted to kWh) ---
    SungrowSensorDescription(
        key="daily_yield",
        name="Daily PV Yield",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        source=SOURCE_API,
        convert=_wh_to_kwh,
    ),
    SungrowSensorDescription(
        key="total_yield",
        name="Total PV Yield",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        source=SOURCE_API,
        convert=_wh_to_kwh,
    ),
    SungrowSensorDescription(
        key="energy_purchased_today",
        name="Grid Import Today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        source=SOURCE_API,
        convert=_wh_to_kwh,
    ),
    SungrowSensorDescription(
        key="total_purchased_energy",
        name="Total Grid Import",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        source=SOURCE_API,
        convert=_wh_to_kwh,
    ),
    SungrowSensorDescription(
        key="feed_in_energy_today",
        name="Grid Export Today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        source=SOURCE_API,
        convert=_wh_to_kwh,
    ),
    SungrowSensorDescription(
        key="feed_in_energy_total",
        name="Total Grid Export",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        source=SOURCE_API,
        convert=_wh_to_kwh,
    ),
    SungrowSensorDescription(
        key="daily_load_consumption",
        name="Daily Load Consumption",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        source=SOURCE_API,
        convert=_wh_to_kwh,
    ),
    SungrowSensorDescription(
        key="total_load_consumption",
        name="Total Load Consumption",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        source=SOURCE_API,
        convert=_wh_to_kwh,
    ),
    SungrowSensorDescription(
        key="daily_direct_energy_consumption",
        name="Daily Self-Consumed PV",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        source=SOURCE_API,
        convert=_wh_to_kwh,
    ),
    SungrowSensorDescription(
        key="ess_daily_charge_ems",
        name="Daily Battery Charge",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        source=SOURCE_API,
        convert=_wh_to_kwh,
    ),
    SungrowSensorDescription(
        key="ess_daily_discharge_ems",
        name="Daily Battery Discharge",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        source=SOURCE_API,
        convert=_wh_to_kwh,
    ),
    SungrowSensorDescription(
        key="energy_storage_cumulative_charge",
        name="Total Battery Charge",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        source=SOURCE_API,
        convert=_wh_to_kwh,
    ),
    SungrowSensorDescription(
        key="cumulative_discharge",
        name="Total Battery Discharge",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        source=SOURCE_API,
        convert=_wh_to_kwh,
    ),

    # --- Battery state ---
    SungrowSensorDescription(
        key="battery_level_soc",
        name="Battery Level SOC (API)",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_API,
        convert=_ratio_to_percent,
    ),
    SungrowSensorDescription(
        key="battery_soc",
        name="Battery SOC (API)",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_API,
    ),
    SungrowSensorDescription(
        key="total_field_soc",
        name="Total Battery SOC",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_API,
    ),

    # --- Performance / environment ---
    SungrowSensorDescription(
        key="p_radiation_h",
        name="Solar Irradiance",
        native_unit_of_measurement="W/m²",
        device_class=SensorDeviceClass.IRRADIANCE,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_API,
    ),
    SungrowSensorDescription(
        key="plant_ambient_temperature",
        name="Ambient Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_API,
    ),
    SungrowSensorDescription(
        key="power_fraction",
        name="Power Utilization",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_API,
        convert=_ratio_to_percent,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),

    # --- Plant info ---
    SungrowSensorDescription(
        key="alarm_count",
        name="Alarm Count",
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_API,
    ),
    SungrowSensorDescription(
        key="fault_count",
        name="Fault Count",
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_API,
    ),
    SungrowSensorDescription(
        key="online_status",
        name="Online Status",
        source=SOURCE_API,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SungrowSensorDescription(
        key="api_last_poll",
        name="API Last Poll",
        device_class=SensorDeviceClass.TIMESTAMP,
        source=SOURCE_API,
    ),
)

# ---------------------------------------------------------------------------
# Modbus-only sensors
# ---------------------------------------------------------------------------

MODBUS_SENSORS: tuple[SungrowSensorDescription, ...] = (
    # --- Live power flow ---
    SungrowSensorDescription(
        key="mb_total_dc_power",
        name="PV DC Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_MODBUS,
    ),
    SungrowSensorDescription(
        key="mb_load_power",
        name="Load Power (Live)",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_MODBUS,
    ),
    SungrowSensorDescription(
        key="mb_battery_power",
        name="Battery Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_MODBUS,
    ),
    SungrowSensorDescription(
        key="mb_export_power",
        name="Grid Export Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_MODBUS,
    ),
    SungrowSensorDescription(
        key="mb_meter_active_power",
        name="Meter Active Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_MODBUS,
    ),
    SungrowSensorDescription(
        key="mb_total_active_power",
        name="Inverter Active Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_MODBUS,
    ),
    SungrowSensorDescription(
        key="mb_reactive_power",
        name="Reactive Power",
        native_unit_of_measurement="var",
        device_class=SensorDeviceClass.REACTIVE_POWER,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_MODBUS,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),

    # --- Battery details ---
    SungrowSensorDescription(
        key="mb_battery_soc",
        name="Battery SOC",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_MODBUS,
    ),
    SungrowSensorDescription(
        key="mb_battery_soh",
        name="Battery Health",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_MODBUS,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SungrowSensorDescription(
        key="mb_battery_voltage",
        name="Battery Voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_MODBUS,
    ),
    SungrowSensorDescription(
        key="mb_battery_current",
        name="Battery Current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_MODBUS,
    ),
    SungrowSensorDescription(
        key="mb_battery_temperature",
        name="Battery Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_MODBUS,
    ),
    SungrowSensorDescription(
        key="mb_bms_max_charge_current",
        name="BMS Max Charge Current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_MODBUS,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SungrowSensorDescription(
        key="mb_bms_max_discharge_current",
        name="BMS Max Discharge Current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_MODBUS,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),

    # --- MPPT strings ---
    SungrowSensorDescription(
        key="mb_mppt1_voltage",
        name="MPPT1 Voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_MODBUS,
    ),
    SungrowSensorDescription(
        key="mb_mppt1_current",
        name="MPPT1 Current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_MODBUS,
    ),
    SungrowSensorDescription(
        key="mb_mppt2_voltage",
        name="MPPT2 Voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_MODBUS,
    ),
    SungrowSensorDescription(
        key="mb_mppt2_current",
        name="MPPT2 Current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_MODBUS,
    ),
    SungrowSensorDescription(
        key="mb_mppt3_voltage",
        name="MPPT3 Voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_MODBUS,
    ),
    SungrowSensorDescription(
        key="mb_mppt3_current",
        name="MPPT3 Current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_MODBUS,
    ),

    # --- Grid phases ---
    SungrowSensorDescription(
        key="mb_phase_a_voltage",
        name="Phase A Voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_MODBUS,
    ),
    SungrowSensorDescription(
        key="mb_phase_b_voltage",
        name="Phase B Voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_MODBUS,
    ),
    SungrowSensorDescription(
        key="mb_phase_c_voltage",
        name="Phase C Voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_MODBUS,
    ),
    SungrowSensorDescription(
        key="mb_phase_a_current",
        name="Phase A Current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_MODBUS,
    ),
    SungrowSensorDescription(
        key="mb_phase_b_current",
        name="Phase B Current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_MODBUS,
    ),
    SungrowSensorDescription(
        key="mb_phase_c_current",
        name="Phase C Current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_MODBUS,
    ),
    SungrowSensorDescription(
        key="mb_grid_frequency",
        name="Grid Frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_MODBUS,
    ),
    SungrowSensorDescription(
        key="mb_meter_phase_a_active_power",
        name="Meter Phase A Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_MODBUS,
    ),
    SungrowSensorDescription(
        key="mb_meter_phase_b_active_power",
        name="Meter Phase B Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_MODBUS,
    ),
    SungrowSensorDescription(
        key="mb_meter_phase_c_active_power",
        name="Meter Phase C Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_MODBUS,
    ),

    # --- Energy totals from Modbus ---
    SungrowSensorDescription(
        key="mb_daily_pv_generation",
        name="Daily PV Generation (Modbus)",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        source=SOURCE_MODBUS,
    ),
    SungrowSensorDescription(
        key="mb_total_pv_generation",
        name="Total PV Generation (Modbus)",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        source=SOURCE_MODBUS,
    ),
    SungrowSensorDescription(
        key="mb_daily_export_from_pv",
        name="Daily PV Export (Modbus)",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        source=SOURCE_MODBUS,
    ),
    SungrowSensorDescription(
        key="mb_total_export_from_pv",
        name="Total PV Export (Modbus)",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        source=SOURCE_MODBUS,
    ),
    SungrowSensorDescription(
        key="mb_daily_battery_charge_from_pv",
        name="Daily Battery Charge from PV",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        source=SOURCE_MODBUS,
    ),
    SungrowSensorDescription(
        key="mb_total_battery_charge_from_pv",
        name="Total Battery Charge from PV",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        source=SOURCE_MODBUS,
    ),
    SungrowSensorDescription(
        key="mb_daily_battery_charge",
        name="Daily Battery Charge (Modbus)",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        source=SOURCE_MODBUS,
    ),
    SungrowSensorDescription(
        key="mb_total_battery_charge",
        name="Total Battery Charge (Modbus)",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        source=SOURCE_MODBUS,
    ),
    SungrowSensorDescription(
        key="mb_daily_direct_consumption",
        name="Daily Direct Consumption (Modbus)",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        source=SOURCE_MODBUS,
    ),
    SungrowSensorDescription(
        key="mb_total_direct_consumption",
        name="Total Direct Consumption (Modbus)",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        source=SOURCE_MODBUS,
    ),
    SungrowSensorDescription(
        key="mb_daily_battery_discharge",
        name="Daily Battery Discharge (Modbus)",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        source=SOURCE_MODBUS,
    ),
    SungrowSensorDescription(
        key="mb_total_battery_discharge",
        name="Total Battery Discharge (Modbus)",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        source=SOURCE_MODBUS,
    ),

    # --- Status ---
    SungrowSensorDescription(
        key="mb_inverter_temperature",
        name="Inverter Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_MODBUS,
    ),
    SungrowSensorDescription(
        key="mb_running_state",
        name="Running State",
        source=SOURCE_MODBUS,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SungrowSensorDescription(
        key="mb_power_flow_status",
        name="Power Flow Status",
        source=SOURCE_MODBUS,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SungrowSensorDescription(
        key="modbus_last_poll",
        name="Modbus Last Poll",
        device_class=SensorDeviceClass.TIMESTAMP,
        source=SOURCE_MODBUS,
    ),
)

# ---------------------------------------------------------------------------
# iHomeManager (iHM) sensors
# ---------------------------------------------------------------------------

IHM_SENSORS: tuple[SungrowSensorDescription, ...] = (
    # --- System info (diagnostic) ---
    SungrowSensorDescription(
        key="ihm_device_type_code",
        name="iHM Device Type",
        source=SOURCE_IHM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SungrowSensorDescription(
        key="ihm_software_version",
        name="iHM Software Version",
        source=SOURCE_IHM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SungrowSensorDescription(
        key="ihm_connected_devices",
        name="iHM Connected Devices",
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_IHM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),

    # --- Power flow (the key sensors) ---
    SungrowSensorDescription(
        key="ihm_inverter_active_power",
        name="Inverter Active Power (iHM)",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_IHM,
    ),
    SungrowSensorDescription(
        key="ihm_grid_active_power",
        name="Grid Active Power (iHM)",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_IHM,
    ),
    SungrowSensorDescription(
        key="ihm_total_load_power",
        name="Total Load Power (iHM)",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_IHM,
    ),

    # --- Energy totals ---
    SungrowSensorDescription(
        key="ihm_grid_import_energy",
        name="Grid Import Energy (iHM)",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        source=SOURCE_IHM,
    ),
    SungrowSensorDescription(
        key="ihm_grid_export_energy",
        name="Grid Export Energy (iHM)",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        source=SOURCE_IHM,
    ),

    # --- Rated / capacity (diagnostic) ---
    SungrowSensorDescription(
        key="ihm_total_rated_active_power",
        name="Total Rated Active Power (iHM)",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        source=SOURCE_IHM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SungrowSensorDescription(
        key="ihm_total_rated_battery_capacity",
        name="Total Rated Battery Capacity (iHM)",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        source=SOURCE_IHM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),

    # --- Battery ---
    SungrowSensorDescription(
        key="ihm_battery_power",
        name="Battery Power (iHM)",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_IHM,
    ),
    SungrowSensorDescription(
        key="ihm_battery_soc",
        name="Battery SOC (iHM)",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_IHM,
    ),
    SungrowSensorDescription(
        key="ihm_battery_power_limit",
        name="Battery Power Limit (iHM)",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        source=SOURCE_IHM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SungrowSensorDescription(
        key="ihm_max_charge_power",
        name="Max Charge Power (iHM)",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        source=SOURCE_IHM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SungrowSensorDescription(
        key="ihm_max_discharge_power",
        name="Max Discharge Power (iHM)",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        source=SOURCE_IHM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SungrowSensorDescription(
        key="ihm_charger_status",
        name="Charger Status (iHM)",
        source=SOURCE_IHM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SungrowSensorDescription(
        key="ihm_ev_charger_power",
        name="EV Charger Power Draw (iHM)",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        source=SOURCE_IHM,
    ),

    # --- Last poll ---
    SungrowSensorDescription(
        key="ihm_last_poll",
        name="iHM Last Poll",
        device_class=SensorDeviceClass.TIMESTAMP,
        source=SOURCE_IHM,
    ),
)
