import mimetypes
from typing import Annotated, Any

import aiofiles
from anyio import Path as AsyncPath
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.concurrency import run_in_threadpool
from starlette import status
from starlette.responses import StreamingResponse

from app import schemas
from app.core.config import settings
from app.core.ctx import Context
from app.core.lock import addon_lock
from app.core.security import verify_apikey, verify_token
from app.db.models import User
from app.db.systemconfig_oper import SystemConfigOper
from app.db.user_oper import (
    get_current_active_superuser,
    get_current_active_superuser_async,
)
from app.factory import app
from app.helper.addon import PluginHelper
from app.log import logger
from app.schemas.types import SystemConfigKey

PROTECTED_ROUTES = {"/api/v1/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
PLUGIN_PREFIX = f"{settings.API_V1_STR}/plugin"

router = APIRouter()


def _update_plugin_api_routes(plugin_id: str | None, action: str):
    """Plugin API route registration and removal :param plugin_id: Plugin ID.

        - If the action is "add" and plugin_id is None, then process all plugins.
        - If the action is "remove", plugin_id must be a valid plugin ID

    :param action: "add" or "remove", determines whether to add or remove the route
    """
    if action not in {"add", "remove"}:
        raise ValueError("Action must be 'add' or 'remove'")

    is_modified = False

    plugin_ids = (
        [plugin_id] if plugin_id else Context.addonmanager.get_running_plugin_ids()
    )
    for plugin_id in plugin_ids:
        routes_removed = _remove_routes(plugin_id)
        if routes_removed:
            is_modified = True

        if action != "add":
            continue
        # Get the API route information of the plugin
        plugin_apis = Context.addonmanager.get_plugin_apis(plugin_id)
        for api in plugin_apis:
            api.path = f"{PLUGIN_PREFIX}{api.path}"
            try:
                dependencies = api.kwargs.setdefault("dependencies", [])
                if not api.auth == "anonymous":
                    if api.auth == "bear" and Depends(verify_token) not in dependencies:
                        dependencies.append(Depends(verify_token))
                    elif Depends(verify_apikey) not in dependencies:
                        dependencies.append(Depends(verify_apikey))
                app.add_api_route(api.path, api.endpoint, **api.kwargs, tags=["plugin"])
                is_modified = True
                logger.debug(f"Added plugin route: {api.path}")
            except Exception as e:
                logger.error(f"Error adding plugin route {api.path}: {str(e)}")

    if is_modified:
        app.setup()


def _remove_routes(plugin_id: str) -> bool:
    """Remove routes related to a single addon.

    :param plugin_id: The addon ID
    :return: Whether any routes have been removed.
    """
    if not plugin_id:
        return False
    prefix = f"{PLUGIN_PREFIX}/{plugin_id}/"
    routes_to_remove = [route for route in app.routes if route.path.startswith(prefix)]
    removed = False
    for route in routes_to_remove:
        try:
            app.routes.remove(route)
            removed = True
            logger.debug(f"Removed plugin route: {route.path}")
        except Exception as e:
            logger.error(f"Error removing plugin route {route.path}: {str(e)}")
    return removed


def remove_plugin_api(plugin_id: str):
    """Dynamically remove the API of a single addon.

    :param plugin_id: The addon ID.
    """
    _update_plugin_api_routes(plugin_id, action="remove")


@router.get("/", summary="All Addons", response_model=list[schemas.Addon])
async def all_addons(
    _: User = Depends(get_current_active_superuser_async),  # noqa: B008
    state: str = "all",
    force: bool = False,
) -> list[schemas.Addon]:
    """Query all addons, including local and online addons.

    Addon states:
        - 'installed'
        - 'market'
        - 'all'
    """
    # Local addons
    local_plugins = Context.addonmanager.get_local_addons()
    # Installed addons
    installed_plugins: list[schemas.Addon] = [
        plugin for plugin in local_plugins if plugin.installed
    ]
    if state == "installed":
        return installed_plugins

    # Not installed local addons
    not_installed_plugins = [plugin for plugin in local_plugins if not plugin.installed]

    online_plugins = await Context.addonmanager.async_get_online_addons(force)
    if not online_plugins:
        # No online addons fetched
        if state == "market":
            # Return not installed local addons
            return not_installed_plugins
        return local_plugins

    # Addon market list
    market_plugins = []
    # Installed addon IDs
    _installed_ids = [plugin.addon_id for plugin in installed_plugins]
    # Not installed online addons or addons with updates
    for plugin in online_plugins:
        if plugin.addon_id not in _installed_ids:
            market_plugins.append(plugin)
        elif plugin.has_update:
            market_plugins.append(plugin)
    # Not installed local addons that are not in the online addons
    _plugin_ids = [plugin.addon_id for plugin in market_plugins]
    for plugin in not_installed_plugins:
        if plugin.addon_id not in _plugin_ids:
            market_plugins.append(plugin)
    # Return addon list
    if state == "market":
        # Return not installed addons
        return market_plugins

    # Return all addons
    return installed_plugins + market_plugins


@router.get(
    "/reload/{plugin_id}", summary="Reload plugin", response_model=schemas.Response
)
def reload_plugin(
    plugin_id: str,
    _: User = Depends(get_current_active_superuser),  # noqa: B008
) -> Any:
    """Reload plugin."""
    # Reload plugin
    Context.addonmanager.reload_addon(plugin_id)
    return schemas.Response(success=True)


@router.get(
    "/install/{plugin_id}", summary="Install addon", response_model=schemas.Response
)
async def install(
    plugin_id: str,
    repo_url: str,
    force: bool | None = False,
    _: User = Depends(get_current_active_superuser_async),  # noqa: B008
) -> Any:
    """Install plugin."""
    # Installed plugins
    async with addon_lock:
        installed_addons = (
            SystemConfigOper().get(SystemConfigKey.UserInstalledAddons) or []
        )
        # Check if the plugin already exists and if it is forced to be installed,
        # otherwise only perform installation statistics
        plugin_helper = PluginHelper()
        if not force and plugin_id in Context.addonmanager.get_addon_ids():
            await plugin_helper.async_install_reg(pid=plugin_id)
        else:
            # The plugin does not exist or needs to be forcibly installed,
            # download, install and register the plugin
            if repo_url:
                state, msg = await plugin_helper.async_install(
                    pid=plugin_id, repo_url=repo_url
                )
                # If the installation fails, respond directly
                if not state:
                    return schemas.Response(success=False, message=msg)
            else:
                # When repo_url is empty, also respond directly
                return schemas.Response(
                    success=False,
                    message="No repository address is passed in, "
                    "the plugin cannot be installed correctly, "
                    "please check the configuration",
                )
        # Install plugin
        if plugin_id not in installed_addons:
            installed_addons.append(plugin_id)
            # Save settings
            await SystemConfigOper().async_set(
                SystemConfigKey.UserInstalledAddons, installed_addons
            )
    # Reload plugin
    await run_in_threadpool(reload_plugin, plugin_id)
    return schemas.Response(success=True)


@router.get(
    "/remotes",
    summary="Get the list of plugin federation components",
    response_model=list[dict],
)
async def remotes(token: str) -> Any:
    """Get the list of plugin federation components."""
    if token != settings.PROJECT_NAME.lower():
        raise HTTPException(status_code=403, detail="Forbidden")
    return Context.addonmanager.get_addon_remotes()


@router.get("/form/{plugin_id}", summary="Get plugin form page")
def plugin_form(
    plugin_id: str,
    _: User = Depends(get_current_active_superuser),  # noqa: B008
) -> dict:
    """Get the plugin configuration form or Vue component URL according to the plugin
    ID."""
    plugin_instance = Context.addonmanager.running_addons.get(plugin_id)
    if not plugin_instance:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plugin {plugin_id} does not exist or is not loaded",
        )

    # Rendering mode
    render_mode, _ = plugin_instance.get_render_mode()
    try:
        conf, model = plugin_instance.get_form()
        return {
            "render_mode": render_mode,
            "conf": conf,
            "model": Context.addonmanager.get_addon_config(plugin_id) or model,
        }
    except Exception as e:
        logger.error(f"Plugin {plugin_id} call method get_form() error: {str(e)}")
    return {}


@router.get("/page/{plugin_id}", summary="Get plugin data page")
def plugin_page(
    plugin_id: str,
    _: User = Depends(get_current_active_superuser),  # noqa: B008
) -> dict:
    """Get the plugin data page according to the plugin ID."""
    plugin_instance = Context.addonmanager.running_addons.get(plugin_id)
    if not plugin_instance:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plugin {plugin_id} does not exist or is not loaded",
        )

    # Rendering mode
    render_mode, _ = plugin_instance.get_render_mode()
    try:
        page = plugin_instance.get_page()
        return {"render_mode": render_mode, "page": page or []}
    except Exception as e:
        logger.error(f"Plugin {plugin_id} call method get_page() error: {str(e)}")
    return {}


@router.get("/{plugin_id}", summary="Get plugin configuration")
async def plugin_config(
    plugin_id: str,
    _: User = Depends(get_current_active_superuser_async),  # noqa: B008
) -> dict:
    """Get plugin configuration information according to plugin ID."""
    return Context.addonmanager.get_addon_config(plugin_id)


@router.put(
    "/{plugin_id}",
    summary="Update plugin configuration",
    response_model=schemas.Response,
)
def set_plugin_config(
    plugin_id: str,
    conf: dict,
    _: User = Depends(get_current_active_superuser),  # noqa: B008
) -> Any:
    """Update plugin configuration."""
    # Save configuration
    Context.addonmanager.save_plugin_config(plugin_id, conf)
    # Re-enable the plugin
    Context.addonmanager.terminate_addon(plugin_id)
    Context.addonmanager.init_addon(plugin_id, conf)
    return schemas.Response(success=True)


@router.delete(
    "/{plugin_id}", summary="Uninstall plugin", response_model=schemas.Response
)
async def uninstall_plugin(
    plugin_id: str,
    _: User = Depends(get_current_active_superuser_async),  # noqa: B008
) -> Any:
    """Uninstall plugin."""
    # Check if the plugin exists
    if plugin_id not in Context.addonmanager.get_addon_ids():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plugin {plugin_id} does not exist",
        )
    async with addon_lock:
        config_oper = SystemConfigOper()
        # Delete installed information
        install_plugins = config_oper.get(SystemConfigKey.UserInstalledAddons) or []
        if plugin_id in install_plugins:
            install_plugins.remove(plugin_id)
            await config_oper.async_set(
                SystemConfigKey.UserInstalledAddons, install_plugins
            )
        # Remove the plugin from the plugin folder
        await _remove_plugin_from_folders(plugin_id)

    # Remove plugin API
    remove_plugin_api(plugin_id)
    # Remove plugin
    await run_in_threadpool(Context.addonmanager.remove_addon, plugin_id)
    return schemas.Response(success=True)


async def _remove_plugin_from_folders(plugin_id: str):
    """Remove the specified plugin from all folders.

    :param plugin_id: The ID of the plugin to be removed
    """
    try:
        config_oper = SystemConfigOper()
        # Get plugin folder configuration
        folders = config_oper.get(SystemConfigKey.PluginFolders) or {}

        # Mark whether there is any modification
        modified = False

        # Traverse all folders and remove the specified plugin
        for folder_name, folder_data in folders.items():
            if plugin_id in folder_data.get("plugins", []):
                folder_data["plugins"].remove(plugin_id)
                logger.info(
                    f"Plugin {plugin_id} has been removed from the folder '{folder_name}'"
                )
                modified = True

        # If there is any modification, save the updated folder configuration
        if modified:
            await config_oper.async_set(SystemConfigKey.PluginFolders, folders)
        else:
            logger.debug(f"Plugin {plugin_id} is not in any folder, no need to remove")

    except Exception as e:
        logger.error(f"Error when removing plugin from folder: {str(e)}")
        # Folder processing failure does not affect the overall process of plugin
        # uninstallation


@router.get("/installed", summary="Installed plugins", response_model=list[str])
async def installed(_: User = Depends(get_current_active_superuser_async)) -> Any:  # noqa: B008
    """Query the list of user-installed plugins."""
    return SystemConfigOper().get(SystemConfigKey.UserInstalledAddons) or []


@router.get("/dashboard/meta", summary="Get all plugin dashboard meta information")
def plugin_dashboard_meta(
    _: schemas.TokenPayload = Depends(verify_token),  # noqa: B008
) -> list[dict]:
    """Get all plugin dashboard meta-information."""
    return Context.addonmanager.get_plugin_dashboard_meta()


@router.get(
    "/dashboard/{plugin_id}/{key}",
    summary="Get plugin dashboard configuration",
    response_model=schemas.AddonDashboard,
)
def plugin_dashboard_by_key(
    plugin_id: str,
    key: str,
    user_agent: Annotated[str | None, Header()] = None,
    _: schemas.TokenPayload = Depends(verify_token),  # noqa: B008
) -> schemas.AddonDashboard:
    """Get the plugin dashboard according to the plugin ID."""
    dashboard = Context.addonmanager.get_plugin_dashboard(plugin_id, key, user_agent)
    if dashboard is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plugin {plugin_id} does not exist or call method get_dashboard() error",
        )
    return dashboard


@router.get("/dashboard/{plugin_id}", summary="Get plugin dashboard configuration")
def plugin_dashboard(
    plugin_id: str,
    user_agent: Annotated[str | None, Header()] = None,
    _: schemas.TokenPayload = Depends(verify_token),  # noqa: B008
) -> schemas.AddonDashboard:
    """Get the plugin dashboard according to the plugin ID."""
    return plugin_dashboard_by_key(plugin_id, "", user_agent)


@router.get("/file/{plugin_id}/{filepath:path}", summary="Get plugin static file")
async def plugin_static_file(plugin_id: str, filepath: str):
    """Get plugin static files."""
    # Basic security check
    if ".." in filepath or ".." in plugin_id:
        logger.warning(
            f"Static File API: Path traversal attempt detected: {plugin_id}/{filepath}"
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    plugin_base_dir = (
        AsyncPath(settings.ROOT_PATH) / "app" / "addons" / plugin_id.lower()
    )
    plugin_file_path = plugin_base_dir / filepath
    if not await plugin_file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{plugin_file_path} does not exist",
        )
    if not await plugin_file_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"{plugin_file_path} is not a file",
        )

    # Determine the MIME type
    response_type, _ = mimetypes.guess_type(str(plugin_file_path))
    suffix = plugin_file_path.suffix.lower()
    # Forcibly correct the MIME type of .mjs and .js
    if suffix in [".js", ".mjs"]:
        response_type = "application/javascript"
    elif (
        suffix == ".css" and not response_type
    ):  # If guess_type does not guess css correctly, also correct it
        response_type = "text/css"
    elif not response_type:  # For other types that cannot be guessed
        response_type = "application/octet-stream"

    try:
        # Asynchronous generator function for streaming file reading
        async def file_generator():
            async with aiofiles.open(plugin_file_path, mode="rb") as file:
                # 8KB block size
                while chunk := await file.read(8192):
                    yield chunk

        return StreamingResponse(
            file_generator(),
            media_type=response_type,
            headers={
                "Content-Disposition": f"inline; filename={plugin_file_path.name}"
            },
        )
    except Exception as e:
        logger.error(
            f"Error creating/sending StreamingResponse for {plugin_file_path}: {e}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Internal Server Error") from e
