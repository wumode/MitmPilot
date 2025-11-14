import ast
import json
import queue
import threading
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal

from jinja2 import Template

from app.core.cache import TTLCache
from app.core.config import global_vars
from app.db.systemconfig_oper import SystemConfigOper
from app.log import logger
from app.schemas.message import Notification
from app.schemas.types import SystemConfigKey
from app.utils.singleton import Singleton, SingletonClass
from app.utils.string import StringUtils


class TemplateContextBuilder:
    """Template context builder."""

    def __init__(self):
        self._context = {}

    def build(self, include_raw_objects: bool = True, **kwargs) -> dict[str, Any]:
        """
        :param include_raw_objects: Whether to include raw objects.
        :return: Rendered context dictionary.
        """
        self._context.clear()
        if kwargs:
            self._context.update(kwargs)

        if include_raw_objects:
            self._add_raw_objects()

        # 移除空值
        return {k: v for k, v in self._context.items() if v is not None}

    def _add_raw_objects(self):
        """Add raw object references."""
        raw_objects = {}
        self._context.update(raw_objects)


class TemplateHelper(metaclass=SingletonClass):
    """Template format rendering helper class."""

    def __init__(self):
        self.builder = TemplateContextBuilder()
        self.cache = TTLCache(region="notification", maxsize=100, ttl=600)

    @staticmethod
    def _generate_cache_key(cuntent: str | dict) -> str:
        """Generate cache key."""
        if isinstance(cuntent, dict):
            base_str = cuntent.get("title", "") + cuntent.get("text", "")
            return StringUtils.md5_hash(
                json.dumps(base_str, sort_keys=True, ensure_ascii=False)
            )

        return StringUtils.md5_hash(cuntent)

    def get_cache_context(self, content: str | dict) -> dict | None:
        """Get cached context."""
        cache_key = self._generate_cache_key(content)
        return self.cache.get(cache_key)

    def set_cache_context(self, content: str | dict, context: dict) -> None:
        """Set cached context."""
        cache_key = self._generate_cache_key(content)
        self.cache[cache_key] = context

    def render(
        self,
        template_content: str,
        template_type: Literal["string", "dict", "literal"] = "literal",
        **kwargs,
    ) -> str | dict | None:
        """Render content based on the template.

        :param template_content: Template string.
        :param template_type: Template string type (message notification `literal`, path `string`).
        :param kwargs: Additional business objects.
        :raises ValueError: When an error occurs during template processing.
        :return: Rendered result.
        """
        try:
            # Parse template string
            parsed = self.parse_template_content(template_content, template_type)
            if not parsed:
                raise ValueError("Template parsing failed")

            context = self.builder.build(**kwargs)
            if not context:
                raise ValueError("Context building failed")

            rendered = self.render_with_context(parsed, context)
            if not rendered:
                raise ValueError("Template rendering failed")

            if (
                rendered := rendered
                if template_type == "string"
                else self.__process_formatted_string(rendered)
            ):
                # 缓存上下文
                self.set_cache_context(rendered, context)
                # 返回渲染结果
                return rendered
            return None
        except Exception as e:
            raise ValueError(f"Template processing failed: {str(e)}") from e

    @staticmethod
    def render_with_context(template_content: str, context: dict) -> str:
        """Render a Jinja2 template string with the given context.

        template_content: Jinja2 template string.
        context: Context data for rendering.
        """
        # Render template
        template = Template(template_content)
        return template.render(context)

    @staticmethod
    def parse_template_content(
        template_content: str | dict,
        template_type: Literal["string", "dict", "literal"] = None,
    ) -> str | None:
        """Parse template string.

        :param template_content: Template format string.
        :param template_type: Template string type.
        """

        def parse_literal(_template_content: str) -> str:
            """Parse Python literal."""
            try:
                template_dict = (
                    ast.literal_eval(_template_content)
                    if isinstance(_template_content, str)
                    else _template_content
                )
                if not isinstance(template_dict, dict):
                    raise ValueError("Parsed result must be a dictionary")
                return json.dumps(template_dict, ensure_ascii=False)
            except (ValueError, SyntaxError) as err:
                raise ValueError(f"Invalid Python literal format: {str(err)}") from err

        try:
            if template_type:
                parse_map = {
                    "string": lambda x: str(x),
                    "dict": lambda x: json.dumps(x, ensure_ascii=False),
                    "literal": parse_literal,
                }
                return parse_map[template_type](template_content)

            # Automatically determine the template type
            if isinstance(template_content, dict):
                return json.dumps(template_content, ensure_ascii=False)
            elif isinstance(template_content, str):
                try:
                    json.loads(template_content)
                    return template_content
                except json.JSONDecodeError:
                    try:
                        return parse_literal(template_content)
                    except (ValueError, SyntaxError):
                        return template_content
            else:
                raise ValueError(f"Unsupported template type: {type(template_content)}")

        except Exception as e:
            logger.error(f"Template parsing failed: {str(e)}")
            return None

    @staticmethod
    def __process_formatted_string(rendered: str) -> dict | str | None:
        """Process formatted string.

        Retain escape characters.
        """

        def restore_chars(obj: Any) -> Any:
            """Restore special characters."""
            if isinstance(obj, str):
                return (
                    obj.replace("\n", "\n")
                    .replace("\r", "\r")
                    .replace("\t", "\t")
                    .replace("\b", "\b")
                    .replace("\f", "\f")
                )
            elif isinstance(obj, dict):
                return {k: restore_chars(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [restore_chars(item) for item in obj]
            return obj

        # Define special character mapping
        special_chars = {
            "\n": "\\n",  # Newline
            "\r": "\\r",  # Carriage return
            "\t": "\\t",  # Tab
            "\b": "\\b",  # Backspace
            "\f": "\\f",  # Form feed
        }

        # Process special characters
        processed = rendered
        for char, escape in special_chars.items():
            processed = processed.replace(char, escape)

        # Attempt to parse as JSON
        try:
            rendered_dict = json.loads(processed)
            return restore_chars(rendered_dict)
        except json.JSONDecodeError:
            return rendered

    def close(self):
        """Clean up resources."""
        if self.cache:
            self.cache.close()


class MessageTemplateHelper:
    """Message template renderer."""

    @staticmethod
    def render(message: Notification, *args, **kwargs) -> Notification | None:
        """Render message template."""
        if not MessageTemplateHelper.is_instance_valid(message):
            if MessageTemplateHelper.meets_update_conditions(message, *args, **kwargs):
                logger.info("Rendering message content using template")
                return MessageTemplateHelper._apply_template_data(
                    message, *args, **kwargs
                )
        return message

    @staticmethod
    def is_instance_valid(message: Notification) -> bool:
        """Check if the message is valid."""
        if isinstance(message, Notification):
            return bool(message.title or message.text)
        return False

    @staticmethod
    def meets_update_conditions(message: Notification, *args, **kwargs) -> bool:
        """Check if the message instance update conditions are met.

        Conditions to be met simultaneously:
        1. The message is a valid Notification instance
        2. The message specifies a template type (ctype)
        3. There is template variable data to be rendered
        """
        if isinstance(message, Notification):
            return True if message.ctype and (args or kwargs) else False
        return False

    @staticmethod
    def _get_template(message: Notification) -> str | None:
        """Get the message template."""
        template_dict: dict[str, str] = SystemConfigOper().get(
            SystemConfigKey.NotificationTemplates
        )
        return template_dict.get(f"{message.ctype.value}")

    @staticmethod
    def _apply_template_data(
        message: Notification, *args, **kwargs
    ) -> Notification | None:
        """Update message instance."""
        try:
            if template := MessageTemplateHelper._get_template(message):
                rendered = TemplateHelper().render(
                    *args, template_content=template, **kwargs
                )
                for key, value in rendered.items():
                    if hasattr(message, key):
                        setattr(message, key, value)
            return message
        except Exception as e:
            logger.error(f"Error updating Notification: {str(e)}")
            return message


class MessageQueueManager(metaclass=SingletonClass):
    """Message sending queue manager."""

    def __init__(
        self, send_callback: Callable | None = None, check_interval: int = 10
    ) -> None:
        """Initialize the message queue manager.

        :param send_callback: Callback function for actually sending messages
        :param check_interval: Time check interval (seconds)
        """
        self.schedule_periods: list[tuple[int, int, int, int]] = []

        self.init_config()

        self.queue: queue.Queue[Any] = queue.Queue()
        self.send_callback: Callable | None = send_callback
        self.check_interval: int = check_interval

        self._running = True
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()

    def init_config(self):
        """Initialize configuration."""
        self.schedule_periods = self._parse_schedule(
            SystemConfigOper().get(SystemConfigKey.NotificationSendTime)
        )

    @staticmethod
    def _parse_schedule(periods: list | dict) -> list[tuple[int, int, int, int]]:
        """Convert string time format to a tuple of minutes.

        Supports 'HH:MM' or 'HH:MM:SS' format.
        """
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
                # Process start time
                start_parts = period["start"].split(":")
                if len(start_parts) == 2:
                    start_h, start_m = map(int, start_parts)
                elif len(start_parts) >= 3:
                    start_h, start_m = map(
                        int, start_parts[:2]
                    )  # Only take the first two parts (HH:MM)
                else:
                    continue
                # Process end time
                end_parts = period["end"].split(":")
                if len(end_parts) == 2:
                    end_h, end_m = map(int, end_parts)
                elif len(end_parts) >= 3:
                    end_h, end_m = map(
                        int, end_parts[:2]
                    )  # Only take the first two parts (HH:MM)
                else:
                    continue

                parsed.append((start_h, start_m, end_h, end_m))
            except ValueError as e:
                logger.error(
                    f"Error parsing time period: {period}. "
                    f"Error: {str(e)}. Skipping this period."
                )
                continue
            except Exception as e:
                logger.error(
                    f"Unexpected error parsing time period: {period}. "
                    f"Error: {str(e)}. Skipping this period."
                )
                continue
        return parsed

    @staticmethod
    def _time_to_minutes(time_str: str) -> int:
        """Convert 'HH:MM' format to minutes."""
        hours, minutes = map(int, time_str.split(":"))
        return hours * 60 + minutes

    def _is_in_scheduled_time(self, current_time: datetime) -> bool:
        """Check if the current time is within the allowed sending period."""
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
        """Send a message (immediately or add to queue)."""
        immediately = kwargs.pop("immediately", False)
        if immediately or self._is_in_scheduled_time(datetime.now()):
            self._send(*args, **kwargs)
        else:
            self.queue.put({"args": args, "kwargs": kwargs})
            logger.info(
                f"Message added to queue, current queue size: {self.queue.qsize()}"
            )

    async def async_send_message(self, *args, **kwargs) -> None:
        """Asynchronously send a message (add to queue directly)."""
        kwargs.pop("immediately", False)
        self.queue.put({"args": args, "kwargs": kwargs})
        logger.info(f"Message added to queue, current queue size: {self.queue.qsize()}")

    def _send(self, *args, **kwargs) -> None:
        """Actually send the message (can be customized via callback)."""
        if self.send_callback:
            try:
                logger.info(f"Sending message: {kwargs}")
                self.send_callback(*args, **kwargs)
            except Exception as e:
                logger.error(f"Error sending message: {str(e)}")

    def _monitor_loop(self) -> None:
        """Background thread to loop, check time, and process the queue."""
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
                        logger.info(
                            f"Messages remaining in queue: {self.queue.qsize()}"
                        )
                    except queue.Empty:
                        break
            time.sleep(self.check_interval)

    def stop(self) -> None:
        """Stop the queue manager."""
        self._running = False
        logger.info("Stopping message queue...")
        self.thread.join()
        logger.info("Message queue stopped.")


class MessageHelper(metaclass=Singleton):
    """Message queue manager, including system and user messages."""

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
        """Put a message.

        :param message: The message content.
        :param role: The message channel.
               - system: System message.
               - plugin: Plugin message.
               - user: User message.
        :param title: The title of the message.
        :param note: Attached JSON data.
        """
        if role in ["system", "plugin"]:
            # Get plugin name if title is not provided
            if role == "plugin" and not title:
                title = "Plugin Notification"
            # System notification, default
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
                # Non-system text notification
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
                # Non-system complex structure notification, such as media
                # info/torrent list, etc.
                content = message.to_dict()
                content["title"] = title
                content["date"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                content["note"] = note
                self.user_queue.put(json.dumps(content))

    def get(self, role: str = "system") -> str | None:
        """Get a message.

        :param role: The message channel.
               - system: System message.
               - plugin: Plugin message.
               - user: User message.
        """
        if role == "system":
            if not self.sys_queue.empty():
                return self.sys_queue.get(block=False)
        else:
            if not self.user_queue.empty():
                return self.user_queue.get(block=False)
        return None


def stop_message():
    """Stop the message service."""
    # Stop the message queue
    MessageQueueManager().stop()
