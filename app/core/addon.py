import copy
import importlib
import inspect
import sys
import traceback
from collections.abc import Callable
from typing import Any

from app import schemas
from app.addons import _AddonBase
from app.core.cache import async_fresh
from app.core.config import settings
from app.core.ctx import Context
from app.core.event import eventmanager
from app.db.systemconfig_oper import SystemConfigOper
from app.helper.addon import PluginHelper
from app.helper.hook import AsyncHookChain, HookChain
from app.helper.ruleparser import ClashRuleParser
from app.log import logger
from app.schemas import AddonApi, AddonService, AddonServiceRegistration, Hook
from app.schemas.rule import Action, RuleType
from app.schemas.types import (
    AddonRenderMode,
    ChainEventType,
    EventType,
    HookEventType,
    SystemConfigKey,
)
from app.utils.object import ObjectUtils
from app.utils.singleton import Singleton
from app.utils.string import StringUtils


class AddonManager(metaclass=Singleton):
    """AddonManager class to manage addons."""

    def __init__(self):
        # addons list
        self._addons: dict[str, type[_AddonBase]] = {}
        # running addons list
        self._running_addons: dict[str, _AddonBase] = {}
        self._config_key: str = f"{SystemConfigKey.AddonConfigPrefix.value}.%s"
        self._hook_chain: HookChain = HookChain()
        self._async_hook_chain: AsyncHookChain = AsyncHookChain()

    def reinit_config(self):
        # stop existing addons
        self.stop_addon()
        # start addons
        self.start_addon()

    @staticmethod
    def check_module(module: Any):
        """Checks the module."""
        if not hasattr(module, "init_addon") or not hasattr(module, "addon_name"):
            return False
        return True

    def start(self):
        Context.mitmmanager.add_addons(self._hook_chain, self._async_hook_chain)
        installed_addons = (
            SystemConfigOper().get(SystemConfigKey.UserInstalledAddons) or []
        )
        # Scan plugin directory, only load eligible plugins
        addons = self._load_selective_addons(
            None, installed_addons, AddonManager.check_module
        )
        # Sort
        addons.sort(key=lambda x: x.addon_order if hasattr(x, "addon_order") else 0)
        for addon in addons:
            addon_id = addon.__name__
            self._addons[addon_id] = addon

        self.start_addon()

    def stop(self):
        self.stop_addon()
        Context.mitmmanager.remove_addon(self._hook_chain)
        Context.mitmmanager.remove_addon(self._async_hook_chain)

    def start_addon(self, aid: str | None = None):
        for addon_id, addon in self._addons.items():
            if aid and addon_id != aid:
                continue
            try:
                # Generate instance
                addon_obj = addon()
                # Store running instance
                self._running_addons[addon_id] = addon_obj
                # Initialize plugin
                self.init_addon(addon_id, self.get_addon_config(addon_id))
                logger.info(
                    f"Loading plugin: {addon_id} Version: {addon_obj.addon_version}"
                )
            except Exception as err:
                logger.error(
                    f"Error loading plugin "
                    f"{addon_id}: {str(err)} - {traceback.format_exc()}"
                )

    def stop_addon(self, aid: str | None = None):
        """Stops the addon service.

        :param aid: Addon ID, if None, stops all addons.
        """
        # Stop addon
        if aid:
            logger.info(f"Stopping adoon {aid}...")
            addon_obj = self._running_addons.get(aid)
            if not addon_obj:
                logger.debug(f"Addon {aid} does not exist or is not loaded")
                return
            addons = {aid: addon_obj}
        else:
            logger.info("Stopping all addons...")
            addons = self._running_addons
        for addon_id in addons:
            self.terminate_addon(addon_id)
        # Clear objects
        if aid:
            # Clear specified addon
            self._addons.pop(aid, None)
            self._running_addons.pop(aid, None)
            # Clear addon module cache, including all submodules
            self._clear_addon_modules(aid)
        else:
            # Clear all
            self._addons.clear()
            self._running_addons.clear()
            # Clear all addon module cache
            self._clear_addon_modules()
        logger.info("Addon stop complete")

    def init_addon(self, addon_id: str, conf: dict):
        """Initializes the addon.

        :param addon_id: Addon ID
        :param conf: Addon configuration
        """
        addon = self._running_addons.get(addon_id)
        if not addon:
            return
        # Initialize plugin
        addon.init_addon(conf)
        # Check plugin status and enable/disable event handler
        self.register_addon_hooks(addon_id)
        self.register_addon(addon_id)
        if addon.get_state():
            # Enable event handler for plugin class
            eventmanager.enable_event_handler(type(addon))
            self.register_services(addon_id)
        else:
            # Disable event handler for plugin class
            eventmanager.disable_event_handler(type(addon))

    def terminate_addon(self, addon_id: str):
        """Terminate the addon.

        :param addon_id: Addon ID
        """
        addon = self._running_addons.get(addon_id)
        if not addon:
            return
        self.deregister_services(addon_id)
        eventmanager.disable_event_handler(type(addon))
        self.deregister_addon(addon_id)
        self.deregister_addon_hooks(addon_id)
        AddonManager._stop_addon(addon)

    def register_addon_hooks(self, aid: str):
        addon_obj = self._running_addons.get(aid)
        if not addon_obj:
            return
        addon_hooks = addon_obj.get_hooks()
        for event, hooks in addon_hooks.items():
            logger.info(f"[{aid}] register {event.value}().")
            event_hooks: list[Hook] = []
            for hook_data in hooks:
                condition: RuleType | None = None
                if hook_data.condition_string:
                    condition_string = (
                        f"{hook_data.condition_string},{Action.COMPATIBLE}"
                    )
                    condition = ClashRuleParser.parse_rule_line(condition_string)
                priority: int = (
                    hook_data.priority if hook_data.priority else addon_obj.addon_order
                )
                hook = Hook(
                    id=f"{aid}",
                    rule=condition,
                    priority=priority,
                    ignore_rest=hook_data.ignore_rest,
                    func=hook_data.func,
                    addon_state=addon_obj.get_state,
                )
                event_hooks.append(hook)
            self._add_hooks(event, event_hooks)

    def deregister_addon_hooks(self, aid: str):
        logger.info(f"[{aid}] deregister all event hooks.")
        self._hook_chain.remove_hooks_by_id(aid)
        self._async_hook_chain.remove_hooks_by_id(aid)

    def register_addon(self, aid: str | None = None):
        """Register addon to mitmproxy."""
        if aid is None:
            addons = [*self._running_addons]
        else:
            addons = (
                [self._running_addons.get(aid)] if aid in self._running_addons else []
            )
        Context.mitmmanager.add_addons(*addons)

    def deregister_addon(self, aid: str | None = None):
        """Remove addon from mitmproxy."""
        if aid is None:
            addons = [*self._running_addons]
        else:
            addons = (
                [self._running_addons.get(aid)] if aid in self._running_addons else []
            )
        for addon in addons:
            Context.mitmmanager.remove_addon(addon)

    def register_services(self, aid: str | None = None):
        running_addons_snapshot = dict(self._running_addons)
        for addon_id, addon in running_addons_snapshot.items():
            if aid and aid != addon_id:
                continue
            services = self.get_addon_services(aid)
            event_data = AddonServiceRegistration(
                addon_id=addon_id, addon_name=addon.addon_name, services=services
            )
            eventmanager.send_event(
                etype=ChainEventType.AddonServiceRegister, data=event_data
            )

    def deregister_services(self, aid: str | None = None):
        running_addons_snapshot = dict(self._running_addons)
        for addon_id in running_addons_snapshot:
            if aid and aid != addon_id:
                continue
            event_data = AddonServiceRegistration(addon_id=addon_id)
            eventmanager.send_event(
                etype=ChainEventType.AddonServiceDeregister, data=event_data
            )

    def get_addon_ids(self) -> list[str]:
        """Retrieves all plugin IDs."""
        return list(self._addons.keys())

    def get_running_plugin_ids(self) -> list[str]:
        """Retrieves all running plugin IDs."""
        return list(self._running_addons.keys())

    def get_plugin_apis(self, pid: str | None = None) -> list[AddonApi]:
        """Retrieves plugin APIs."""
        ret_apis: list[AddonApi] = []
        if pid:
            plugins = {pid: self._running_addons.get(pid)}
        else:
            plugins = self._running_addons
        for plugin_id, plugin in plugins.items():
            if pid and pid != plugin_id:
                continue
            if hasattr(plugin, "get_api") and ObjectUtils.check_method(plugin.get_api):
                try:
                    apis = plugin.get_api() or []
                    for api in apis:
                        api.path = f"/{plugin_id}{api.path}"
                    ret_apis.extend(apis)
                except Exception as e:
                    logger.error(f"Error getting plugin {plugin_id} API: {str(e)}")
        return ret_apis

    def get_addon_services(self, aid: str | None = None) -> list[AddonService]:
        """Retrieves plugin services."""
        ret_services: list[AddonService] = []
        # Create a dictionary snapshot to avoid concurrent modification
        running_addons_snapshot = dict(self._running_addons)
        for addon_id, addon in running_addons_snapshot.items():
            if aid and aid != addon_id:
                continue
            if hasattr(addon, "get_service") and ObjectUtils.check_method(
                addon.get_service
            ):
                try:
                    if not addon.get_state():
                        continue
                    services = addon.get_service() or []
                    ret_services.extend(services)
                except Exception as e:
                    logger.error(f"Error getting plugin {addon_id} service: {str(e)}")
        return ret_services

    def get_plugin_attr(self, pid: str, attr: str) -> Any:
        """Retrieves plugin attributes.

        :param pid: Plugin ID
        :param attr: Attribute name
        """
        plugin = self._running_addons.get(pid)
        if not plugin:
            return None
        if not hasattr(plugin, attr):
            return None
        return getattr(plugin, attr)

    def get_addon_modules(
        self, addon_id: str | None = None
    ) -> dict[tuple, dict[str, Any]]:
        """
        Retrieves plugin modules.
        {
            addon_id: {
                method: function
            }
        }
        """
        ret_modules = {}
        # Create a dictionary snapshot to avoid concurrent modification
        running_addons_snapshot = dict(self._running_addons)
        for aid, addon in running_addons_snapshot.items():
            if addon_id and addon_id != aid:
                continue
            if hasattr(addon, "get_module") and ObjectUtils.check_method(
                addon.get_module
            ):
                try:
                    if not addon.get_state():
                        continue
                    addon_modules = addon.get_module() or []
                    ret_modules[(aid, addon.addon_name)] = addon_modules
                except Exception as e:
                    logger.error(f"Error getting plugin {aid} module: {str(e)}")
        return ret_modules

    def get_plugin_dashboard_meta(self) -> list[dict[str, str]]:
        """Get all plugin dashboard meta information."""
        dashboard_meta = []
        # Create a dictionary snapshot to avoid concurrent modification
        running_plugins_snapshot = dict(self._running_addons)
        for plugin_id, plugin in running_plugins_snapshot.items():
            if not hasattr(plugin, "get_dashboard") or not ObjectUtils.check_method(
                plugin.get_dashboard
            ):
                continue
            try:
                if not plugin.get_state():
                    continue
                # If it is a multi-dashboard implementation
                if hasattr(plugin, "get_dashboard_meta") and ObjectUtils.check_method(
                    plugin.get_dashboard_meta
                ):
                    meta = plugin.get_dashboard_meta()
                    if meta:
                        dashboard_meta.extend(
                            [
                                {
                                    "id": plugin_id,
                                    "name": m.get("name"),
                                    "key": m.get("key"),
                                }
                                for m in meta
                                if m
                            ]
                        )
                else:
                    dashboard_meta.append(
                        {
                            "id": plugin_id,
                            "name": plugin.addon_name,
                            "key": "",
                        }
                    )
            except Exception as e:
                logger.error(
                    f"Error getting plugin [{plugin_id}] dashboard meta data: {str(e)}"
                )
        return dashboard_meta

    def get_plugin_dashboard(
        self, pid: str, key: str, user_agent: str = None
    ) -> schemas.AddonDashboard | None:
        """Get plugin dashboard."""

        # Get plugin instance
        plugin_instance = self.running_addons.get(pid)
        if not plugin_instance:
            return None

        # Render mode
        render_mode = plugin_instance.get_render_mode()
        # Get plugin dashboard
        try:
            dashboard = plugin_instance.get_dashboard(key=key, user_agent=user_agent)
        except Exception as e:
            logger.error(f"Plugin {pid} failed to call method get_dashboard: {str(e)}")
            return None
        if dashboard is None:
            return None
        return schemas.AddonDashboard(
            id=pid,
            name=plugin_instance.addon_name,
            key=key,
            render_mode=render_mode,
            cols=dashboard.cols,
            attrs=dashboard.attrs,
            elements=dashboard.elements,
        )

    def get_local_addons(self) -> list[schemas.Addon]:
        """Retrieves information about all locally downloaded plugins."""
        # Return value
        addons = []
        # Installed plugins
        installed_apps = (
            SystemConfigOper().get(SystemConfigKey.UserInstalledAddons) or []
        )
        for aid, addon_class in self._addons.items():
            # Running plugin
            addon_obj = self._running_addons.get(aid)
            # Basic attributes
            addon = schemas.Addon(addon_id=aid)
            # Installation status
            if aid in installed_apps:
                addon.installed = True
            else:
                addon.installed = False
            # Running status
            if addon_obj and hasattr(addon_obj, "get_state"):
                try:
                    state = addon_obj.get_state()
                except Exception as e:
                    logger.error(f"Error getting plugin {aid} status: {str(e)}")
                    state = False
                addon.state = state
            else:
                addon.state = False
            # Whether there is a detail page
            if hasattr(addon_class, "get_page"):
                if ObjectUtils.check_method(addon_class.get_page):
                    addon.has_page = True
                else:
                    addon.has_page = False
            # Public key
            if hasattr(addon_class, "addon_public_key"):
                addon.plugin_public_key = addon_class.addon_public_key
            # Name
            if hasattr(addon_class, "addon_name"):
                addon.addon_name = addon_class.addon_name
            # Description
            if hasattr(addon_class, "addon_desc"):
                addon.addon_desc = addon_class.addon_desc
            # Version
            if hasattr(addon_class, "addon_version"):
                addon.addon_version = addon_class.addon_version
            # Icon
            if hasattr(addon_class, "addon_icon"):
                addon.addon_icon = addon_class.addon_icon
            # Author
            if hasattr(addon_class, "addon_author"):
                addon.addon_author = addon_class.addon_author
            # Author link
            if hasattr(addon_class, "author_url"):
                addon.author_url = addon_class.author_url
            # Load order
            if hasattr(addon_class, "addon_order"):
                addon.addon_order = addon_class.addon_order
            # Whether update is needed
            addon.has_update = False
            # Local flag
            addon.is_local = True
            # Summary
            addons.append(addon)
        # Re-sort by load order
        addons.sort(key=lambda x: x.addon_order if hasattr(x, "addon_order") else 0)
        return addons

    async def async_get_online_addons(self, force: bool = False) -> list[schemas.Addon]:
        """Asynchronously retrieves information about all online addons.

        :param force: Whether to force refresh (ignore cache).
        """
        if not settings.ADDON_MARKET:
            return []

        # Used to store v1 version plugins
        plugins = []

        # Use asynchronous concurrency to get online plugins
        import asyncio

        tasks = []

        for m in settings.ADDON_MARKET.split(","):
            if not m:
                continue
            # Create task to get plugins
            base_task = asyncio.create_task(
                self.async_get_plugins_from_market(m, force)
            )
            tasks.append(base_task)

        # Execute all tasks concurrently
        if tasks:
            completed_tasks = await asyncio.gather(*tasks, return_exceptions=True)
            for _i, result in enumerate(completed_tasks):
                # Check for exceptions
                if isinstance(result, Exception):
                    logger.error(f"Failed to get plugin market data: {str(result)}")
                    continue
                assert isinstance(result, list)
                plugins.extend(result)
        return PluginHelper.process_plugins_list(plugins)

    def get_addon_config(self, aid: str) -> dict:
        """Retrieves addon configuration.

        :param aid: Addon ID
        """
        if not self._addons.get(aid):
            return {}
        conf = SystemConfigOper().get(self._config_key % aid)
        if conf:
            # Remove empty keys
            return {k: v for k, v in conf.items() if k}
        return {}

    def save_plugin_config(self, pid: str, conf: dict, force: bool = False) -> bool:
        """Saves the plugin configuration.

        :param pid: Plugin ID
        :param conf: Configuration
        :param force: Force save
        """
        if not force and not self._addons.get(pid):
            return False
        SystemConfigOper().set(self._config_key % pid, conf)
        return True

    def _add_hooks(self, event: HookEventType, hooks: list[Hook]):
        for hook in hooks:
            if inspect.iscoroutinefunction(hook.func):
                self._async_hook_chain.add_hook(event, hook)
            else:
                self._hook_chain.add_hook(event, hook)

    @staticmethod
    def _stop_addon(addon: _AddonBase):
        """Stops the addon.

        :param addon: Addon instance
        """
        try:
            # Close database
            if hasattr(addon, "close"):
                addon.close()
            # Stop plugin
            if hasattr(addon, "stop_service"):
                addon.stop_service()
        except Exception as e:
            logger.warn(f"Error stopping plugin {addon.addon_name}: {str(e)}")

    def remove_addon(self, addon_id: str):
        """Removes a plugin from memory.

        :param addon_id: Plugin ID
        """
        self.stop_addon(addon_id)

    @staticmethod
    def _clear_addon_modules(addon_id: str | None = None):
        """Clears the cache for the plugin and all its submodules.

        :param addon_id: Plugin ID
        """

        # Construct plugin module prefix
        if addon_id:
            addon_module_prefix = f"app.addons.{addon_id.lower()}"
        else:
            addon_module_prefix = "app.addons"

        # Collect module names to be deleted (create a copy of the module name list
        # to avoid modifying the dictionary during iteration)
        modules_to_remove = []
        for module_name in list(sys.modules.keys()):
            if module_name == addon_module_prefix or module_name.startswith(
                addon_module_prefix + "."
            ):
                modules_to_remove.append(module_name)

        # Delete modules
        for module_name in modules_to_remove:
            try:
                del sys.modules[module_name]
                logger.debug(f"Plugin module cache cleared: {module_name}")
            except KeyError:
                # Module may have already been deleted
                pass

        importlib.invalidate_caches()
        logger.debug("Finder cache cleared")

        if addon_id:
            if modules_to_remove:
                logger.info(
                    f"Addon {addon_id} cleared {len(modules_to_remove)} "
                    f"module caches in total: {modules_to_remove}"
                )
            else:
                logger.debug(f"Plugin {addon_id} found no module caches to clear")

    @staticmethod
    def _load_selective_addons(
        aid: str | None, installed_addons: list[str], check_module_func: Callable
    ) -> list[type[_AddonBase]]:
        """Selectively loads plugins, only importing those that meet the conditions.

        :param aid: Specified plugin ID, if empty, loads all installed plugins.
        :param installed_addons: List of installed plugins
        :param check_module_func: Module check function
        :return: List of plugin classes
        """
        import importlib

        addons: list[type[_AddonBase]] = []
        addons_dir = settings.ROOT_PATH / "app" / settings.ADDON_FOLDER

        if not addons_dir.exists():
            return addons

        if aid:
            # Load specified plugin
            target_addons = [aid.lower()]
        else:
            # Load installed plugins
            target_addons = [plugin_id.lower() for plugin_id in installed_addons]
        if settings.DEV and settings.DEV_ADDON:
            target_addons.append(settings.DEV_ADDON.lower())
        if not target_addons:
            return addons

        # Scan addons directory
        _loaded_modules = set()
        for addon_dir in addons_dir.iterdir():
            if not addon_dir.is_dir() or addon_dir.name.startswith("_"):
                continue

            # Check if it is a plugin that needs to be loaded
            if addon_dir.name not in target_addons:
                continue

            # Check if __init__.py exists
            init_file = addon_dir / "__init__.py"
            if not init_file.exists():
                continue

            original_sys_path = list(sys.path)
            try:
                # Prioritize loading plugin virtual environment
                venv_path = (
                    addon_dir
                    / ".venv"
                    / "lib"
                    / f"python{sys.version_info.major}.{sys.version_info.minor}"
                    / "site-packages"
                )
                if venv_path.exists():
                    sys.path.insert(0, str(venv_path))
                    logger.debug(
                        f"Loading virtual environment for plugin {addon_dir.name}: {venv_path}"
                    )

                # Construct module name
                module_name = f"app.addons.{addon_dir.name}"

                # Import module
                module = importlib.import_module(module_name)
                importlib.reload(module)

                # Check classes in the module
                for name, obj in module.__dict__.items():
                    if name.startswith("_") or name == _AddonBase.__name__:
                        continue
                    if not (isinstance(obj, type) and issubclass(obj, _AddonBase)):
                        continue
                    if name in _loaded_modules:
                        continue
                    if check_module_func(obj):
                        _loaded_modules.add(name)
                        addons.append(obj)
                        logger.info(f"Found eligible plugin class: {name}")
                        break

            except Exception as err:
                logger.error(
                    f"Failed to load plugin {addon_dir.name}: {str(err)} - {traceback.format_exc()}"
                )
            finally:
                # Restore sys.path
                sys.path[:] = original_sys_path

        return addons

    def reload_addon(self, addon_id: str):
        """Reloads a plugin into memory.

        :param addon_id: Plugin ID
        """
        # Remove the plugin instance first
        self.stop_addon(addon_id)
        addons = AddonManager._load_selective_addons(
            addon_id, [addon_id], AddonManager.check_module
        )
        for addon in addons:
            addon_id = addon.__name__
            self._addons[addon_id] = addon
        # Reload
        self.start_addon(addon_id)
        # Broadcast event
        eventmanager.send_event(EventType.AddonReload, data={"addon_id": addon_id})

    @staticmethod
    def get_plugin_remote_entry(plugin_id: str, dist_path: str = "dist/assets") -> str:
        """Retrieves the remote entry address of the plugin.

        :param plugin_id: Plugin ID
        :param dist_path: Plugin distribution path
        :return: Remote entry address
        """
        if dist_path.startswith("/"):
            dist_path = dist_path[1:]
        if dist_path.endswith("/"):
            dist_path = dist_path[:-1]
        return f"/plugin/file/{plugin_id.lower()}/{dist_path}/remoteEntry.js"

    def get_addon_remotes(self, aid: str | None = None) -> list[dict[str, Any]]:
        """Retrieves the list of plugin federation components."""
        remotes = []
        # Create a dictionary snapshot to avoid concurrent modification
        running_addons_snapshot = dict(self._running_addons)
        for addon_id, addon in running_addons_snapshot.items():
            if aid and aid != addon_id:
                continue
            if hasattr(addon, "get_render_mode"):
                render_mode = addon.get_render_mode()
                if render_mode != AddonRenderMode.vue:
                    continue
                remotes.append(
                    {
                        "id": addon_id,
                        "url": self.get_plugin_remote_entry(addon_id),
                        "name": addon.addon_name,
                    }
                )
        return remotes

    def get_addon_rules(self) -> list[str]:
        rules = []
        running_addons_snapshot = dict(self._running_addons)
        for aid, addon in running_addons_snapshot.items():
            if ObjectUtils.check_method(addon.get_clash_rules):
                for rule in addon.get_clash_rules():
                    condition_string = f"{rule},{Action.COMPATIBLE}"
                    parsed = ClashRuleParser.parse_rule_line(condition_string)
                    if not parsed or not ClashRuleParser.valid_rule_for_provider(
                        parsed
                    ):
                        logger.warn(f"Invalid rule {aid}:{rule}")
                        continue
                    rules.append(parsed.condition_string())
        return rules

    @property
    def running_addons(self) -> dict[str, _AddonBase]:
        """Retrieves the list of running plugins.

        :return: List of running plugins
        """
        return self._running_addons

    @property
    def addons(self) -> dict[str, Any]:
        """Retrieves the list of addons.

        :return: List of addons
        """
        return self._addons

    async def async_get_plugins_from_market(
        self, market: str, force: bool = False
    ) -> list[schemas.Addon] | None:
        """Asynchronously retrieves plugin information from the specified market.

        :param market: Market URL or identifier
        :param force: Whether to force refresh (ignore cache).
        :return: List of plugins, or [] if retrieval fails.
        """
        if not settings.ADDON_MARKET:
            return []
        # Installed plugins
        installed_apps = (
            SystemConfigOper().get(SystemConfigKey.UserInstalledAddons) or []
        )
        # Get online plugins
        async with async_fresh(force):
            online_plugins = await PluginHelper().async_get_plugins(market)
        if online_plugins is None:
            logger.warning(
                f"Failed to get addon library: {market}, "
                f"please check GitHub network connection"
            )
            return []
        ret_plugins = []
        add_time = len(online_plugins)
        for plugin_info in online_plugins:
            pid = plugin_info.addon_id
            plugin = self._process_plugin_info(
                pid, plugin_info, market, installed_apps, add_time
            )
            if plugin:
                ret_plugins.append(plugin)
            add_time -= 1

        return ret_plugins

    def _process_plugin_info(
        self,
        pid: str,
        plugin_info: schemas.Addon,
        market: str,
        installed_apps: list[str],
        add_time: int,
    ) -> schemas.Addon | None:
        """Processes single plugin information, creating a schemas.Plugin object.

        :param pid: Plugin ID
        :param plugin_info: Plugin information dictionary
        :param market: Market URL
        :param installed_apps: List of installed plugins
        :param add_time: Addition order
        :return: Created plugin object, or None if validation fails.
        """
        # Running plugin
        plugin_obj = self._running_addons.get(pid)
        # Non-running plugin
        plugin_static = self._addons.get(pid)
        plugin = copy.deepcopy(plugin_info)
        # Installation status
        if pid in installed_apps and plugin_static:
            plugin.installed = True
        else:
            plugin.installed = False
        # Whether there is a new version
        plugin.has_update = False
        if plugin_static:
            installed_version = plugin_static.addon_version
            addon_version = (
                plugin_info.addon_version if plugin_info.addon_version else ""
            )
            if StringUtils.compare_version(installed_version, "<", addon_version):
                # Needs update
                plugin.has_update = True
        # Running status
        if plugin_obj and hasattr(plugin_obj, "get_state"):
            try:
                state = plugin_obj.get_state()
            except Exception as e:
                logger.error(f"Error getting plugin {pid} status: {str(e)}")
                state = False
            plugin.state = state
        else:
            plugin.state = False
        # Whether there is a detail page
        plugin.has_page = False
        if plugin_obj and hasattr(plugin_obj, "get_page"):
            if ObjectUtils.check_method(plugin_obj.get_page):
                plugin.has_page = True
        # Repository link
        plugin.repo_url = market
        # Local flag
        plugin.is_local = False
        # Addition order
        plugin.add_time = add_time

        return plugin
