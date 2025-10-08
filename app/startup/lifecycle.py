from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.startup.addons_initializer import init_addons, stop_addons
from app.startup.master_initializer import init_master, stop_master
from app.startup.modules_initializer import init_modules, stop_modules
from app.startup.routers_initializer import init_routers
from app.startup.scheduler_initializer import init_scheduler, stop_scheduler


async def init_extra():
    """
    Synchronizes plugins and restarts related dependent services.
    """
    pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Defines the application's lifecycle events.
    """
    print("Starting up...")
    # Initialize modules
    init_modules()
    # Initialize routers
    init_routers(app)
    # Initialize mitmproxy
    await init_master()
    # Initialize addons
    init_addons()
    # Initialize scheduler
    init_scheduler()

    try:
        # Yield here, indicating that the application has started and control is returned to the FastAPI main event loop
        yield
    finally:
        print("Shutting down...")
        # Stop scheduler
        stop_scheduler()
        # Stop addons
        stop_addons()
        # Stop Mitmproxy
        await stop_master()
        # Stop modules
        stop_modules()
