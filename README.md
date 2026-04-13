# Sungrow Inverter Integration for Home Assistant

A Home Assistant (HACS) custom integration for Sungrow solar inverters that combines **three independent data sources** into native HA sensor entities:

| Source | Connection | Data | Latency |
|--------|-----------|------|---------|
| **iSolarCloud API** | Cloud (OAuth2) | Historical energy, load power, alarms | ~5 min |
| **Modbus TCP** | LAN (inverter) | Live power, battery, MPPT, grid phases | ~30 sec |
| **iHomeManager** | LAN (iHM) | System-wide load, grid point, VPP | ~30 sec |

Each source can be **independently enabled or disabled** from the options UI. No MQTT broker required.

## Supported Hardware

- **Inverters**: Sungrow SH series (hybrid), SG series (string) — tested on SH15T
- **Communication**: WiNet-S / WiNet-S2 dongles (Modbus TCP, port 502)
- **iHomeManager**: Sungrow iHM (slave ID 247, Modbus TCP)
- **iSolarCloud**: Europe, China, International, Australia gateways

## Installation

### HACS (Recommended)

1. Open **HACS** in Home Assistant
2. Click **Integrations** → **Custom repositories** (three-dot menu top right)
3. Add repository URL: `https://github.com/Cyber40014/sungrow-solarcloud-haos-integration`
4. Category: **Integration**
5. Click **Add** → find **Sungrow Inverter** → **Download**
6. Restart Home Assistant

### Manual Installation

1. Download the latest release from [GitHub Releases](https://github.com/Cyber40014/sungrow-solarcloud-haos-integration/releases)
2. Copy `custom_components/sungrow/` to your HA `config/custom_components/` directory
3. Restart Home Assistant

## Setup

After installation, add the integration:

**Settings** → **Devices & Services** → **Add Integration** → search **Sungrow Inverter**

The setup wizard guides you through multiple steps depending on which sources you want.

### Step 1: Connection Mode

Choose one of three modes:

| Mode | Description |
|------|-------------|
| **Both** (recommended) | iSolarCloud API + Modbus — best of both worlds |
| **API only** | Cloud data only, no local network access needed |
| **Modbus only** | Local data only, no cloud account needed |

### Step 2: iSolarCloud API (if API or Both)

You need OAuth2 app credentials from the iSolarCloud Developer Portal.

#### Getting API Credentials

1. Go to [https://developer-api.isolarcloud.com/](https://developer-api.isolarcloud.com/)
2. Register a developer account (approval takes ~1-2 business days)
3. Create an application — you'll get:
   - **App Key**
   - **App Secret**
   - **Application ID**
4. Set the redirect URI to: `http://homeassistant.local:8123/auth/external/callback`

#### Configuration Fields

| Field | Description |
|-------|-------------|
| Server region | Europe, China, International, or Australia |
| App Key | From developer portal |
| App Secret | From developer portal |
| Application ID | From developer portal |
| Redirect URI | Must match what you set in the developer portal |
| API poll interval | How often to fetch data (default: 300 seconds) |

#### OAuth Authorization

After entering credentials:
1. The wizard shows an authorization URL
2. Open it in your browser, log in with your iSolarCloud account
3. Authorize the app
4. Copy the **authorization code** from the redirect URL
5. Paste it into the wizard (code expires in ~5 minutes)

### Step 3: Modbus Connection (if Modbus or Both)

Direct LAN connection to the inverter's WiNet-S dongle.

| Field | Description | Default |
|-------|-------------|---------|
| Inverter IP address | LAN IP of WiNet-S dongle | — |
| Connection type | Direct Modbus TCP or WiNet Web | TCP |
| Port | Modbus TCP port | 502 |
| Slave ID | Modbus slave address | 1 |
| WiNet-S username | Dongle web UI credentials | admin |
| WiNet-S password | Dongle web UI credentials | pw8888 |
| Use SSL/TLS | Enable encrypted Modbus | off |
| Verify SSL | Verify server certificate | off |
| SSL certificate file | Path to CA cert (for self-signed) | — |
| Modbus poll interval | How often to read registers | 30 sec |

> **Note**: If your inverter uses Sungrow's AES encryption on Modbus TCP, the integration auto-detects and handles it transparently.

### Step 4: iHomeManager (optional)

The iHM provides system-wide power flow data that the inverter alone cannot provide (total load, grid connection point).

| Field | Description | Default |
|-------|-------------|---------|
| Enable iHomeManager | Activate iHM polling | off |
| iHM IP address | LAN IP of iHomeManager | — |
| Port | Modbus TCP port (502, 503, or 504) | 502 |
| Slave ID | iHM Modbus address | 247 |
| iHM poll interval | How often to read registers | 30 sec |

> **Note**: The iHM supports only 1 TCP connection per port. If another tool is using port 502, try 503 or 504.

## Options

After initial setup, all settings can be adjusted without re-adding the integration:

**Settings** → **Devices & Services** → **Sungrow Inverter** → **Configure**

You can:
- Enable/disable each data source independently (API, Modbus, iHM)
- Adjust poll intervals
- Change SSL settings
- Configure iHM (even if it wasn't set up initially)

## Devices & Sensors

The integration creates up to **three separate devices** in Home Assistant, depending on which sources are enabled:

### Sungrow iSolarCloud (API)

| Sensor | Unit | Description |
|--------|------|-------------|
| PV Power | W | Current PV generation |
| Load Power | W | Household consumption |
| Battery SOC (API) | % | Battery state of charge |
| Daily PV Yield | kWh | Today's PV generation |
| Daily Load Consumption | kWh | Today's load consumption |
| Grid Import/Export Today | kWh | Today's grid exchange |
| Total PV Yield | kWh | Lifetime PV generation |
| Alarm Count / Fault Count | — | Active alerts |
| API Last Poll | timestamp | Last successful API poll |
| *...and more* | | |

### Sungrow Inverter (Modbus)

| Sensor | Unit | Description |
|--------|------|-------------|
| PV DC Power | W | Live PV output |
| Inverter Active Power | W | Inverter AC output |
| Battery Power / SOC / Voltage / Current | W, %, V, A | Live battery state |
| Phase A/B/C Voltage & Current | V, A | Grid phase details |
| Grid Frequency | Hz | Mains frequency |
| MPPT1/2/3 Voltage & Current | V, A | Per-string PV data |
| Inverter Temperature | °C | Internal temperature |
| Daily/Total PV Generation | kWh | Energy counters |
| Modbus Last Poll | timestamp | Last successful poll |
| *...and more* | | |

### Sungrow iHomeManager (iHM)

| Sensor | Unit | Description |
|--------|------|-------------|
| Grid Active Power (iHM) | kW | Grid connection point — matches Live-Bild |
| Total Load Power (iHM) | kW | System-wide load power |
| Inverter Active Power (iHM) | kW | Aggregated inverter output |
| Battery Power (iHM) | kW | System battery charge/discharge |
| Battery SOC (iHM) | % | Aggregated battery SOC |
| Grid Import/Export Energy (iHM) | kWh | Energy totals |
| Charger Status (iHM) | — | Idle, Standby, Charging, Completed |
| iHM Last Poll | timestamp | Last successful poll |
| *...and more* | | |

## Resilience

- **Stale data on failure**: When a data source fails, sensors keep their last known values instead of going Unavailable. The "Last Poll" timestamp sensors let you monitor health.
- **Independent sources**: API, Modbus, and iHM failures are isolated — one going down doesn't affect the others.
- **Auto-recovery**: All coordinators automatically retry on their configured interval.
- **Log suppression**: After 3 consecutive failures, repeated warnings are suppressed to avoid log spam.

## SSL/TLS for Modbus

For installations where Modbus traffic needs encryption (e.g., across VLANs):

1. Enable **Use SSL/TLS** in the Modbus config
2. For **self-signed certificates**: leave "Verify SSL" disabled
3. For **CA-signed certificates**: enable "Verify SSL" and optionally provide the CA cert file path

## Diagnostics

The integration provides diagnostic data for troubleshooting:

**Settings** → **Devices & Services** → **Sungrow Inverter** → **three-dot menu** → **Download diagnostics**

Sensitive fields (tokens, passwords, secrets) are automatically redacted.

## Known Limitations

- **Load Power (Modbus)**: Register 13007 returns 0 on SH15T — this data comes from the iHomeManager, not the inverter. Use the iHM or API for load power.
- **Meter registers**: Registers 5600-5606 may return 0 depending on your meter setup.
- **iSolarCloud latency**: The API typically refreshes data every ~5 minutes on the backend, regardless of how frequently you poll.
- **iHM single connection**: Each iHM port (502/503/504) supports only 1 concurrent TCP connection.

## Troubleshooting

### "Config flow could not be loaded"
Restart Home Assistant after copying the integration files. Clear your browser cache.

### API shows "Network unreachable"
The integration forces IPv4 connections. If the error persists, check your HA instance's internet connectivity (Settings → System → Network).

### Modbus sensors show 0
Some registers don't return data on certain inverter models. This is a hardware limitation. Check if the same values are missing in other Modbus tools (e.g., SunGather).

### "Last Poll" shows Unavailable
Ensure you have the latest version. The Last Poll sensors require `datetime` objects (fixed in v1.0.0-beta).

## Credits & Third-Party Licenses

This integration uses or was inspired by the following projects:

| Project | License | Usage |
|---------|---------|-------|
| [pysolarcloud](https://github.com/bugjam/pysolarcloud) | MIT | iSolarCloud OAuth2 API client library (runtime dependency) |
| [SunGather](https://github.com/bohdan-s/SunGather) | GPL-3.0 | Modbus TCP register maps (reference only, no code copied) |
| [hacs-sungrow-home](https://github.com/Cyber40014/hacs-sungrow-home) | — | iSolarCloud API + MQTT approach (predecessor project) |

Home Assistant core dependencies (not bundled with this integration):
- [aiohttp](https://github.com/aio-libs/aiohttp) — Apache-2.0 / MIT — async HTTP client
- [voluptuous](https://github.com/alecthomas/voluptuous) — BSD-3-Clause — config schema validation

## License

Apache License 2.0 — see [LICENSE](LICENSE) for details.
