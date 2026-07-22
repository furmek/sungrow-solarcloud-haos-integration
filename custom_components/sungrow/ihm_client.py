"""Async Modbus TCP client for Sungrow iHomeManager (iHM).

The iHM is a separate device from the inverter that provides system-wide
power flow data: grid connection point totals, total load, battery aggregates,
and VPP dispatch info.

Key differences from the SH15T inverter (modbus_client.py):
  - Slave ID: 247 (not 1)
  - Register addresses in the spec are 1-indexed; we store spec addresses
    and subtract 1 at read time (clearer mapping to documentation)
  - Word order for 32-bit: CDAB (same swap_words=True as SH15T)
  - Minimum 1 second between reads (iHM protocol requirement)
  - No encryption, no SSL, no WiNet-S — plain Modbus TCP only
  - Uses function code 0x04 (Read Input Registers) for all reads

This file is intentionally self-contained — it does not import from
modbus_client.py so both files can evolve independently.
"""
from __future__ import annotations

import asyncio
import logging
import struct
import time
from dataclasses import dataclass
from typing import Any

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Register definitions
# ---------------------------------------------------------------------------
# IMPORTANT: All addresses below are 1-indexed as documented in the official
# Sungrow iHM specification. We subtract 1 at read time to convert to the
# 0-indexed Modbus protocol addresses. This keeps the register map easy to
# cross-reference with the datasheet.

@dataclass(frozen=True)
class IHMReg:
    """Single iHM Modbus register definition."""

    name: str
    address: int      # 1-indexed (spec address)
    count: int         # number of 16-bit registers
    data_type: str     # u16, i16, u32, i32, string
    scale: float = 1.0
    unit: str | None = None

    # Unavailable sentinel values per data type:
    #   U16: 0xFFFF, S16: 0x7FFF, U32: 0xFFFFFFFF, S32: 0x7FFFFFFF
    @property
    def nan_value(self) -> int | None:
        if self.data_type == "u16":
            return 0xFFFF
        if self.data_type == "i16":
            return 0x7FFF
        if self.data_type == "u32":
            return 0xFFFFFFFF
        if self.data_type == "i32":
            return 0x7FFFFFFF
        return None


# Charger status enum mapping
_CHARGER_STATUS = {
    1: "Idle",
    2: "Standby",
    3: "Charging",
    6: "Charging completed",
}

# --- System & Device Info ---
REGISTERS_INFO: list[IHMReg] = [
    IHMReg("ihm_device_type_code",   8000, 1, "u16"),
    IHMReg("ihm_software_version",   8318, 15, "string"),
    IHMReg("ihm_connected_devices",  8005, 1, "u16"),
]

# --- Power & Energy ---
REGISTERS_POWER: list[IHMReg] = [
    IHMReg("ihm_total_rated_active_power",  8145, 2, "u32", 0.1, "kW"),
    IHMReg("ihm_total_rated_battery_capacity", 8147, 2, "u32", 0.1, "kWh"),
    IHMReg("ihm_inverter_active_power",     8155, 2, "i32", 0.01, "kW"),
    IHMReg("ihm_grid_active_power",         8157, 2, "i32", 0.01, "kW"),
    IHMReg("ihm_total_load_power",          8159, 2, "i32", 0.01, "kW"),
    IHMReg("ihm_grid_import_energy",        8176, 2, "u32", 0.1, "kWh"),
    IHMReg("ihm_grid_export_energy",        8178, 2, "u32", 0.1, "kWh"),
]

# --- Battery ---
REGISTERS_BATTERY: list[IHMReg] = [
    IHMReg("ihm_battery_power_limit",     8149, 2, "u32", 0.1, "kW"),
    IHMReg("ihm_max_charge_power",        8151, 1, "u16", 0.1, "kW"),
    IHMReg("ihm_max_discharge_power",     8153, 1, "u16", 0.1, "kW"),
    IHMReg("ihm_battery_power",           8161, 2, "i32", 0.01, "kW"),
    IHMReg("ihm_battery_soc",             8163, 1, "u16", 0.1, "%"),
    IHMReg("ihm_ev_charger_power",        8593, 2, "u32", 1.0, "W"),
    IHMReg("ihm_charger_status",          8552, 1, "u16"),
]

ALL_REGISTERS: list[IHMReg] = (
    REGISTERS_INFO
    + REGISTERS_POWER
    + REGISTERS_BATTERY
)


# ---------------------------------------------------------------------------
# Exploratory raw register scan
# ---------------------------------------------------------------------------
# Contiguous input-register ranges (spec / 1-indexed addresses, inclusive)
# read as raw u16 to hunt for undocumented counters such as an EV charger
# accumulated-energy register. Each range is fetched in a single FC 0x04
# block read and split into per-register ihm_raw_register_<addr> values.
# Temporary diagnostic aid - remove once the useful registers are identified.
RAW_EXPLORE_RANGES: tuple[tuple[int, int], ...] = (
    (8590, 8650),
)

# --- Holding registers for future expansion (read-write, not implemented) ---
# TODO: Implement write support for these registers when needed.
REGISTERS_HOLDING_TODO: list[dict[str, Any]] = [
    {"address": 8024, "type": "U16", "desc": "Energy management mode (1=Self-consumption, 4=VPP, 5=Compulsory)"},
    {"address": 8033, "type": "U16", "desc": "External VPP heartbeat (write every N seconds if VPP active)"},
    {"address": 8025, "type": "U16", "desc": "Charge/discharge command (0xAA=Charge, 0xBB=Discharge, 0xCC=Stop)"},
    {"address": 8026, "type": "U32", "desc": "Charge/discharge power limit (scale 0.1 kW)"},
    {"address": 8028, "type": "U16", "desc": "Feed-in limitation toggle (0=Off, 1=On)"},
    {"address": 8031, "type": "S16", "desc": "Feed-in limitation ratio (0-1000, scale 0.1%)"},
    {"address": 8051, "type": "U16", "desc": "Active power limitation toggle (0x55=Off, 0xAA=On)"},
    {"address": 8052, "type": "U16", "desc": "Active power limit ratio (0-1000, scale 0.1%)"},
]


class IHMError(Exception):
    """Raised on iHM communication errors."""


# ---------------------------------------------------------------------------
# Decode helpers
# ---------------------------------------------------------------------------

def _decode(reg: IHMReg, raw_words: list[int]) -> Any:
    """Decode raw 16-bit Modbus words into a scaled Python value."""
    if not raw_words or len(raw_words) < reg.count:
        return None

    # String type: concat bytes, decode UTF-8, strip nulls
    if reg.data_type == "string":
        raw_bytes = b""
        for word in raw_words:
            raw_bytes += struct.pack(">H", word)
        return raw_bytes.decode("utf-8", errors="replace").rstrip("\x00").strip()

    if reg.count == 1:
        raw = raw_words[0]
        nan = reg.nan_value
        if nan is not None and raw == nan:
            return None
        if reg.data_type == "i16":
            if raw >= 0x8000:
                raw -= 0x10000
        value = round(raw * reg.scale, 3) if reg.scale != 1.0 else raw

        # Charger status: map to human-readable string
        if reg.name == "ihm_charger_status":
            return _CHARGER_STATUS.get(raw, f"Unknown ({raw})")

        return value

    if reg.count == 2:
        hi, lo = raw_words[0], raw_words[1]
        # Sungrow iHM uses CDAB word order (same as SH15T): swap words
        combined = (lo << 16) | hi
        nan = reg.nan_value
        if nan is not None and combined == nan:
            return None
        if reg.data_type == "i32":
            if combined >= 0x80000000:
                combined -= 0x100000000
        return round(combined * reg.scale, 3) if reg.scale != 1.0 else combined

    return None


# ---------------------------------------------------------------------------
# Modbus TCP framing (function code 0x04 — Read Input Registers)
# ---------------------------------------------------------------------------

_MBAP_HEADER = struct.Struct(">HHHB")  # transaction_id, protocol_id, length, unit_id
_FC04_REQUEST = struct.Struct(">BHH")  # function_code, start_address, quantity


def _build_read_request(
    transaction_id: int, unit_id: int, address: int, count: int
) -> bytes:
    """Build a Modbus TCP Read Input Registers (FC 0x04) request."""
    pdu = _FC04_REQUEST.pack(0x04, address, count)
    header = _MBAP_HEADER.pack(transaction_id, 0, len(pdu) + 1, unit_id)
    return header + pdu


def _parse_response(data: bytes, expected_count: int) -> list[int] | None:
    """Parse a Modbus TCP response and return register words."""
    if len(data) < 9:
        return None

    # MBAP header: 7 bytes, then function code + byte count + data
    func_code = data[7]
    if func_code & 0x80:
        error_code = data[8] if len(data) > 8 else 0
        _LOGGER.debug("Modbus error response: FC=0x%02X error=%d", func_code, error_code)
        return None

    byte_count = data[8]
    payload = data[9:9 + byte_count]
    if len(payload) < expected_count * 2:
        return None

    words = []
    for i in range(expected_count):
        words.append(struct.unpack(">H", payload[i * 2:i * 2 + 2])[0])
    return words


# ---------------------------------------------------------------------------
# iHM Client
# ---------------------------------------------------------------------------

class IHMClient:
    """Async Modbus TCP client for Sungrow iHomeManager."""

    def __init__(
        self,
        host: str,
        port: int = 502,
        slave_id: int = 247,
        timeout: int = 10,
    ) -> None:
        self._host = host
        self._port = port
        self._slave_id = slave_id
        self._timeout = timeout
        self._transaction_id = 0
        self._last_read_time: float = 0.0

    async def _enforce_min_interval(self) -> None:
        """Ensure at least 1 second between reads (iHM protocol requirement)."""
        elapsed = time.monotonic() - self._last_read_time
        if elapsed < 1.0:
            await asyncio.sleep(1.0 - elapsed)

    async def _read_registers(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        reg: IHMReg,
    ) -> list[int] | None:
        """Read a single register group from the iHM."""
        await self._enforce_min_interval()

        self._transaction_id = (self._transaction_id + 1) & 0xFFFF

        # Subtract 1 from spec address to get 0-indexed Modbus address
        wire_address = reg.address - 1

        request = _build_read_request(
            self._transaction_id, self._slave_id, wire_address, reg.count
        )
        writer.write(request)
        await writer.drain()

        try:
            response = await asyncio.wait_for(
                reader.read(256), timeout=self._timeout
            )
        except asyncio.TimeoutError:
            _LOGGER.debug("Timeout reading iHM register %s (addr=%d)", reg.name, reg.address)
            return None

        self._last_read_time = time.monotonic()
        return _parse_response(response, reg.count)

    async def _read_raw_block(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        start_address: int,
        count: int,
    ) -> list[int] | None:
        """Read a contiguous block of input registers in one request.

        start_address is a 1-indexed spec address; the block spans
        count registers. Used by the exploratory raw register scan.
        """
        await self._enforce_min_interval()

        self._transaction_id = (self._transaction_id + 1) & 0xFFFF
        wire_address = start_address - 1

        request = _build_read_request(
            self._transaction_id, self._slave_id, wire_address, count
        )
        writer.write(request)
        await writer.drain()

        try:
            response = await asyncio.wait_for(
                reader.read(512), timeout=self._timeout
            )
        except asyncio.TimeoutError:
            _LOGGER.debug(
                "Timeout reading iHM raw block %d..%d",
                start_address, start_address + count - 1,
            )
            return None

        self._last_read_time = time.monotonic()
        return _parse_response(response, count)

    async def async_get_data(self) -> dict[str, Any]:
        """Read all iHM registers and return a flat dict."""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port),
                timeout=self._timeout,
            )
        except (OSError, asyncio.TimeoutError) as exc:
            raise IHMError(
                f"Cannot connect to iHM at {self._host}:{self._port}: {exc}"
            ) from exc

        _LOGGER.debug("Connected to iHM at %s:%d (slave=%d)", self._host, self._port, self._slave_id)

        data: dict[str, Any] = {}
        errors = 0
        try:
            for reg in ALL_REGISTERS:
                words = await self._read_registers(reader, writer, reg)
                if words is not None:
                    value = _decode(reg, words)
                    if value is not None:
                        data[reg.name] = value
                    else:
                        errors += 1
                else:
                    errors += 1

            for _start, _end in RAW_EXPLORE_RANGES:
                block_count = _end - _start + 1
                words = await self._read_raw_block(
                    reader, writer, _start, block_count
                )
                if words is None:
                    errors += block_count
                    continue
                for offset, word in enumerate(words):
                    data[f"ihm_raw_register_{_start + offset}"] = word
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

        _LOGGER.debug(
            "iHM read %d/%d registers from %s (%d unavailable)",
            len(data), len(ALL_REGISTERS), self._host, errors,
        )
        return data

    async def async_test_connection(self) -> tuple[bool, str]:
        """Test connectivity by reading device type code."""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port),
                timeout=self._timeout,
            )
        except (OSError, asyncio.TimeoutError) as exc:
            return False, f"Cannot connect to iHM at {self._host}:{self._port}: {exc}"

        try:
            # Read device type code (register 8000)
            test_reg = REGISTERS_INFO[0]  # ihm_device_type_code
            words = await self._read_registers(reader, writer, test_reg)
            if words is not None:
                value = _decode(test_reg, words)
                if value is not None:
                    msg = f"Connected to iHM (device_type=0x{value:04X})"
                    if value == 0x072A:
                        msg += " — confirmed iHomeManager"
                    _LOGGER.info(msg)
                    return True, msg
                return False, "iHM returned empty device type"
            return False, "No response from iHM — check slave ID"
        except Exception as exc:
            return False, f"iHM test error: {exc}"
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
