from enum import Enum


# System configuration key dictionary
class SystemConfigKey(Enum):
    # User installed addons
    UserInstalledAddons = "UserInstalledAddons"
    # Addon configuration prefix
    AddonConfigPrefix = "addon"
    # Notification message format template
    NotificationTemplates = "NotificationTemplates"
    # Notification send time
    NotificationSendTime = "NotificationSendTime"
    # Message notification configuration
    Notifications = "Notifications"
    # Notification scenario switch settings
    NotificationSwitches = "NotificationSwitches"
    # Plugin installation statistics
    PluginInstallReport = "PluginInstallReport"
    # Plugin folder grouping configuration
    PluginFolders = "PluginFolders"


# User configuration key dictionary
class UserConfigKey(Enum):
    # Monitoring dashboard
    Dashboard = "Dashboard"


# Synchronous chained events
class ChainEventType(Enum):
    # Authentication verification
    AuthVerification = "auth.verification"
    # Authentication interception
    AuthIntercept = "auth.intercept"
    # Command registration
    CommandRegister = "command.register"
    # Addon service registration
    AddonServiceRegister = "service.register"
    # Addon service deregistration
    AddonServiceDeregister = "service.deregister"


# Asynchronous broadcast events
class EventType(Enum):
    # Addon needs to be reloaded
    AddonReload = "addon.reload"
    # Trigger addon action
    AddonAction = "addon.action"
    # Addon triggered event
    AddonTriggered = "addon.triggered"
    # Execute command
    CommandExcute = "command.excute"
    # Received external user message
    UserMessage = "user.message"
    # Received Webhook message
    WebhookMessage = "webhook.message"
    # Send message notification
    NoticeMessage = "notice.message"
    # System error
    SystemError = "system.error"
    # Module needs to be reloaded
    ModuleReload = "module.reload"
    # Configuration item updated
    ConfigChanged = "config.updated"
    # Message interaction action
    MessageAction = "message.action"
    # Execute workflow
    WorkflowExecute = "workflow.execute"


# Message type
class NotificationType(Enum):
    # Addon message
    Addon = "Addon"
    # Other messages
    Other = "Other"


# Message channel
class MessageChannel(Enum):
    """Message channel."""

    WeChat = "WeChat"
    Telegram = "Telegram"
    Slack = "Slack"
    SynologyChat = "SynologyChat"
    VoceChat = "VoceChat"
    Web = "Web"
    WebPush = "WebPush"


# Module type
class ModuleType(Enum):
    # Message service
    Notification = "notification"
    # Other
    Other = "other"


# Other miscellaneous module types
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
