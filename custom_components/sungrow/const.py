"""Constants for the Sungrow integration."""

DOMAIN = "sungrow"

# --- Connection modes ---
MODE_API = "api"
MODE_MODBUS = "modbus"
MODE_BOTH = "both"

# --- iSolarCloud OAuth2 config keys ---
CONF_SERVER = "server"
CONF_APP_KEY = "app_key"
CONF_APP_SECRET = "app_secret"
CONF_APPLICATION_ID = "application_id"
CONF_REDIRECT_URI = "redirect_uri"
CONF_AUTH_CODE = "auth_code"
CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_TOKEN_EXPIRES_AT = "token_expires_at"

# --- Modbus config keys ---
CONF_MODBUS_HOST = "modbus_host"
CONF_MODBUS_PORT = "modbus_port"
CONF_MODBUS_SLAVE_ID = "modbus_slave_id"
CONF_MODBUS_CONNECTION = "modbus_connection"
CONF_MODBUS_USE_SSL = "modbus_use_ssl"
CONF_MODBUS_VERIFY_SSL = "modbus_verify_ssl"
CONF_MODBUS_SSL_CERTFILE = "modbus_ssl_certfile"
CONF_MODBUS_USERNAME = "modbus_username"
CONF_MODBUS_PASSWORD = "modbus_password"

# --- iHomeManager (iHM) config keys ---
CONF_IHM_ENABLED = "ihm_enabled"
CONF_IHM_HOST = "ihm_host"
CONF_IHM_PORT = "ihm_port"
CONF_IHM_SLAVE_ID = "ihm_slave_id"
CONF_IHM_SCAN_INTERVAL = "ihm_scan_interval"

# --- Enable/disable toggles (options flow) ---
CONF_API_ENABLED = "api_enabled"
CONF_MODBUS_ENABLED = "modbus_enabled"

# --- General config ---
CONF_MODE = "mode"
CONF_API_SCAN_INTERVAL = "api_scan_interval"
CONF_MODBUS_SCAN_INTERVAL = "modbus_scan_interval"

# --- Defaults ---
DEFAULT_SERVER = "Europe"
DEFAULT_API_SCAN_INTERVAL = 300  # 5 min — matches iSolarCloud refresh rate
DEFAULT_MODBUS_SCAN_INTERVAL = 30  # 30 sec — real-time local data
DEFAULT_IHM_SCAN_INTERVAL = 30   # 30 sec — same as Modbus
DEFAULT_MODBUS_PORT_TCP = 502
DEFAULT_MODBUS_PORT_WEB = 8082
DEFAULT_MODBUS_SLAVE_ID = 1
DEFAULT_IHM_PORT = 502
DEFAULT_IHM_SLAVE_ID = 247

# --- Modbus connection types ---
CONNECTION_TCP = "tcp"
CONNECTION_WEB = "web"

MODBUS_CONNECTIONS = {
    CONNECTION_TCP: "Direct Modbus TCP (port 502)",
    CONNECTION_WEB: "WiNet Web (port 8082, with TCP fallback)",
}

# --- iSolarCloud server URLs ---
SERVERS = {
    "Europe": "https://gateway.isolarcloud.eu",
    "China": "https://gateway.isolarcloud.com.hk",
    "International": "https://gateway.isolarcloud.com",
    "Australia": "https://augateway.isolarcloud.com",
}

# --- iSolarCloud device types ---
DEVICE_TYPE_NAMES = {
    1: "inverter_string",
    2: "inverter_max",
    14: "inverter_hybrid",
    17: "grid_meter",
    22: "communication_module",
    43: "battery",
    47: "meter",
}

# --- Platforms to set up ---
PLATFORMS = ["sensor"]
