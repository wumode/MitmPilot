from abc import ABCMeta, abstractmethod
from collections.abc import Callable
from typing import TypeVar

from app.helper.service import ServiceConfigHelper
from app.schemas import Notification, NotificationConf
from app.schemas.types import MessageChannel, ModuleType, OtherModulesType


class _ModuleBase(metaclass=ABCMeta):
    """Base class for modules.

    Implement the corresponding methods, which will be called automatically when needed.
    Returning None means that the module is not enabled, and the next module will be
    executed. Modules with the same input and output parameters, or with no output, can
    be implemented by multiple modules repeatedly.
    """

    @abstractmethod
    def init_module(self) -> None:
        """Initializes the module."""
        pass

    @abstractmethod
    def init_setting(self) -> tuple[str, str | bool]:
        """Module switch setting.

        Returns the switch name and switch value. If the switch value is True, it means
        that the module is enabled if it has a value. Not implementing this method or
        returning None means that the switch is not used. Some modules support enabling
        multiple instances at the same time. In this case, the settings are separated by
        commas, and the switch value is checked using 'in'.
        """
        pass

    @staticmethod
    @abstractmethod
    def get_name() -> str:
        """Gets the module name."""
        pass

    @staticmethod
    @abstractmethod
    def get_type() -> ModuleType:
        """Gets the module type."""
        pass

    @staticmethod
    @abstractmethod
    def get_subtype() -> MessageChannel | OtherModulesType:
        """Gets the module subtype."""
        pass

    @staticmethod
    @abstractmethod
    def get_priority() -> int:
        """Gets the module priority.

        The smaller the number, the higher the priority. The priority is only effective
        under the same interface.
        """
        pass

    @abstractmethod
    def stop(self) -> None:
        """If the module has a service that needs to be stopped when it is closed, this
        method needs to be implemented.

        :return: None. This method can be processed by multiple modules at the same
            time.
        """
        pass

    @abstractmethod
    def test(self) -> tuple[bool, str] | None:
        """Tests the module.

        Returns the test result and error message.
        """
        pass


# Define generics to represent specific service and configuration types
TService = TypeVar("TService", bound=object)
TConf = TypeVar("TConf")


class ServiceBase[TService, TConf](metaclass=ABCMeta):
    """Abstract base class for services, responsible for service initialization,
    instance retrieval, and configuration management."""

    def __init__(self):
        """Initializes an instance of the ServiceBase class."""
        self._configs: dict[str, TConf] | None = None
        self._instances: dict[str, TService] | None = None
        self._service_name: str | None = None

    def init_service(
        self,
        service_name: str,
        service_type: type[TService] | Callable[..., TService] | None = None,
    ):
        """Initializes the service, gets the configuration, and instantiates the
        corresponding service.

        :param service_name: The name of the service, used as the basis for
            configuration matching.
        :param service_type: The type of the service, which can be a class type
            (Type[TService]), a factory function (Callable), or None to skip
            instantiation.
        """
        if not service_name:
            raise Exception("service_name is null")
        self._service_name = service_name
        configs = self.get_configs()
        if configs is None:
            return
        self._configs = configs
        self._instances = {}
        if not service_type:
            return
        for conf in self._configs.values():
            # Create an instance through the service type or factory function
            if isinstance(service_type, type):
                # If a class type is passed in, call the constructor to instantiate
                self._instances[conf.name] = service_type(name=conf.name, **conf.config)
            else:
                # If a factory function is passed in, call the factory function directly
                self._instances[conf.name] = service_type(conf)

    def get_instances(self) -> dict[str, TService]:
        """Gets the list of service instances.

        :return: The list of service instances.
        """
        instances = self._instances if self._instances else {}
        return instances

    def get_instance(self, name: str | None = None) -> TService | None:
        """Gets the service instance with the specified name.

        :param name: The name of the instance, optional. If None, the default instance
            is returned.
        :return: The matching service instance, or None if it does not exist.
        """
        if not self._instances:
            return None
        if name:
            return self._instances.get(name)
        name = self.get_default_config_name()
        return self._instances.get(name) if name else None

    @abstractmethod
    def get_configs(self) -> dict[str, TConf]:
        """Gets the dictionary of enabled service configurations.

        :return: Returns the configuration dictionary.
        """
        pass

    def get_config(self, name: str | None = None) -> TConf | None:
        """Gets the service configuration with the specified name.

        :param name: The name of the configuration, optional. If None, the default
            service configuration is returned.
        :return: The matching configuration, or None if it does not exist.
        """
        if not self._configs:
            return None
        if name:
            return self._configs.get(name)
        name = self.get_default_config_name()
        return self._configs.get(name) if name else None

    def get_default_config_name(self) -> str | None:
        """Gets the name of the default service configuration.

        :return: The name of the first configuration by default.
        """
        # Use the name of the first configuration by default
        first_conf = next(iter(self._configs.values()), None)
        return first_conf.name if first_conf else None


class _MessageBase(ServiceBase[TService, NotificationConf]):
    """Base class for messages."""

    def __init__(self):
        """Initializes the message base class and sets the message channel."""
        super().__init__()
        self._channel: MessageChannel | None = None

    def get_configs(self) -> dict[str, NotificationConf]:
        """Gets the configuration dictionary of enabled message notification channels.

        :return: The configuration dictionary for message notifications.
        """
        configs = ServiceConfigHelper.get_notification_configs()
        if not self._service_name:
            return {}
        return {
            conf.name: conf
            for conf in configs
            if conf.type == self._service_name and conf.enabled
        }

    def check_message(self, message: Notification, source: str = None) -> bool:
        """Checks the message channel and message type to determine whether to process
        the message.

        :param message: The notification message to check.
        :param source: The source of the message, optional.
        :return: Whether to process the message.
        """
        # Check the message channel
        if message.channel and message.channel != self._channel:
            return False
        # Check the message source
        if message.source and message.source != source:
            return False
        # When not sending directly, check the message type switch
        if not message.userid and message.mtype:
            conf = self.get_config(source)
            if conf:
                switches = conf.switches or []
                if message.mtype.value not in switches:
                    return False
        return True
