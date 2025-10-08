from app.core.addon import AddonManager
from app.core.ctx import Context


def init_addons():
    """
    Initializes addons.
    """
    Context.addonmanager = AddonManager()
    Context.addonmanager.start()


def stop_addons():
    """
    Stops addons.
    """
    try:
        AddonManager().stop()
    except Exception as e:
        print(f"An error occurred while stopping addons: {e}")
