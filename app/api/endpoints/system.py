import asyncio
import io
from collections import deque
from pathlib import Path
from typing import Annotated

import aiofiles
import yaml
from anyio import Path as AsyncPath
from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse, StreamingResponse
from PIL import Image

from app import schemas
from app.chain.system import SystemChain
from app.core.cache import AsyncFileCache
from app.core.config import global_vars, settings
from app.core.ctx import Context
from app.core.event import eventmanager
from app.core.security import verify_apikey, verify_resource_token, verify_token
from app.db.models import User
from app.db.systemconfig_oper import SystemConfigOper
from app.db.user_oper import (
    get_current_active_superuser,
    get_current_active_superuser_async,
    get_current_active_user_async,
)
from app.helper.message import MessageHelper
from app.log import logger
from app.scheduler import Scheduler
from app.schemas import ConfigChangeEventData
from app.schemas.types import EventType, SystemConfigKey
from app.utils.crypto import HashUtils
from app.utils.http import AsyncRequestUtils, RequestUtils
from app.utils.security import SecurityUtils
from app.utils.url import UrlUtils
from version import APP_VERSION

router = APIRouter()


async def fetch_image(
    url: str,
    proxy: bool = False,
    use_cache: bool = False,
    if_none_match: str | None = None,
    allowed_domains: set[str] | None = None,
) -> Response | None:
    """Process image cache logic, support HTTP cache and disk cache."""
    if not url:
        return None

    if allowed_domains is None:
        allowed_domains = set(settings.SECURITY_IMAGE_DOMAINS)

    # Verify URL security
    if not SecurityUtils.is_safe_url(url, allowed_domains):
        logger.warn(f"Blocked unsafe image URL: {url}")
        return None

    # Cache path
    sanitized_path = SecurityUtils.sanitize_url_path(url)
    cache_path = Path("images") / sanitized_path
    if not cache_path.suffix:
        # If there is no file type, add a suffix, a compromise between malicious file
        # types and actual needs
        cache_path = cache_path.with_suffix(".jpg")

    # Cache object, the cache expiration time is the global image cache days
    cache_backend = AsyncFileCache(
        base=settings.CACHE_PATH, ttl=settings.GLOBAL_IMAGE_CACHE_DAYS * 24 * 3600
    )

    if use_cache:
        content = await cache_backend.get(cache_path.as_posix(), region="images")
        if content:
            # Check If-None-Match
            etag = HashUtils.md5(content)
            headers = RequestUtils.generate_cache_headers(etag, max_age=86400 * 7)
            if if_none_match == etag:
                return Response(status_code=304, headers=headers)
            # Return cached image
            return Response(
                content=content,
                media_type=UrlUtils.get_mime_type(url, "image/jpeg"),
                headers=headers,
            )

    # Request remote image
    referer = "https://movie.douban.com/" if "doubanio.com" in url else None
    proxies = settings.PROXY if proxy else None
    response = await AsyncRequestUtils(
        ua=settings.NORMAL_USER_AGENT,
        proxies=proxies,
        referer=referer,
        accept_type="image/avif,image/webp,image/apng,*/*",
    ).get_res(url=url)
    if not response:
        logger.warn(f"Failed to fetch image from URL: {url}")
        return None

    # Verify that the downloaded content is a valid image
    try:
        content = response.content
        Image.open(io.BytesIO(content)).verify()  # type: ignore
    except Exception as e:
        logger.warn(f"Invalid image format for URL {url}: {e}")
        return None

    # Get request response header
    response_headers = response.headers
    cache_control_header = response_headers.get("Cache-Control", "")
    cache_directive, max_age = RequestUtils.parse_cache_control(cache_control_header)

    # Save cache
    if use_cache:
        await cache_backend.set(cache_path.as_posix(), content, region="images")
        logger.debug(f"Image cached at {cache_path.as_posix()}")

    # Check If-None-Match
    etag = HashUtils.md5(content)
    if if_none_match == etag:
        headers = RequestUtils.generate_cache_headers(etag, cache_directive, max_age)
        return Response(status_code=304, headers=headers)

    # Response
    headers = RequestUtils.generate_cache_headers(etag, cache_directive, max_age)
    return Response(
        content=content,
        media_type=response_headers.get("Content-Type")
        or UrlUtils.get_mime_type(url, "image/jpeg"),
        headers=headers,
    )


@router.get(
    "/global",
    summary="Query non-sensitive system settings",
    response_model=schemas.Response,
)
def get_global_setting(token: str):
    """Query non-sensitive system settings (default authentication)"""
    if token != settings.PROJECT_NAME.lower():
        raise HTTPException(status_code=403, detail="Forbidden")

    # FIXME: When adding sensitive configuration items, you need to add exclusions here
    info = settings.dict(
        exclude={
            "SECRET_KEY",
            "RESOURCE_SECRET_KEY",
            "API_TOKEN",
            "GITHUB_TOKEN",
            "REPO_GITHUB_TOKEN",
        }
    )

    return schemas.Response(success=True, data=info)


@router.get(
    "/setting/{key}", summary="Query system settings", response_model=schemas.Response
)
async def get_setting(key: str, _: User = Depends(get_current_active_user_async)):  # noqa: B008
    """Query system settings (administrator only)"""
    if hasattr(settings, key):
        value = getattr(settings, key)
    else:
        value = SystemConfigOper().get(key)
    return schemas.Response(success=True, data={"value": value})


@router.post(
    "/setting/{key}", summary="Update system settings", response_model=schemas.Response
)
async def set_setting(
    key: str,
    value: Annotated[list | dict | bool | int | str | None, Body()] = None,
    _: User = Depends(get_current_active_superuser_async),  # noqa: B008
):
    """Update system settings (administrator only)"""
    if hasattr(settings, key):
        success, message = settings.update_setting(key=key, value=value)
        if success:
            # Send configuration change event
            await eventmanager.async_send_event(
                etype=EventType.ConfigChanged,
                data=ConfigChangeEventData(key=key, value=value, change_type="update"),
            )
        elif success is None:
            success = True
        return schemas.Response(success=success, message=message)
    elif key in {item.value for item in SystemConfigKey}:
        if isinstance(value, list):
            value = list(filter(None, value))
            value = value if value else None
        success = await SystemConfigOper().async_set(key, value)
        if success:
            # Send configuration change event
            await eventmanager.async_send_event(
                etype=EventType.ConfigChanged,
                data=ConfigChangeEventData(key=key, value=value, change_type="update"),
            )
        return schemas.Response(success=True)
    else:
        return schemas.Response(
            success=False, message=f"Configuration item '{key}' does not exist"
        )


@router.get("/message", summary="Real-time message")
async def get_message(
    request: Request,
    role: str = "system",
    _: schemas.TokenPayload = Depends(get_current_active_user_async),  # noqa: B008
):
    """Get real-time system messages, the return format is SSE."""
    message = MessageHelper()

    async def event_generator():
        try:
            while not global_vars.is_system_stopped:
                if await request.is_disconnected():
                    break
                detail = message.get(role)
                yield f"data: {detail or ''}\n\n"
                await asyncio.sleep(3)
        except asyncio.CancelledError:
            return

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get(
    "/env", summary="Query system configuration", response_model=schemas.Response
)
async def get_env_setting(_: User = Depends(get_current_active_user_async)):  # noqa: B008
    """Query system environment variables, including the current version number
    (administrator only)"""
    info = settings.model_dump(exclude={"SECRET_KEY", "RESOURCE_SECRET_KEY"})
    info.update(
        {
            "VERSION": APP_VERSION,
            "FRONTEND_VERSION": await SystemChain().get_frontend_version(),
        }
    )
    return schemas.Response(success=True, data=info)


@router.post(
    "/env", summary="Update system configuration", response_model=schemas.Response
)
async def set_env_setting(
    env: dict,
    _: User = Depends(get_current_active_superuser_async),  # noqa: B008
):
    """Update system environment variables (administrator only)"""
    result = settings.update_settings(env=env)
    # Count the results of success and failure
    success_updates = {k: v for k, v in result.items() if v[0]}
    failed_updates = {k: v for k, v in result.items() if v[0] is False}

    if failed_updates:
        return schemas.Response(
            success=False,
            message=f"{', '.join([v[1] for v in failed_updates.values()])}",
            data={"success_updates": success_updates, "failed_updates": failed_updates},
        )

    if success_updates:
        for key in success_updates.keys():
            # Send configuration change event
            await eventmanager.async_send_event(
                etype=EventType.ConfigChanged,
                data=ConfigChangeEventData(
                    key=key, value=getattr(settings, key, None), change_type="update"
                ),
            )

    return schemas.Response(
        success=True,
        message="All configuration items have been updated successfully",
        data={"success_updates": success_updates},
    )


@router.get("/logging", summary="Real-time log")
async def get_logging(
    request: Request,
    length: int = 50,
    logfile: str = "mitmpilot.log",
    _: schemas.TokenPayload = Depends(get_current_active_user_async),  # noqa: B008
):
    """Get real-time system log Return format SSE."""
    base_path = AsyncPath(settings.LOG_PATH)
    log_path = base_path / logfile

    if not await SecurityUtils.async_is_safe_path(
        base_path=base_path, user_path=log_path, allowed_suffixes={".log"}
    ):
        raise HTTPException(status_code=404, detail="Not Found")

    if not await log_path.exists() or not await log_path.is_file():
        raise HTTPException(status_code=404, detail="Not Found")

    async def log_generator():
        try:
            # Use a fixed-size deque to limit memory usage
            lines_queue = deque(maxlen=max(length, 50))
            # Get file size
            file_stat = await log_path.stat()
            file_size = file_stat.st_size

            # Read historical logs
            async with aiofiles.open(log_path, encoding="utf-8", errors="ignore") as f:
                # Optimize large file reading strategy
                if file_size > 100 * 1024:
                    # Only read the last 100KB of content
                    bytes_to_read = min(file_size, 100 * 1024)
                    position = file_size - bytes_to_read
                    await f.seek(position)
                    content = await f.read()
                    # Find the first complete line
                    first_newline = content.find("\n")
                    if first_newline != -1:
                        content = content[first_newline + 1 :]
                else:
                    # Small files are read directly
                    content = await f.read()

                # Split by line and add to the queue, only keep non-empty lines
                lines = [line.strip() for line in content.splitlines() if line.strip()]
                # Only take the last N lines
                for line in lines[-max(length, 50) :]:
                    lines_queue.append(line)

            # Output historical logs
            for line in lines_queue:
                yield f"data: {line}\n\n"

            # Real-time monitoring of new logs
            async with aiofiles.open(log_path, encoding="utf-8", errors="ignore") as f:
                # Move the file pointer to the end of the file and continue to monitor
                # new content
                await f.seek(0, 2)
                # Record the initial file size
                initial_stat = await log_path.stat()
                initial_size = initial_stat.st_size
                # Real-time monitoring of new logs, using a shorter polling interval
                while not global_vars.is_system_stopped:
                    if await request.is_disconnected():
                        break
                    # Check if the file has new content
                    current_stat = await log_path.stat()
                    current_size = current_stat.st_size
                    if current_size > initial_size:
                        # The file has new content, read the new line
                        line = await f.readline()
                        if line:
                            line = line.strip()
                            if line:
                                yield f"data: {line}\n\n"
                        initial_size = current_size
                    else:
                        # No new content, wait for a short time
                        await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            return
        except Exception as err:
            logger.error(f"Log reading exception: {err}")
            yield f"data: Log reading exception: {err}\n\n"

    return StreamingResponse(log_generator(), media_type="text/event-stream")


@router.get("/logging2", summary="Real-time log")
async def get_logging2(
    logfile: str = "mitmpilot.log",
    _: schemas.TokenPayload = Depends(verify_resource_token),  # noqa: B008
):
    """Get system log :return text/plain."""
    base_path = AsyncPath(settings.LOG_PATH)
    log_path = base_path / logfile

    if not await SecurityUtils.async_is_safe_path(
        base_path=base_path, user_path=log_path, allowed_suffixes={".log"}
    ):
        raise HTTPException(status_code=404, detail="Not Found")

    if not await log_path.exists() or not await log_path.is_file():
        raise HTTPException(status_code=404, detail="Not Found")

    # Return all logs as a text response
    if not await log_path.exists():
        return Response(content="Log file does not exist!", media_type="text/plain")
    try:
        # Use aiofiles to read files asynchronously
        async with aiofiles.open(log_path, encoding="utf-8", errors="ignore") as file:
            text = await file.read()
        # Output in reverse order
        text = "\n".join(text.split("\n")[::-1])
        return Response(content=text, media_type="text/plain")
    except Exception as e:
        return Response(
            content=f"Failed to read log file: {e}", media_type="text/plain"
        )


@router.get("/img/{proxy}", summary="Image proxy")
async def proxy_img(
    imgurl: str,
    proxy: bool = False,
    cache: bool = False,
    if_none_match: Annotated[str | None, Header()] = None,
    _: schemas.TokenPayload = Depends(verify_resource_token),  # noqa: B008
) -> Response:
    """Image proxy, optional whether to use a proxy server, supports HTTP cache."""
    # Media server adds image proxy support
    allowed_domains = set(settings.SECURITY_IMAGE_DOMAINS)
    response = await fetch_image(
        url=imgurl,
        proxy=proxy,
        use_cache=cache,
        if_none_match=if_none_match,
        allowed_domains=allowed_domains,
    )
    if response is None:
        raise HTTPException(status_code=404, detail="Image not found or invalid")
    return response


@router.get(
    "/versions",
    summary="Query all release versions of Github",
    response_model=schemas.Response,
)
async def latest_version(_: schemas.TokenPayload = Depends(verify_token)):  # noqa: B008
    """Query all release versions from GitHub."""
    version_res = await AsyncRequestUtils(
        proxies=settings.PROXY, headers=settings.GITHUB_HEADERS
    ).get_res("https://api.github.com/repos/wumode/MitmPilot/releases")
    if version_res:
        ver_json = version_res.json()
        if ver_json:
            return schemas.Response(success=True, data=ver_json)
    return schemas.Response(success=False)


@router.get("rules", summary="Clash rules")
def get_rules(_: schemas.TokenPayload = Depends(verify_apikey)) -> PlainTextResponse:  # noqa: B008
    rules = Context.addonmanager.get_addon_rules()
    res = yaml.dump({"payload": rules}, allow_unicode=True)
    return PlainTextResponse(content=res, media_type="application/x-yaml")


@router.get("/runscheduler", summary="Run service", response_model=schemas.Response)
def run_scheduler(jobid: str, _: User = Depends(get_current_active_superuser)):  # noqa: B008
    """Execute command (administrator only)"""
    if not jobid:
        return schemas.Response(success=False, message="Command cannot be empty!")
    Scheduler().start(jobid)
    return schemas.Response(success=True)
