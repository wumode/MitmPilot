import os
import platform
import subprocess
from pathlib import Path

import psutil


class SystemUtils:
    @staticmethod
    def get_config_path(config_dir: str | None = None) -> Path:
        """Gets the configuration path."""
        if not config_dir:
            config_dir = os.getenv("CONFIG_DIR")
        if config_dir:
            return Path(config_dir)
        else:
            return Path(__file__).parents[2] / "config"

    @staticmethod
    def get_env_path() -> Path:
        """Gets the environment file path."""
        return SystemUtils.get_config_path() / "app.env"

    @staticmethod
    def execute_with_subprocess(pip_command: list) -> tuple[bool, str]:
        """Executes a command, captures standard output and error output, and logs them.

        :param pip_command: The command to execute, provided as a list
        :return:
            - if the command was successful
            - information or error message
        """
        try:
            # Use subprocess.run to capture stdout and stderr
            result = subprocess.run(
                pip_command,
                check=True,
                text=True,
                capture_output=True,
            )
            # Merge stdout and stderr
            output = result.stdout + result.stderr
            return True, output
        except subprocess.CalledProcessError as e:
            error_message = f"Command: {' '.join(pip_command)}, failed to execute, error message: {e.stderr.strip()}"
            return False, error_message
        except Exception as e:
            error_message = (
                f"Unknown error, command: {' '.join(pip_command)}, error: {str(e)}"
            )
            return False, error_message

    @staticmethod
    def is_macos() -> bool:
        """Checks if the operating system is macOS."""
        return platform.system() == "Darwin"

    @staticmethod
    def is_aarch64() -> bool:
        """Checks if the CPU architecture is ARM64."""
        return platform.machine().lower() in ("aarch64", "arm64")

    @staticmethod
    def is_aarch() -> bool:
        """Checks if the CPU architecture is ARM32."""
        arch_name = platform.machine().lower()
        return arch_name.startswith(("arm", "aarch")) and arch_name not in (
            "aarch64",
            "arm64",
        )

    @staticmethod
    def is_x86_64() -> bool:
        """Checks if the CPU architecture is AMD64 (x86_64)"""
        return platform.machine().lower() in ("amd64", "x86_64")

    @staticmethod
    def is_x86_32() -> bool:
        """Checks if the CPU architecture is AMD32 (x86_32)"""
        return platform.machine().lower() in ("i386", "i686", "x86", "386", "x86_32")

    @staticmethod
    def cpu_arch() -> str:
        """Gets the CPU architecture."""
        if SystemUtils.is_x86_64():
            return "x86_64"
        elif SystemUtils.is_x86_32():
            return "x86_32"
        elif SystemUtils.is_aarch64():
            return "Arm64"
        elif SystemUtils.is_aarch():
            return "Arm32"
        else:
            return platform.machine()

    @staticmethod
    def cpu_usage() -> int:
        """Gets CPU usage percentage."""
        return int(psutil.cpu_percent())

    @staticmethod
    def memory_usage() -> list[int]:
        """Gets the current program's memory usage and percentage."""
        current_process = psutil.Process()
        process_memory = current_process.memory_info().rss
        system_memory = psutil.virtual_memory().total
        process_memory_percent = (process_memory / system_memory) * 100
        return [process_memory, int(process_memory_percent)]

    @staticmethod
    def network_usage() -> list[int]:
        """Gets current network traffic (upload and download, in bytes/s)"""
        import time

        # Get initial network statistics
        net_io_1 = psutil.net_io_counters()
        time.sleep(1)  # Wait for 1 second
        # Get network statistics after 1 second
        net_io_2 = psutil.net_io_counters()

        # Calculate traffic change within 1 second
        upload_speed = net_io_2.bytes_sent - net_io_1.bytes_sent
        download_speed = net_io_2.bytes_recv - net_io_1.bytes_recv

        return [int(upload_speed), int(download_speed)]
