import os
import platform
import subprocess
from pathlib import Path

import psutil


class SystemUtils:
    @staticmethod
    def get_config_path(config_dir: str | None = None) -> Path:
        """
        获取配置路径
        """
        if not config_dir:
            config_dir = os.getenv("CONFIG_DIR")
        if config_dir:
            return Path(config_dir)
        else:
            return Path(__file__).parents[2] / "config"

    @staticmethod
    def get_env_path() -> Path:
        """
        获取配置路径
        """
        return SystemUtils.get_config_path() / "app.env"

    @staticmethod
    def execute_with_subprocess(pip_command: list) -> tuple[bool, str]:
        """
        执行命令并捕获标准输出和错误输出，记录日志。

        :param pip_command: 要执行的命令，以列表形式提供
        :return: (命令是否成功, 输出信息或错误信息)
        """
        try:
            # 使用 subprocess.run 捕获标准输出和标准错误
            result = subprocess.run(
                pip_command,
                check=True,
                text=True,
                capture_output=True,
            )
            # 合并 stdout 和 stderr
            output = result.stdout + result.stderr
            return True, output
        except subprocess.CalledProcessError as e:
            error_message = (
                f"命令：{' '.join(pip_command)}，执行失败，错误信息：{e.stderr.strip()}"
            )
            return False, error_message
        except Exception as e:
            error_message = f"未知错误，命令：{' '.join(pip_command)}，错误：{str(e)}"
            return False, error_message

    @staticmethod
    def is_macos() -> bool:
        """
        判断是否为MacOS系统
        """
        return platform.system() == "Darwin"

    @staticmethod
    def is_aarch64() -> bool:
        """
        判断是否为ARM64架构
        """
        return platform.machine().lower() in ("aarch64", "arm64")

    @staticmethod
    def is_aarch() -> bool:
        """
        判断是否为ARM32架构
        """
        arch_name = platform.machine().lower()
        return arch_name.startswith(("arm", "aarch")) and arch_name not in (
            "aarch64",
            "arm64",
        )

    @staticmethod
    def is_x86_64() -> bool:
        """
        判断是否为AMD64架构
        """
        return platform.machine().lower() in ("amd64", "x86_64")

    @staticmethod
    def is_x86_32() -> bool:
        """
        判断是否为AMD32架构
        """
        return platform.machine().lower() in ("i386", "i686", "x86", "386", "x86_32")

    @staticmethod
    def cpu_arch() -> str:
        """
        获取CPU架构
        """
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
        """
        获取CPU使用率
        """
        return int(psutil.cpu_percent())

    @staticmethod
    def memory_usage() -> list[int]:
        """
        获取当前程序的内存使用量和使用率
        """
        current_process = psutil.Process()
        process_memory = current_process.memory_info().rss
        system_memory = psutil.virtual_memory().total
        process_memory_percent = (process_memory / system_memory) * 100
        return [process_memory, int(process_memory_percent)]

    @staticmethod
    def network_usage() -> list[int]:
        """
        获取当前网络流量（上行和下行流量，单位：bytes/s）
        """
        import time

        # 获取初始网络统计
        net_io_1 = psutil.net_io_counters()
        time.sleep(1)  # 等待1秒
        # 获取1秒后的网络统计
        net_io_2 = psutil.net_io_counters()

        # 计算1秒内的流量变化
        upload_speed = net_io_2.bytes_sent - net_io_1.bytes_sent
        download_speed = net_io_2.bytes_recv - net_io_1.bytes_recv

        return [int(upload_speed), int(download_speed)]
