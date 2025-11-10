from __future__ import annotations

import json
import queue
import threading
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

from app.core.config import global_vars
from app.db.systemconfig_oper import SystemConfigOper
from app.log import logger
from app.schemas.message import Notification
from app.schemas.types import SystemConfigKey
from app.utils.singleton import Singleton, SingletonClass


class MessageTemplateHelper:
    """消息模板渲染器."""

    @staticmethod
    def render(message: Notification, *args, **kwargs) -> Notification | None:
        """渲染消息模板."""
        if not MessageTemplateHelper.is_instance_valid(message):
            if MessageTemplateHelper.meets_update_conditions(message, *args, **kwargs):
                logger.info("将使用模板渲染消息内容")
                return MessageTemplateHelper._apply_template_data(
                    message, *args, **kwargs
                )
        return message

    @staticmethod
    def is_instance_valid(message: Notification) -> bool:
        """检查消息是否有效."""
        if isinstance(message, Notification):
            return bool(message.title or message.text)
        return False

    @staticmethod
    def meets_update_conditions(message: Notification, *args, **kwargs) -> bool:
        """判断是否满足消息实例更新条件.

        满足条件需同时具备：
        1. 消息为有效Notification实例
        2. 消息指定了模板类型(ctype)
        3. 存在待渲染的模板变量数据
        """
        if isinstance(message, Notification):
            return True if message.ctype and (args or kwargs) else False
        return False

    @staticmethod
    def _get_template(message: Notification) -> str | None:
        """获取消息模板."""
        template_dict: dict[str, str] = SystemConfigOper().get(
            SystemConfigKey.NotificationTemplates
        )
        return template_dict.get(f"{message.ctype.value}")


class MessageQueueManager(metaclass=SingletonClass):
    """消息发送队列管理器."""

    def __init__(
        self, send_callback: Callable | None = None, check_interval: int = 10
    ) -> None:
        """消息队列管理器初始化.

        :param send_callback: 实际发送消息的回调函数
        :param check_interval: 时间检查间隔（秒）
        """
        self.schedule_periods: list[tuple[int, int, int, int]] = []

        self.init_config()

        self.queue: queue.Queue[Any] = queue.Queue()
        self.send_callback = send_callback
        self.check_interval: int = check_interval

        self._running = True
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()

    def init_config(self):
        """初始化配置."""
        self.schedule_periods = self._parse_schedule(
            SystemConfigOper().get(SystemConfigKey.NotificationSendTime)
        )

    @staticmethod
    def _parse_schedule(periods: list | dict) -> list[tuple[int, int, int, int]]:
        """将字符串时间格式转换为分钟数元组 支持格式为 'HH:MM' 或 'HH:MM:SS' 的时间字符串."""
        parsed = []
        if not periods:
            return parsed
        if not isinstance(periods, list):
            periods = [periods]
        for period in periods:
            if not period:
                continue
            if not period.get("start") or not period.get("end"):
                continue
            try:
                # 处理 start 时间
                start_parts = period["start"].split(":")
                if len(start_parts) == 2:
                    start_h, start_m = map(int, start_parts)
                elif len(start_parts) >= 3:
                    start_h, start_m = map(
                        int, start_parts[:2]
                    )  # 只取前两个部分 (HH:MM)
                else:
                    continue
                # 处理 end 时间
                end_parts = period["end"].split(":")
                if len(end_parts) == 2:
                    end_h, end_m = map(int, end_parts)
                elif len(end_parts) >= 3:
                    end_h, end_m = map(int, end_parts[:2])  # 只取前两个部分 (HH:MM)
                else:
                    continue

                parsed.append((start_h, start_m, end_h, end_m))
            except ValueError as e:
                logger.error(
                    f"解析时间周期时出现错误：{period}. 错误：{str(e)}. 跳过此周期。"
                )
                continue
            except Exception as e:
                logger.error(
                    f"解析时间周期时出现意外错误：{period}. 错误：{str(e)}. 跳过此周期。"
                )
                continue
        return parsed

    @staticmethod
    def _time_to_minutes(time_str: str) -> int:
        """将 'HH:MM' 格式转换为分钟数."""
        hours, minutes = map(int, time_str.split(":"))
        return hours * 60 + minutes

    def _is_in_scheduled_time(self, current_time: datetime) -> bool:
        """检查当前时间是否在允许发送的时间段内."""
        if not self.schedule_periods:
            return True
        current_minutes = current_time.hour * 60 + current_time.minute
        for period in self.schedule_periods:
            s_h, s_m, e_h, e_m = period
            start = s_h * 60 + s_m
            end = e_h * 60 + e_m

            if start <= end:
                if start <= current_minutes <= end:
                    return True
            else:
                if current_minutes >= start or current_minutes <= end:
                    return True
        return False

    def send_message(self, *args, **kwargs) -> None:
        """发送消息（立即发送或加入队列）"""
        immediately = kwargs.pop("immediately", False)
        if immediately or self._is_in_scheduled_time(datetime.now()):
            self._send(*args, **kwargs)
        else:
            self.queue.put({"args": args, "kwargs": kwargs})
            logger.info(f"消息已加入队列，当前队列长度：{self.queue.qsize()}")

    async def async_send_message(self, *args, **kwargs) -> None:
        """异步发送消息（直接加入队列）"""
        kwargs.pop("immediately", False)
        self.queue.put({"args": args, "kwargs": kwargs})
        logger.info(f"消息已加入队列，当前队列长度：{self.queue.qsize()}")

    def _send(self, *args, **kwargs) -> None:
        """实际发送消息（可通过回调函数自定义）"""
        if self.send_callback:
            try:
                logger.info(f"发送消息：{kwargs}")
                self.send_callback(*args, **kwargs)
            except Exception as e:
                logger.error(f"发送消息错误：{str(e)}")

    def _monitor_loop(self) -> None:
        """后台线程循环检查时间并处理队列."""
        while self._running:
            current_time = datetime.now()
            if self._is_in_scheduled_time(current_time):
                while not self.queue.empty():
                    if global_vars.is_system_stopped:
                        break
                    if not self._is_in_scheduled_time(datetime.now()):
                        break
                    try:
                        message = self.queue.get_nowait()
                        self._send(*message["args"], **message["kwargs"])
                        logger.info(f"队列剩余消息：{self.queue.qsize()}")
                    except queue.Empty:
                        break
            time.sleep(self.check_interval)

    def stop(self) -> None:
        """停止队列管理器."""
        self._running = False
        logger.info("正在停止消息队列...")
        self.thread.join()
        logger.info("消息队列已停止")


class MessageHelper(metaclass=Singleton):
    """消息队列管理器，包括系统消息和用户消息."""

    def __init__(self):
        self.sys_queue = queue.Queue()
        self.user_queue = queue.Queue()

    def put(
        self,
        message: Any,
        role: str = "plugin",
        title: str = None,
        note: list | dict = None,
    ):
        """存消息 :param message: 消息 :param role: 消息通道 systm：系统消息，plugin：插件消息，user：用户消息
        :param title: 标题 :param note: 附件json."""
        if role in ["system", "plugin"]:
            # 没有标题时获取插件名称
            if role == "plugin" and not title:
                title = "插件通知"
            # 系统通知，默认
            self.sys_queue.put(
                json.dumps(
                    {
                        "type": role,
                        "title": title,
                        "text": message,
                        "date": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                        "note": note,
                    }
                )
            )
        else:
            if isinstance(message, str):
                # 非系统的文本通知
                self.user_queue.put(
                    json.dumps(
                        {
                            "title": title,
                            "text": message,
                            "date": time.strftime(
                                "%Y-%m-%d %H:%M:%S", time.localtime()
                            ),
                            "note": note,
                        }
                    )
                )
            elif hasattr(message, "to_dict"):
                # 非系统的复杂结构通知，如媒体信息/种子列表等。
                content = message.to_dict()
                content["title"] = title
                content["date"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                content["note"] = note
                self.user_queue.put(json.dumps(content))

    def get(self, role: str = "system") -> str | None:
        """取消息 :param role: 消息通道 systm：系统消息，plugin：插件消息，user：用户消息."""
        if role == "system":
            if not self.sys_queue.empty():
                return self.sys_queue.get(block=False)
        else:
            if not self.user_queue.empty():
                return self.user_queue.get(block=False)
        return None


def stop_message():
    """停止消息服务."""
    # 停止消息队列
    MessageQueueManager().stop()
