import re
import threading
import uuid
from collections.abc import Callable
from pathlib import Path
from threading import Event
from urllib.parse import urljoin

import telebot
from telebot import apihelper
from telebot.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
    InputMediaPhoto,
)

from app.core.config import settings
from app.log import logger
from app.utils.common import retry
from app.utils.http import RequestUtils


class RetryException(Exception):
    pass


class Telegram:
    _ds_url = (
        f"http://127.0.0.1:{settings.PORT}/api/v1/message?token={settings.API_TOKEN}"
    )
    _event = Event()
    _bot: telebot.TeleBot = None
    _callback_handlers: dict[str, Callable] = {}  # Stores callback handlers
    _user_chat_mapping: dict[
        str, str
    ] = {}  # userid -> chat_id mapping for reply targeting
    _bot_username: str | None = None  # Bot username for mention detection
    _escape_chars = r"_*[]()~`>#+-=|{}.!"  # Telegram MarkdownV2
    _markdown_escape_pattern = re.compile(
        f"([{re.escape(_escape_chars)}])"
    )  # Regex pattern to escape special characters according to Telegram MarkdownV2 rules

    def __init__(
        self,
        TELEGRAM_TOKEN: str | None = None,
        TELEGRAM_CHAT_ID: str | None = None,
        **kwargs,
    ):
        """Initializes parameters."""
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
            logger.error("Telegram configuration is incomplete!")
            return
        # Token
        self._telegram_token = TELEGRAM_TOKEN
        # Chat Id
        self._telegram_chat_id = TELEGRAM_CHAT_ID
        # Initialize bot
        if self._telegram_token and self._telegram_chat_id:
            # Telegram bot API address, format: https://api.telegram.org
            if kwargs.get("API_URL"):
                apihelper.API_URL = urljoin(kwargs["API_URL"], "/bot{0}/{1}")
                apihelper.FILE_URL = urljoin(kwargs["API_URL"], "/file/bot{0}/{1}")
            else:
                apihelper.proxy = settings.PROXY
            # bot
            _bot = telebot.TeleBot(self._telegram_token, parse_mode="MarkdownV2")
            # Record handle
            self._bot = _bot
            # Get and store bot username for @ detection
            try:
                bot_info = _bot.get_me()
                self._bot_username = bot_info.username
                logger.info(f"Telegram bot username: @{self._bot_username}")
            except Exception as e:
                logger.error(f"Failed to get bot information: {e}")
                self._bot_username = None

            # Mark channel source
            if kwargs.get("name"):
                self._ds_url = f"{self._ds_url}&source={kwargs.get('name')}"

            @_bot.message_handler(commands=["start", "help"])
            def send_welcome(message):
                _bot.reply_to(
                    message,
                    "Tip: Send a name directly or `subscribe`+name to search or "
                    "subscribe to movies and TV series",
                )

            @_bot.message_handler(func=lambda message: True)
            def echo_all(message):
                # Update user-chat mapping when receiving messages
                self._update_user_chat_mapping(message.from_user.id, message.chat.id)

                # Check if we should process this message
                if self._should_process_message(message):
                    RequestUtils(timeout=15).post_res(self._ds_url, json=message.json)

            @_bot.callback_query_handler(func=lambda call: True)
            def callback_query(call):
                """Handles button click callbacks."""
                try:
                    # Update user-chat mapping for callbacks too
                    self._update_user_chat_mapping(
                        call.from_user.id, call.message.chat.id
                    )

                    # Parse callback data
                    callback_data = call.data
                    user_id = str(call.from_user.id)

                    logger.info(
                        f"Received button callback: {callback_data}, user: {user_id}"
                    )

                    # Send callback data to the main program for processing
                    callback_json = {
                        "callback_query": {
                            "id": call.id,
                            "from": call.from_user.to_dict(),
                            "message": {
                                "message_id": call.message.message_id,
                                "chat": {
                                    "id": call.message.chat.id,
                                },
                            },
                            "data": callback_data,
                        }
                    }

                    # Acknowledge callback first to prevent user from seeing loading state
                    _bot.answer_callback_query(call.id)

                    # Send to main program for processing
                    RequestUtils(timeout=15).post_res(self._ds_url, json=callback_json)

                except Exception as err:
                    logger.error(f"Failed to process button callback: {str(err)}")
                    _bot.answer_callback_query(
                        call.id, "Processing failed, please try again"
                    )

            def run_polling():
                """Defines the thread function to run infinity_polling."""
                try:
                    _bot.infinity_polling(long_polling_timeout=30, logger_level=None)
                except Exception as err:
                    logger.error(
                        f"Telegram message receiving service exception: {str(err)}"
                    )

            # Start thread to run infinity_polling
            self._polling_thread = threading.Thread(target=run_polling, daemon=True)
            self._polling_thread.start()
            logger.info("Telegram message receiving service started")

    @property
    def bot_username(self) -> str | None:
        """Gets the bot username.

        :return: Bot username or None.
        """
        return self._bot_username

    def _update_user_chat_mapping(self, userid: int, chat_id: int) -> None:
        """Updates the user-chat mapping.

        :param userid: User ID
        :param chat_id: Chat ID.
        """
        if userid and chat_id:
            self._user_chat_mapping[str(userid)] = str(chat_id)

    def _get_user_chat_id(self, userid: str) -> str | None:
        """Gets the chat ID corresponding to the user.

        :param userid: User ID
        :return: Chat ID or None.
        """
        return self._user_chat_mapping.get(str(userid)) if userid else None

    def _should_process_message(self, message) -> bool:
        """Determines whether this message should be processed.

        :param message: Telegram message object
        :return: Whether to process.
        """
        # Private messages are always processed
        if message.chat.type == "private":
            logger.debug(f"Processing private message: user {message.from_user.id}")
            return True

        # Command messages in group chats are always processed (starting with /)
        if message.text and message.text.startswith("/"):
            logger.debug(f"Processing group command message: {message.text[:20]}...")
            return True

        # Check if bot was @mentioned in group chat
        if message.chat.type in ["group", "supergroup"]:
            if not self._bot_username:
                # If bot username is not obtained, process all messages for safety
                logger.debug("Bot username not obtained, processing all group messages")
                return True

            # Check if @bot_username is in the message text
            if message.text and f"@{self._bot_username}" in message.text:
                logger.debug(
                    f"@{self._bot_username} detected, processing group message"
                )
                return True

            # Check if bot is mentioned in message entities
            if message.entities:
                for entity in message.entities:
                    if entity.type == "mention":
                        mention_text = message.text[
                            entity.offset : entity.offset + entity.length
                        ]
                        if mention_text == f"@{self._bot_username}":
                            logger.debug(
                                f"@{self._bot_username} detected via entity, "
                                f"processing group message"
                            )
                            return True

            # If bot is not @mentioned in group chat, do not process
            logger.debug(
                f"Group message not @mentioned bot, skipping processing: "
                f"{message.text[:30] if message.text else 'No text'}..."
            )
            return False

        # Other chat types are processed by default
        logger.debug(f"Processing other chat type message: {message.chat.type}")
        return True

    def get_state(self) -> bool:
        """Gets the state."""
        return self._bot is not None

    def send_msg(
        self,
        title: str | None,
        text: str | None = None,
        image: str | None = None,
        userid: str | None = None,
        link: str | None = None,
        buttons: list[list[dict]] | None = None,
        original_message_id: int | None = None,
        original_chat_id: str | None = None,
    ) -> bool | None:
        """Sends a Telegram message.

        :param title: Message title
        :param text: Message content
        :param image: Message image URL
        :param userid: Target user ID for sending the message. If empty, sends to
            administrator.
        :param link: Link to jump to
        :param buttons: Button list, format: [[{"text": "Button text", "callback_data":
            "Callback data"}]]
        :param original_message_id: Original message ID, if provided, edits the original
            message
        :param original_chat_id: Chat ID of the original message, required when editing
            messages
        """
        if not self._telegram_token or not self._telegram_chat_id:
            return None

        if not title and not text:
            logger.warn("Title and content cannot be empty at the same time")
            return False

        try:
            if title:
                title = self.escape_markdown(title)
            if text:
                # Escape Markdown special characters in text
                text = self.escape_markdown(text)
                caption = f"*{title}*\n{text}"
            else:
                caption = f"*{title}*"

            if link:
                caption = f"{caption}\n[View Details]({link})"

            # Determine target chat_id with improved logic using user mapping
            chat_id = self._determine_target_chat_id(userid, original_chat_id)

            # Create button keyboard
            reply_markup = None
            if buttons:
                reply_markup = self._create_inline_keyboard(buttons)

            # Determine whether to edit an existing message or send a new one
            if original_message_id and original_chat_id:
                # Edit message
                return self.__edit_message(
                    original_chat_id, original_message_id, caption, buttons, image
                )
            else:
                # Send new message
                return self.__send_request(
                    userid=chat_id,
                    image=image,
                    caption=caption,
                    reply_markup=reply_markup,
                )

        except Exception as msg_e:
            logger.error(f"Failed to send message: {msg_e}")
            return False

    def _determine_target_chat_id(
        self, userid: str | None = None, original_chat_id: str | None = None
    ) -> str:
        """Determines the target chat ID, using user mapping to ensure replies go to the
        correct chat.

        :param userid: User ID
        :param original_chat_id: Chat ID of the original message
        :return: Target chat ID.
        """
        # 1. Prioritize using the original message's chat ID (for editing messages)
        if original_chat_id:
            return original_chat_id

        # 2. If userid is provided, try to get the user's chat ID from the mapping
        if userid:
            mapped_chat_id = self._get_user_chat_id(userid)
            if mapped_chat_id:
                return mapped_chat_id
            # If not in mapping, fall back to using userid as chat ID (for private chats)
            return userid

        # 3. Finally, use the default chat ID
        return self._telegram_chat_id

    @staticmethod
    def _create_inline_keyboard(buttons: list[list[dict]]) -> InlineKeyboardMarkup:
        """Creates an inline keyboard.

        :param buttons: Button configuration, format: [[{"text": "Button text",
            "callback_data": "Callback data", "url": "link"}]]
        :return: InlineKeyboardMarkup object.
        """
        keyboard = []
        for row in buttons:
            button_row = []
            for button in row:
                if "url" in button:
                    # URL button
                    btn = InlineKeyboardButton(text=button["text"], url=button["url"])
                else:
                    # Callback button
                    btn = InlineKeyboardButton(
                        text=button["text"], callback_data=button["callback_data"]
                    )
                button_row.append(btn)
            keyboard.append(button_row)
        return InlineKeyboardMarkup(keyboard)

    def answer_callback_query(
        self, callback_query_id: int, text: str | None = None, show_alert: bool = False
    ) -> bool | None:
        """Answers a callback query."""
        if not self._bot:
            return None

        try:
            self._bot.answer_callback_query(
                callback_query_id, text=text, show_alert=show_alert
            )
            return True
        except Exception as e:
            logger.error(f"Failed to answer callback query: {str(e)}")
            return False

    def delete_msg(self, message_id: int, chat_id: int | None = None) -> bool | None:
        """Deletes a Telegram message.

        :param message_id: Message ID
        :param chat_id: Chat ID
        :return: Whether the deletion was successful.
        """
        if not self._telegram_token or not self._telegram_chat_id:
            return None

        try:
            # Determine the chat ID for the message to be deleted
            if chat_id:
                target_chat_id = chat_id
            else:
                target_chat_id = self._telegram_chat_id

            # Delete message
            result = self._bot.delete_message(
                chat_id=target_chat_id, message_id=int(message_id)
            )
            if result:
                logger.info(
                    f"Successfully deleted Telegram message: chat_id={target_chat_id}, "
                    f"message_id={message_id}"
                )
                return True
            else:
                logger.error(
                    f"Failed to delete Telegram message: chat_id={target_chat_id}, "
                    f"message_id={message_id}"
                )
                return False
        except Exception as e:
            logger.error(f"Exception while deleting Telegram message: {str(e)}")
            return False

    def __edit_message(
        self,
        chat_id: str,
        message_id: int,
        text: str,
        buttons: list[list[dict]] | None = None,
        image: str | None = None,
    ) -> bool | None:
        """Edits a sent message.

        :param chat_id: Chat ID
        :param message_id: Message ID
        :param text: New message content
        :param buttons: Button list
        :param image: Image URL or path
        :return: Whether the edit was successful.
        """
        if not self._bot:
            return None

        try:
            # Create button keyboard
            reply_markup = None
            if buttons:
                reply_markup = self._create_inline_keyboard(buttons)

            if image:
                # If there is an image, use edit_message_media
                media = InputMediaPhoto(
                    media=image, caption=text, parse_mode="MarkdownV2"
                )
                self._bot.edit_message_media(
                    chat_id=chat_id,
                    message_id=message_id,
                    media=media,
                    reply_markup=reply_markup,
                )
            else:
                # If there is no image, use edit_message_text
                self._bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode="MarkdownV2",
                    reply_markup=reply_markup,
                )
            return True
        except Exception as e:
            logger.error(f"Failed to edit message: {str(e)}")
            return False

    @retry(RetryException, logger=logger)
    def __send_request(
        self,
        userid: str | None = None,
        image: str | None = None,
        caption="",
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> bool:
        """Sends a message to Telegram.

        :param reply_markup: Inline keyboard.
        """
        if image:
            res = RequestUtils(
                proxies=settings.PROXY, ua=settings.NORMAL_USER_AGENT
            ).get_res(image)
            if res is None:
                raise Exception("Failed to get image")
            if res.content:
                # Use a random identifier to construct the full path of the image file
                # and write the image content to the file
                image_file = Path(settings.TEMP_PATH) / "telegram" / str(uuid.uuid4())
                if not image_file.parent.exists():
                    image_file.parent.mkdir(parents=True, exist_ok=True)
                image_file.write_bytes(res.content)
                photo = InputFile(image_file)
                # Send image to Telegram
                ret = self._bot.send_photo(
                    chat_id=userid or self._telegram_chat_id,
                    photo=photo,
                    caption=caption,
                    parse_mode="MarkdownV2",
                    reply_markup=reply_markup,
                )
                if ret is None:
                    raise RetryException("Failed to send image message")
                return True
        # Send messages in segments of 4096
        ret = None
        if len(caption) > 4095:
            for i in range(0, len(caption), 4095):
                ret = self._bot.send_message(
                    chat_id=userid or self._telegram_chat_id,
                    text=caption[i : i + 4095],
                    parse_mode="MarkdownV2",
                    reply_markup=reply_markup if i == 0 else None,
                )
        else:
            ret = self._bot.send_message(
                chat_id=userid or self._telegram_chat_id,
                text=caption,
                parse_mode="MarkdownV2",
                reply_markup=reply_markup,
            )
        if ret is None:
            raise RetryException("Failed to send text message")
        return True if ret else False

    def register_commands(self, commands: dict[str, dict]):
        """Registers menu commands."""
        if not self._bot:
            return
        # Set bot commands
        if commands:
            self._bot.delete_my_commands()
            self._bot.set_my_commands(
                commands=[
                    telebot.types.BotCommand(cmd[1:], str(desc.get("description")))
                    for cmd, desc in commands.items()
                ]
            )

    def delete_commands(self):
        """Cleans up menu commands."""
        if not self._bot:
            return
        # Clean up menu commands
        self._bot.delete_my_commands()

    def stop(self):
        """Stops the Telegram message receiving service."""
        if self._bot:
            self._bot.stop_polling()
            self._polling_thread.join()
            logger.info("Telegram message receiving service stopped")

    def escape_markdown(self, text: str) -> str:
        # Escape special characters according to Telegram MarkdownV2 rules
        if not isinstance(text, str):
            return str(text) if text is not None else ""
        return self._markdown_escape_pattern.sub(r"\\\1", text)
