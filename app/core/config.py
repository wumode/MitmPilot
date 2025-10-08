import copy
import json
import os
import platform
import secrets
import sys
import threading
from pathlib import Path
from typing import Any, Literal

from dotenv import set_key
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings

from app.log import log_settings, logger
from app.utils.system import SystemUtils
from version import APP_VERSION


class SystemConfModel(BaseModel):
    """The system-critical resource size configuration."""

    # Number of schedulers
    scheduler: int = 0
    # Thread pool size
    threadpool: int = 0
    # Cache expiration time (seconds)
    cache_lifespan: int = 0


class ConfigModel(BaseModel):
    class Config:
        extra = "ignore"

    CONFIG_DIR: str | None = None

    # ==================== Basic Application Configuration ====================
    # Project name
    PROJECT_NAME: str = "MitmPilot"
    # Domain name format; https://mitmpilot.com
    APP_DOMAIN: str = ""
    # API path
    API_V1_STR: str = "/api/v1"
    # Frontend resource path
    FRONTEND_PATH: str = "/public"
    # Timezone
    TZ: str = "Asia/Shanghai"
    # API listening address
    HOST: str = "0.0.0.0"
    # API listening port
    PORT: int = 6006
    # Whether in development mode
    DEV: bool = False
    # Plugin class name under development
    DEV_ADDON: str | None = None
    # Plugin folder
    ADDON_FOLDER: Literal["addons"] = "addons"

    # ==================== Security Authentication Configuration ====================
    # Secret key
    SECRET_KEY: str = secrets.token_urlsafe(32)
    # Resource secret key
    RESOURCE_SECRET_KEY: str = secrets.token_urlsafe(32)
    # Allowed hosts
    ALLOWED_HOSTS: list = Field(default_factory=lambda: ["*"])
    # TOKEN expiration time
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8
    # RESOURCE_TOKEN expiration time
    RESOURCE_ACCESS_TOKEN_EXPIRE_SECONDS: int = 60 * 30
    # Superuser initial username
    SUPERUSER: str = "admin"
    # Superuser initial password
    SUPERUSER_PASSWORD: str | None = None
    # Auxiliary authentication, allowing authentication through external services,
    # single sign-on, and automatic user creation.
    AUXILIARY_AUTH_ENABLE: bool = False
    # API key, needs to be changed
    API_TOKEN: str | None = None
    # User authentication site
    AUTH_SITE: str = ""
    # Certificate filename
    CERT_FILENAME: str = "mitmproxy-ca-cert.pem"

    # ==================== Database Configuration ====================
    # Database type, supports sqlite and postgresql, sqlite is used by default.
    DB_TYPE: str = "sqlite"
    # Whether to output SQL statements in the console, disabled by default.
    DB_ECHO: bool = False
    # Database connection timeout (seconds), defaults to 60 seconds.
    DB_TIMEOUT: int = 60
    # Whether to enable WAL mode, only for SQLite, enabled by default.
    DB_WAL_ENABLE: bool = True
    # Database connection pool type, QueuePool, NullPool
    DB_POOL_TYPE: str = "QueuePool"
    # Whether to pre-ping when getting a connection.
    DB_POOL_PRE_PING: bool = True
    # Database connection recycle time (seconds)
    DB_POOL_RECYCLE: int = 300
    # Database connection pool timeout for getting a connection (seconds)
    DB_POOL_TIMEOUT: int = 30
    # SQLite connection pool size
    DB_SQLITE_POOL_SIZE: int = 10
    # SQLite connection pool overflow quantity
    DB_SQLITE_MAX_OVERFLOW: int = 50
    # PostgreSQL host address
    DB_POSTGRESQL_HOST: str = "localhost"
    # PostgreSQL port
    DB_POSTGRESQL_PORT: int = 5432
    # PostgreSQL database name
    DB_POSTGRESQL_DATABASE: str = "mitmpilot"
    # PostgreSQL username
    DB_POSTGRESQL_USERNAME: str = "mitmpilot"
    # PostgreSQL password
    DB_POSTGRESQL_PASSWORD: str = "mitmpilot"
    # PostgreSQL connection pool size
    DB_POSTGRESQL_POOL_SIZE: int = 10
    # PostgreSQL connection pool overflow quantity
    DB_POSTGRESQL_MAX_OVERFLOW: int = 50

    # ==================== Cache Configuration ====================
    # Cache type, supports cachetools and redis, cachetools is used by default.
    CACHE_BACKEND_TYPE: str = "cachetools"
    # Cache connection string, only required for external caches (e.g., Redis, Memcached).
    CACHE_BACKEND_URL: str = "redis://localhost:6379"
    # Redis cache max memory limit,
    # if not configured, it's "1024mb" when large memory mode is enabled, and "256mb"
    # when not enabled.
    CACHE_REDIS_MAXMEMORY: str | None = None
    # Temporary file retention days
    TEMP_FILE_DAYS: int = 3
    # Metadata recognition cache expiration time (hours), 0 for automatic.
    META_CACHE_EXPIRE: int = 0
    # Global image cache retention days
    GLOBAL_IMAGE_CACHE_DAYS: int = 7

    # ==================== Plugin Configuration ====================
    # Plugin installation data sharing
    PLUGIN_STATISTIC_SHARE: bool = True
    # Upstream proxy
    UPSTREAM_PROXY: str = ""
    # Plugin market repository address, multiple addresses separated by commas, address ending with /
    ADDON_MARKET: str = "https://github.com/wumode/MitmPilot-Addons"

    # ==================== Performance Configuration ====================
    # large memory mode
    LARGE_MEMORY_MODE: bool = False

    # ==================== Github & PIP ====================
    # Github token, to increase API rate limit threshold ghp_****
    GITHUB_TOKEN: str | None = None

    # ==================== Service Address Configuration ====================
    MP_SERVER_HOST: str = "https://mitmpilot.com"

    # ==================== Network Proxy Configuration ====================
    # Network proxy server address
    PROXY_HOST: str | None = None

    # Personalization
    # Login page movie poster, bing/customize
    WALLPAPER: str = "bing"
    # Custom wallpaper API address
    CUSTOMIZE_WALLPAPER_API_URL: str | None = None

    # Security configuration
    # Allowed image cache domains
    SECURITY_IMAGE_DOMAINS: list = Field(
        default=[
            "raw.githubusercontent.com",
            "github.com",
        ]
    )


class Settings(BaseSettings, ConfigModel):
    class Config:
        case_sensitive = True
        env_file = SystemUtils.get_env_path()
        env_file_encoding = "utf-8"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Initialize configuration directory and subdirectories
        for path in [self.CONFIG_PATH, self.LOG_PATH]:
            if not path.exists():
                path.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def generic_type_converter(
        value: Any,
        original_value: Any,
        expected_type: type,
        default: Any,
        field_name: str,
        raise_exception: bool = False,
    ) -> tuple[Any, bool]:
        """Generic type conversion function, converts values according to the expected
        type.

        Returns default value if conversion fails
        :return: Tuple (converted value, whether update is needed)
        """
        if isinstance(value, (list, dict, set)):
            value = copy.deepcopy(value)
        # 如果 value 是 None，仍需要检查与 original_value 是否不一致
        if value is None:
            return default, str(value) != str(original_value)

        if isinstance(value, str):
            value = value.strip()

        try:
            if expected_type is bool:
                if isinstance(value, bool):
                    return value, str(value).lower() != str(original_value).lower()
                if isinstance(value, str):
                    value_clean = value.lower()
                    bool_map = {
                        "false": False,
                        "no": False,
                        "0": False,
                        "off": False,
                        "true": True,
                        "yes": True,
                        "1": True,
                        "on": True,
                    }
                    if value_clean in bool_map:
                        converted = bool_map[value_clean]
                        return converted, str(converted).lower() != str(
                            original_value
                        ).lower()
                elif isinstance(value, (int, float)):
                    converted = bool(value)
                    return converted, str(converted).lower() != str(
                        original_value
                    ).lower()
                return default, True
            elif expected_type is int:
                if isinstance(value, int):
                    return value, str(value) != str(original_value)
                if isinstance(value, str):
                    converted = int(value)
                    return converted, str(converted) != str(original_value)
            elif expected_type is float:
                if isinstance(value, float):
                    return value, str(value) != str(original_value)
                if isinstance(value, str):
                    converted = float(value)
                    return converted, str(converted) != str(original_value)
            elif expected_type is str:
                converted = str(value).strip()
                return converted, converted != str(original_value)
            elif expected_type is list:
                if isinstance(value, list):
                    return value, str(value) != str(original_value)
                if isinstance(value, str):
                    items = json.loads(value)
                    if isinstance(original_value, list):
                        return items, items != original_value
                    else:
                        return items, str(items) != str(original_value)
            else:
                return value, str(value) != str(original_value)
        except (ValueError, TypeError) as e:
            if raise_exception:
                raise ValueError(
                    f"The value '{value}' for configuration item '{field_name}' "
                    f"cannot be converted to the correct type"
                ) from e
            logger.error(
                f"The value '{value}' for configuration item '{field_name}' "
                f"cannot be converted to the correct type, "
                f"using default value '{default}', error message: {e}"
            )
        return default, True

    @field_validator("API_TOKEN")
    @classmethod
    def api_token_validator(cls, v):
        converted_value, needs_update = cls.validate_api_token(v, v)
        if needs_update:
            cls.update_env_config("API_TOKEN", v, converted_value)
        return converted_value

    @staticmethod
    def validate_api_token(value: Any, original_value: Any) -> tuple[Any, bool]:
        """Validate API_TOKEN."""
        if isinstance(value, (list, dict, set)):
            value = copy.deepcopy(value)
        value = value.strip() if isinstance(value, str) else None
        if not value or len(value) < 16:
            new_token = secrets.token_urlsafe(16)
            if not value:
                logger.info(
                    f"'API_TOKEN' is not set, a new random 【API_TOKEN】{new_token} "
                    f"has been generated"
                )
            else:
                logger.warning(
                    f"'API_TOKEN' length is less than 16 characters, "
                    f"there is a security risk, "
                    f"a new random 【API_TOKEN】{new_token} has been generated")
            return new_token, True
        return value, str(value) != str(original_value)

    @staticmethod
    def update_env_config(
        field_name: str, original_value: Any, converted_value: Any
    ) -> tuple[bool, str]:
        """Update env configuration."""
        message = ""
        is_converted = original_value is not None and str(original_value) != str(
            converted_value
        )
        if is_converted:
            message = (f"The value '{original_value}' for configuration "
                       f"item '{field_name}' is invalid, "
                       f"it has been replaced with '{converted_value}'")
            logger.warning(message)

        if field_name in os.environ:
            message = (
                f"Configuration item '{field_name}' has been set in environment "
                f"variables, please update manually to maintain consistency"
            )
            logger.warning(message)
            return False, message
        else:
            # If it is a list, dictionary or set type, convert it to a JSON string
            if isinstance(converted_value, (list, dict, set)):
                value_to_write = json.dumps(converted_value)
            else:
                value_to_write = (
                    str(converted_value) if converted_value is not None else ""
                )

            set_key(
                dotenv_path=SystemUtils.get_env_path(),
                key_to_set=field_name,
                value_to_set=value_to_write,
                quote_mode="always",
            )
            if is_converted:
                logger.info(f"Configuration item '{field_name}' has been automatically "
                            f"corrected and written to 'app.env' file")
        return True, message

    def update_setting(self, key: str, value: Any) -> tuple[bool | None, str]:
        """Update single configuration item."""
        if not hasattr(self, key):
            return False, f"Configuration item '{key}' does not exist"

        try:
            field = Settings.model_fields[key]
            original_value = getattr(self, key)
            if key == "API_TOKEN":
                converted_value, needs_update = self.validate_api_token(
                    value, original_value
                )
            else:
                converted_value, needs_update = self.generic_type_converter(
                    value, original_value, field.annotation, field.default, key
                )
            # If no exception is thrown, use converted_value for update
            if needs_update or str(value) != str(converted_value):
                success, message = self.update_env_config(key, value, converted_value)
                # Only update memory when configuration is successfully updated
                if success:
                    setattr(self, key, converted_value)
                    if hasattr(log_settings, key):
                        setattr(log_settings, key, converted_value)
                return success, message
            return None, ""
        except Exception as e:
            return False, str(e)

    def update_settings(
        self, env: dict[str, Any]
    ) -> dict[str, tuple[bool | None, str]]:
        """Update multiple configuration items."""
        results = {}
        for k, v in env.items():
            results[k] = self.update_setting(k, v)
        return results

    @property
    def VERSION_FLAG(self) -> str:
        """Version identifier, used to distinguish major versions.

        If empty, it's v1, not allowed to be modified externally.
        """
        return ""

    @property
    def CONFIG_PATH(self) -> Path:
        if self.CONFIG_DIR:
            return Path(self.CONFIG_DIR)
        return self.ROOT_PATH / "config"

    @property
    def CACHE_PATH(self):
        return self.CONFIG_PATH / "cache"

    @property
    def LOG_PATH(self) -> Path:
        return self.CONFIG_PATH / "logs"

    @property
    def UV_PATH(self) -> Path:
        return Path(sys.executable).parent / "uv"

    @property
    def ROOT_PATH(self) -> Path:
        return Path(__file__).parents[2]

    @property
    def ADDON_DATA_PATH(self) -> Path:
        return self.CONFIG_PATH / "addons"

    @property
    def TEMP_PATH(self) -> Path:
        return self.CONFIG_PATH / "temp"

    @property
    def CONF(self) -> SystemConfModel:
        """Returns system configuration based on memory mode."""
        return SystemConfModel(scheduler=100, threadpool=100)

    @property
    def PROXY(self) -> dict | None:
        if self.PROXY_HOST:
            return {
                "http": self.PROXY_HOST,
                "https": self.PROXY_HOST,
            }
        return None

    @property
    def USER_AGENT(self) -> str:
        """Global user agent string."""
        return (f"{self.PROJECT_NAME}/{APP_VERSION[1:]} ({platform.system()} "
                f"{platform.release()}; {SystemUtils.cpu_arch()})")

    @property
    def NORMAL_USER_AGENT(self) -> str:
        """Default browser user agent string."""
        return ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36")

    @property
    def GITHUB_HEADERS(self) -> dict:
        """Github request headers."""
        if self.GITHUB_TOKEN:
            return {
                "Authorization": f"Bearer {self.GITHUB_TOKEN}",
                "User-Agent": self.NORMAL_USER_AGENT,
            }
        return {}


settings = Settings()


class MitmOpts(BaseSettings):
    class Config:
        case_sensitive = True
        env_file = SystemUtils.get_env_path()
        env_file_encoding = "utf-8"
        env_prefix = "MITMOPTS_"
        extra = "ignore"

    # Add all certificates of the upstream server to the certificate chain.
    ADD_UPSTREAM_CERTS_TO_CLIENT_CHAIN: bool = False
    # Opposite of --ignore-hosts.
    ALLOW_HOSTS: list[str] = Field(default_factory=list)
    # Strip out request headers that might cause 304-not-modified.
    ANTICACHE: bool = False
    # Try to convince servers to send us un-compressed data.
    ANTICOMP: bool = False
    # Block connections from public IP addresses.
    BLOCK_GLOBAL: bool = True
    # Block matching requests and return an empty response.
    BLOCK_LIST: list[str] = Field(default_factory=list)
    # Block connections from local (private) IP addresses.
    BLOCK_PRIVATE: bool = False
    # Byte size limit of HTTP request and response bodies.
    BODY_SIZE_LIMIT: str | None = None
    # Passphrase for decrypting the private key in --cert.
    CERT_PASSPHRASE: str | None = None
    # SSL certificates of the form "[domain=]path".
    CERTS: list[str] = Field(default_factory=list)
    # Set supported ciphers for client <-> mitmproxy connections.
    CIPHERS_CLIENT: str | None = None
    # Set supported ciphers for mitmproxy <-> server connections.
    CIPHERS_SERVER: str | None = None
    # Client certificate file or directory.
    CLIENT_CERTS: str | None = None
    # Replay client requests from a saved file.
    CLIENT_REPLAY: list[str] = Field(default_factory=list)
    # Concurrency limit on in-flight client replay requests.
    CLIENT_REPLAY_CONCURRENCY: int = 1
    # Persist command history between mitmproxy invocations.
    COMMAND_HISTORY: bool = True
    # Location of the default mitmproxy configuration files.
    CONFDIR: str | None = None
    # Set the local IP address for connecting to upstream servers.
    CONNECT_ADDR: str | None = None
    # Determine when server connections should be established.
    CONNECTION_STRATEGY: Literal["eager", "lazy"] = "eager"
    # Flow content view lines limit.
    CONTENT_VIEW_LINES_CUTOFF: int = 512
    # Name servers to use for lookups.
    DNS_NAME_SERVERS: list[str] = Field(default_factory=list)
    # Use the hosts file for DNS lookups.
    DNS_USE_HOSTS_FILE: bool = True
    # The default content view mode.
    DUMPER_DEFAULT_CONTENTVIEW: str = "auto"
    # Limit which flows are dumped.
    DUMPER_FILTER: str | None = None
    # Effort to connect to the same IP as in the original request.
    EXPORT_PRESERVE_ORIGINAL_IP: bool = False
    # The display detail level for flows in mitmdump.
    FLOW_DETAIL: int = 1
    # Save a HAR file with all flows on exit.
    HARDUMP: str = ""
    # Enable/disable HTTP/2 support.
    HTTP2: bool = True
    # Send a PING frame on idle HTTP/2 connections.
    HTTP2_PING_KEEPALIVE: int = 58
    # Enable/disable support for QUIC and HTTP/3.
    HTTP3: bool = True
    # Include host header with CONNECT requests.
    HTTP_CONNECT_SEND_HOST_HEADER: bool = True
    # Ignore host and forward all traffic without processing it.
    IGNORE_HOSTS: list[str] = Field(default_factory=list)
    # Keep Alt-Svc headers as-is.
    KEEP_ALT_SVC_HEADER: bool = False
    # Keep the original host header.
    KEEP_HOST_HEADER: bool = False
    # Continue serving after client playback, server playback or file read.
    KEEPSERVING: bool = False
    # TLS key size for certificates and CA.
    KEY_SIZE: int = 2048
    # Address to bind proxy server(s) to.
    LISTEN_HOST: str = "0.0.0.0"
    # Port to bind proxy server(s) to.
    LISTEN_PORT: int | None = None
    # Map remote resources to a local file.
    MAP_LOCAL: list[str] = Field(default_factory=list)
    # Map remote resources to another remote URL.
    MAP_REMOTE: list[str] = Field(default_factory=list)
    # The proxy server type(s) to spawn.
    MODE: list[str] = Field(default_factory=lambda: ["regular"])
    # Replacement pattern for request/response bodies.
    MODIFY_BODY: list[str] = Field(default_factory=list)
    # Header modify pattern.
    MODIFY_HEADERS: list[str] = Field(default_factory=list)
    # Normalize outgoing HTTP/2 header names.
    NORMALIZE_OUTBOUND_HEADERS: bool = True
    # Toggle the mitmproxy onboarding app.
    ONBOARDING: bool = True
    # Onboarding app domain.
    ONBOARDING_HOST: str = "mitm.it"
    # Path to a .proto file for resolving Protobuf field names.
    PROTOBUF_DEFINITIONS: str | None = None
    # Enable debug logs in the proxy core.
    PROXY_DEBUG: bool = False
    # Require proxy authentication.
    PROXYAUTH: str | None = None
    # Enable/disable raw TCP connections.
    RAWTCP: bool = True
    # Read only matching flows.
    READFILE_FILTER: str | None = None
    # Request a client certificate.
    REQUEST_CLIENT_CERT: bool = False
    # Read flows from file.
    RFILE: str | None = None
    # Stream flows to file as they arrive.
    SAVE_STREAM_FILE: str | None = None
    # Filter which flows are written to file.
    SAVE_STREAM_FILTER: str | None = None
    # Execute a script.
    SCRIPTS: list[str] = Field(default_factory=list)
    # Start a proxy server.
    SERVER: bool = True
    # Replay server responses from a saved file.
    SERVER_REPLAY: list[str] = Field(default_factory=list)
    # Behavior for extra requests during replay.
    SERVER_REPLAY_EXTRA: str = "forward"
    # Ignore request content while searching for a saved flow to replay.
    SERVER_REPLAY_IGNORE_CONTENT: bool = False
    # Ignore request destination host while searching for a saved flow to replay.
    SERVER_REPLAY_IGNORE_HOST: bool = False
    # Request parameters to be ignored while searching for a saved flow to replay.
    SERVER_REPLAY_IGNORE_PARAMS: list[str] = Field(default_factory=list)
    # Request payload parameters to be ignored while searching for a saved flow to replay.
    SERVER_REPLAY_IGNORE_PAYLOAD_PARAMS: list[str] = Field(default_factory=list)
    # Ignore request destination port while searching for a saved flow to replay.
    SERVER_REPLAY_IGNORE_PORT: bool = False
    # Kill extra requests during replay.
    SERVER_REPLAY_KILL_EXTRA: bool = False
    # Deprecated alias for `server_replay_reuse`.
    SERVER_REPLAY_NOPOP: bool = False
    # Refresh server replay responses by adjusting date, expires and last-modified headers.
    SERVER_REPLAY_REFRESH: bool = True
    # Don't remove flows from server replay state after use.
    SERVER_REPLAY_REUSE: bool = False
    # Request headers that need to match while searching for a saved flow to replay.
    SERVER_REPLAY_USE_HEADERS: list[str] = Field(default_factory=list)
    # Record ignored flows in the UI.
    SHOW_IGNORED_HOSTS: bool = False
    # Use the Host header to construct URLs for display.
    SHOWHOST: bool = False
    # Do not verify upstream server SSL/TLS certificates.
    SSL_INSECURE: bool = False
    # Path to a PEM formatted trusted CA certificate.
    SSL_VERIFY_UPSTREAM_TRUSTED_CA: str | None = None
    # Path to a directory of trusted CA certificates.
    SSL_VERIFY_UPSTREAM_TRUSTED_CONFDIR: str | None = None
    # Set sticky auth filter.
    STICKYAUTH: str | None = None
    # Set sticky cookie filter.
    STICKYCOOKIE: str | None = None
    # Store HTTP request and response bodies when streamed.
    STORE_STREAMED_BODIES: bool = False
    # Stream data to the client if body exceeds the given threshold.
    STREAM_LARGE_BODIES: str | None = None
    # Strip Encrypted ClientHello (ECH) data from DNS HTTPS records.
    STRIP_ECH: bool = True
    # Generic TCP SSL proxy mode for all hosts that match the pattern.
    TCP_HOSTS: list[str] = Field(default_factory=list)
    # Log verbosity.
    TERMLOG_VERBOSITY: str = "info"
    # Use a specific elliptic curve for ECDHE key exchange on client connections.
    TLS_ECDH_CURVE_CLIENT: str | None = None
    # Use a specific elliptic curve for ECDHE key exchange on server connections.
    TLS_ECDH_CURVE_SERVER: str | None = None
    # Set the maximum TLS version for client connections.
    TLS_VERSION_CLIENT_MAX: str = "UNBOUNDED"
    # Set the minimum TLS version for client connections.
    TLS_VERSION_CLIENT_MIN: str = "TLS1_2"
    # Set the maximum TLS version for server connections.
    TLS_VERSION_SERVER_MAX: str = "UNBOUNDED"
    # Set the minimum TLS version for server connections.
    TLS_VERSION_SERVER_MIN: str = "TLS1_2"
    # Generic UDP SSL proxy mode for all hosts that match the pattern.
    UDP_HOSTS: list[str] = Field(default_factory=list)
    # Add HTTP Basic authentication to upstream proxy requests.
    UPSTREAM_AUTH: str | None = None
    # Connect to upstream server to look up certificate details.
    UPSTREAM_CERT: bool = True
    # Make sure that incoming HTTP requests are not malformed.
    VALIDATE_INBOUND_HEADERS: bool = True
    # Enable/disable WebSocket support.
    WEBSOCKET: bool = True

    @field_validator("CONFDIR")
    @classmethod
    def validate_confdir(cls, v: str | None) -> str:
        if v is None:
            return str(settings.CONFIG_PATH)
        return v


mitmopts = MitmOpts()


class GlobalVar:
    """Global identifiers."""

    # System stop event
    STOP_EVENT: threading.Event = threading.Event()
    # Webpush subscriptions
    SUBSCRIPTIONS: list[dict] = []
    # Workflows requiring emergency stop
    EMERGENCY_STOP_WORKFLOWS: list[int] = []
    # File organization requiring emergency stop
    EMERGENCY_STOP_TRANSFER: list[str] = []

    def stop_system(self):
        """Stops the system."""
        self.STOP_EVENT.set()

    @property
    def is_system_stopped(self):
        """Whether the system is stopped."""
        return self.STOP_EVENT.is_set()


# Global identifiers
global_vars = GlobalVar()
