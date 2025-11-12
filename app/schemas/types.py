from enum import Enum


# 系统配置Key字典
class SystemConfigKey(Enum):
    # 用户已安装的插件
    UserInstalledAddons = "UserInstalledAddons"
    # 插件配置前缀
    AddonConfigPrefix = "addon"
    # 通知消息格式模板
    NotificationTemplates = "NotificationTemplates"
    # 通知发送时间
    NotificationSendTime = "NotificationSendTime"
    # 消息通知配置
    Notifications = "Notifications"
    # 通知场景开关设置
    NotificationSwitchs = "NotificationSwitchs"
    # 插件安装统计
    PluginInstallReport = "PluginInstallReport"
    # 插件文件夹分组配置
    PluginFolders = "PluginFolders"


# 用户配置Key字典
class UserConfigKey(Enum):
    # 监控面板
    Dashboard = "Dashboard"


# 同步链式事件
class ChainEventType(Enum):
    # 认证验证
    AuthVerification = "auth.verification"
    # 认证拦截
    AuthIntercept = "auth.intercept"
    # 命令注册
    CommandRegister = "command.register"
    # 插件服务注册
    AddonServiceRegister = "service.register"
    # 插件服务注销
    AddonServiceDeregister = "service.deregister"


# 异步广播事件
class EventType(Enum):
    # 插件需要重载
    AddonReload = "addon.reload"
    # 触发插件动作
    AddonAction = "addon.action"
    # 插件触发事件
    AddonTriggered = "addon.triggered"
    # 执行命令
    CommandExcute = "command.excute"
    # 收到用户外来消息
    UserMessage = "user.message"
    # 收到Webhook消息
    WebhookMessage = "webhook.message"
    # 发送消息通知
    NoticeMessage = "notice.message"
    # 系统错误
    SystemError = "system.error"
    # 模块需要重载
    ModuleReload = "module.reload"
    # 配置项更新
    ConfigChanged = "config.updated"
    # 消息交互动作
    MessageAction = "message.action"
    # 执行工作流
    WorkflowExecute = "workflow.execute"


# 消息类型
class NotificationType(Enum):
    # 插件消息
    Addon = "Addon"
    # 其它消息
    Other = "Other"


# 消息渠道
class MessageChannel(Enum):
    """消息渠道."""

    Wechat = "Wechat"
    Telegram = "Telegram"
    Slack = "Slack"
    SynologyChat = "SynologyChat"
    VoceChat = "VoceChat"
    Web = "Web"
    WebPush = "WebPush"


# 模块类型
class ModuleType(Enum):
    # 其它
    Other = "other"


# 其他杂项模块类型
class OtherModulesType(Enum):
    # PostgreSQL
    PostgreSQL = "PostgreSQL"
    # Redis
    Redis = "Redis"


class HookEventType(Enum):
    requestheaders = "requestheaders"
    request = "request"
    responseheaders = "responseheaders"
    response = "response"
    error = "error"


class AddonRenderMode(Enum):
    vuetify = "vuetify"
    vue = "vue"
