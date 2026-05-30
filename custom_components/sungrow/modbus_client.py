"""Async Modbus TCP client for Sungrow hybrid inverters.

Supports three connection modes:
  1. Direct Modbus TCP (port 502) — with Sungrow AES encryption auto-detection
  2. WiNet Web (port 8082) — WebSocket + HTTP API (no encryption needed)
  3. Plain Modbus TCP — fallback for older inverters without encryption

Sungrow's WiNet-S dongle encrypts Modbus TCP traffic using AES-ECB.
The key is negotiated on connect: the client sends a GET_KEY request,
the dongle replies with a 16-byte public key, and the session key is
derived by XOR'ing it with a known private key. If the dongle returns
all-zeros or all-0xFF, encryption is not active.

Also supports optional SSL/TLS wrapping with self-signed certificate support.
"""
from __future__ import annotations

import asyncio
import json
import logging
import ssl
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Sungrow AES encryption constants
_SUNGROW_PRIV_KEY = b"Grow#0*2Sun68CbE"
_NO_CRYPTO_1 = b"\x00" * 16
_NO_CRYPTO_2 = b"\xff" * 16
_GET_KEY_CMD = b"\x68\x68\x00\x00\x00\x06\xf7\x04\x0a\xe7\x00\x08"
_HEADER = bytes([0x68, 0x68])


# ---------------------------------------------------------------------------
# Register definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ModbusReg:
    """Single Modbus register definition."""

    name: str
    address: int
    count: int
    data_type: str  # u16, i16, u32, i32
    scale: float = 1.0
    unit: str | None = None
    nan_value: int | None = None
    swap_words: bool = True  # Sungrow uses lo-hi word order for 32-bit


REGISTERS_POWER: list[ModbusReg] = [
    ModbusReg("mb_total_dc_power",       5016, 2, "u32", 1.0, "W"),
    ModbusReg("mb_load_power",          13007, 2, "i32", 1.0, "W", nan_value=0x7FFFFFFF),
    ModbusReg("mb_battery_power",        5213, 2, "i32", 1.0, "W"),
    ModbusReg("mb_export_power",        13009, 2, "i32", 1.0, "W", nan_value=0x7FFFFFFF),
    ModbusReg("mb_meter_active_power",   5600, 2, "i32", 1.0, "W", nan_value=0x7FFFFFFF),
    ModbusReg("mb_total_active_power",  13033, 2, "i32", 1.0, "W"),
    ModbusReg("mb_reactive_power",       5032, 2, "i32", 1.0, "W"),
]

REGISTERS_BATTERY: list[ModbusReg] = [
    ModbusReg("mb_battery_soc",             13022, 1, "u16", 0.1, "%"),
    ModbusReg("mb_battery_soh",             13023, 1, "u16", 0.1, "%"),
    ModbusReg("mb_battery_voltage",         13019, 1, "u16", 0.1, "V"),
    ModbusReg("mb_battery_current",          5630, 1, "i16", 0.1, "A"),
    ModbusReg("mb_battery_temperature",     13024, 1, "i16", 0.1, "°C"),
    ModbusReg("mb_bms_max_charge_current",   5634, 1, "u16", 1.0, "A"),
    ModbusReg("mb_bms_max_discharge_current",5635, 1, "u16", 1.0, "A"),
]

REGISTERS_MPPT: list[ModbusReg] = [
    ModbusReg("mb_mppt1_voltage", 5010, 1, "u16", 0.1, "V"),
    ModbusReg("mb_mppt1_current", 5011, 1, "u16", 0.1, "A"),
    ModbusReg("mb_mppt2_voltage", 5012, 1, "u16", 0.1, "V"),
    ModbusReg("mb_mppt2_current", 5013, 1, "u16", 0.1, "A"),
    ModbusReg("mb_mppt3_voltage", 5014, 1, "u16", 0.1, "V", nan_value=0xFFFF),
    ModbusReg("mb_mppt3_current", 5015, 1, "u16", 0.1, "A", nan_value=0xFFFF),
]

REGISTERS_GRID: list[ModbusReg] = [
    ModbusReg("mb_phase_a_voltage",  5018, 1, "u16", 0.1, "V"),
    ModbusReg("mb_phase_b_voltage",  5019, 1, "u16", 0.1, "V"),
    ModbusReg("mb_phase_c_voltage",  5020, 1, "u16", 0.1, "V"),
    ModbusReg("mb_phase_a_current", 13030, 1, "i16", 0.1, "A"),
    ModbusReg("mb_phase_b_current", 13031, 1, "i16", 0.1, "A"),
    ModbusReg("mb_phase_c_current", 13032, 1, "i16", 0.1, "A"),
    ModbusReg("mb_grid_frequency",   5241, 1, "u16", 0.01, "Hz"),
    ModbusReg("mb_meter_phase_a_active_power", 5602, 2, "i32", 1.0, "W", nan_value=0x7FFFFFFF),
    ModbusReg("mb_meter_phase_b_active_power", 5604, 2, "i32", 1.0, "W", nan_value=0x7FFFFFFF),
    ModbusReg("mb_meter_phase_c_active_power", 5606, 2, "i32", 1.0, "W", nan_value=0x7FFFFFFF),
]

REGISTERS_ENERGY: list[ModbusReg] = [
    ModbusReg("mb_daily_pv_generation",             13001, 1, "u16", 0.1, "kWh"),
    ModbusReg("mb_total_pv_generation",             13002, 2, "u32", 0.1, "kWh"),
    ModbusReg("mb_daily_export_from_pv",            13004, 1, "u16", 0.1, "kWh"),
    ModbusReg("mb_total_export_from_pv",            13005, 2, "u32", 0.1, "kWh"),
    ModbusReg("mb_daily_battery_charge_from_pv",    13011, 1, "u16", 0.1, "kWh"),
    ModbusReg("mb_total_battery_charge_from_pv",    13012, 2, "u32", 0.1, "kWh"),
    ModbusReg("mb_daily_direct_consumption",        13016, 1, "u16", 0.1, "kWh"),
    ModbusReg("mb_total_direct_consumption",        13017, 2, "u32", 0.1, "kWh"),
    ModbusReg("mb_daily_battery_discharge",         13025, 1, "u16", 0.1, "kWh"),
    ModbusReg("mb_total_battery_discharge",         13026, 2, "u32", 0.1, "kWh"),
    ModbusReg("mb_daily_battery_charge",            13039, 1, "u16", 0.1, "kWh"),
    ModbusReg("mb_total_battery_charge",            13040, 2, "u32", 0.1, "kWh"),
]

REGISTERS_STATUS: list[ModbusReg] = [
    ModbusReg("mb_inverter_temperature", 5007, 1, "i16", 0.1, "°C"),
    ModbusReg("mb_running_state",       12999, 1, "u16", 1.0),
    ModbusReg("mb_power_flow_status",   13000, 1, "u16", 1.0),
]

ALL_REGISTERS: list[ModbusReg] = (
    REGISTERS_POWER
    + REGISTERS_BATTERY
    + REGISTERS_MPPT
    + REGISTERS_GRID
    + REGISTERS_ENERGY
    + REGISTERS_STATUS
)


class ModbusError(Exception):
    """Raised on Modbus communication errors."""


# ---------------------------------------------------------------------------
# Decode helpers
# ---------------------------------------------------------------------------

def _decode(reg: ModbusReg, raw_words: list[int]) -> Any:
    """Decode raw 16-bit Modbus words into a scaled Python value."""
    if not raw_words or len(raw_words) < reg.count:
        return None

    if reg.count == 1:
        raw = raw_words[0]
        if reg.nan_value is not None and raw == reg.nan_value:
            return None
        if reg.data_type == "i16":
            if raw >= 0x8000:
                raw -= 0x10000
        return round(raw * reg.scale, 3) if reg.scale != 1.0 else raw

    if reg.count == 2:
        hi, lo = raw_words[0], raw_words[1]
        if reg.swap_words:
            combined = (lo << 16) | hi
        else:
            combined = (hi << 16) | lo
        if reg.nan_value is not None and combined == reg.nan_value:
            return None
        if reg.data_type == "i32":
            if combined >= 0x80000000:
                combined -= 0x100000000
        return round(combined * reg.scale, 3) if reg.scale != 1.0 else combined

    return None


# ---------------------------------------------------------------------------
# SSL context builder
# ---------------------------------------------------------------------------

def _build_ssl_context(
    verify: bool = False,
    certfile: str | None = None,
) -> ssl.SSLContext:
    """Build an SSL context for Modbus-over-TLS."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        _LOGGER.debug("SSL: verification DISABLED (self-signed OK)")
    else:
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED

    if certfile:
        cert_path = Path(certfile)
        if cert_path.is_file():
            ctx.load_verify_locations(str(cert_path))
            _LOGGER.debug("SSL: loaded cert from %s", cert_path)
        else:
            _LOGGER.warning("SSL certfile '%s' not found", certfile)
            if verify:
                ctx.load_default_certs()
    elif verify:
        ctx.load_default_certs()

    return ctx


# ---------------------------------------------------------------------------
# Sungrow AES encryption helper
# ---------------------------------------------------------------------------

class _SungrowCrypto:
    """Handles Sungrow's AES-ECB encryption for Modbus TCP.

    Uses only the Python standard library (no pycryptodome dependency).
    Implements a minimal AES-ECB using the built-in `hashlib` where
    available, or falls back to a pure-Python AES implementation.
    """

    def __init__(self) -> None:
        self._key: bytes | None = None
        self._cipher: Any = None

    @property
    def is_active(self) -> bool:
        return self._cipher is not None

    def setup(self, pub_key: bytes) -> bool:
        """Derive session key from public key and set up AES cipher.

        Returns True if encryption is active, False if not needed.
        """
        if pub_key == _NO_CRYPTO_1 or pub_key == _NO_CRYPTO_2 or len(pub_key) != 16:
            _LOGGER.debug("Sungrow encryption not active (pub_key=%s)", pub_key.hex())
            self._key = None
            self._cipher = None
            return False

        self._key = bytes(a ^ b for a, b in zip(pub_key, _SUNGROW_PRIV_KEY))

        # Try pycryptodome first (faster, may already be installed)
        try:
            from Cryptodome.Cipher import AES
            self._cipher = AES.new(self._key, AES.MODE_ECB)
            _LOGGER.debug("Sungrow AES encryption active (using pycryptodome)")
            return True
        except ImportError:
            pass

        # Try the older pycrypto import path
        try:
            from Crypto.Cipher import AES
            self._cipher = AES.new(self._key, AES.MODE_ECB)
            _LOGGER.debug("Sungrow AES encryption active (using pycrypto)")
            return True
        except ImportError:
            pass

        # Pure Python AES-ECB fallback (no external dependency)
        self._cipher = _PurePythonAES(self._key)
        _LOGGER.debug("Sungrow AES encryption active (pure Python fallback)")
        return True

    def encrypt(self, data: bytes) -> bytes:
        if self._cipher is None:
            return data
        return self._cipher.encrypt(data)

    def decrypt(self, data: bytes) -> bytes:
        if self._cipher is None:
            return data
        return self._cipher.decrypt(data)


class _PurePythonAES:
    """Minimal AES-128 ECB implementation (no external dependencies).

    Only supports 16-byte key and ECB mode — sufficient for Sungrow's
    Modbus encryption which uses fixed 16-byte blocks.
    """

    # AES S-box
    _SBOX = [
        0x63,0x7c,0x77,0x7b,0xf2,0x6b,0x6f,0xc5,0x30,0x01,0x67,0x2b,0xfe,0xd7,0xab,0x76,
        0xca,0x82,0xc9,0x7d,0xfa,0x59,0x47,0xf0,0xad,0xd4,0xa2,0xaf,0x9c,0xa4,0x72,0xc0,
        0xb7,0xfd,0x93,0x26,0x36,0x3f,0xf7,0xcc,0x34,0xa5,0xe5,0xf1,0x71,0xd8,0x31,0x15,
        0x04,0xc7,0x23,0xc3,0x18,0x96,0x05,0x9a,0x07,0x12,0x80,0xe2,0xeb,0x27,0xb2,0x75,
        0x09,0x83,0x2c,0x1a,0x1b,0x6e,0x5a,0xa0,0x52,0x3b,0xd6,0xb3,0x29,0xe3,0x2f,0x84,
        0x53,0xd1,0x00,0xed,0x20,0xfc,0xb1,0x5b,0x6a,0xcb,0xbe,0x39,0x4a,0x4c,0x58,0xcf,
        0xd0,0xef,0xaa,0xfb,0x43,0x4d,0x33,0x85,0x45,0xf9,0x02,0x7f,0x50,0x3c,0x9f,0xa8,
        0x51,0xa3,0x40,0x8f,0x92,0x9d,0x38,0xf5,0xbc,0xb6,0xda,0x21,0x10,0xff,0xf3,0xd2,
        0xcd,0x0c,0x13,0xec,0x5f,0x97,0x44,0x17,0xc4,0xa7,0x7e,0x3d,0x64,0x5d,0x19,0x73,
        0x60,0x81,0x4f,0xdc,0x22,0x2a,0x90,0x88,0x46,0xee,0xb8,0x14,0xde,0x5e,0x0b,0xdb,
        0xe0,0x32,0x3a,0x0a,0x49,0x06,0x24,0x5c,0xc2,0xd3,0xac,0x62,0x91,0x95,0xe4,0x79,
        0xe7,0xc8,0x37,0x6d,0x8d,0xd5,0x4e,0xa9,0x6c,0x56,0xf4,0xea,0x65,0x7a,0xae,0x08,
        0xba,0x78,0x25,0x2e,0x1c,0xa6,0xb4,0xc6,0xe8,0xdd,0x74,0x1f,0x4b,0xbd,0x8b,0x8a,
        0x70,0x3e,0xb5,0x66,0x48,0x03,0xf6,0x0e,0x61,0x35,0x57,0xb9,0x86,0xc1,0x1d,0x9e,
        0xe1,0xf8,0x98,0x11,0x69,0xd9,0x8e,0x94,0x9b,0x1e,0x87,0xe9,0xce,0x55,0x28,0xdf,
        0x8c,0xa1,0x89,0x0d,0xbf,0xe6,0x42,0x68,0x41,0x99,0x2d,0x0f,0xb0,0x54,0xbb,0x16,
    ]

    # Inverse S-box
    _INV_SBOX = [0] * 256

    # Rcon
    _RCON = [0x01,0x02,0x04,0x08,0x10,0x20,0x40,0x80,0x1b,0x36]

    def __init__(self, key: bytes) -> None:
        # Build inverse S-box
        for i, v in enumerate(self._SBOX):
            self._INV_SBOX[v] = i
        self._round_keys = self._expand_key(key)

    def _expand_key(self, key: bytes) -> list[list[int]]:
        key_words = [list(key[i:i+4]) for i in range(0, 16, 4)]
        for i in range(4, 44):
            temp = list(key_words[i - 1])
            if i % 4 == 0:
                temp = temp[1:] + temp[:1]
                temp = [self._SBOX[b] for b in temp]
                temp[0] ^= self._RCON[i // 4 - 1]
            key_words.append([a ^ b for a, b in zip(key_words[i - 4], temp)])
        return [sum(key_words[i:i+4], []) for i in range(0, 44, 4)]

    def _sub_bytes(self, state: list[int]) -> list[int]:
        return [self._SBOX[b] for b in state]

    def _inv_sub_bytes(self, state: list[int]) -> list[int]:
        return [self._INV_SBOX[b] for b in state]

    def _shift_rows(self, s: list[int]) -> list[int]:
        return [
            s[0],s[5],s[10],s[15], s[4],s[9],s[14],s[3],
            s[8],s[13],s[2],s[7], s[12],s[1],s[6],s[11],
        ]

    def _inv_shift_rows(self, s: list[int]) -> list[int]:
        return [
            s[0],s[13],s[10],s[7], s[4],s[1],s[14],s[11],
            s[8],s[5],s[2],s[15], s[12],s[9],s[6],s[3],
        ]

    @staticmethod
    def _xtime(a: int) -> int:
        return ((a << 1) ^ 0x1b) & 0xff if a & 0x80 else (a << 1) & 0xff

    def _mix_single(self, a: int, b: int, c: int, d: int) -> tuple[int,int,int,int]:
        t = a ^ b ^ c ^ d
        u = a
        a ^= t ^ self._xtime(a ^ b)
        b ^= t ^ self._xtime(b ^ c)
        c ^= t ^ self._xtime(c ^ d)
        d ^= t ^ self._xtime(d ^ u)
        return a & 0xff, b & 0xff, c & 0xff, d & 0xff

    def _mix_columns(self, s: list[int]) -> list[int]:
        r = list(s)
        for i in range(4):
            r[i*4], r[i*4+1], r[i*4+2], r[i*4+3] = self._mix_single(
                s[i*4], s[i*4+1], s[i*4+2], s[i*4+3]
            )
        return r

    @staticmethod
    def _gmul(a: int, b: int) -> int:
        p = 0
        for _ in range(8):
            if b & 1:
                p ^= a
            hi = a & 0x80
            a = (a << 1) & 0xff
            if hi:
                a ^= 0x1b
            b >>= 1
        return p

    def _inv_mix_columns(self, s: list[int]) -> list[int]:
        r = list(s)
        for i in range(4):
            a, b, c, d = s[i*4], s[i*4+1], s[i*4+2], s[i*4+3]
            r[i*4]   = self._gmul(a,14) ^ self._gmul(b,11) ^ self._gmul(c,13) ^ self._gmul(d,9)
            r[i*4+1] = self._gmul(a,9)  ^ self._gmul(b,14) ^ self._gmul(c,11) ^ self._gmul(d,13)
            r[i*4+2] = self._gmul(a,13) ^ self._gmul(b,9)  ^ self._gmul(c,14) ^ self._gmul(d,11)
            r[i*4+3] = self._gmul(a,11) ^ self._gmul(b,13) ^ self._gmul(c,9)  ^ self._gmul(d,14)
        return r

    def _add_round_key(self, state: list[int], rk: list[int]) -> list[int]:
        return [a ^ b for a, b in zip(state, rk)]

    def _encrypt_block(self, block: bytes) -> bytes:
        state = list(block)
        state = self._add_round_key(state, self._round_keys[0])
        for r in range(1, 10):
            state = self._sub_bytes(state)
            state = self._shift_rows(state)
            state = self._mix_columns(state)
            state = self._add_round_key(state, self._round_keys[r])
        state = self._sub_bytes(state)
        state = self._shift_rows(state)
        state = self._add_round_key(state, self._round_keys[10])
        return bytes(state)

    def _decrypt_block(self, block: bytes) -> bytes:
        state = list(block)
        state = self._add_round_key(state, self._round_keys[10])
        for r in range(9, 0, -1):
            state = self._inv_shift_rows(state)
            state = self._inv_sub_bytes(state)
            state = self._add_round_key(state, self._round_keys[r])
            state = self._inv_mix_columns(state)
        state = self._inv_shift_rows(state)
        state = self._inv_sub_bytes(state)
        state = self._add_round_key(state, self._round_keys[0])
        return bytes(state)

    def encrypt(self, data: bytes) -> bytes:
        out = b""
        for i in range(0, len(data), 16):
            out += self._encrypt_block(data[i:i+16])
        return out

    def decrypt(self, data: bytes) -> bytes:
        out = b""
        for i in range(0, len(data), 16):
            out += self._decrypt_block(data[i:i+16])
        return out


# ---------------------------------------------------------------------------
# Raw TCP transport with Sungrow encryption
# ---------------------------------------------------------------------------

class _SungrowTcpTransport:
    """Low-level async TCP transport with Sungrow AES encryption.

    Implements the Sungrow Modbus framing protocol:
    1. Connect TCP
    2. Send GET_KEY to negotiate encryption
    3. Wrap/unwrap Modbus frames with AES-ECB
    """

    def __init__(
        self,
        host: str,
        port: int,
        timeout: int,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout
        self._ssl_context = ssl_context
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._crypto = _SungrowCrypto()
        self._transaction_id = b"\x00\x00"

    async def connect(self) -> bool:
        """Open TCP connection and negotiate encryption."""
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(
                    self._host, self._port, ssl=self._ssl_context
                ),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError:
            _LOGGER.debug("TCP connect to %s:%s timed out", self._host, self._port)
            return False
        except ssl.SSLError as exc:
            _LOGGER.warning(
                "TLS handshake with %s:%s failed: %s. "
                "For self-signed certs, disable 'Verify SSL'.",
                self._host, self._port, exc,
            )
            return False
        except OSError as exc:
            _LOGGER.debug("TCP connect to %s:%s failed: %s", self._host, self._port, exc)
            return False

        _LOGGER.debug("TCP connected to %s:%s", self._host, self._port)

        # Negotiate Sungrow encryption
        try:
            await self._negotiate_encryption()
        except Exception as exc:
            _LOGGER.warning(
                "Encryption negotiation failed (will try plain Modbus): %s", exc
            )

        return True

    async def _negotiate_encryption(self) -> None:
        """Send GET_KEY, set up AES, then reconnect (required by Sungrow protocol).

        The Sungrow WiNet-S dongle expects:
        1. Plain TCP connect
        2. Send GET_KEY command (unencrypted)
        3. Receive 25-byte response with 16-byte public key at offset 9
        4. Close the connection
        5. Reconnect — from this point all traffic is AES-encrypted

        This matches the behavior of SungrowModbusTcpClient.
        """
        self._writer.write(_GET_KEY_CMD)
        await self._writer.drain()

        try:
            key_response = await asyncio.wait_for(
                self._reader.read(25), timeout=5
            )
        except asyncio.TimeoutError:
            _LOGGER.debug("No encryption key response — assuming plain Modbus")
            return

        if len(key_response) < 25:
            _LOGGER.debug(
                "Short key response (%d bytes) — assuming plain Modbus",
                len(key_response),
            )
            return

        pub_key = key_response[9:25]
        if self._crypto.setup(pub_key):
            _LOGGER.info(
                "Sungrow AES encryption negotiated with %s (reconnecting)",
                self._host,
            )
            # Close and reconnect — the dongle requires a fresh connection
            # for encrypted communication (same as SungrowModbusTcpClient)
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass

            # Brief pause before reconnect (Sungrow timing requirement)
            await asyncio.sleep(1)

            try:
                self._reader, self._writer = await asyncio.wait_for(
                    asyncio.open_connection(
                        self._host, self._port, ssl=self._ssl_context
                    ),
                    timeout=self._timeout,
                )
                _LOGGER.debug("Reconnected to %s:%s for encrypted session", self._host, self._port)
            except Exception as exc:
                raise ModbusError(
                    f"Failed to reconnect after key exchange: {exc}"
                ) from exc
        else:
            _LOGGER.info("Sungrow inverter at %s does not use encryption", self._host)

    async def send_modbus(self, request: bytes) -> bytes:
        """Send a Modbus request and return the raw response."""
        if self._writer is None or self._reader is None:
            raise ModbusError("Not connected")

        self._transaction_id = request[:2]

        if self._crypto.is_active:
            response = await self._send_encrypted(request)
        else:
            response = await self._send_plain(request)

        return response

    async def _send_plain(self, request: bytes) -> bytes:
        """Send plain (unencrypted) Modbus TCP frame."""
        self._writer.write(request)
        await self._writer.drain()

        # Read MBAP header (7 bytes) then payload
        try:
            header = await asyncio.wait_for(
                self._reader.readexactly(7), timeout=self._timeout
            )
        except (asyncio.TimeoutError, asyncio.IncompleteReadError) as exc:
            raise ModbusError(f"No response: {exc}") from exc

        length = struct.unpack(">H", header[4:6])[0]
        try:
            payload = await asyncio.wait_for(
                self._reader.readexactly(length - 1),  # -1 for unit_id already in header
                timeout=self._timeout,
            )
        except (asyncio.TimeoutError, asyncio.IncompleteReadError) as exc:
            raise ModbusError(f"Incomplete response: {exc}") from exc

        return header + payload

    async def _send_encrypted(self, request: bytes) -> bytes:
        """Send AES-encrypted Sungrow Modbus frame."""
        length = len(request)
        padding = 16 - (length % 16)

        # Replace MBAP header with Sungrow header
        frame = _HEADER + request[2:] + bytes([0xff] * padding)
        crypto_header = bytes([1, 0, length, padding])

        encrypted = crypto_header + self._crypto.encrypt(frame)
        self._writer.write(encrypted)
        await self._writer.drain()

        # Read encrypted response
        try:
            resp_header = await asyncio.wait_for(
                self._reader.readexactly(4), timeout=self._timeout
            )
        except (asyncio.TimeoutError, asyncio.IncompleteReadError) as exc:
            raise ModbusError(f"No encrypted response: {exc}") from exc

        packet_len = resp_header[2]
        resp_padding = resp_header[3]
        total = packet_len + resp_padding

        try:
            encrypted_data = await asyncio.wait_for(
                self._reader.readexactly(total), timeout=self._timeout
            )
        except (asyncio.TimeoutError, asyncio.IncompleteReadError) as exc:
            raise ModbusError(f"Incomplete encrypted response: {exc}") from exc

        decrypted = self._crypto.decrypt(encrypted_data)
        # Restore transaction ID (Sungrow replaces first 2 bytes with 0x6868)
        result = self._transaction_id + decrypted[2:packet_len]
        return result

    async def close(self) -> None:
        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
            self._reader = None


# ---------------------------------------------------------------------------
# WiNet Web transport (WebSocket + HTTP)
# ---------------------------------------------------------------------------

class _WiNetWebTransport:
    """Async transport using WiNet-S dongle's HTTP/WebSocket API.

    Connects via WebSocket for token, then uses HTTP GET for register reads.
    No encryption needed — the dongle serves plain data over HTTP.
    """

    def __init__(
        self,
        host: str,
        port: int,
        timeout: int,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout
        self._username = username or "admin"
        self._password = password or "pw8888"
        self._token: str = ""
        self._dev_type: str = ""
        self._dev_code: str = ""

    async def connect(self) -> bool:
        """Connect via WebSocket and get session token."""
        import aiohttp

        ws_url = f"ws://{self._host}:{self._port}/ws/home/overview"
        _LOGGER.debug("WiNet Web connecting to %s", ws_url)

        try:
            session = aiohttp.ClientSession()
            ws = await asyncio.wait_for(
                session.ws_connect(ws_url), timeout=self._timeout
            )
        except Exception as exc:
            _LOGGER.debug("WiNet WebSocket connect failed: %s", exc)
            try:
                await session.close()
            except Exception:
                pass
            return False

        try:
            # Get token — send credentials for dongles that require auth
            await ws.send_json({
                "lang": "en_us", "token": "", "service": "connect",
                "username": self._username, "passwd": self._password,
            })
            msg = await asyncio.wait_for(ws.receive_json(), timeout=self._timeout)

            if msg.get("result_msg") != "success":
                _LOGGER.warning("WiNet connect failed: %s", msg.get("result_msg"))
                return False

            self._token = msg["result_data"]["token"]

            # Get device info
            await ws.send_json({
                "lang": "en_us", "token": self._token,
                "service": "devicelist", "type": "0", "is_check_token": "0"
            })
            msg = await asyncio.wait_for(ws.receive_json(), timeout=self._timeout)

            if msg.get("result_msg") == "success":
                dev = msg["result_data"]["list"][0]
                self._dev_type = str(dev["dev_type"])
                self._dev_code = str(dev["dev_code"])
                _LOGGER.info("WiNet Web connected (token acquired, dev_type=%s)", self._dev_type)
            else:
                _LOGGER.warning("WiNet devicelist failed: %s", msg.get("result_msg"))
                return False

        except Exception as exc:
            _LOGGER.debug("WiNet Web setup error: %s", exc)
            return False
        finally:
            await ws.close()
            await session.close()

        self._session = aiohttp.ClientSession()
        return True

    async def read_registers(
        self, address: int, count: int, slave: int, func_code: int = 4
    ) -> list[int] | None:
        """Read registers via HTTP GET."""
        # func_code 4 = input registers, 3 = holding registers
        param_type = 0 if func_code == 4 else 1

        url = (
            f"http://{self._host}/device/getParam"
            f"?dev_id={slave}"
            f"&dev_type={self._dev_type}"
            f"&dev_code={self._dev_code}"
            f"&type=3"
            f"&param_addr={address + 1}"  # WiNet uses 1-based addressing
            f"&param_num={count}"
            f"&param_type={param_type}"
            f"&token={self._token}"
            f"&lang=en_us"
            f"&time123456={int(time.time())}"
        )

        try:
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=self._timeout)) as resp:
                if resp.status != 200:
                    _LOGGER.debug("WiNet HTTP %d for addr %d", resp.status, address)
                    return None

                data = await resp.json()

                if data.get("result_code") == 106:
                    _LOGGER.warning("WiNet token expired — reconnection needed")
                    self._token = ""
                    return None

                if data.get("result_code") != 1:
                    _LOGGER.debug(
                        "WiNet error for addr %d: %s", address, data.get("result_msg")
                    )
                    return None

                # Parse hex string response: "00 1A 00 2B "
                hex_str = data["result_data"]["param_value"].strip()
                if not hex_str:
                    return None

                hex_bytes = bytes.fromhex(hex_str.replace(" ", ""))
                words = []
                for i in range(0, len(hex_bytes), 2):
                    if i + 1 < len(hex_bytes):
                        words.append(struct.unpack(">H", hex_bytes[i:i+2])[0])
                return words

        except Exception as exc:
            _LOGGER.debug("WiNet HTTP error for addr %d: %s", address, exc)
            return None

    async def close(self) -> None:
        if hasattr(self, "_session") and self._session:
            await self._session.close()
            self._session = None


# ---------------------------------------------------------------------------
# Main client
# ---------------------------------------------------------------------------

class SungrowModbusClient:
    """Async Modbus client for Sungrow inverters.

    Supports:
      - tcp: Direct Modbus TCP with Sungrow AES encryption auto-detection
      - web: WiNet-S HTTP/WebSocket API (port 8082)
      - Optional SSL/TLS wrapping (for tcp mode)
    """

    def __init__(
        self,
        host: str,
        *,
        connection: str = "tcp",
        port: int | None = None,
        slave_id: int = 1,
        use_ssl: bool = False,
        verify_ssl: bool = False,
        ssl_certfile: str | None = None,
        username: str | None = None,
        password: str | None = None,
        timeout: int = 10,
    ) -> None:
        self._host = host
        self._connection = connection
        self._port = port or (502 if connection == "tcp" else 8082)
        self._slave_id = slave_id
        self._use_ssl = use_ssl
        self._timeout = timeout
        self._username = username
        self._password = password

        self._ssl_context: ssl.SSLContext | None = None
        if use_ssl:
            self._ssl_context = _build_ssl_context(verify_ssl, ssl_certfile)
            _LOGGER.info(
                "Modbus SSL/TLS enabled for %s:%s (verify=%s)",
                host, self._port, verify_ssl,
            )

        self._tcp_transport: _SungrowTcpTransport | None = None
        self._web_transport: _WiNetWebTransport | None = None
        self._web_failed: bool = False  # skip WebSocket after first failure

    async def _connect_tcp(self) -> bool:
        """Connect via TCP with Sungrow encryption."""
        transport = _SungrowTcpTransport(
            self._host, self._port, self._timeout, self._ssl_context
        )
        if await transport.connect():
            self._tcp_transport = transport
            return True

        # Fallback to port 502 if web port failed
        if self._connection == "web" and self._port != 502:
            _LOGGER.warning(
                "WiNet port %d failed, trying TCP fallback on 502", self._port
            )
            transport = _SungrowTcpTransport(
                self._host, 502, self._timeout, self._ssl_context
            )
            if await transport.connect():
                self._tcp_transport = transport
                return True

        return False

    async def _connect_web(self) -> bool:
        """Connect via WiNet Web API."""
        if self._web_failed:
            # WebSocket previously failed — go straight to TCP
            return await self._connect_tcp()

        transport = _WiNetWebTransport(
            self._host, self._port, self._timeout,
            self._username, self._password,
        )
        if await transport.connect():
            self._web_transport = transport
            return True

        # Fallback to TCP and remember to skip WebSocket next time
        self._web_failed = True
        _LOGGER.warning(
            "WiNet Web connect failed, falling back to TCP (will skip WebSocket for future polls)"
        )
        return await self._connect_tcp()

    async def _connect(self) -> None:
        """Connect using configured mode."""
        if self._connection == "web":
            ok = await self._connect_web()
        else:
            ok = await self._connect_tcp()

        if not ok:
            raise ModbusError(
                f"Could not connect to inverter at {self._host}:{self._port}. "
                "Check that Modbus is enabled on the WiNet-S dongle and the IP is reachable."
            )

    async def _disconnect(self) -> None:
        """Close all transports."""
        if self._tcp_transport:
            await self._tcp_transport.close()
            self._tcp_transport = None
        if self._web_transport:
            await self._web_transport.close()
            self._web_transport = None

    async def _read_register(self, reg: ModbusReg) -> Any:
        """Read a single register via the active transport."""
        words: list[int] | None = None

        if self._web_transport:
            words = await self._web_transport.read_registers(
                reg.address, reg.count, self._slave_id
            )
        elif self._tcp_transport:
            # Build Modbus TCP request frame
            # Transaction ID (2) + Protocol (2) + Length (2) + Unit (1) + FC (1) + Addr (2) + Count (2)
            request = struct.pack(
                ">HHHBBHH",
                0x0001,        # transaction ID
                0x0000,        # protocol ID
                0x0006,        # length
                self._slave_id,
                0x04,          # function code: read input registers
                reg.address,
                reg.count,
            )
            try:
                response = await self._tcp_transport.send_modbus(request)
                if len(response) < 9:
                    return None
                # Parse response: skip MBAP header (7) + FC (1) + byte count (1)
                byte_count = response[8]
                data_bytes = response[9:9 + byte_count]
                words = []
                for i in range(0, len(data_bytes), 2):
                    if i + 1 < len(data_bytes):
                        words.append(struct.unpack(">H", data_bytes[i:i+2])[0])
            except ModbusError as exc:
                _LOGGER.debug("Read error for %s: %s", reg.name, exc)
                return None
            except Exception as exc:
                _LOGGER.debug("Read error for %s: %s", reg.name, exc)
                return None
        else:
            return None

        if words is None:
            return None
        return _decode(reg, words)

    async def async_get_data(self) -> dict[str, Any]:
        """Read all registers and return a flat dict."""
        await self._connect()

        data: dict[str, Any] = {}
        errors = 0
        try:
            for reg in ALL_REGISTERS:
                value = await self._read_register(reg)
                if value is not None:
                    data[reg.name] = value
                else:
                    errors += 1
                await asyncio.sleep(0)  # yield to event loop
        finally:
            await self._disconnect()

        _LOGGER.debug(
            "Modbus read %d/%d registers from %s (%d unavailable)",
            len(data), len(ALL_REGISTERS), self._host, errors,
        )
        return data

    async def async_test_connection(self) -> tuple[bool, str]:
        """Test connectivity by reading battery SOC."""
        try:
            await self._connect()
        except ModbusError as exc:
            return False, str(exc)
        except Exception as exc:
            return False, f"Unexpected error: {exc}"

        try:
            test_reg = ModbusReg("test_soc", 13022, 1, "u16", 0.1, "%")
            value = await self._read_register(test_reg)
            if value is None:
                return False, (
                    "Connected but reading registers failed. "
                    "Check Slave ID and that Modbus is enabled on the WiNet-S dongle."
                )
            return True, f"OK — battery SOC = {value}%"
        finally:
            await self._disconnect()
