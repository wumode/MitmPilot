import re
from pathlib import Path

import aiofiles

from app.chain import ChainBase
from app.core.config import settings
from app.log import logger
from app.utils.http import RequestUtils
from version import APP_VERSION, FRONTEND_VERSION


class SystemChain(ChainBase):
    """System-level processing chain."""

    _restart_file = "__system_restart__"

    async def __get_version_message(self) -> str:
        """Get version information text."""
        server_release_version = self.__get_server_release_version()
        front_release_version = self.__get_front_release_version()
        server_local_version = self.get_server_local_version()
        front_local_version = await self.get_frontend_version()
        if server_release_version == server_local_version:
            title = (
                f"Current backend version: {server_local_version}, "
                f"already the latest version\n"
            )
        else:
            title = (
                f"Current backend version: {server_local_version}, "
                f"remote version: {server_release_version}\n"
            )
        if front_release_version == front_local_version:
            title += (
                f"Current frontend version: {front_local_version}, "
                f"already the latest version"
            )
        else:
            title += (
                f"Current frontend version: {front_local_version}, "
                f"remote version: {front_release_version}"
            )
        return title

    @staticmethod
    def __get_server_release_version():
        """Get the latest version of the backend V2."""
        try:
            # Get a list of all released versions
            response = RequestUtils(
                proxies=settings.PROXY, headers=settings.GITHUB_HEADERS
            ).get_res("https://api.github.com/repos/wumode/MitmPilot/releases")
            if response:
                releases = [release["tag_name"] for release in response.json()]
                if not releases:
                    logger.warn("Error getting the latest version of the backend!")
                else:
                    # Find the latest version
                    latest = sorted(
                        releases, key=lambda s: list(map(int, re.findall(r"\d+", s)))
                    )[-1]
                    logger.info(f"Get the latest backend version: {latest}")
                    return latest
            else:
                logger.error(
                    "Unable to obtain backend version information, "
                    "please check the network connection or GitHub API request."
                )
        except Exception as err:
            logger.error(f"Failed to get the latest backend version: {str(err)}")
        return None

    @staticmethod
    def __get_front_release_version():
        """Get the latest version of the frontend V2."""
        try:
            # Get a list of all released versions
            response = RequestUtils(
                proxies=settings.PROXY, headers=settings.GITHUB_HEADERS
            ).get_res("https://api.github.com/repos/wumode/MitmPilot-Frontend/releases")
            if response:
                releases = [release["tag_name"] for release in response.json()]
                if not releases:
                    logger.warn("Error getting the latest version of the frontend!")
                else:
                    # Find the latest version
                    latest = sorted(
                        releases, key=lambda s: list(map(int, re.findall(r"\d+", s)))
                    )[-1]
                    logger.info(f"Get the latest frontend version: {latest}")
                    return latest
            else:
                logger.error(
                    "Unable to obtain frontend version information, "
                    "please check the network connection or GitHub API request."
                )
        except Exception as err:
            logger.error(f"Failed to get the latest frontend version: {str(err)}")
        return None

    @staticmethod
    def get_server_local_version():
        """View the current version."""
        return APP_VERSION

    @staticmethod
    async def get_frontend_version():
        """Get frontend version."""
        version_file = Path(settings.FRONTEND_PATH) / "version.txt"
        if version_file.exists():
            try:
                async with aiofiles.open(version_file) as f:
                    version = str(await f.read()).strip()
                return version
            except Exception as err:
                logger.debug(f"Error loading version file {version_file}: {str(err)}")
        return FRONTEND_VERSION
