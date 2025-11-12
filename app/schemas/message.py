from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel, Field

from app.schemas.types import MessageChannel, NotificationType


class ComingMessage(BaseModel):
    """Incoming message."""

    # User ID
    userid: str | int | None = None
    # User name
    username: str | None = None
    # Message channel
    channel: MessageChannel | None = None
    # Source (channel name)
    source: str | None = None
    # Message body
    text: str | None = None
    # Time
    date: str | None = None
    # Message direction
    action: int | None = 0
    # Whether it is a callback message
    is_callback: bool | None = False
    # Callback data
    callback_data: str | None = None
    # Message ID (for locating the original message during callback)
    message_id: str | int | None = None
    # Chat ID (for locating the chat during callback)
    chat_id: str | None = None
    # Complete callback query information (raw data)
    callback_query: dict | None = None

    def to_dict(self):
        """Convert to dictionary."""
        items = self.model_dump()
        for k, v in items.items():
            if isinstance(v, MessageChannel):
                items[k] = v.value
        return items


class Notification(BaseModel):
    """"""

    # Message channel
    channel: MessageChannel | None = None
    # Message source
    source: str | None = None
    # Message type
    mtype: NotificationType | None = None
    # Title
    title: str | None = None
    # Text content
    text: str | None = None
    # Image
    image: str | None = None
    # Link
    link: str | None = None
    # User ID
    userid: str | int | None = None
    # User name
    username: str | None = None
    # Time
    date: str | None = None
    # Message direction
    action: int | None = 1
    # Dictionary of target user IDs for the message, used when no user ID is specified
    targets: dict | None = None
    # TODO: using pydantic model for button
    # Button list, format: [[{"text": "Button text", "callback_data": "Callback data", "url": "Link"}]]
    buttons: list[list[dict]] | None = None
    # Original message ID, for editing messages
    original_message_id: str | int | None = None
    # Original chat ID of the message, for editing messages
    original_chat_id: str | None = None

    def to_dict(self):
        """Convert to dictionary."""
        items = self.model_dump()
        for k, v in items.items():
            if isinstance(v, MessageChannel) or isinstance(v, NotificationType):
                items[k] = v.value
        return items


class NotificationSwitch(BaseModel):
    """Message switch."""

    # Message type
    mtype: str | None = None
    # WeChat switch
    wechat: bool | None = False
    # TG switch
    telegram: bool | None = False
    # Slack switch
    slack: bool | None = False
    # SynologyChat switch
    synologychat: bool | None = False
    # VoceChat switch
    vocechat: bool | None = False
    # WebPush switch
    webpush: bool | None = False


class Subscription(BaseModel):
    """Client message subscription."""

    endpoint: str | None = None
    keys: dict | None = Field(default_factory=dict)


class SubscriptionMessage(BaseModel):
    """Client subscription message body."""

    title: str | None = None
    body: str | None = None
    icon: str | None = None
    url: str | None = None
    data: dict | None = Field(default_factory=dict)


class ChannelCapability(Enum):
    """Channel capability enumeration."""

    # Support inline buttons
    INLINE_BUTTONS = "inline_buttons"
    # Support menu commands
    MENU_COMMANDS = "menu_commands"
    # Support message editing
    MESSAGE_EDITING = "message_editing"
    # Support message deletion
    MESSAGE_DELETION = "message_deletion"
    # Support callback queries
    CALLBACK_QUERIES = "callback_queries"
    # Support rich text
    RICH_TEXT = "rich_text"
    # Support images
    IMAGES = "images"
    # Support links
    LINKS = "links"
    # Support file sending
    FILE_SENDING = "file_sending"


@dataclass
class ChannelCapabilities:
    """Channel capability configuration."""

    channel: MessageChannel
    capabilities: set[ChannelCapability]
    max_buttons_per_row: int = 5
    max_button_rows: int = 10
    max_button_text_length: int = 30
    fallback_enabled: bool = True


class ChannelCapabilityManager:
    """Channel capability manager."""

    _capabilities: dict[MessageChannel, ChannelCapabilities] = {
        MessageChannel.Telegram: ChannelCapabilities(
            channel=MessageChannel.Telegram,
            capabilities={
                ChannelCapability.INLINE_BUTTONS,
                ChannelCapability.MENU_COMMANDS,
                ChannelCapability.MESSAGE_EDITING,
                ChannelCapability.MESSAGE_DELETION,
                ChannelCapability.CALLBACK_QUERIES,
                ChannelCapability.RICH_TEXT,
                ChannelCapability.IMAGES,
                ChannelCapability.LINKS,
                ChannelCapability.FILE_SENDING,
            },
            max_buttons_per_row=4,
            max_button_rows=10,
            max_button_text_length=30,
        ),
        MessageChannel.Wechat: ChannelCapabilities(
            channel=MessageChannel.Wechat,
            capabilities={
                ChannelCapability.IMAGES,
                ChannelCapability.LINKS,
                ChannelCapability.MENU_COMMANDS,
            },
            fallback_enabled=True,
        ),
        MessageChannel.Slack: ChannelCapabilities(
            channel=MessageChannel.Slack,
            capabilities={
                ChannelCapability.INLINE_BUTTONS,
                ChannelCapability.MESSAGE_EDITING,
                ChannelCapability.MESSAGE_DELETION,
                ChannelCapability.CALLBACK_QUERIES,
                ChannelCapability.RICH_TEXT,
                ChannelCapability.IMAGES,
                ChannelCapability.LINKS,
                ChannelCapability.MENU_COMMANDS,
            },
            max_buttons_per_row=3,
            max_button_rows=8,
            max_button_text_length=25,
            fallback_enabled=True,
        ),
        MessageChannel.SynologyChat: ChannelCapabilities(
            channel=MessageChannel.SynologyChat,
            capabilities={
                ChannelCapability.RICH_TEXT,
                ChannelCapability.IMAGES,
                ChannelCapability.LINKS,
            },
            fallback_enabled=True,
        ),
        MessageChannel.VoceChat: ChannelCapabilities(
            channel=MessageChannel.VoceChat,
            capabilities={
                ChannelCapability.RICH_TEXT,
                ChannelCapability.IMAGES,
                ChannelCapability.LINKS,
            },
            fallback_enabled=True,
        ),
        MessageChannel.WebPush: ChannelCapabilities(
            channel=MessageChannel.WebPush,
            capabilities={ChannelCapability.LINKS},
            fallback_enabled=True,
        ),
        MessageChannel.Web: ChannelCapabilities(
            channel=MessageChannel.Web,
            capabilities={
                ChannelCapability.RICH_TEXT,
                ChannelCapability.IMAGES,
                ChannelCapability.LINKS,
            },
            fallback_enabled=True,
        ),
    }

    @classmethod
    def get_capabilities(cls, channel: MessageChannel) -> ChannelCapabilities | None:
        """Get channel capabilities."""
        return cls._capabilities.get(channel)

    @classmethod
    def supports_capability(
        cls, channel: MessageChannel, capability: ChannelCapability
    ) -> bool:
        """Check if the channel supports a certain capability."""
        channel_caps = cls.get_capabilities(channel)
        if not channel_caps:
            return False
        return capability in channel_caps.capabilities

    @classmethod
    def supports_buttons(cls, channel: MessageChannel) -> bool:
        """Check if the channel supports buttons."""
        return cls.supports_capability(channel, ChannelCapability.INLINE_BUTTONS)

    @classmethod
    def supports_callbacks(cls, channel: MessageChannel) -> bool:
        """Check if the channel supports callbacks."""
        return cls.supports_capability(channel, ChannelCapability.CALLBACK_QUERIES)

    @classmethod
    def supports_editing(cls, channel: MessageChannel) -> bool:
        """Check if the channel supports message editing."""
        return cls.supports_capability(channel, ChannelCapability.MESSAGE_EDITING)

    @classmethod
    def supports_deletion(cls, channel: MessageChannel) -> bool:
        """Check if the channel supports message deletion."""
        return cls.supports_capability(channel, ChannelCapability.MESSAGE_DELETION)

    @classmethod
    def get_max_buttons_per_row(cls, channel: MessageChannel) -> int:
        """Get the maximum number of buttons per row."""
        channel_caps = cls.get_capabilities(channel)
        return channel_caps.max_buttons_per_row if channel_caps else 2

    @classmethod
    def get_max_button_rows(cls, channel: MessageChannel) -> int:
        """Get the maximum number of button rows."""
        channel_caps = cls.get_capabilities(channel)
        return channel_caps.max_button_rows if channel_caps else 5

    @classmethod
    def get_max_button_text_length(cls, channel: MessageChannel) -> int:
        """Get the maximum length of button text."""
        channel_caps = cls.get_capabilities(channel)
        return channel_caps.max_button_text_length if channel_caps else 20

    @classmethod
    def should_use_fallback(cls, channel: MessageChannel) -> bool:
        """Whether to use a fallback strategy."""
        channel_caps = cls.get_capabilities(channel)
        return channel_caps.fallback_enabled if channel_caps else True
