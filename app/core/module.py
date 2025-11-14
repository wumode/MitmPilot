import traceback
from collections.abc import Generator
from typing import Any

from app.core.config import settings
from app.core.event import eventmanager
from app.helper.module import ModuleHelper
from app.log import logger
from app.schemas.types import EventType, MessageChannel, ModuleType, OtherModulesType
from app.utils.object import ObjectUtils
from app.utils.singleton import Singleton


class ModuleManager(metaclass=Singleton):
    """Module Manager."""

    # Sub-module type collection
    SubType = MessageChannel | OtherModulesType

    def __init__(self):
        # Module list
        self._modules: dict = {}
        # Running module list
        self._running_modules: dict = {}
        self.load_modules()

    def load_modules(self):
        """Load all modules."""
        # Scan module directory
        modules = ModuleHelper.load(
            "app.modules",
            filter_func=lambda _, obj: hasattr(obj, "init_module")
            and hasattr(obj, "init_setting"),
        )
        self._running_modules = {}
        self._modules = {}
        for module in modules:
            module_id = module.__name__
            self._modules[module_id] = module
            try:
                # Create instance
                _module = module()
                # Initialize module
                if self.check_setting(_module.init_setting()):
                    # Control loading through module switch
                    _module.init_module()
                    self._running_modules[module_id] = _module
                    logger.debug(f"Module Loaded: {module_id}")
            except Exception as err:
                logger.error(
                    f"Load Module Error: {module_id}, "
                    f"{str(err)} - {traceback.format_exc()}",
                    exc_info=True,
                )

    def stop(self):
        """Stop all modules."""
        logger.info("Stopping all modules...")
        for module_id, module in self._running_modules.items():
            if hasattr(module, "stop"):
                try:
                    module.stop()
                    logger.debug(f"Module Stopped: {module_id}")
                except Exception as err:
                    logger.error(
                        f"Stop Module Error: {module_id}, "
                        f"{str(err)} - {traceback.format_exc()}",
                        exc_info=True,
                    )
        logger.info("All modules stopped.")

    def reload(self):
        """Reload all modules."""
        self.stop()
        self.load_modules()
        eventmanager.send_event(etype=EventType.ModuleReload, data={})

    def test(self, modleid: str) -> tuple[bool, str]:
        """Test module."""
        if modleid not in self._running_modules:
            return False, ""
        module = self._running_modules[modleid]
        if hasattr(module, "test") and ObjectUtils.check_method(module.test):
            result = module.test()
            if not result:
                return False, ""
            return result
        return True, "Module does not support testing"

    @staticmethod
    def check_setting(setting: tuple | None) -> bool:
        """Check if the switch is turned on.

        The switch uses commas to separate multiple values. If any of them match, it
        means it is turned on.
        """
        if not setting:
            return True
        switch, value = setting
        option = getattr(settings, switch)
        if not option:
            return False
        if option and value is True:
            return True
        if value in option:
            return True
        return False

    def get_running_module(self, module_id: str) -> Any:
        """Get the running instance of a module by its ID."""
        if not module_id:
            return None
        if not self._running_modules:
            return None
        return self._running_modules.get(module_id)

    def get_running_modules(self, method: str) -> Generator:
        """Get a list of modules that implement the same method."""
        if not self._running_modules:
            return
        for _, module in self._running_modules.items():
            if hasattr(module, method) and ObjectUtils.check_method(
                getattr(module, method)
            ):
                yield module

    def get_running_type_modules(self, module_type: ModuleType) -> Generator:
        """Get a list of modules of a specified type."""
        if not self._running_modules:
            return
        for _, module in self._running_modules.items():
            if hasattr(module, "get_type") and module.get_type() == module_type:
                yield module

    def get_running_subtype_module(self, module_subtype: SubType) -> Generator:
        """Get modules of a specified subtype."""
        if not self._running_modules:
            return
        for _, module in self._running_modules.items():
            if (
                hasattr(module, "get_subtype")
                and module.get_subtype() == module_subtype
            ):
                yield module

    def get_module(self, module_id: str) -> Any:
        """Get a module by its ID."""
        if not module_id:
            return None
        if not self._modules:
            return None
        return self._modules.get(module_id)

    def get_modules(self) -> dict:
        """Get the list of modules."""
        return self._modules

    def get_module_ids(self) -> list[str]:
        """Get the list of module IDs."""
        return list(self._modules.keys())
