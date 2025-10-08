from typing import Any

from pydantic import BaseModel, Field


class ServiceInfo(BaseModel):
    """
    封装服务相关信息的数据类
    """

    # 名称
    name: str
    # 实例
    instance: Any | None = None
    # 模块
    module: Any | None = None
    # 类型
    type: str | None = None
    # 配置
    config: Any | None = None


class NotificationConf(BaseModel):
    """
    通知配置
    """

    # 名称
    name: str
    # 类型 telegram/wechat/vocechat/synologychat/slack/webpush
    type: str | None = None
    # 配置
    config: dict | None = Field(default_factory=dict)
    # 场景开关
    switchs: list | None = Field(default_factory=list)
    # 是否启用
    enabled: bool | None = False


class NotificationSwitchConf(BaseModel):
    """
    通知场景开关配置
    """

    # 场景名称
    type: str = None
    # 通知范围 all/user/admin
    action: str | None = "all"
