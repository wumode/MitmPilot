from app.core.ctx import Context
from app.core.master import MitmManager


async def init_master():
    """
    Initializes DumpMaster.
    """
    Context.mitmmanager = MitmManager()
    await Context.mitmmanager.start()


async def stop_master():
    """
    Stops DumpMaster.
    """
    try:
        await MitmManager().stop()
    except Exception as e:
        print(f"An error occurred while stopping DumpMaster: {e}")
