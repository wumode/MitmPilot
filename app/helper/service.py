from collections.abc import Iterator
from typing import TypeVar

from app.core.module import ModuleManager
from app.db.systemconfig_oper import SystemConfigOper
from app.schemas import NotificationConf, NotificationSwitchConf, ServiceInfo
from app.schemas.types import ModuleType, NotificationType, SystemConfigKey

TConf = TypeVar("TConf")


class ServiceConfigHelper:
    """Configuration helper class for retrieving different types of service
    configurations."""

    @staticmethod
    def get_configs(config_key: SystemConfigKey, conf_type: type) -> list:
        """Generic method to retrieve configurations, gets configurations based on
        config_key and returns a list of specified type.

        :param config_key: The key for the system configuration
        :param conf_type: The class type used to instantiate the configuration object
        :return: A list of configuration objects
        """
        config_data = SystemConfigOper().get(config_key)
        if not config_data:
            return []
        # Directly use conf_type to instantiate configuration objects
        return [conf_type(**conf) for conf in config_data]

    @staticmethod
    def get_notification_configs() -> list[NotificationConf]:
        """Retrieves the configuration for message notification channels."""
        return ServiceConfigHelper.get_configs(
            SystemConfigKey.Notifications, NotificationConf
        )

    @staticmethod
    def get_notification_switches() -> list[NotificationSwitchConf]:
        """Retrieves the switches for message notification scenarios."""
        return ServiceConfigHelper.get_configs(
            SystemConfigKey.NotificationSwitches, NotificationSwitchConf
        )

    @staticmethod
    def get_notification_switch(mtype: NotificationType) -> str | None:
        """Retrieves the switch for a specified type of message notification
        scenario."""
        switches = ServiceConfigHelper.get_notification_switches()
        for switch in switches:
            if switch.type == mtype.value:
                return switch.action
        return None


class ServiceBaseHelper[TConf]:
    """Generic service helper class, abstracting common logic for retrieving
    configurations and service instances."""

    def __init__(
        self,
        config_key: SystemConfigKey,
        conf_type: type[TConf],
        module_type: ModuleType,
    ):
        self.modulemanager = ModuleManager()
        self.config_key = config_key
        self.conf_type = conf_type
        self.module_type = module_type

    def get_configs(self, include_disabled: bool = False) -> dict[str, TConf]:
        """Retrieves the list of configurations.

        :param include_disabled: Whether to include disabled configurations, defaults to
            False (only enabled configurations are returned)
        :return: Dictionary of configurations
        """
        configs: list[TConf] = ServiceConfigHelper.get_configs(
            self.config_key, self.conf_type
        )
        return (
            {
                config.name: config
                for config in configs
                if (config.name and config.type and config.enabled) or include_disabled
            }
            if configs
            else {}
        )

    def get_config(self, name: str) -> TConf | None:
        """Retrieves the configuration with the specified name."""
        if not name:
            return None
        configs = self.get_configs()
        return configs.get(name)

    def iterate_module_instances(self) -> Iterator[ServiceInfo]:
        """Iterates through instances of all modules and their corresponding
        configurations, returning ServiceInfo instances."""
        configs = self.get_configs()
        for module in self.modulemanager.get_running_type_modules(self.module_type):
            if not module:
                continue
            module_instances = module.get_instances()
            if not isinstance(module_instances, dict):
                continue
            for name, instance in module_instances.items():
                if not instance:
                    continue
                config = configs.get(name)
                service_info = ServiceInfo(
                    name=name,
                    instance=instance,
                    module=module,
                    type=config.type if config else None,
                    config=config,
                )
                yield service_info

    def get_services(
        self, type_filter: str | None = None, name_filters: list[str] | None = None
    ) -> dict[str, ServiceInfo]:
        """Retrieves a list of service information, filtered by type and name list.

        :param type_filter: The service type to filter by
        :param name_filters: A list of service names to filter by
        :return: A dictionary of filtered service information
        """
        name_filters_set = set(name_filters) if name_filters else None

        return {
            service_info.name: service_info
            for service_info in self.iterate_module_instances()
            if service_info.config
            and (type_filter is None or service_info.type == type_filter)
            and (name_filters_set is None or service_info.name in name_filters_set)
        }

    def get_service(
        self, name: str, type_filter: str | None = None
    ) -> ServiceInfo | None:
        """Retrieves service information for the specified name, filtered by type.

        :param name: Service name
        :param type_filter: The service type to filter by
        :return: Corresponding service information, or None if not found or type does
            not match
        """
        if not name:
            return None
        for service_info in self.iterate_module_instances():
            if service_info.name == name:
                if service_info.config and (
                    type_filter is None or service_info.type == type_filter
                ):
                    return service_info
        return None
