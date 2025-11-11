import asyncio
import logging
import queue
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import click
from pydantic import BaseModel, ConfigDict
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.utils.system import SystemUtils


class LogConfigModel(BaseModel):
    """Pydantic configuration model describing all configuration items, their types, and
    default values."""

    model_config = ConfigDict(extra="ignore")

    # Configuration file directory
    CONFIG_DIR: str | None = None
    # Whether it is in debug mode
    DEBUG: bool = False
    # Log level (DEBUG, INFO, WARNING, ERROR, etc.)
    LOG_LEVEL: str = "INFO"
    # Maximum log file size (in MB)
    LOG_MAX_FILE_SIZE: int = 5
    # Number of backup log files
    LOG_BACKUP_COUNT: int = 10
    # Console log format
    LOG_CONSOLE_FORMAT: str = "%(leveltext)s[%(name)s] %(asctime)s %(message)s"
    # File log format
    LOG_FILE_FORMAT: str = "【%(levelname)s】%(asctime)s - %(message)s"
    # Asynchronous file write queue size
    ASYNC_FILE_QUEUE_SIZE: int = 1000
    # Number of asynchronous file write threads
    ASYNC_FILE_WORKERS: int = 2
    # Batch write size
    BATCH_WRITE_SIZE: int = 50
    # Write timeout (in seconds)
    WRITE_TIMEOUT: float = 3.0


class LogSettings(BaseSettings, LogConfigModel):
    """Log settings class."""

    model_config = SettingsConfigDict(
        case_sensitive=True,
        env_file=SystemUtils.get_env_path(),
        env_file_encoding="utf-8",
    )

    @property
    def CONFIG_PATH(self):
        return SystemUtils.get_config_path(self.CONFIG_DIR)

    @property
    def LOG_PATH(self):
        """Gets the log storage path."""
        return self.CONFIG_PATH / "logs"

    @property
    def LOG_MAX_FILE_SIZE_BYTES(self):
        """Converts the log file size to bytes (MB -> Bytes)."""
        return self.LOG_MAX_FILE_SIZE * 1024 * 1024


# Instantiate log settings
log_settings = LogSettings()

# Log level color mapping
level_name_colors = {
    logging.DEBUG: lambda level_name: click.style(str(level_name), fg="cyan"),
    logging.INFO: lambda level_name: click.style(str(level_name), fg="green"),
    logging.WARNING: lambda level_name: click.style(str(level_name), fg="yellow"),
    logging.ERROR: lambda level_name: click.style(str(level_name), fg="red"),
    logging.CRITICAL: lambda level_name: click.style(str(level_name), fg="bright_red"),
}


class CustomFormatter(logging.Formatter):
    """Custom log output format."""

    def __init__(self, fmt=None):
        super().__init__(fmt)

    def format(self, record):
        separator = " " * (8 - len(record.levelname))
        record.leveltext = (
            level_name_colors[record.levelno](record.levelname + ":") + separator
        )
        return super().format(record)


class LogEntry:
    """Log entry."""

    def __init__(
        self, level: str, message: str, file_path: Path, timestamp: datetime = None
    ):
        self.level = level
        self.message = message
        self.file_path = file_path
        self.timestamp: datetime = datetime.now() if timestamp is None else timestamp


class NonBlockingFileHandler:
    """
    Non-blocking file handler - implements log rotation using RotatingFileHandler.
    """

    _instance = None
    _lock = threading.Lock()
    _rotating_handlers = {}

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return

        self._initialized = True
        self._write_queue = queue.Queue(maxsize=log_settings.ASYNC_FILE_QUEUE_SIZE)
        self._executor = ThreadPoolExecutor(
            max_workers=log_settings.ASYNC_FILE_WORKERS, thread_name_prefix="LogWriter"
        )
        self._running = True

        # Start the background writer thread
        self._write_thread = threading.Thread(target=self._batch_writer, daemon=True)
        self._write_thread.start()

    def _get_rotating_handler(self, file_path: Path) -> RotatingFileHandler:
        """Gets or creates a RotatingFileHandler instance."""
        if file_path not in self._rotating_handlers:
            # Ensure the directory exists
            file_path.parent.mkdir(parents=True, exist_ok=True)

            # Create a RotatingFileHandler
            handler = RotatingFileHandler(
                filename=str(file_path),
                maxBytes=log_settings.LOG_MAX_FILE_SIZE_BYTES,
                backupCount=log_settings.LOG_BACKUP_COUNT,
                encoding="utf-8",
            )

            # Set the formatter
            formatter = logging.Formatter(log_settings.LOG_FILE_FORMAT)
            handler.setFormatter(formatter)

            self._rotating_handlers[file_path] = handler

        return self._rotating_handlers[file_path]

    def write_log(self, level: str, message: str, file_path: Path):
        """
        Writes a log - automatically detects the coroutine environment and uses the appropriate method.
        """
        entry = LogEntry(level, message, file_path)

        # Detect if in a coroutine environment
        if self._is_in_event_loop():
            # In a coroutine environment, use non-blocking write
            self._write_non_blocking(entry)
        else:
            # Not in a coroutine environment, write synchronously
            self._write_sync(entry)

    @staticmethod
    def _is_in_event_loop() -> bool:
        """Detects if currently in an event loop."""
        try:
            loop = asyncio.get_running_loop()
            return loop is not None
        except RuntimeError:
            return False

    def _write_non_blocking(self, entry: LogEntry):
        """Non-blocking write (for coroutine environments)."""
        try:
            self._write_queue.put_nowait(entry)
        except queue.Full:
            # If the queue is full, use the thread pool to handle it
            self._executor.submit(self._write_sync, entry)

    @staticmethod
    def _write_sync(entry: LogEntry):
        """Synchronously writes a log."""
        try:
            # Get the RotatingFileHandler instance
            handler = NonBlockingFileHandler()._get_rotating_handler(entry.file_path)

            # Use the emit method of RotatingFileHandler, passing only the original message
            record = logging.LogRecord(
                name="",
                level=getattr(logging, entry.level.upper(), logging.INFO),
                pathname="",
                lineno=0,
                msg=entry.message,
                args=(),
                exc_info=None,
            )
            record.created = entry.timestamp.timestamp()
            handler.emit(record)
        except Exception as e:
            # If file writing fails, at least output to the console
            print(f"Log writing failed {entry.file_path}: {e}")
            print(f"【{entry.level.upper()}】{entry.timestamp} - {entry.message}")

    def _batch_writer(self):
        """Background batch writer thread."""
        while self._running:
            try:
                # Collect a batch of log entries
                batch = []
                end_time = time.time() + log_settings.WRITE_TIMEOUT

                while (
                    len(batch) < log_settings.BATCH_WRITE_SIZE
                    and time.time() < end_time
                ):
                    try:
                        remaining_time = max(0, int(end_time - time.time()))
                        entry = self._write_queue.get(timeout=remaining_time)
                        batch.append(entry)
                    except queue.Empty:
                        break

                if batch:
                    self._write_batch(batch)

            except Exception as e:
                print(f"Batch writer thread error: {e}")
                time.sleep(0.1)

    def _write_batch(self, batch: list):
        """Writes logs in batches."""
        # Group by file
        file_groups = {}
        for entry in batch:
            if entry.file_path not in file_groups:
                file_groups[entry.file_path] = []
            file_groups[entry.file_path].append(entry)

        # Batch write to each file
        for file_path, entries in file_groups.items():
            try:
                # Get the RotatingFileHandler
                handler = self._get_rotating_handler(file_path)

                # Batch write
                for entry in entries:
                    # Use the emit method of RotatingFileHandler, passing only the original message
                    record = logging.LogRecord(
                        name="",
                        level=getattr(logging, entry.level.upper(), logging.INFO),
                        pathname="",
                        lineno=0,
                        msg=entry.message,
                        args=(),
                        exc_info=None,
                    )
                    record.created = entry.timestamp.timestamp()
                    handler.emit(record)
            except Exception as e:
                print(f"Batch write failed {file_path}: {e}")
                # Fallback to writing one by one
                for entry in entries:
                    self._write_sync(entry)

    def shutdown(self):
        """Shuts down the file handler."""
        self._running = False
        if hasattr(self, "_write_thread"):
            self._write_thread.join(timeout=5)
        if self._executor:
            self._executor.shutdown(wait=True)

        # Clear the cache
        self._rotating_handlers.clear()


class LoggerManager:
    """Log management."""

    # Manages all Loggers
    _loggers: dict[str, Any] = {}
    # Default log file name
    _default_log_file = "mitmpilot.log"
    # Thread lock
    _lock = threading.Lock()
    # Non-blocking file handler
    _file_handler = NonBlockingFileHandler()

    def get_logger(self, name: str) -> logging.Logger:
        """Gets an independent logger with a specified name.

        Creates a separate log file, e.g., 'diag_memory.log'.
        :param name: The name of the logger, which will also be used as the filename.
        :return: A configured logging.Logger instance.
        """
        # Use the name as the log file name
        logfile = f"{name}.log"
        with LoggerManager._lock:
            # Check if this logger has already been created
            _logger = self._loggers.get(logfile)
            if not _logger:
                # If not, create a new one using the existing __setup_console_logger
                _logger = self.__setup_console_logger(log_file=logfile)
                self._loggers[logfile] = _logger
        return _logger

    @staticmethod
    def __get_caller():
        """Gets the caller's file name and plugin name.

        If a plugin calls a built-in module, it can also be written to the plugin's log
        file.
        """
        # Caller's file name
        caller_name = None
        # Caller's plugin name
        plugin_name = None

        try:
            frame = sys._getframe(3)  # noqa
        except (AttributeError, ValueError):
            # If the frame cannot be obtained, return the default value
            return "log.py", None

        while frame:
            filepath = Path(frame.f_code.co_filename)
            parts = filepath.parts
            # Set the caller's file name
            if not caller_name:
                if parts[-1] == "__init__.py" and len(parts) >= 2:
                    caller_name = parts[-2]
                else:
                    caller_name = parts[-1]
            # Set the caller's plugin name
            if "app" in parts:
                if not plugin_name and "plugins" in parts:
                    try:
                        plugins_index = parts.index("plugins")
                        if plugins_index + 1 < len(parts):
                            plugin_candidate = parts[plugins_index + 1]
                            if plugin_candidate == "__init__.py":
                                plugin_name = "plugin"
                            else:
                                plugin_name = plugin_candidate
                            break
                    except ValueError:
                        pass
                if "main.py" in parts:
                    # Reached the program's entry point, stop iterating
                    break
            elif len(parts) != 1:
                # Exceeded the program's scope, stop iterating
                break
            # Get the previous frame
            try:
                frame = frame.f_back
            except AttributeError:
                break
        return caller_name or "log.py", plugin_name

    @staticmethod
    def __setup_console_logger(log_file: str):
        """Initializes a console logger instance (file output is handled by
        NonBlockingFileHandler).

        :param log_file: The relative path of the log file.
        """
        log_file_path = log_settings.LOG_PATH / log_file

        # Create a new instance
        _logger = logging.getLogger(log_file_path.stem)

        # Set the log level
        _logger.setLevel(LoggerManager.__get_log_level())

        # Remove existing handlers to avoid duplication
        for handler in _logger.handlers:
            _logger.removeHandler(handler)

        # Set only the console logger (file logging is handled by NonBlockingFileHandler)
        console_handler = logging.StreamHandler()
        console_formatter = CustomFormatter(log_settings.LOG_CONSOLE_FORMAT)
        console_handler.setFormatter(console_formatter)
        _logger.addHandler(console_handler)

        # Prevent propagation to the parent logger
        _logger.propagate = False

        return _logger

    def update_loggers(self):
        """Updates logger instances."""
        with LoggerManager._lock:
            for _logger in self._loggers.values():
                self.__update_logger_handlers(_logger)

    @staticmethod
    def __update_logger_handlers(_logger: logging.Logger):
        """Updates the handler configuration of a Logger.

        :param _logger: The Logger instance to be updated.
        """
        # Update existing handlers (only the console handler)
        for handler in _logger.handlers:
            try:
                if isinstance(handler, logging.StreamHandler):
                    # Update the console output format
                    console_formatter = CustomFormatter(log_settings.LOG_CONSOLE_FORMAT)
                    handler.setFormatter(console_formatter)
            except Exception as e:
                print(f"Failed to update log handler: {handler}. Error: {e}")
        # Update the log level
        _logger.setLevel(LoggerManager.__get_log_level())

    @staticmethod
    def __get_log_level():
        """Gets the current log level."""
        return (
            logging.DEBUG
            if log_settings.DEBUG
            else getattr(logging, log_settings.LOG_LEVEL.upper(), logging.INFO)
        )

    def logger(self, method: str, msg: str, *args, **kwargs):
        """Gets the logger for a module.

        :param method: The log method.
        :param msg: The log message.
        """
        # Get the current log level
        current_level = self.__get_log_level()
        method_level = getattr(logging, method.upper(), logging.INFO)

        # If the current method's level is lower than the set log level, do not process
        if method_level < current_level:
            return

        # Get the caller's file name and plugin name
        caller_name, plugin_name = self.__get_caller()

        # Format the message
        formatted_msg = f"{caller_name} - {msg}"
        if args:
            try:
                formatted_msg = formatted_msg % args
            except (TypeError, ValueError):
                # If formatting fails, concatenate directly
                formatted_msg = f"{formatted_msg} {' '.join(str(arg) for arg in args)}"

        # Differentiate plugin logs
        if plugin_name:
            # Use the plugin log file
            logfile = Path("plugins") / f"{plugin_name}.log"
        else:
            # Use the default log file
            logfile = self._default_log_file

        # Build the full log file path
        log_file_path = log_settings.LOG_PATH / logfile

        # Use the non-blocking file handler to write to the file log
        self._file_handler.write_log(method.upper(), formatted_msg, log_file_path)

        # Also maintain console output (using standard logging)
        with LoggerManager._lock:
            _logger = self._loggers.get(str(logfile))
            if not _logger:
                _logger = self.__setup_console_logger(log_file=str(logfile))
                self._loggers[str(logfile)] = _logger

        # Output only to the console; file writing is already handled by _file_handler
        if hasattr(_logger, method):
            log_method = getattr(_logger, method)
            log_method(formatted_msg)

    def info(self, msg: str, *args, **kwargs):
        """Outputs an info level log."""
        self.logger("info", msg, *args, **kwargs)

    def debug(self, msg: str, *args, **kwargs):
        """Outputs a debug level log."""
        self.logger("debug", msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs):
        """Outputs a warning level log."""
        self.logger("warning", msg, *args, **kwargs)

    def warn(self, msg: str, *args, **kwargs):
        """Outputs a warning level log (compatible)."""
        self.warning(msg, *args, **kwargs)

    def error(self, msg: str, *args, **kwargs):
        """Outputs an error level log."""
        self.logger("error", msg, *args, **kwargs)

    def critical(self, msg: str, *args, **kwargs):
        """Outputs a critical error level log."""
        self.logger("critical", msg, *args, **kwargs)

    @classmethod
    def shutdown(cls):
        """Shuts down the logger manager and cleans up resources."""
        if cls._file_handler:
            cls._file_handler.shutdown()


# Initialize the logger manager
logger = LoggerManager()
