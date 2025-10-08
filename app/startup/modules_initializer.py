import asyncio

from app.core.ctx import Context
from app.core.event import EventManager
from app.core.module import ModuleManager
from app.helper.thread import ThreadHelper


def stop_modules():
    """
    Service shutdown.
    """
    # Stop modules
    ModuleManager().stop()
    # Stop event consumption
    EventManager().stop()
    # Stop the thread pool
    ThreadHelper().shutdown()


def init_modules():
    """
    Starts modules.
    """
    Context.loop = asyncio.get_running_loop()
    # Load the thread pool
    ThreadHelper()
    # Load modules
    Context.modulemanager = ModuleManager()
    # Start event consumption
    EventManager().start()
