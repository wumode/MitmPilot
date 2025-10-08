import asyncio
import signal

import setproctitle
import uvicorn
import uvloop

from app.core.config import settings
from app.db.init import init_db, update_db
from app.factory import app

# Set process name
setproctitle.setproctitle(settings.PROJECT_NAME)

server = uvicorn.Server(
    uvicorn.Config(
        app, host=settings.HOST, port=settings.PORT, reload=settings.DEV, workers=1
    )
)


async def main():
    """Main function to run the FastAPI service"""
    await server.serve()


def signal_handler(signum, frame):
    """
    Signal handler for graceful service shutdown.
    """
    print(f"Received signal {signum}, shutting down gracefully...")
    server.should_exit = True


if __name__ == "__main__":
    # Register signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    # Initialize the database
    init_db()
    # Update the database
    update_db()
    # Configure uvloop
    uvloop.install()
    asyncio.run(main())
