import sys
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any

import httpx
import requests
import urllib3
from requests import Response, Session
from urllib3.exceptions import InsecureRequestWarning

from app.core.config import settings
from app.log import logger

urllib3.disable_warnings(InsecureRequestWarning)


def cookie_parse(cookies_str: str, array: bool = False) -> list | dict:
    """解析cookie，转化为字典或者数组.

    :param cookies_str: cookie字符串
    :param array: 是否转化为数组
    :return: 字典或者数组
    """
    if not cookies_str:
        return {}
    cookie_dict = {}
    cookies = cookies_str.split(";")
    for cookie in cookies:
        cstr = cookie.split("=")
        if len(cstr) > 1:
            cookie_dict[cstr[0].strip()] = cstr[1].strip()
    if array:
        return [{"name": k, "value": v} for k, v in cookie_dict.items()]
    return cookie_dict


def get_caller():
    """获取调用者的名称，识别是否为插件调用."""
    # 调用者名称
    caller_name = None

    try:
        frame = sys._getframe(3)  # noqa
    except (AttributeError, ValueError):
        return None

    while frame:
        filepath = Path(frame.f_code.co_filename)
        parts = filepath.parts
        if "app" in parts:
            if not caller_name and "plugins" in parts:
                try:
                    plugins_index = parts.index("plugins")
                    if plugins_index + 1 < len(parts):
                        plugin_candidate = parts[plugins_index + 1]
                        if plugin_candidate != "__init__.py":
                            caller_name = plugin_candidate
                        break
                except ValueError:
                    pass
            if "main.py" in parts:
                break
        elif len(parts) != 1:
            break
        try:
            frame = frame.f_back
        except AttributeError:
            break
    return caller_name


class RequestUtils:
    """HTTP请求工具类，提供同步HTTP请求的基本功能."""

    def __init__(
        self,
        headers: dict = None,
        ua: str = None,
        cookies: str | dict = None,
        proxies: dict = None,
        session: Session = None,
        timeout: int = None,
        referer: str = None,
        content_type: str = None,
        accept_type: str = None,
    ):
        """
        :param headers: 请求头部信息
        :param ua: User-Agent字符串
        :param cookies: Cookie字符串或字典
        :param proxies: 代理设置
        :param session: requests.Session实例，如果为None则创建新的Session
        :param timeout: 请求超时时间，默认为20秒
        :param referer: Referer头部信息
        :param content_type: 请求的Content-Type，默认为 "application/x-www-form-urlencoded; charset=UTF-8"
        :param accept_type: Accept头部信息，默认为 "application/json"
        """
        self._proxies = proxies
        self._session = session
        self._timeout = timeout or 20
        if not content_type:
            content_type = "application/x-www-form-urlencoded; charset=UTF-8"
        if headers:
            self._headers = headers
        else:
            if ua and ua == settings.USER_AGENT:
                caller_name = get_caller()
                if caller_name:
                    ua = f"{settings.USER_AGENT} Plugin/{caller_name}"
            self._headers = {
                "User-Agent": ua,
                "Content-Type": content_type,
                "Accept": accept_type,
                "referer": referer,
            }
        if cookies:
            if isinstance(cookies, str):
                self._cookies = cookie_parse(cookies)
            else:
                self._cookies = cookies
        else:
            self._cookies = None

    @contextmanager
    def response_manager(self, method: str, url: str, **kwargs):
        """响应管理器上下文管理器，确保响应对象被正确关闭.

        :param method: HTTP方法
        :param url: 请求的URL
        :param kwargs: 其他请求参数.
        """
        response = None
        try:
            response = self.request(method=method, url=url, **kwargs)
            yield response
        finally:
            if response:
                try:
                    response.close()
                except Exception as e:
                    logger.debug(f"关闭响应失败: {e}")

    def request(
        self, method: str, url: str, raise_exception: bool = False, **kwargs
    ) -> Response | None:
        """发起HTTP请求.

        :param method: HTTP方法，如 get, post, put 等
        :param url: 请求的URL
        :param raise_exception: 是否在发生异常时抛出异常，否则默认拦截异常返回None
        :param kwargs: 其他请求参数，如headers, cookies, proxies等
        :return: HTTP响应对象
        :raises: requests.exceptions.RequestException 仅raise_exception为True时会抛出.
        """
        if self._session is None:
            req_method = requests.request
        else:
            req_method = self._session.request
        kwargs.setdefault("headers", self._headers)
        kwargs.setdefault("cookies", self._cookies)
        kwargs.setdefault("proxies", self._proxies)
        kwargs.setdefault("timeout", self._timeout)
        kwargs.setdefault("verify", False)
        kwargs.setdefault("stream", False)
        try:
            return req_method(method, url, **kwargs)
        except requests.exceptions.RequestException as e:
            # 获取更详细的错误信息
            error_msg = (
                str(e)
                if str(e)
                else f"未知网络错误 (URL: {url}, Method: {method.upper()})"
            )
            logger.debug(f"请求失败: {error_msg}")
            if raise_exception:
                raise
            return None

    def get(self, url: str, params: dict = None, **kwargs) -> str | None:
        """发送GET请求.

        :param url: 请求的URL
        :param params: 请求的参数
        :param kwargs: 其他请求参数，如headers, cookies, proxies等
        :return: 响应的内容，若发生RequestException则返回None.
        """
        response = self.request(method="get", url=url, params=params, **kwargs)
        if response:
            try:
                content = str(response.content, "utf-8")
                return content
            except Exception as e:
                logger.debug(f"处理响应内容失败: {e}")
                return None
            finally:
                response.close()
        return None

    def post(
        self, url: str, data: Any = None, json: dict = None, **kwargs
    ) -> Response | None:
        """发送POST请求.

        :param url: 请求的URL
        :param data: 请求的数据
        :param json: 请求的JSON数据
        :param kwargs: 其他请求参数，如headers, cookies, proxies等
        :return: HTTP响应对象，若发生RequestException则返回None.
        """
        return self.request(method="post", url=url, data=data, json=json, **kwargs)

    def put(self, url: str, data: Any = None, **kwargs) -> Response | None:
        """发送PUT请求.

        :param url: 请求的URL
        :param data: 请求的数据
        :param kwargs: 其他请求参数，如 headers, cookies, proxies等
        :return: HTTP响应对象，若发生RequestException则返回None.
        """
        return self.request(method="put", url=url, data=data, **kwargs)

    def get_res(
        self,
        url: str,
        params: dict = None,
        data: Any = None,
        json: dict = None,
        allow_redirects: bool = True,
        raise_exception: bool = False,
        **kwargs,
    ) -> Response | None:
        """发送GET请求并返回响应对象.

        :param url: 请求的URL
        :param params: 请求的参数
        :param data: 请求的数据
        :param json: 请求的JSON数据
        :param allow_redirects: 是否允许重定向
        :param raise_exception: 是否在发生异常时抛出异常，否则默认拦截异常返回None
        :param kwargs: 其他请求参数，如headers, cookies, proxies等
        :return: HTTP响应对象，若发生RequestException则返回None
        :raises: requests.exceptions.RequestException 仅raise_exception为True时会抛出.
        """
        return self.request(
            method="get",
            url=url,
            params=params,
            data=data,
            json=json,
            allow_redirects=allow_redirects,
            raise_exception=raise_exception,
            **kwargs,
        )

    @contextmanager
    def get_stream(self, url: str, params: dict = None, **kwargs):
        """获取流式响应的上下文管理器，适用于大文件下载.

        :param url: 请求的URL
        :param params: 请求的参数
        :param kwargs: 其他请求参数
        """
        kwargs["stream"] = True
        response = self.request(method="get", url=url, params=params, **kwargs)
        try:
            yield response
        finally:
            if response:
                response.close()

    def post_res(
        self,
        url: str,
        data: Any = None,
        params: dict = None,
        allow_redirects: bool = True,
        files: Any = None,
        json: dict = None,
        raise_exception: bool = False,
        **kwargs,
    ) -> Response | None:
        """发送POST请求并返回响应对象.

        :param url: 请求的URL
        :param data: 请求的数据
        :param params: 请求的参数
        :param allow_redirects: 是否允许重定向
        :param files: 请求的文件
        :param json: 请求的JSON数据
        :param raise_exception: 是否在发生异常时抛出异常，否则默认拦截异常返回None
        :param kwargs: 其他请求参数，如headers, cookies, proxies等
        :return: HTTP响应对象，若发生RequestException则返回None
        :raises: requests.exceptions.RequestException 仅 raise_exception 为True时会抛出.
        """
        return self.request(
            method="post",
            url=url,
            data=data,
            params=params,
            allow_redirects=allow_redirects,
            files=files,
            json=json,
            raise_exception=raise_exception,
            **kwargs,
        )

    def put_res(
        self,
        url: str,
        data: Any = None,
        params: dict = None,
        allow_redirects: bool = True,
        files: Any = None,
        json: dict = None,
        raise_exception: bool = False,
        **kwargs,
    ) -> Response | None:
        """发送PUT请求并返回响应对象.

        :param url: 请求的URL
        :param data: 请求的数据
        :param params: 请求的参数
        :param allow_redirects: 是否允许重定向
        :param files: 请求的文件
        :param json: 请求的JSON数据
        :param raise_exception: 是否在发生异常时抛出异常，否则默认拦截异常返回None
        :param kwargs: 其他请求参数，如headers, cookies, proxies 等
        :return: HTTP响应对象，若发生 RequestException 则返回 None
        :raises: requests.exceptions.RequestException 仅 raise_exception 为True时会抛出.
        """
        return self.request(
            method="put",
            url=url,
            data=data,
            params=params,
            allow_redirects=allow_redirects,
            files=files,
            json=json,
            raise_exception=raise_exception,
            **kwargs,
        )

    def delete_res(
        self,
        url: str,
        data: Any = None,
        params: dict = None,
        allow_redirects: bool = True,
        raise_exception: bool = False,
        **kwargs,
    ) -> Response | None:
        """发送DELETE请求并返回响应对象.

        :param url: 请求的URL
        :param data: 请求的数据
        :param params: 请求的参数
        :param allow_redirects: 是否允许重定向
        :param raise_exception: 是否在发生异常时抛出异常，否则默认拦截异常返回None
        :param kwargs: 其他请求参数，如headers, cookies, proxies等
        :return: HTTP响应对象，若发生 RequestException 则返回None
        :raises: requests.exceptions.RequestException 仅 raise_exception 为True时会抛出.
        """
        return self.request(
            method="delete",
            url=url,
            data=data,
            params=params,
            allow_redirects=allow_redirects,
            raise_exception=raise_exception,
            **kwargs,
        )

    def get_json(self, url: str, params: dict = None, **kwargs) -> dict | None:
        """发送GET请求并返回JSON数据，自动关闭连接.

        :param url: 请求的URL
        :param params: 请求的参数
        :param kwargs: 其他请求参数
        :return: JSON数据，若发生异常则返回None.
        """
        response = self.request(method="get", url=url, params=params, **kwargs)
        if response:
            try:
                data = response.json()
                return data
            except Exception as e:
                logger.debug(f"解析JSON失败: {e}")
                return None
            finally:
                response.close()
        return None

    def post_json(
        self, url: str, data: Any = None, json: dict = None, **kwargs
    ) -> dict | None:
        """发送POST请求并返回JSON数据，自动关闭连接.

        :param url: 请求的URL
        :param data: 请求的数据
        :param json: 请求的JSON数据
        :param kwargs: 其他请求参数
        :return: JSON数据，若发生异常则返回None.
        """
        if json is None:
            json = {}
        response = self.request(method="post", url=url, data=data, json=json, **kwargs)
        if response:
            try:
                data = response.json()
                return data
            except Exception as e:
                logger.debug(f"解析JSON失败: {e}")
                return None
            finally:
                response.close()
        return None

    @staticmethod
    def parse_cache_control(header: str) -> tuple[str, int | None]:
        """解析 Cache-Control 头，返回 cache_directive 和 max_age.

        :param header: Cache-Control 头部的字符串
        :return: cache_directive 和 max_age
        """
        cache_directive = ""
        max_age = None

        if not header:
            return cache_directive, max_age

        directives = [directive.strip() for directive in header.split(",")]
        for directive in directives:
            if directive.startswith("max-age"):
                try:
                    max_age = int(directive.split("=")[1])
                except Exception as e:
                    logger.debug(
                        f"Invalid max-age directive in Cache-Control header: {directive}, {e}"
                    )
            elif directive in {
                "no-cache",
                "private",
                "public",
                "no-store",
                "must-revalidate",
            }:
                cache_directive = directive

        return cache_directive, max_age

    @staticmethod
    def generate_cache_headers(
        etag: str | None,
        cache_control: str | None = "public",
        max_age: int | None = 86400,
    ) -> dict:
        """生成 HTTP 响应的 ETag 和 Cache-Control 头.

        :param etag: 响应的 ETag 值。如果为 None，则不添加 ETag 头部。
        :param cache_control: Cache-Control 指令，例如 "public"、"private" 等。默认为 "public"
        :param max_age: Cache-Control 的 max-age 值（秒）。默认为 86400 秒（1天）
        :return: HTTP 头部的字典
        """
        cache_headers = {}

        if etag:
            cache_headers["ETag"] = etag

        if cache_control and max_age is not None:
            cache_headers["Cache-Control"] = f"{cache_control}, max-age={max_age}"
        elif cache_control:
            cache_headers["Cache-Control"] = cache_control
        elif max_age is not None:
            cache_headers["Cache-Control"] = f"max-age={max_age}"

        return cache_headers


class AsyncRequestUtils:
    """异步HTTP请求工具类，提供异步HTTP请求的基本功能."""

    def __init__(
        self,
        headers: dict | None = None,
        ua: str | None = None,
        cookies: str | dict | None = None,
        proxies: dict | None = None,
        client: httpx.AsyncClient | None = None,
        timeout: int | None = None,
        referer: str | None = None,
        content_type: str | None = None,
        accept_type: str | None = None,
    ):
        """
        :param headers: 请求头部信息
        :param ua: User-Agent字符串
        :param cookies: Cookie字符串或字典
        :param proxies: 代理设置
        :param client: httpx.AsyncClient实例，如果为None则创建新的客户端
        :param timeout: 请求超时时间，默认为20秒
        :param referer: Referer头部信息
        :param content_type: 请求的Content-Type，默认为 "application/x-www-form-urlencoded; charset=UTF-8"
        :param accept_type: Accept头部信息，默认为 "application/json"
        """
        self._proxies = self._convert_proxies_for_httpx(proxies)
        self._client = client
        self._timeout = timeout or 20
        if not content_type:
            content_type = "application/x-www-form-urlencoded; charset=UTF-8"
        if headers:
            # 过滤掉None值的headers
            self._headers = {k: v for k, v in headers.items() if v is not None}
        else:
            if ua and ua == settings.USER_AGENT:
                caller_name = get_caller()
                if caller_name:
                    ua = f"{settings.USER_AGENT} Plugin/{caller_name}"
            self._headers = {}
            if ua:
                self._headers["User-Agent"] = ua
            if content_type:
                self._headers["Content-Type"] = content_type
            if accept_type:
                self._headers["Accept"] = accept_type
            if referer:
                self._headers["referer"] = referer
        if cookies:
            if isinstance(cookies, str):
                self._cookies = cookie_parse(cookies)
            else:
                self._cookies = cookies
        else:
            self._cookies = None

    @staticmethod
    def _convert_proxies_for_httpx(proxies: dict | None) -> str | None:
        """将requests格式的代理配置转换为httpx兼容的格式.

        :param proxies: requests格式的代理配置 {"http": "http://proxy:port", "https":
            "http://proxy:port"}
        :return: httpx兼容的代理字符串或None
        """
        if not proxies:
            return None

        # 如果已经是字符串格式，直接返回
        if isinstance(proxies, str):
            return proxies

        # 如果是字典格式，提取http或https代理
        if isinstance(proxies, dict):
            # 优先使用https代理，如果没有则使用http代理
            proxy_url = proxies.get("https") or proxies.get("http")
            if proxy_url:
                return proxy_url

        return None

    @asynccontextmanager
    async def response_manager(self, method: str, url: str, **kwargs):
        """异步响应管理器上下文管理器，确保响应对象被正确关闭.

        :param method: HTTP方法
        :param url: 请求的URL
        :param kwargs: 其他请求参数
        """
        response = None
        try:
            response = await self.request(method=method, url=url, **kwargs)
            yield response
        finally:
            if response:
                try:
                    await response.aclose()
                except Exception as e:
                    logger.debug(f"关闭异步响应失败: {e}")

    async def request(
        self, method: str, url: str, raise_exception: bool = False, **kwargs
    ) -> httpx.Response | None:
        """发起异步HTTP请求.

        :param method: HTTP方法，如 get, post, put 等
        :param url: 请求的URL
        :param raise_exception: 是否在发生异常时抛出异常，否则默认拦截异常返回None
        :param kwargs: 其他请求参数，如headers, cookies, proxies等
        :return: HTTP响应对象
        :raises: httpx.RequestError 仅raise_exception为True时会抛出
        """
        if self._client is None:
            # 创建临时客户端
            async with httpx.AsyncClient(
                proxy=self._proxies,
                timeout=self._timeout,
                verify=False,
                follow_redirects=True,
            ) as client:
                return await self._make_request(
                    client, method, url, raise_exception, **kwargs
                )
        else:
            return await self._make_request(
                self._client, method, url, raise_exception, **kwargs
            )

    async def _make_request(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        raise_exception: bool = False,
        **kwargs,
    ) -> httpx.Response | None:
        """执行实际的异步请求."""
        kwargs.setdefault("headers", self._headers)
        kwargs.setdefault("cookies", self._cookies)

        try:
            return await client.request(method, url, **kwargs)
        except httpx.RequestError as e:
            # 获取更详细的错误信息
            error_msg = (
                str(e)
                if str(e)
                else f"未知网络错误 (URL: {url}, Method: {method.upper()})"
            )
            logger.debug(f"异步请求失败: {error_msg}")
            if raise_exception:
                raise
            return None

    async def get(self, url: str, params: dict = None, **kwargs) -> str | None:
        """发送异步GET请求.

        :param url: 请求的URL
        :param params: 请求的参数
        :param kwargs: 其他请求参数，如headers, cookies, proxies等
        :return: 响应的内容，若发生RequestError则返回None
        """
        response = await self.request(method="get", url=url, params=params, **kwargs)
        if response:
            try:
                content = response.text
                return content
            except Exception as e:
                logger.debug(f"处理异步响应内容失败: {e}")
                return None
            finally:
                await response.aclose()  # 确保连接被关闭
        return None

    async def post(
        self, url: str, data: Any = None, json: dict = None, **kwargs
    ) -> httpx.Response | None:
        """发送异步POST请求.

        :param url: 请求的URL
        :param data: 请求的数据
        :param json: 请求的JSON数据
        :param kwargs: 其他请求参数，如headers, cookies, proxies等
        :return: HTTP响应对象，若发生RequestError则返回None
        """
        return await self.request(
            method="post", url=url, data=data, json=json, **kwargs
        )

    async def put(self, url: str, data: Any = None, **kwargs) -> httpx.Response | None:
        """发送异步PUT请求.

        :param url: 请求的URL
        :param data: 请求的数据
        :param kwargs: 其他请求参数，如headers, cookies, proxies等
        :return: HTTP响应对象，若发生RequestError则返回None
        """
        return await self.request(method="put", url=url, data=data, **kwargs)

    async def get_res(
        self,
        url: str,
        params: dict = None,
        data: Any = None,
        json: dict = None,
        allow_redirects: bool = True,
        raise_exception: bool = False,
        **kwargs,
    ) -> httpx.Response | None:
        """发送异步GET请求并返回响应对象.

        :param url: 请求的URL
        :param params: 请求的参数
        :param data: 请求的数据
        :param json: 请求的JSON数据
        :param allow_redirects: 是否允许重定向
        :param raise_exception: 是否在发生异常时抛出异常，否则默认拦截异常返回None
        :param kwargs: 其他请求参数，如headers, cookies, proxies等
        :return: HTTP响应对象，若发生RequestError则返回None
        :raises: httpx.RequestError 仅raise_exception为True时会抛出.
        """
        return await self.request(
            method="get",
            url=url,
            params=params,
            data=data,
            json=json,
            follow_redirects=allow_redirects,
            raise_exception=raise_exception,
            **kwargs,
        )

    @asynccontextmanager
    async def get_stream(self, url: str, params: dict = None, **kwargs):
        """获取异步流式响应的上下文管理器，适用于大文件下载.

        :param url: 请求的URL
        :param params: 请求的参数
        :param kwargs: 其他请求参数
        """
        kwargs["stream"] = True
        response = await self.request(method="get", url=url, params=params, **kwargs)
        try:
            yield response
        finally:
            if response:
                await response.aclose()

    async def post_res(
        self,
        url: str,
        data: Any = None,
        params: dict = None,
        allow_redirects: bool = True,
        files: Any = None,
        json: dict = None,
        raise_exception: bool = False,
        **kwargs,
    ) -> httpx.Response | None:
        """发送异步POST请求并返回响应对象.

        :param url: 请求的URL
        :param data: 请求的数据
        :param params: 请求的参数
        :param allow_redirects: 是否允许重定向
        :param files: 请求的文件
        :param json: 请求的JSON数据
        :param raise_exception: 是否在发生异常时抛出异常，否则默认拦截异常返回None
        :param kwargs: 其他请求参数，如headers, cookies, proxies等
        :return: HTTP响应对象，若发生RequestError则返回None
        :raises: httpx.RequestError 仅raise_exception为True时会抛出
        """
        return await self.request(
            method="post",
            url=url,
            data=data,
            params=params,
            follow_redirects=allow_redirects,
            files=files,
            json=json,
            raise_exception=raise_exception,
            **kwargs,
        )

    async def put_res(
        self,
        url: str,
        data: Any = None,
        params: dict = None,
        allow_redirects: bool = True,
        files: Any = None,
        json: dict = None,
        raise_exception: bool = False,
        **kwargs,
    ) -> httpx.Response | None:
        """发送异步PUT请求并返回响应对象.

        :param url: 请求的URL
        :param data: 请求的数据
        :param params: 请求的参数
        :param allow_redirects: 是否允许重定向
        :param files: 请求的文件
        :param json: 请求的JSON数据
        :param raise_exception: 是否在发生异常时抛出异常，否则默认拦截异常返回None
        :param kwargs: 其他请求参数，如headers, cookies, proxies等
        :return: HTTP响应对象，若发生RequestError则返回None
        :raises: httpx.RequestError 仅raise_exception为True时会抛出.
        """
        return await self.request(
            method="put",
            url=url,
            data=data,
            params=params,
            follow_redirects=allow_redirects,
            files=files,
            json=json,
            raise_exception=raise_exception,
            **kwargs,
        )

    async def delete_res(
        self,
        url: str,
        data: Any = None,
        params: dict = None,
        allow_redirects: bool = True,
        raise_exception: bool = False,
        **kwargs,
    ) -> httpx.Response | None:
        """发送异步DELETE请求并返回响应对象.

        :param url: 请求的URL
        :param data: 请求的数据
        :param params: 请求的参数
        :param allow_redirects: 是否允许重定向
        :param raise_exception: 是否在发生异常时抛出异常，否则默认拦截异常返回None
        :param kwargs: 其他请求参数，如headers, cookies, proxies等
        :return: HTTP响应对象，若发生RequestError则返回None
        :raises: httpx.RequestError 仅raise_exception为True时会抛出.
        """
        return await self.request(
            method="delete",
            url=url,
            data=data,
            params=params,
            follow_redirects=allow_redirects,
            raise_exception=raise_exception,
            **kwargs,
        )

    async def get_json(self, url: str, params: dict = None, **kwargs) -> dict | None:
        """发送异步GET请求并返回JSON数据，自动关闭连接.

        :param url: 请求的URL
        :param params: 请求的参数
        :param kwargs: 其他请求参数
        :return: JSON数据，若发生异常则返回None
        """
        response = await self.request(method="get", url=url, params=params, **kwargs)
        if response:
            try:
                data = response.json()
                return data
            except Exception as e:
                logger.debug(f"解析异步JSON失败: {e}")
                return None
            finally:
                await response.aclose()
        return None

    async def post_json(
        self, url: str, data: Any = None, json: dict = None, **kwargs
    ) -> dict | None:
        """发送异步POST请求并返回JSON数据，自动关闭连接.

        :param url: 请求的URL
        :param data: 请求的数据
        :param json: 请求的JSON数据
        :param kwargs: 其他请求参数
        :return: JSON数据，若发生异常则返回None.
        """
        if json is None:
            json = {}
        response = await self.request(
            method="post", url=url, data=data, json=json, **kwargs
        )
        if response:
            try:
                data = response.json()
                return data
            except Exception as e:
                logger.debug(f"解析异步JSON失败: {e}")
                return None
            finally:
                await response.aclose()
        return None
