from typing import Any

from app.db import DbOper
from app.db.models.addondata import AddonData


class AddonDataOper(DbOper):
    """
    Addon data management.
    """

    def save(self, plugin_id: str, key: str, value: Any):
        """
        Save addon data.
        :param plugin_id: Addon ID
        :param key: Data key
        :param value: Data value
        """
        plugin = AddonData.get_addon_data_by_key(self._db, plugin_id, key)  # noqa
        if plugin:
            plugin.update(self._db, {"value": value})
        else:
            AddonData(addon_id=plugin_id, key=key, value=value).create(self._db)  # noqa

    def get_data(self, plugin_id: str, key: str | None = None) -> Any:
        """
        Get addon data.
        :param plugin_id: Addon ID
        :param key: Data key
        """
        if key:
            data = AddonData.get_addon_data_by_key(self._db, plugin_id, key)  # noqa
            if not data:
                return None
            return data.value
        else:
            return AddonData.get_addon_data(self._db, plugin_id)  # noqa

    def del_data(self, plugin_id: str, key: str | None = None) -> Any:
        """
        Delete addon data.
        :param plugin_id: Addon ID
        :param key: Data key
        """
        if key:
            AddonData.del_addon_data_by_key(self._db, plugin_id, key)  # noqa
        else:
            AddonData.del_addon_data(self._db, plugin_id)  # noqa

    def truncate(self):
        """
        Truncate addon data.
        """
        AddonData.truncate(self._db)  # noqa

    def get_data_all(self, plugin_id: str) -> Any:
        """
        Get all addon data.
        :param plugin_id: Addon ID
        """
        return AddonData.get_addon_data_by_plugin_id(self._db, plugin_id)  # noqa
