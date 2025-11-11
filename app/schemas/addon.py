from collections.abc import Callable, Iterator
from typing import Any, Literal

from apscheduler.triggers.base import BaseTrigger
from pydantic import BaseModel, ConfigDict, Field, RootModel

from app.schemas.types import AddonRenderMode


class Addon(BaseModel):
    """Addon information."""

    # Addon ID
    addon_id: str
    # Addon name
    addon_name: str | None = None
    # Addon description
    addon_desc: str | None = None
    # Addon icon
    addon_icon: str | None = None
    # Addon version
    addon_version: str | None = None
    # Addon label
    addon_label: str | None = None
    # Addon author
    addon_author: str | None = None
    # Author's homepage
    author_url: str | None = None
    # Addon config item ID prefix
    addon_config_prefix: str | None = None
    # Loading order
    addon_order: int | None = 0
    # Accessible user level
    auth_level: int | None = 0
    # Whether it is installed
    installed: bool | None = False
    # Running state
    state: bool | None = False
    # Whether there is a details page
    has_page: bool | None = False
    # Whether there is a new version
    has_update: bool | None = False
    # Whether it is local
    is_local: bool | None = False
    # Repository URL
    repo_url: str | None = None
    # Number of installations
    install_count: int | None = 0
    # Update history
    history: dict | None = Field(default_factory=dict)
    # Add time, the smaller the value, the later it is released
    add_time: int | None = 0
    # Addon public key
    addon_public_key: str | None = None
    # Main program version requirements
    version_required: str | None = None
    # Whether it is a release package
    release: bool = False


class AddonList(RootModel[list[Addon]]):
    def __iter__(self) -> Iterator[Addon]:
        return iter(self.root)

    def __len__(self) -> int:
        return len(self.root)


class AddonApi(BaseModel):
    path: str
    endpoint: Callable[..., Any]
    auth: Literal["anonymous", "apikey", "bear"] = "apikey"
    kwargs: dict = Field(default_factory=dict)


class AddonService(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    # Service ID
    id: str
    # Service name
    name: str
    # Trigger: 'cron', 'interval', 'date', BaseTrigger
    trigger: Literal["cron", "interval", "date"] | BaseTrigger
    # self.xxx
    func: Callable[..., Any]
    # Timer parameters
    kwargs: dict = Field(default_factory=dict)
    # Method parameters
    func_kwargs: dict = Field(default_factory=dict)


class DashboardAttrs(BaseModel):
    # Auto-refresh time in seconds
    refresh: int = 10
    # Whether to display the border, default is True, when False,
    # the component border and margin are cancelled,
    # and the plugin controls it by itself
    border: bool = True
    # Component title, if there is a title, it will be displayed,
    # otherwise the plugin name will be displayed
    title: str | None = None
    # Component subtitle, if omitted, the subtitle will not be displayed
    subtitle: str | None = None


class DashboardCols(BaseModel):
    cols: int = 12
    md: int = 12


class Dashboard(BaseModel):
    # Global configuration
    attrs: Dashboard = Field(default_factory=DashboardAttrs)
    # col columns
    cols: DashboardCols = Field(default_factory=DashboardCols)
    # Page elements
    elements: list[dict] = Field(default_factory=list)


class AddonDashboard(Dashboard):
    """Addon dashboard."""

    # addon id
    id: str
    # name
    name: str
    # dashboard key
    key: str
    # render mode
    render_mode: AddonRenderMode = Field(default=AddonRenderMode.vuetify)
