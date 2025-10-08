import inspect
import traceback
from typing import Any

from fastapi.concurrency import run_in_threadpool

from app.core.addon import AddonManager
from app.core.event import EventManager
from app.core.module import ModuleManager
from app.helper.message import MessageHelper, MessageQueueManager
from app.log import logger
from app.schemas import ComingMessage
from app.schemas.types import EventType, MessageChannel
from app.utils.object import ObjectUtils


class ChainBase:
    """
    Processing chain base class
    """

    def __init__(self):
        """
        Public initialization
        """
        self.modulemanager = ModuleManager()
        self.eventmanager = EventManager()
        self.addonmanager = AddonManager()
        self.messagehelper = MessageHelper()
        self.messagequeue = MessageQueueManager(send_callback=self.run_module)

    @staticmethod
    def __is_valid_empty(ret):
        """
        Judge whether the result is empty
        """
        if isinstance(ret, tuple):
            return all(value is None for value in ret)
        else:
            return ret is None

    def __handle_plugin_error(
        self, err: Exception, plugin_id: str, plugin_name: str, method: str, **kwargs
    ):
        """
        Handle plugin module execution errors
        """
        if kwargs.get("raise_exception"):
            raise
        logger.error(
            f"Error running plugin {plugin_id} module {method}: {str(err)}\n{traceback.format_exc()}"
        )
        self.messagehelper.put(
            title=f"{plugin_name} has an error", message=str(err), role="plugin"
        )
        self.eventmanager.send_event(
            EventType.SystemError,
            {
                "type": "plugin",
                "addon_id": plugin_id,
                "plugin_name": plugin_name,
                "plugin_method": method,
                "error": str(err),
                "traceback": traceback.format_exc(),
            },
        )

    def __handle_system_error(
        self, err: Exception, module_id: str, module_name: str, method: str, **kwargs
    ):
        """
        Handle system module execution errors
        """
        if kwargs.get("raise_exception"):
            raise
        logger.error(
            f"Error running module {module_id}.{method}: {str(err)}\n{traceback.format_exc()}"
        )
        self.messagehelper.put(
            title=f"{module_name} has an error", message=str(err), role="system"
        )
        self.eventmanager.send_event(
            EventType.SystemError,
            {
                "type": "module",
                "module_id": module_id,
                "module_name": module_name,
                "module_method": method,
                "error": str(err),
                "traceback": traceback.format_exc(),
            },
        )

    def __execute_addon_modules(self, method: str, result: Any, *args, **kwargs) -> Any:
        """
        Execute plugin module
        """
        for plugin, module_dict in self.addonmanager.get_addon_modules().items():
            plugin_id, plugin_name = plugin
            if method in module_dict:
                func = module_dict[method]
                if func:
                    try:
                        logger.info(
                            f"Request plugin {plugin_name} to execute: {method} ..."
                        )
                        if self.__is_valid_empty(result):
                            # Return None, execute for the first time or need to continue to execute the next module
                            result = func(*args, **kwargs)
                        elif isinstance(result, list):
                            # Return as a list, merge when there are multiple module running results
                            temp = func(*args, **kwargs)
                            if isinstance(temp, list):
                                result.extend(temp)
                        else:
                            break
                    except Exception as err:
                        self.__handle_plugin_error(
                            err, plugin_id, plugin_name, method, **kwargs
                        )
        return result

    async def __async_execute_plugin_modules(
        self, method: str, result: Any, *args, **kwargs
    ) -> Any:
        """
        Asynchronously execute plugin modules
        """
        for plugin, module_dict in self.addonmanager.get_addon_modules().items():
            plugin_id, plugin_name = plugin
            if method in module_dict:
                func = module_dict[method]
                if func:
                    try:
                        logger.info(
                            f"Request plugin {plugin_name} to execute: {method} ..."
                        )
                        if self.__is_valid_empty(result):
                            # Return None, execute for the first time or need to continue to execute the next module
                            if inspect.iscoroutinefunction(func):
                                result = await func(*args, **kwargs)
                            else:
                                # The plugin synchronous function runs in an asynchronous environment to avoid blocking
                                result = await run_in_threadpool(func, *args, **kwargs)
                        elif isinstance(result, list):
                            # Return as a list, merge when there are multiple module running results
                            if inspect.iscoroutinefunction(func):
                                temp = await func(*args, **kwargs)
                            else:
                                # The plugin synchronous function runs in an asynchronous environment to avoid blocking
                                temp = await run_in_threadpool(func, *args, **kwargs)
                            if isinstance(temp, list):
                                result.extend(temp)
                        else:
                            break
                    except Exception as err:
                        self.__handle_plugin_error(
                            err, plugin_id, plugin_name, method, **kwargs
                        )
        return result

    def __execute_system_modules(
        self, method: str, result: Any, *args, **kwargs
    ) -> Any:
        """
        Execute system module
        """
        logger.debug(f"Request system module to execute: {method} ...")
        for module in sorted(
            self.modulemanager.get_running_modules(method),
            key=lambda x: x.get_priority(),
        ):
            module_id = module.__class__.__name__
            try:
                module_name = module.get_name()
            except Exception as err:
                logger.debug(f"Error getting module name: {str(err)}")
                module_name = module_id
            try:
                func = getattr(module, method)
                if self.__is_valid_empty(result):
                    # Return None, execute for the first time or need to continue to execute the next module
                    result = func(*args, **kwargs)
                elif ObjectUtils.check_signature(func, result):
                    # The return result is consistent with the method signature, and the result is passed in
                    result = func(result)
                elif isinstance(result, list):
                    # Return as a list, merge when there are multiple module running results
                    temp = func(*args, **kwargs)
                    if isinstance(temp, list):
                        result.extend(temp)
                else:
                    # Abort and continue execution
                    break
            except Exception as err:
                self.__handle_system_error(
                    err, module_id, module_name, method, **kwargs
                )
        return result

    async def __async_execute_system_modules(
        self, method: str, result: Any, *args, **kwargs
    ) -> Any:
        """
        Asynchronously execute system modules
        """
        logger.debug(f"Request system module to execute: {method} ...")
        for module in sorted(
            self.modulemanager.get_running_modules(method),
            key=lambda x: x.get_priority(),
        ):
            module_id = module.__class__.__name__
            try:
                module_name = module.get_name()
            except Exception as err:
                logger.debug(f"Error getting module name: {str(err)}")
                module_name = module_id
            try:
                func = getattr(module, method)
                if self.__is_valid_empty(result):
                    # Return None, execute for the first time or need to continue to execute the next module
                    if inspect.iscoroutinefunction(func):
                        result = await func(*args, **kwargs)
                    else:
                        result = func(*args, **kwargs)
                elif ObjectUtils.check_signature(func, result):
                    # The return result is consistent with the method signature, and the result is passed in
                    if inspect.iscoroutinefunction(func):
                        result = await func(result)
                    else:
                        result = func(result)
                elif isinstance(result, list):
                    # Return as a list, merge when there are multiple module running results
                    if inspect.iscoroutinefunction(func):
                        temp = await func(*args, **kwargs)
                    else:
                        temp = func(*args, **kwargs)
                    if isinstance(temp, list):
                        result.extend(temp)
                else:
                    # Abort and continue execution
                    break
            except Exception as err:
                self.__handle_system_error(
                    err, module_id, module_name, method, **kwargs
                )
        return result

    def run_module(self, method: str, *args, **kwargs) -> Any:
        """
        Run all modules that contain this method,
        and then return the result
        When kwargs contains the named parameter raise_exception,
        if the module method throws an exception and raise_exception is True, the exception is thrown synchronously
        """
        result = None

        # Execute plugin module
        result = self.__execute_addon_modules(method, result, *args, **kwargs)

        if not self.__is_valid_empty(result) and not isinstance(result, list):
            # The plugin module returns a result that is not empty and not a list, and returns directly
            return result

        # Execute system module
        return self.__execute_system_modules(method, result, *args, **kwargs)

    async def async_run_module(self, method: str, *args, **kwargs) -> Any:
        """
        Asynchronously run all modules that contain this method,
        and then return the result
        When kwargs contains the named parameter raise_exception,
        if the module method throws an exception and raise_exception is True, the exception is thrown synchronously
        Support mixed calls of asynchronous and synchronous methods
        """
        result = None

        # Execute plugin module
        result = await self.__async_execute_plugin_modules(
            method, result, *args, **kwargs
        )

        if not self.__is_valid_empty(result) and not isinstance(result, list):
            # The plugin module returns a result that is not empty and not a list, and returns directly
            return result

        # Execute system module
        return await self.__async_execute_system_modules(
            method, result, *args, **kwargs
        )

    def message_parser(
        self, source: str, body: Any, form: Any, args: Any
    ) -> ComingMessage | None:
        """
        Parse the message content, return a dictionary, pay attention to the following agreed values:
        userid: User ID
        username: User name
        text: Content
        :param source: Message source (channel configuration name)
        :param body: Request body
        :param form: Form
        :param args: Parameters
        :return: Message channel, message content
        """
        return self.run_module(
            "message_parser", source=source, body=body, form=form, args=args
        )

    def delete_message(
        self,
        channel: MessageChannel,
        source: str,
        message_id: str | int,
        chat_id: str | int | None = None,
    ) -> bool:
        """
        Delete message
        :param channel: Message channel
        :param source: Message source (specify a specific message module)
        :param message_id: Message ID
        :param chat_id: Chat ID (such as group ID)
        :return: Whether the deletion was successful
        """
        return self.run_module(
            "delete_message",
            channel=channel,
            source=source,
            message_id=message_id,
            chat_id=chat_id,
        )

    def register_commands(self, commands: dict[str, dict]) -> None:
        """
        Register menu commands
        """
        self.run_module("register_commands", commands=commands)

    def scheduler_job(self) -> None:
        """
        Scheduled task, called every 10 minutes,
        the module implements this interface to achieve scheduled services
        """
        self.run_module("scheduler_job")

    def clear_cache(self) -> None:
        """
        Clear the cache, the module implements this interface to respond to the clear cache event
        """
        self.run_module("clear_cache")
