import asyncio
import io
import shutil
import sys
import traceback
import zipfile
from collections.abc import Awaitable, Callable
from pathlib import Path

import aiofiles
import aioshutil
from anyio import Path as AsyncPath
from pydantic import ValidationError
from requests import Response

from app.core.cache import cached, fresh
from app.core.config import settings
from app.db.systemconfig_oper import SystemConfigOper
from app.log import logger
from app.schemas import Addon, AddonList, GithubItem
from app.schemas.types import SystemConfigKey
from app.utils.http import AsyncRequestUtils, RequestUtils
from app.utils.singleton import WeakSingleton
from app.utils.string import StringUtils
from version import APP_VERSION

ADDON_DIR = Path(settings.ROOT_PATH) / "app" / settings.ADDON_FOLDER


class PluginHelper(metaclass=WeakSingleton):
    """Plugin market management, download and install plugins locally."""

    _base_url = "https://raw.githubusercontent.com/{user}/{repo}/main/"
    _install_reg = f"{settings.MP_SERVER_HOST}/plugin/install/{{aid}}"
    _install_report = f"{settings.MP_SERVER_HOST}/plugin/install"
    _install_statistic = f"{settings.MP_SERVER_HOST}/plugin/statistic"
    _pyproject = "pyproject.toml"

    def __init__(self):
        self.systemconfig = SystemConfigOper()
        if settings.PLUGIN_STATISTIC_SHARE:
            if not self.systemconfig.get(SystemConfigKey.PluginInstallReport):
                if self.install_report():
                    self.systemconfig.set(SystemConfigKey.PluginInstallReport, "1")

    def get_plugins(self, repo_url: str, force: bool = False) -> AddonList | None:
        """Retrieves a list of all the latest plugins from GitHub.

        :param repo_url: GitHub repository address
        :param force: Whether to force refresh, ignoring the cache.
        """
        with fresh(force):
            return self._request_plugins(repo_url)

    @staticmethod
    def get_repo_info(repo_url: str) -> tuple[str | None, str | None]:
        """Retrieves GitHub repository information."""
        if not repo_url:
            return None, None
        if not repo_url.endswith("/"):
            repo_url += "/"
        if repo_url.count("/") < 6:
            repo_url = f"{repo_url}main/"
        try:
            user, repo = repo_url.split("/")[-4:-2]
        except Exception as e:
            logger.error(f"解析GitHub仓库地址失败：{str(e)} - {traceback.format_exc()}")
            return None, None
        return user, repo

    @cached(maxsize=1, ttl=1800)
    def get_statistic(self) -> dict:
        """Retrieves plugin installation statistics."""
        if not settings.PLUGIN_STATISTIC_SHARE:
            return {}
        res = RequestUtils(proxies=settings.PROXY, timeout=10).get_res(
            self._install_statistic
        )
        if res is not None and res.status_code == 200:
            return res.json()
        return {}

    def install_reg(self, pid: str, repo_url: str | None = None) -> bool:
        """Registers plugin installation for statistics."""
        if not settings.PLUGIN_STATISTIC_SHARE:
            return False
        if not pid:
            return False
        install_reg_url = self._install_reg.format(pid=pid)
        res = RequestUtils(
            proxies=settings.PROXY, content_type="application/json", timeout=5
        ).post(install_reg_url, json={"addon_id": pid, "repo_url": repo_url})
        if res is not None and res.status_code == 200:
            return True
        return False

    def install_report(self, items: list[tuple[str, str | None]] | None = None) -> bool:
        """Reports existing plugin installation statistics (batch).

        :param items: Optional, in the format [(addon_id, repo_url), ...];
                      if not provided, it falls back to historical configuration,
                      only sending addon_id.
        """
        if not settings.PLUGIN_STATISTIC_SHARE:
            return False
        payload_plugins = []
        if items:
            for pid, repo_url in items:
                if pid:
                    payload_plugins.append({"addon_id": pid, "repo_url": repo_url})
        else:
            plugins = self.systemconfig.get(SystemConfigKey.UserInstalledAddons)
            if not plugins:
                return False
            payload_plugins = [
                {"addon_id": plugin, "repo_url": None} for plugin in plugins
            ]
        res = RequestUtils(
            proxies=settings.PROXY, content_type="application/json", timeout=5
        ).post(self._install_report, json={"plugins": payload_plugins})
        return True if res else False

    @staticmethod
    def __backup_plugin(pid: str) -> str | None:
        """Backs up the old plugin directory.

        :param pid: Plugin ID
        :return: Path to the backup directory
        """
        plugin_dir = ADDON_DIR / pid.lower()
        backup_dir = Path(settings.TEMP_PATH) / "plugin_backup" / pid.lower()

        if plugin_dir.exists():
            # Clear the existing backup directory during backup to prevent residual
            # files from affecting it.
            if backup_dir.exists():
                shutil.rmtree(backup_dir, ignore_errors=True)
                logger.debug(f"{pid} Old backup directory cleared {backup_dir}")

            shutil.copytree(plugin_dir, backup_dir, dirs_exist_ok=True)
            logger.debug(f"{pid} 插件已备份到 {backup_dir}")

        return str(backup_dir) if backup_dir.exists() else None

    @staticmethod
    def __restore_plugin(pid: str, backup_dir: str):
        """Restores the old plugin directory.

        :param pid: Plugin ID
        :param backup_dir: Path to the backup directory
        """
        plugin_dir = ADDON_DIR / pid.lower()
        if plugin_dir.exists():
            shutil.rmtree(plugin_dir, ignore_errors=True)
            logger.debug(f"{pid} 已清理插件目录 {plugin_dir}")

        if Path(backup_dir).exists():
            shutil.copytree(backup_dir, plugin_dir, dirs_exist_ok=True)
            logger.debug(f"{pid} 已还原插件目录 {plugin_dir}")
            shutil.rmtree(backup_dir, ignore_errors=True)
            logger.debug(f"{pid} 已删除备份目录 {backup_dir}")

    @staticmethod
    def __remove_old_plugin(pid: str):
        """Removes the old plugin.

        :param pid: Plugin ID
        """
        plugin_dir = ADDON_DIR / pid.lower()
        if plugin_dir.exists():
            shutil.rmtree(plugin_dir, ignore_errors=True)

    @staticmethod
    def _request_github(
        url: str, headers: dict | None = None, timeout: int = 30
    ) -> Response | None:
        res = RequestUtils(
            headers=headers or settings.GITHUB_HEADERS,
            timeout=timeout,
            proxies=settings.PROXY,
        ).get_res(url)

        return res

    @staticmethod
    async def _async_request_github(
        url: str, headers: dict | None = None, timeout: int = 30
    ) -> Response | None:
        res = await AsyncRequestUtils(
            headers=headers or settings.GITHUB_HEADERS,
            timeout=timeout,
            proxies=settings.PROXY,
        ).get_res(url)

        return res

    @staticmethod
    def __standardize_pkg_name(name: str) -> str:
        """Standardizes the package name by converting it to lowercase and replacing
        hyphens with underscores.

        :param name: Original package name
        :return: Standardized package name
        """
        return name.lower().replace("-", "_") if name else name

    async def async_get_plugin_package_version(
        self, pid: str, repo_url: str
    ) -> str | None:
        """Asynchronous version of the method to get the plugin version, same
        functionality as get_plugin_package_version."""
        addons = await self.async_get_plugins(repo_url)
        if addons is None:
            return None
        addon = next((item for item in addons if item.id == pid), None)
        if addon is not None:
            version_required = addon.version_required or "0.0.0"
            return version_required
        return None

    @cached(maxsize=128, ttl=1800)
    async def async_get_plugins(self, repo_url: str) -> AddonList | None:
        """Asynchronously retrieves a list of all the latest plugins from GitHub.

        :param repo_url: GitHub repository address
        """
        user, repo = self.get_repo_info(repo_url)
        if not user or not repo:
            return None
        raw_url = self._base_url.format(user=user, repo=repo)
        package_url = f"{raw_url}package.json"

        res = await PluginHelper._async_request_github(url=package_url)
        if res is None:
            return None
        if res:
            content = res.text
            try:
                return AddonList.model_validate_json(content)
            except ValidationError:
                logger.warn(f"插件包数据解析失败：{content}")
                return None
        return None

    @cached(maxsize=128, ttl=1800)
    def _request_plugins(self, repo_url: str) -> AddonList | None:
        """Retrieves a list of all the latest plugins from GitHub (without cache).

        :param repo_url: GitHub repository address
        """
        user, repo = self.get_repo_info(repo_url)
        if not user or not repo:
            return None
        raw_url = self._base_url.format(user=user, repo=repo)
        package_url = f"{raw_url}package.json"

        res = PluginHelper._request_github(url=package_url)
        if res is None:
            return None
        if res:
            content = res.text
            try:
                return AddonList.model_validate_json(content)
            except ValidationError:
                logger.warn(f"插件包数据解析失败：{content}")
                return None
        return None

    async def async_get_statistic(self) -> dict:
        """Asynchronously retrieves plugin installation statistics."""
        if not settings.PLUGIN_STATISTIC_SHARE:
            return {}
        res = await AsyncRequestUtils(proxies=settings.PROXY, timeout=10).get_res(
            self._install_statistic
        )
        if res is None:
            return {}
        if res.status_code == 200:
            return res.json()
        return {}

    async def async_install_reg(self, pid: str, repo_url: str | None = None) -> bool:
        """Asynchronously registers plugin installation for statistics."""
        if not settings.PLUGIN_STATISTIC_SHARE:
            return False
        if not pid:
            return False
        install_reg_url = self._install_reg.format(pid=pid)
        res = await AsyncRequestUtils(
            proxies=settings.PROXY, content_type="application/json", timeout=5
        ).post(install_reg_url, json={"addon_id": pid, "repo_url": repo_url})
        if res is not None and res.status_code == 200:
            return True
        return False

    async def async_install_report(
        self, items: list[tuple[str, str | None]] | None = None
    ) -> bool:
        """Asynchronously reports existing plugin installation statistics (batch).

        :param items: Optional, in the format [(addon_id, repo_url), ...];
                      if not provided, it falls back to historical configuration,
                      only sending addon_id.
        """
        if not settings.PLUGIN_STATISTIC_SHARE:
            return False
        payload_plugins = []
        if items:
            for pid, repo_url in items:
                if pid:
                    payload_plugins.append({"addon_id": pid, "repo_url": repo_url})
        else:
            plugins = self.systemconfig.get(SystemConfigKey.UserInstalledAddons)
            if not plugins:
                return False
            payload_plugins = [
                {"addon_id": plugin, "repo_url": None} for plugin in plugins
            ]
        res = await AsyncRequestUtils(
            proxies=settings.PROXY, content_type="application/json", timeout=5
        ).post(self._install_report, json={"plugins": payload_plugins})
        return True if res else False

    @staticmethod
    async def __async_get_file_list(
        pid: str, user_repo: str
    ) -> tuple[list[GithubItem] | None, str]:
        """Asynchronously retrieves the plugin's file list.

        :param pid: Plugin ID
        :param user_repo: GitHub repository user/repo path
        :return: File list, error message
        """
        file_api = (
            f"https://api.github.com/repos/{user_repo}/contents/addons/{pid.lower()}"
        )
        res = await PluginHelper._async_request_github(file_api)
        if res is None:
            return None, "连接仓库失败"
        elif res.status_code != 200:
            return (
                None,
                f"Failed to connect to repository: {res.status_code} - "
                f"{
                    'Rate limit exceeded, please set Github Token or try again later'
                    if res.status_code == 403
                    else res.reason
                }",
            )

        try:
            ret: list[GithubItem] = []
            for item in res.json():
                ret.append(GithubItem.model_validate(item))
            if isinstance(ret, list) and len(ret) > 0 and "message" not in ret[0]:
                return ret, ""
            else:
                return (
                    None,
                    "Plugin does not exist in the repository or "
                    "the returned data format is incorrect",
                )
        except Exception as e:
            logger.error(f"Failed to parse plugin data: {e}")
            return None, "Failed to parse plugin data"

    async def __async_download_files(
        self, pid: str, file_list: list[GithubItem], user_repo: str
    ) -> tuple[bool, str]:
        """Asynchronously downloads plugin files.

        :param pid: Plugin ID
        :param file_list: List of files to download, including file metadata
        :param user_repo: GitHub repository user/repo path
        :return: Success status, error message
        """
        if not file_list:
            return False, "File list is empty"

        # 使用栈结构来替代递归调用，避免递归深度过大问题
        stack = [(pid, file_list)]

        while stack:
            current_pid, current_file_list = stack.pop()

            for item in current_file_list:
                if item.download_url:
                    logger.debug(f"Downloading file: {item.path}")
                    res = await self._async_request_github(item.download_url)
                    if not res:
                        return False, f"File {item.path} download failed!"
                    elif res.status_code != 200:
                        return (
                            False,
                            f"Failed to download file {item.path}: {res.status_code}",
                        )

                    relative_path: str = item.path
                    # 创建插件文件夹并写入文件
                    file_path = AsyncPath(settings.ROOT_PATH) / "app" / relative_path
                    await file_path.parent.mkdir(parents=True, exist_ok=True)
                    async with aiofiles.open(file_path, "w", encoding="utf-8") as f:
                        await f.write(res.text)
                    logger.debug(
                        f"File {item.path} downloaded successfully, saved to: {file_path}"
                    )
                else:
                    # If it's a subdirectory, add its contents to the stack for further
                    # processing.
                    sub_list, msg = await self.__async_get_file_list(
                        f"{current_pid}/{item.name}", user_repo
                    )
                    if not sub_list:
                        return False, msg
                    stack.append((f"{current_pid}/{item.name}", sub_list))

        return True, ""

    async def __async_backup_plugin(self, pid: str) -> str | None:
        """Asynchronously backs up the old plugin directory.

        :param pid: Plugin ID
        :return: Path to the backup directory
        """
        plugin_dir = AsyncPath(ADDON_DIR) / pid.lower()
        backup_dir = AsyncPath(settings.TEMP_PATH) / "plugin_backup" / pid.lower()

        if await plugin_dir.exists():
            # Clear the existing backup directory during backup to prevent residual
            # files from affecting it.
            if await backup_dir.exists():
                await aioshutil.rmtree(backup_dir, ignore_errors=True)
                logger.debug(f"{pid} Old backup directory cleared {backup_dir}")

            # Asynchronously copy the directory.
            await self._async_copytree(plugin_dir, backup_dir)
            logger.debug(f"{pid} Plugin backed up to {backup_dir}")

        return str(backup_dir) if await backup_dir.exists() else None

    async def __async_restore_plugin(self, pid: str, backup_dir: str):
        """Asynchronously restores the old plugin directory.

        :param pid: Plugin ID
        :param backup_dir: Path to the backup directory
        """
        plugin_dir = AsyncPath(ADDON_DIR) / pid.lower()
        if await plugin_dir.exists():
            await aioshutil.rmtree(plugin_dir, ignore_errors=True)
            logger.debug(f"{pid} Plugin directory cleared {plugin_dir}")

        backup_path = AsyncPath(backup_dir)
        if await backup_path.exists():
            await self._async_copytree(src=backup_path, dst=plugin_dir)
            logger.debug(f"{pid} Plugin directory restored {plugin_dir}")
            await aioshutil.rmtree(backup_path, ignore_errors=True)
            logger.debug(f"{pid} Backup directory deleted {backup_dir}")

    @staticmethod
    async def __async_remove_old_plugin(pid: str):
        """Asynchronously removes the old plugin.

        :param pid: Plugin ID
        """
        plugin_dir = AsyncPath(ADDON_DIR) / pid.lower()
        if await plugin_dir.exists():
            await aioshutil.rmtree(plugin_dir, ignore_errors=True)

    async def _async_copytree(self, src: AsyncPath, dst: AsyncPath):
        """Asynchronously and recursively copies a directory.

        :param src: Source directory
        :param dst: Destination directory
        """
        if not await src.exists():
            return

        await dst.mkdir(parents=True, exist_ok=True)

        async for item in src.iterdir():
            dst_item = dst / item.name
            if await item.is_dir():
                await self._async_copytree(item, dst_item)
            else:
                async with aiofiles.open(item, "rb") as src_file:
                    content = await src_file.read()
                async with aiofiles.open(dst_item, "wb") as dst_file:
                    await dst_file.write(content)

    async def async_install(
        self,
        pid: str,
        repo_url: str,
        force_install: bool = False,
    ) -> tuple[bool, str]:
        """Asynchronously installs a plugin, including dependency installation and file
        download, with automatic fallback for related resources.

        1. Check and get the specified plugin version, confirm version compatibility.
        2. Get the file list from GitHub (including requirements.txt).
        3. Delete the old plugin directory (backup if not a forced installation).
        4. Download and pre-install dependencies from requirements.txt (if present).
        5. Download and install other plugin files.
        6. Attempt to install dependencies again (to ensure complete installation).
        :param pid: Plugin ID
        :param repo_url: Plugin repository address
        :param force_install: Whether to install the plugin forcibly. Disabled by
                              default, no backup or restore operations are performed
                              when enabled.
        :return: (Success status, error message)
        """

        # Validate parameters
        if not pid or not repo_url:
            return False, "Parameter error"

        # Get user and repository name from GitHub repo_url
        user, repo = self.get_repo_info(repo_url)
        if not user or not repo:
            return False, "Unsupported plugin repository address format"

        user_repo = f"{user}/{repo}"

        # 1. Prioritize checking for the specified plugin version
        meta = await self.__async_get_plugin_meta(pid, repo_url)

        if meta is None or StringUtils.compare_version(
            meta.version_required if meta.version_required else "0.0.0",
            ">",
            APP_VERSION,
        ):
            msg = f"{pid} No plugin found for the current version"
            logger.debug(msg)
            return False, msg
        # package_version is empty, indicating that the plugin was found in package.json
        logger.debug(f"{pid} Plugin found for the current version in package.json")

        # 2. Unified asynchronous installation process (release or file list)

        # Whether it's a release package
        is_release = meta.release
        # Plugin version number
        plugin_version = meta.addon_version
        if is_release:
            # Use PluginID_PluginVersion as Release tag
            if not plugin_version:
                return (
                    False,
                    f"Version number for {pid} not found in plugin manifest, unable to "
                    f"perform Release installation",
                )
            # Concatenate release_tag
            release_tag = f"{pid}_v{plugin_version}"

            # Install using release
            async def prepare_release() -> tuple[bool, str]:
                return await self.__async_install_from_release(
                    pid, user_repo, release_tag
                )

            return await self.__install_flow_async(
                pid, force_install, prepare_release, repo_url
            )
        else:
            # If there is no release_tag, use the file list installation method.
            async def prepare_filelist() -> tuple[bool, str]:
                return await self.__prepare_content_via_filelist_async(pid, user_repo)

            return await self.__install_flow_async(
                pid, force_install, prepare_filelist, repo_url
            )

    async def __async_get_plugin_meta(self, pid: str, repo_url: str) -> Addon | None:
        try:
            addons = await self.async_get_plugins(repo_url)
            if addons is None:
                return None
            return next((item for item in addons if item.addon_id == pid), None)
        except Exception as e:
            logger.warn(f"Failed to get plugin {pid} metadata: {e}")
            return None

    async def async_init_venv(self, pid: str) -> tuple[bool, str]:
        # Check and create a virtual environment and install dependencies for the plugin.
        target_path = ADDON_DIR / pid.lower()
        pyproject_path = target_path / self._pyproject
        if pyproject_path.exists():
            logger.info(
                f"pyproject.toml detected, creating virtual environment and installing "
                f"dependencies for {pid}..."
            )
            try:
                uv_path = settings.UV_PATH
                if not uv_path.exists():
                    err_msg = (
                        "uv command not found, please ensure uv is "
                        "installed and in PATH environment variable"
                    )
                    logger.error(err_msg)
                    return False, err_msg

                # 1. Create virtual environment
                logger.info(f"Creating virtual environment for plugin {pid}...")
                process_venv = await asyncio.create_subprocess_shell(
                    f'"{uv_path}" venv -p "{sys.executable}"',
                    cwd=str(target_path),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr_venv = await process_venv.communicate()
                if process_venv.returncode != 0:
                    err_msg = (
                        f"Failed to create virtual environment for plugin "
                        f"{pid}: {stderr_venv.decode()}"
                    )
                    logger.error(err_msg)

                    return False, err_msg
                logger.info(
                    f"Virtual environment for plugin {pid} created successfully."
                )

                # 2. Install dependencies
                logger.info(f"Installing dependencies for plugin {pid}...")
                process_install = await asyncio.create_subprocess_shell(
                    f'"{uv_path}" pip install .',
                    cwd=str(target_path),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr_install = await process_install.communicate()
                if process_install.returncode != 0:
                    err_msg = (
                        f"Failed to install dependencies for plugin "
                        f"{pid}: {stderr_install.decode()}"
                    )
                    logger.error(err_msg)
                    return False, err_msg
                logger.info(f"Dependencies for plugin {pid} installed successfully.")
            except Exception as e:
                err_msg = f"Error executing uv command: {e}"
                logger.error(err_msg)
                return False, err_msg
        return True, ""

    async def __install_flow_async(
        self,
        pid: str,
        force_install: bool,
        prepare_content: Callable[[], Awaitable[tuple[bool, str]]],
        repo_url: str | None = None,
    ) -> tuple[bool, str]:
        """Asynchronous installation flow, handling plugin content preparation,
        dependency installation, and registration."""
        backup_dir = None
        if not force_install:
            backup_dir = await self.__async_backup_plugin(pid)

        await self.__async_remove_old_plugin(pid)

        success, message = await prepare_content()
        if not success:
            logger.error(f"{pid} Failed to prepare plugin content: {message}")
            if backup_dir:
                await self.__async_restore_plugin(pid, backup_dir)
                logger.warning(
                    f"{pid} Plugin installation failed, backup plugin restored"
                )
            else:
                await self.__async_remove_old_plugin(pid)
                logger.warning(
                    f"{pid} Corresponding plugin directory has been cleaned, "
                    f"please try to reinstall"
                )
            return False, message

        success, message = await self.async_init_venv(pid=pid)
        if not success:
            if backup_dir:
                await self.__async_restore_plugin(pid, backup_dir)
                logger.warning(
                    f"{pid} Plugin installation failed, backup plugin restored"
                )
        await self.async_install_reg(pid, repo_url)
        return True, ""

    async def __prepare_content_via_filelist_async(
        self, pid: str, user_repo: str
    ) -> tuple[bool, str]:
        """Asynchronously prepares plugin content, getting plugin files and dependencies
        via the file list."""
        file_list, msg = await self.__async_get_file_list(pid, user_repo)
        if not file_list:
            return False, msg
        ok, m = await self.__async_download_files(pid, file_list, user_repo)
        if not ok:
            return False, m
        return True, ""

    async def __async_install_from_release(
        self, pid: str, user_repo: str, release_tag: str
    ) -> tuple[bool, str]:
        """Installs a plugin from a GitHub Release asset file (asynchronously).

        Specification: The release contains an asset named "{aid}_v{version}.zip",
        where the zip root is the plugin files;
        Extract all of them to app/addons/{aid}
        """
        # 拼接资产文件名
        asset_name = f"{release_tag.lower()}.zip"

        release_api = (
            f"https://api.github.com/repos/{user_repo}/releases/tags/{release_tag}"
        )
        rel_res = await self._async_request_github(release_api)
        if rel_res is None or rel_res.status_code != 200:
            return (
                False,
                f"Failed to get Release information: {
                    rel_res.status_code if rel_res else 'Connection failed'
                }",
            )

        try:
            rel_json = rel_res.json()
            assets = rel_json.get("assets") or []
            asset = next((a for a in assets if a.get("name") == asset_name), None)
            if not asset:
                return False, f"Asset file not found: {asset_name}"
            asset_id = asset.get("id")
            if not asset_id:
                return False, "Asset missing ID information"
            # Construct the API download URL for the asset
            download_url = (
                f"https://api.github.com/repos/{user_repo}/releases/assets/{asset_id}"
            )
        except Exception as e:
            logger.error(f"Failed to parse Release information: {e}")
            return False, f"Failed to parse Release information: {e}"

        # 使用资产的API端点下载，需要设置Accept头为application/octet-stream
        headers = settings.REPO_GITHUB_HEADERS(repo=user_repo).copy()
        headers["Accept"] = "application/octet-stream"
        res = await self._async_request_github(download_url, headers=headers)
        if res is None or res.status_code != 200:
            return (
                False,
                f"Failed to download asset: {
                    res.status_code if res else 'Connection failed'
                }",
            )

        try:
            with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
                namelist = zf.namelist()
                if not namelist:
                    return False, "Zip file content is empty"
                names_with_slash = [n for n in namelist if "/" in n]
                base_prefix = ""
                if names_with_slash and len(names_with_slash) == len(namelist):
                    first_seg = names_with_slash[0].split("/")[0]
                    if all(n.startswith(first_seg + "/") for n in namelist):
                        base_prefix = first_seg + "/"

                dest_base = (
                    AsyncPath(settings.ROOT_PATH)
                    / "app"
                    / settings.ADDON_FOLDER
                    / pid.lower()
                )
                wrote_any = False
                for name in namelist:
                    rel_path = name[len(base_prefix) :]
                    if not rel_path:
                        continue
                    if rel_path.endswith("/"):
                        await (dest_base / rel_path.rstrip("/")).mkdir(
                            parents=True, exist_ok=True
                        )
                        continue
                    dest_path = dest_base / rel_path
                    await dest_path.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(name, "r") as src:
                        data = src.read()
                    async with aiofiles.open(dest_path, "wb") as dst:
                        await dst.write(data)
                    wrote_any = True
                if not wrote_any:
                    return False, "No writable files in the zip package"
            return True, ""
        except Exception as e:
            logger.error(f"Failed to decompress Release zip package: {e}")
            return False, f"Failed to decompress Release zip package: {e}"

    @staticmethod
    def process_plugins_list(base_version_plugins: list[Addon]) -> list[Addon]:
        """
        Processes the plugin list: merges, deduplicates, sorts, and keeps the highest
        version.
        :param base_version_plugins: List of base version plugins
        :return: Processed plugin list
        """
        # Prioritize processing higher version plugins
        all_plugins = [*base_version_plugins]
        # Deduplicate
        all_plugins = list(
            {f"{p.addon_id}{p.addon_version}": p for p in all_plugins}.values()
        )
        # Sort all plugins by repo order in settings
        all_plugins.sort(
            key=lambda x: settings.ADDON_MARKET.split(",").index(x.repo_url)
            if x.repo_url
            else 0
        )
        # For plugins with the same ID, keep the one with the highest version number.
        max_versions = {}
        for p in all_plugins:
            if p.addon_id not in max_versions or StringUtils.compare_version(
                p.addon_version, ">", max_versions[p.addon_id]
            ):
                max_versions[p.addon_id] = p.addon_version
        result = [p for p in all_plugins if p.addon_version == max_versions[p.addon_id]]
        logger.info(f"Retrieved {len(result)} online plugins in total")
        return result
