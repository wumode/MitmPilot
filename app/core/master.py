import asyncio
from asyncio import AbstractEventLoop

from mitmproxy import ctx
from mitmproxy.options import Options
from mitmproxy.tools.dump import DumpMaster

from app.core.config import mitmopts
from app.log import logger
from app.utils.singleton import Singleton


class MitmManager(metaclass=Singleton):
    """
    Mitmproxy instance manager.
    """

    def __init__(self):
        self.master: DumpMaster | None = None
        self.task: asyncio.Task | None = None
        self.loop: AbstractEventLoop = asyncio.get_running_loop()

    @property
    def is_running(self) -> bool:
        """
        Check if mitmproxy is running.
        """
        return self.task is not None and not self.task.done()

    async def start(self):
        """
        Start mitmproxy.
        """
        if self.is_running:
            logger.info("[*] mitmproxy is already running.")
            return

        opts = Options(
            listen_host=mitmopts.LISTEN_HOST,
            listen_port=mitmopts.LISTEN_PORT,
            mode=mitmopts.MODE,
            confdir=mitmopts.CONFDIR,
        )
        self.master = DumpMaster(opts, loop=self.loop)
        options = {
            key.lower(): value
            for key, value in mitmopts.model_dump(exclude_unset=True).items()
        }
        opts.update(**options)
        logger.info(f"Mitmproxy mode: {ctx.options.mode}")

        async def _run():
            assert isinstance(self.master, DumpMaster)
            logger.info("[*] mitmproxy is starting...")
            try:
                await self.master.run()
            except asyncio.CancelledError:
                logger.error("[*] mitmproxy run cancelled.")
            finally:
                logger.info("[*] mitmproxy shutdown complete.")

        self.task = asyncio.create_task(_run())

    async def stop(self):
        """
        Stop mitmproxy.
        """
        if not self.is_running or not self.master or not self.task:
            logger.info("[*] mitmproxy is not running.")
            return
        assert self.master is not None
        assert self.task is not None
        logger.info("[*] mitmproxy is stopping...")
        self.master.shutdown()
        try:
            await asyncio.wait_for(self.task, timeout=5.0)
        except (TimeoutError, asyncio.CancelledError):
            pass
        finally:
            self.master = None
            self.task = None
            logger.info("[*] mitmproxy stopped.")

    def add_addons(self, *addons):
        assert self.master is not None
        self.master.addons.add(*addons)

    def remove_addon(self, addon):
        assert self.master is not None
        self.master.addons.remove(addon)
