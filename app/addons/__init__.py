from abc import ABCMeta, abstractmethod
from pathlib import Path
from typing import Any

from app.chain import ChainBase
from app.core.config import settings
from app.core.event import EventManager
from app.db.addondata_oper import AddonDataOper
from app.db.systemconfig_oper import SystemConfigOper
from app.helper.message import MessageHelper
from app.schemas import AddonApi, AddonService, Dashboard, HookData, Notification
from app.schemas.types import (
    AddonRenderMode,
    HookEventType,
    MessageChannel,
    NotificationType,
    SystemConfigKey,
)


class AddonChian(ChainBase):
    """插件处理链."""

    pass


class _AddonBase(metaclass=ABCMeta):
    """The addon module base class.

    Implements addons by inheriting this class.
    """

    # name
    addon_name: str = ""
    # version
    addon_version: str = ""
    # description
    addon_desc: str = ""
    # loading order
    addon_order: int = 9999
    # minium system version
    version_required: str | None = None

    def __init__(self):
        self.addondata = AddonDataOper()
        self.systemconfig = SystemConfigOper()
        self.eventmanager = EventManager()
        # 处理链
        self.chain = AddonChian()
        # 系统消息
        self.systemmessage = MessageHelper()

    @abstractmethod
    def init_addon(self, config: dict = None):
        """Initialize addon.

        :param config: configuration dictionary
        """
        pass

    @abstractmethod
    def get_state(self) -> bool:
        """Get addon running status."""
        pass

    def get_hooks(self) -> dict[HookEventType, list[HookData]]:
        """Get addon hooks."""
        raise NotImplementedError

    def get_clash_rules(self) -> list[str]:
        """Get addon rules.

        :return: The Clash rules that the addon expects to intercept traffic.
                 Example: ['DOMAIN-SUFFIX,baidu.com', 'DOMAIN,www.google.com']
        """
        raise NotImplementedError

    @staticmethod
    def get_render_mode() -> AddonRenderMode:
        """Get addon rendering mode :return: Rendering mode.

        Vue/vuetify, default is vuetify
        """
        return AddonRenderMode.vuetify

    def get_api(self) -> list[AddonApi]:
        """Register addon API."""
        raise NotImplementedError

    @abstractmethod
    def get_form(self) -> tuple[list[dict] | None, dict[str, Any]]:
        """Assemble the addon configuration page.

        The addon configuration page
        is assembled using Vuetify components, refer to: https://vuetifyjs.com/
        :return:
            - Page configuration (vuetify mode) or None (vue mode);
            - Default data structure
        """
        pass

    def get_page(self) -> list[dict] | None:
        """
        Assemble the addon details page, need to return the page configuration with data
        The addon details page is assembled using Vuetify components,
        refer to: https://vuetifyjs.com/

        :return: Page configuration (vuetify mode) or None (vue mode)
        """
        raise NotImplementedError

    def get_service(self) -> list[AddonService]:
        """Register addon public services."""
        raise NotImplementedError

    def get_dashboard(self, key: str, **kwargs) -> Dashboard | None:
        """
        Get the addon dashboard page, need to return:
        1. Dashboard col configuration dictionary;
        2. Global configuration (layout, auto refresh, etc.);
        3. Dashboard page element configuration with data json (vuetify)
        or None (vue mode)

        :param key: Dashboard key, return the corresponding dashboard data according
        to the specified key
        """
        raise NotImplementedError

    def get_dashboard_meta(self) -> list[dict[str, str]] | None:
        """
        Get addon dashboard meta-information
        Return example:
            [{
                "key": "dashboard1", // The key of the dashboard, unique within
                the current addon
                "name": "Dashboard 1" // The name of the dashboard
            }, {
                "key": "dashboard2",
                "name": "Dashboard 2"
            }]
        """
        raise NotImplementedError

    def get_name(self) -> str:
        """Get addon name.

        :return: The addon name.
        """
        return self.addon_name

    def update_config(self, config: dict, addon_id: str | None = None) -> bool | None:
        """Update configuration information.

        :param config: The configuration information dictionary
        :param addon_id: Addon ID.
        """
        if not addon_id:
            addon_id = self.__class__.__name__
        return self.systemconfig.set(
            f"{SystemConfigKey.AddonConfigPrefix.value}.{addon_id}", config
        )

    def get_config(self, addon_id: str | None = None) -> Any:
        """Get configuration information.

        :param addon_id: Addon ID.
        """
        if not addon_id:
            addon_id = self.__class__.__name__
        return self.systemconfig.get(
            f"{SystemConfigKey.AddonConfigPrefix.value}.{addon_id}"
        )

    def get_data_path(self, addon_id: str | None = None) -> Path:
        """Get addon data storage directory."""
        if not addon_id:
            addon_id = self.__class__.__name__
        data_path = settings.ADDON_DATA_PATH / f"{addon_id}"
        if not data_path.exists():
            data_path.mkdir(parents=True)
        return data_path

    def save_data(self, key: str, value: Any, addon_id: str | None = None):
        """Save addon data.

        :param key: Data key
        :param value: Data value
        :param addon_id: Addon ID.
        """
        if not addon_id:
            addon_id = self.__class__.__name__
        self.addondata.save(addon_id, key, value)

    def get_data(self, key: str | None = None, addon_id: str | None = None) -> Any:
        """Get addon data.

        :param key: Data key
        :param addon_id: addon_id.
        """
        if not addon_id:
            addon_id = self.__class__.__name__
        return self.addondata.get_data(addon_id, key)

    def del_data(self, key: str, addon_id: str | None = None) -> Any:
        """Delete addon date.

        :param key: Data key
        :param addon_id: addon_id.
        """
        if not addon_id:
            addon_id = self.__class__.__name__
        return self.addondata.del_data(addon_id, key)

    def post_message(
        self,
        channel: MessageChannel | None = None,
        mtype: NotificationType | None = None,
        title: str | None = None,
        text: str | None = None,
        image: str | None = None,
        link: str | None = None,
        userid: str | None = None,
        username: str | None = None,
        **kwargs,
    ):
        """Send a message."""
        if not link:
            link = settings.MP_DOMAIN(
                f"#/addons?tab=installed&id={self.__class__.__name__}"
            )
        self.chain.post_message(
            Notification(
                channel=channel,
                mtype=mtype,
                title=title,
                text=text,
                image=image,
                link=link,
                userid=userid,
                username=username,
                **kwargs,
            )
        )

    async def async_post_message(
        self,
        channel: MessageChannel | None = None,
        mtype: NotificationType | None = None,
        title: str | None = None,
        text: str | None = None,
        image: str | None = None,
        link: str | None = None,
        userid: str | None = None,
        username: str | None = None,
        **kwargs,
    ):
        """Send a message."""
        if not link:
            link = settings.MP_DOMAIN(
                f"#/addons?tab=installed&id={self.__class__.__name__}"
            )
        await self.chain.async_post_message(
            Notification(
                channel=channel,
                mtype=mtype,
                title=title,
                text=text,
                image=image,
                link=link,
                userid=userid,
                username=username,
                **kwargs,
            )
        )
