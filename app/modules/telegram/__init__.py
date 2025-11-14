import copy
import json
import re
from typing import Any

from app.core.event import Event, eventmanager
from app.log import logger
from app.modules import _MessageBase, _ModuleBase
from app.modules.telegram.telegram import Telegram
from app.schemas import (
    ComingMessage,
    CommandRegisterEventData,
    ConfigChangeEventData,
    Notification,
    NotificationConf,
)
from app.schemas.types import (
    ChainEventType,
    EventType,
    MessageChannel,
    ModuleType,
    SystemConfigKey,
)
from app.utils.structures import DictUtils


class TelegramModule(_ModuleBase, _MessageBase[Telegram]):
    def init_module(self) -> None:
        """Initializes the module."""
        super().init_service(
            service_name=Telegram.__name__.lower(), service_type=Telegram
        )
        self._channel = MessageChannel.Telegram

    @eventmanager.register(EventType.ConfigChanged)
    def handle_config_changed(self, event: Event):
        """Handles configuration change events.

        :param event: The event object.
        """
        if not event:
            return
        event_data: ConfigChangeEventData = event.event_data
        if event_data.key not in [SystemConfigKey.Notifications.value]:
            return
        logger.info("Configuration changed, reloading Telegram module...")
        self.init_module()

    @staticmethod
    def get_name() -> str:
        return "Telegram"

    @staticmethod
    def get_type() -> ModuleType:
        """Gets the module type."""
        return ModuleType.Notification

    @staticmethod
    def get_subtype() -> MessageChannel:
        """Gets the module subtype."""
        return MessageChannel.Telegram

    @staticmethod
    def get_priority() -> int:
        """Gets the module priority.

        Lower numbers mean higher priority. Only effective for the same interface.
        """
        return 0

    def stop(self):
        """Stops the module."""
        for client in self.get_instances().values():
            client.stop()

    def test(self) -> tuple[bool, str] | None:
        """Tests the module's connectivity."""
        if not self.get_instances():
            return None
        for name, client in self.get_instances().items():
            state = client.get_state()
            if not state:
                return False, f"Telegram {name} is not ready"
        return True, ""

    def init_setting(self) -> tuple[str, str | bool]:
        pass

    def message_parser(
        self, source: str, body: Any, form: Any, args: Any
    ) -> ComingMessage | None:
        """Parses message content and returns a dictionary, noting the following
        conventions:

            - userid: User ID
            - username: Username
            - text: Content

        :param source: Message source
        :param body: Request body
        :param form: Form data
        :param args: Arguments
        :return: Channel, message body
        """
        """
            Normal message format:
            {
                'update_id': ,
                'message': {
                    'message_id': 'xx',
                    'from': {
                        'id': ,
                        'is_bot': False,
                        'first_name': '',
                        'username': '',
                        'language_code': 'zh-hans'
                    },
                    'chat': {
                        'id': ,
                        'first_name': '',
                        'username': '',
                        'type': 'private'
                    },
                    'date': ,
                    'text': ''
                }
            }

            Button callback format:
            {
                'callback_query': {
                    'id': '',
                    'from': {...},
                    'message': {...},
                    'data': 'callback_data'
                }
            }
        """
        # Get service configuration
        client_config = self.get_config(source)
        if not client_config:
            return None
        client: Telegram | None = self.get_instance(client_config.name)
        if not client:
            return None
        try:
            message: dict = json.loads(body)
        except Exception as err:
            logger.debug(f"Failed to parse Telegram message: {str(err)}")
            return None

        if message:
            # Handle button callbacks
            if "callback_query" in message:
                return self._handle_callback_query(message, client_config)

            # Handle regular messages
            return self._handle_text_message(message, client_config, client)

        return None

    @staticmethod
    def _handle_callback_query(
        message: dict, client_config: NotificationConf
    ) -> ComingMessage | None:
        """Handles button callback queries."""
        callback_query: dict = message.get("callback_query", {})
        user_info = callback_query.get("from", {})
        callback_data = callback_query.get("data", "")
        user_id = user_info.get("id")
        user_name = user_info.get("username")

        if callback_data and user_id:
            logger.info(
                f"Received Telegram button callback from {client_config.name}: "
                f"userid={user_id}, username={user_name}, callback_data={callback_data}"
            )

            # Return callback_data as a special format text for the main program to
            # recognize it as a button callback
            callback_text = f"CALLBACK:{callback_data}"

            # Create CommingMessage containing complete callback information
            return ComingMessage(
                channel=MessageChannel.Telegram,
                source=client_config.name,
                userid=user_id,
                username=user_name,
                text=callback_text,
                is_callback=True,
                callback_data=callback_data,
                message_id=callback_query.get("message", {}).get("message_id"),
                chat_id=str(
                    callback_query.get("message", {}).get("chat", {}).get("id", "")
                ),
                callback_query=callback_query,
            )
        return None

    def _handle_text_message(
        self, msg: dict, client_config: NotificationConf, client: Telegram
    ) -> ComingMessage | None:
        """Handles regular text messages."""
        text: str | None = msg.get("text")
        user_id = msg.get("from", {}).get("id")
        user_name = msg.get("from", {}).get("username")
        # Extract chat_id to enable correct reply targeting
        chat_id = msg.get("chat", {}).get("id")

        if text and user_id:
            logger.info(
                f"Received Telegram message from {client_config.name}: "
                f"userid={user_id}, username={user_name}, "
                f"chat_id={chat_id}, text={text}"
            )

            # Clean bot mentions from text to ensure consistent processing
            cleaned_text = self._clean_bot_mention(
                text, client.bot_username if client else None
            )

            # Check permissions
            admin_users = client_config.config.get("TELEGRAM_ADMINS")
            user_list = client_config.config.get("TELEGRAM_USERS")
            config_chat_id = client_config.config.get("TELEGRAM_CHAT_ID")

            if cleaned_text.startswith("/"):
                if (
                    admin_users
                    and str(user_id) not in admin_users.split(",")
                    and str(user_id) != config_chat_id
                ):
                    client.send_msg(
                        title="Only administrators have permission to execute this command",
                        userid=user_id,
                    )
                    return None
            else:
                if user_list and str(user_id) not in user_list.split(","):
                    logger.info(
                        f"User {user_id} is not in the user whitelist, "
                        f"cannot use this bot"
                    )
                    client.send_msg(
                        title="You are not in the user whitelist, cannot use this bot",
                        userid=user_id,
                    )
                    return None

            return ComingMessage(
                channel=MessageChannel.Telegram,
                source=client_config.name,
                userid=user_id,
                username=user_name,
                text=cleaned_text,  # Use cleaned text
                chat_id=str(chat_id) if chat_id else None,
            )
        return None

    @staticmethod
    def _clean_bot_mention(text: str, bot_username: str | None) -> str:
        """Cleans the @bot part from the message to ensure consistent text processing.

        :param text: Original message text
        :param bot_username: Bot username
        :return: Cleaned text.
        """
        if not text or not bot_username:
            return text

        # Remove @bot_username from the beginning and any position in text
        cleaned = text
        mention_pattern = f"@{bot_username}"

        if cleaned.startswith(mention_pattern):
            cleaned = cleaned[len(mention_pattern) :].lstrip()

        # Remove mention at any other position
        cleaned = cleaned.replace(mention_pattern, "").strip()

        # Clean up multiple spaces
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        return cleaned

    def post_message(self, message: Notification) -> None:
        """Sends a message.

        :param message: Message body
        :return: Success or failure.
        """
        for conf in self.get_configs().values():
            if not self.check_message(message, conf.name):
                continue
            targets = message.targets
            userid = message.userid
            if not userid and targets is not None:
                userid = targets.get("telegram_userid")
                if not userid:
                    logger.warn(
                        "User did not specify Telegram user ID, message cannot be sent"
                    )
                    return
            client: Telegram | None = self.get_instance(conf.name)
            if client:
                if message.original_message_id:
                    original_message_id = int(message.original_message_id)
                else:
                    original_message_id = None
                client.send_msg(
                    title=message.title,
                    text=message.text,
                    image=message.image,
                    userid=f"{userid}",
                    link=message.link,
                    buttons=message.buttons,
                    original_message_id=original_message_id,
                    original_chat_id=message.original_chat_id,
                )

    def delete_message(
        self,
        channel: MessageChannel,
        source: str,
        message_id: int,
        chat_id: int | None = None,
    ) -> bool:
        """Deletes a message.

        :param channel: Message channel
        :param source: Specified message source
        :param message_id: Message ID
        :param chat_id: Chat ID
        :return: Whether the deletion was successful.
        """
        success = False
        for conf in self.get_configs().values():
            if channel != self._channel:
                break
            if source != conf.name:
                continue
            client: Telegram | None = self.get_instance(conf.name)
            if client:
                result = client.delete_msg(message_id=message_id, chat_id=chat_id)
                if result:
                    success = True
        return success

    def register_commands(self, commands: dict[str, dict]):
        """Registers commands, this function receives the system's available command
        menu.

        :param commands: Command dictionary.
        """
        for client_config in self.get_configs().values():
            client = self.get_instance(client_config.name)
            if not client:
                continue

            # Trigger event, allowing command data adjustment. Deep copy is needed
            # here to avoid instance sharing
            scoped_commands = copy.deepcopy(commands)
            event = eventmanager.send_event(
                ChainEventType.CommandRegister,
                CommandRegisterEventData(
                    commands=scoped_commands,
                    origin="Telegram",
                    service=client_config.name,
                ),
            )

            # If the event returns valid event_data, use the adjusted commands from
            # the event
            if event and event.event_data:
                event_data: CommandRegisterEventData = event.event_data
                # If the event is canceled, skip command registration and clear
                # the menu
                if event_data.cancel:
                    client.delete_commands()
                    logger.debug(
                        f"Command registration for {client_config.name} "
                        f"canceled by event: {event_data.source}"
                    )
                    continue
                scoped_commands = event_data.commands or {}
                if not scoped_commands:
                    logger.debug("Filtered commands are empty, skipping registration.")
                    client.delete_commands()

            # scoped_commands must be a subset of commands
            filtered_scoped_commands = DictUtils.filter_keys_to_subset(
                scoped_commands, commands
            )
            # If filtered_scoped_commands is empty, skip registration
            if not filtered_scoped_commands:
                logger.debug("Filtered commands are empty, skipping registration.")
                client.delete_commands()
                continue
            # Compare adjusted commands with current commands
            if filtered_scoped_commands != commands:
                logger.debug(
                    f"Command set has changed, Updating new commands: "
                    f"{filtered_scoped_commands}"
                )
            client.register_commands(filtered_scoped_commands)
