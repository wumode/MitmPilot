from abc import ABCMeta, abstractmethod
from collections.abc import Callable
from typing import TypeVar

from app.helper.service import ServiceConfigHelper
from app.schemas import Notification, NotificationConf
from app.schemas.types import MessageChannel, ModuleType, OtherModulesType


class _ModuleBase(metaclass=ABCMeta):
    """
    模块基类，实现对应方法，在有需要时会被自动调用，返回None代表不启用该模块，将继续执行下一模块
    输入参数与输出参数一致的，或没有输出的，可以被多个模块重复实现
    """

    @abstractmethod
    def init_module(self) -> None:
        """
        模块初始化
        """
        pass

    @abstractmethod
    def init_setting(self) -> tuple[str, str | bool]:
        """
        模块开关设置，返回开关名和开关值，开关值为True时代表有值即打开，不实现该方法或返回None代表不使用开关
        部分模块支持同时开启多个，此时设置项以,分隔，开关值使用in判断
        """
        pass

    @staticmethod
    @abstractmethod
    def get_name() -> str:
        """
        获取模块名称
        """
        pass

    @staticmethod
    @abstractmethod
    def get_type() -> ModuleType:
        """
        获取模块类型
        """
        pass

    @staticmethod
    @abstractmethod
    def get_subtype() -> MessageChannel | OtherModulesType:
        """
        获取模块子类型
        """
        pass

    @staticmethod
    @abstractmethod
    def get_priority() -> int:
        """
        获取模块优先级，数字越小优先级越高，只有同一接口下优先级才生效
        """
        pass

    @abstractmethod
    def stop(self) -> None:
        """
        如果关闭时模块有服务需要停止，需要实现此方法
        :return: None，该方法可被多个模块同时处理
        """
        pass

    @abstractmethod
    def test(self) -> tuple[bool, str] | None:
        """
        模块测试, 返回测试结果和错误信息
        """
        pass


# 定义泛型，用于表示具体的服务类型和配置类型
TService = TypeVar("TService", bound=object)
TConf = TypeVar("TConf")


class ServiceBase[TService, TConf](metaclass=ABCMeta):
    """
    抽象服务基类，负责服务的初始化、获取实例和配置管理
    """

    def __init__(self):
        """
        初始化 ServiceBase 类的实例
        """
        self._configs: dict[str, TConf] | None = None
        self._instances: dict[str, TService] | None = None
        self._service_name: str | None = None

    def init_service(
        self,
        service_name: str,
        service_type: type[TService] | Callable[..., TService] | None = None,
    ):
        """
        初始化服务，获取配置并实例化对应服务

        :param service_name: 服务名称，作为配置匹配的依据
        :param service_type: 服务的类型，可以是类类型（Type[TService]）、工厂函数（Callable）或 None 来跳过实例化
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
            # 通过服务类型或工厂函数来创建实例
            if isinstance(service_type, type):
                # 如果传入的是类类型，调用构造函数实例化
                self._instances[conf.name] = service_type(name=conf.name, **conf.config)
            else:
                # 如果传入的是工厂函数，直接调用工厂函数
                self._instances[conf.name] = service_type(conf)

    def get_instances(self) -> dict[str, TService]:
        """
        获取服务实例列表

        :return: 返回服务实例列表
        """
        instances = self._instances if self._instances else {}
        return instances

    def get_instance(self, name: str | None = None) -> TService | None:
        """
        获取指定名称的服务实例

        :param name: 实例名称，可选。如果为 None，则返回默认实例
        :return: 返回符合条件的服务实例，若不存在则返回 None
        """
        if not self._instances:
            return None
        if name:
            return self._instances.get(name)
        name = self.get_default_config_name()
        return self._instances.get(name) if name else None

    @abstractmethod
    def get_configs(self) -> dict[str, TConf]:
        """
        获取已启用的服务配置字典

        :return: 返回配置字典
        """
        pass

    def get_config(self, name: str | None = None) -> TConf | None:
        """
        获取指定名称的服务配置

        :param name: 配置名称，可选。如果为 None，则返回默认服务配置
        :return: 返回符合条件的配置，若不存在则返回 None
        """
        if not self._configs:
            return None
        if name:
            return self._configs.get(name)
        name = self.get_default_config_name()
        return self._configs.get(name) if name else None

    def get_default_config_name(self) -> str | None:
        """
        获取默认服务配置的名称

        :return: 默认第一个配置的名称
        """
        # 默认使用第一个配置的名称
        first_conf = next(iter(self._configs.values()), None)
        return first_conf.name if first_conf else None


class _MessageBase(ServiceBase[TService, NotificationConf]):
    """
    消息基类
    """

    def __init__(self):
        """
        初始化消息基类，并设置消息通道
        """
        super().__init__()
        self._channel: MessageChannel | None = None

    def get_configs(self) -> dict[str, NotificationConf]:
        """
        获取已启用的消息通知渠道的配置字典

        :return: 返回消息通知的配置字典
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
        """
        检查消息渠道及消息类型，判断是否处理消息

        :param message: 要检查的通知消息
        :param source: 消息来源，可选
        :return: 返回布尔值，表示是否处理该消息
        """
        # 检查消息渠道
        if message.channel and message.channel != self._channel:
            return False
        # 检查消息来源
        if message.source and message.source != source:
            return False
        # 不是定向发送时，检查消息类型开关
        if not message.userid and message.mtype:
            conf = self.get_config(source)
            if conf:
                switchs = conf.switchs or []
                if message.mtype.value not in switchs:
                    return False
        return True
