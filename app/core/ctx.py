import typing
from asyncio import AbstractEventLoop

if typing.TYPE_CHECKING:
    from app.core.addon import AddonManager
    from app.core.master import MitmManager
    from app.core.module import ModuleManager


class Context:
    addonmanager: AddonManager
    modulemanager: ModuleManager
    mitmmanager: MitmManager
    loop: AbstractEventLoop
