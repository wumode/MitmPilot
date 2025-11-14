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
    """Parses a cookie string into a dictionary or a list of dictionaries.

    :param cookies_str: The cookie string
    :param array: Whether to convert to a list of dictionaries
    :return: A dictionary or a list of dictionaries
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
    """Gets the name of the caller to identify if it's a plugin call."""
    # Caller name
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
    """HTTP request utility class, providing basic synchronous HTTP request
    functions."""

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
        :param headers: Request headers
        :param ua: User-Agent string
        :param cookies: Cookie string or dictionary
        :param proxies: Proxy settings
        :param session: requests.Session instance, if None, a new Session will be created
        :param timeout: Request timeout in seconds, defaults to 20 seconds
        :param referer: Referer header information
        :param content_type: Request Content-Type, defaults to "application/x-www-form-urlencoded; charset=UTF-8"
        :param accept_type: Accept header information, defaults to "application/json"
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
        """Response manager context manager, ensuring the response object is properly
        closed.

        :param method: HTTP method
        :param url: Request URL
        :param kwargs: Other request parameters.
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
        """Initiates an HTTP request.

        :param method: HTTP method, such as get, post, put, etc.
        :param url: Request URL
        :param raise_exception: Whether to raise an exception if one occurs, otherwise
            exceptions are caught and None is returned by default
        :param kwargs: Other request parameters, such as headers, cookies, proxies, etc.
        :return: HTTP response object
        :raises: requests.exceptions.RequestException only if raise_exception is True.
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
            # Get more detailed error information
            error_msg = (
                str(e)
                if str(e)
                else f"Unknown network error (URL: {url}, Method: {method.upper()})"
            )
            logger.debug(f"Request failed: {error_msg}")
            if raise_exception:
                raise
            return None

    def get(self, url: str, params: dict = None, **kwargs) -> str | None:
        """Sends a GET request.

        :param url: Request URL
        :param params: Request parameters
        :param kwargs: Other request parameters, such as headers, cookies, proxies, etc.
        :return: Response content, or None if a RequestException occurs.
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
        """Sends a POST request.

        :param url: Request URL
        :param data: Request data
        :param json: Request JSON data
        :param kwargs: Other request parameters, such as headers, cookies, proxies, etc.
        :return: HTTP response object, or None if a RequestException occurs.
        """
        return self.request(method="post", url=url, data=data, json=json, **kwargs)

    def put(self, url: str, data: Any = None, **kwargs) -> Response | None:
        """Sends a PUT request.

        :param url: Request URL
        :param data: Request data
        :param kwargs: Other request parameters, such as headers, cookies, proxies, etc.
        :return: HTTP response object, or None if a RequestException occurs.
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
        """Sends a GET request and returns the response object.

        :param url: Request URL
        :param params: Request parameters
        :param data: Request data
        :param json: Request JSON data
        :param allow_redirects: Whether to allow redirects
        :param raise_exception: Whether to raise an exception if one occurs, otherwise
            exceptions are caught and None is returned by default
        :param kwargs: Other request parameters, such as headers, cookies, proxies, etc.
        :return: HTTP response object, or None if a RequestException occurs
        :raises: requests.exceptions.RequestException only if raise_exception is True.
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
        """Context manager for obtaining a streaming response, suitable for large file
        downloads.

        :param url: Request URL
        :param params: Request parameters
        :param kwargs: Other request parameters
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
        """Sends a POST request and returns the response object.

        :param url: Request URL
        :param data: Request data
        :param params: Request parameters
        :param allow_redirects: Whether to allow redirects
        :param files: Request files
        :param json: Request JSON data
        :param raise_exception: Whether to raise an exception if one occurs, otherwise
            exceptions are caught and None is returned by default
        :param kwargs: Other request parameters, such as headers, cookies, proxies, etc.
        :return: HTTP response object, or None if a RequestException occurs
        :raises: requests.exceptions.RequestException only if raise_exception is True.
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
        """Sends a PUT request and returns the response object.

        :param url: Request URL
        :param data: Request data
        :param params: Request parameters
        :param allow_redirects: Whether to allow redirects
        :param files: Request files
        :param json: Request JSON data
        :param raise_exception: Whether to raise an exception if one occurs, otherwise
            exceptions are caught and None is returned by default
        :param kwargs: Other request parameters, such as headers, cookies, proxies, etc.
        :return: HTTP response object, or None if a RequestException occurs
        :raises: requests.exceptions.RequestException only if raise_exception is True.
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
        """Sends a DELETE request and returns the response object.

        :param url: Request URL
        :param data: Request data
        :param params: Request parameters
        :param allow_redirects: Whether to allow redirects
        :param raise_exception: Whether to raise an exception if one occurs, otherwise
            exceptions are caught and None is returned by default
        :param kwargs: Other request parameters, such as headers, cookies, proxies, etc.
        :return: HTTP response object, or None if a RequestException occurs
        :raises: requests.exceptions.RequestException only if raise_exception is True.
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
        """Sends a GET request and returns JSON data, automatically closing the
        connection.

        :param url: Request URL
        :param params: Request parameters
        :param kwargs: Other request parameters
        :return: JSON data, or None if an exception occurs.
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
        """Sends a POST request and returns JSON data, automatically closing the
        connection.

        :param url: Request URL
        :param data: Request data
        :param json: Request JSON data
        :param kwargs: Other request parameters
        :return: JSON data, or None if an exception occurs.
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
        """Parses the Cache-Control header, returning the cache_directive and max_age.

        :param header: The Cache-Control header string
        :return: cache_directive and max_age
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
        """Generates ETag and Cache-Control headers for HTTP responses.

        :param etag: The ETag value for the response. If None, no ETag header is added.
        :param cache_control: Cache-Control directive, e.g., "public", "private", etc.
            Defaults to "public"
        :param max_age: Cache-Control max-age value (seconds). Defaults to 86400 seconds
            (1 day)
        :return: Dictionary of HTTP headers
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
    """Asynchronous HTTP request utility class, providing basic asynchronous HTTP
    request functions."""

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
        :param headers: Request headers
        :param ua: User-Agent string
        :param cookies: Cookie string or dictionary
        :param proxies: Proxy settings
        :param client: httpx.AsyncClient instance, if None, a new client will be created
        :param timeout: Request timeout in seconds, defaults to 20 seconds
        :param referer: Referer header information
        :param content_type: Request Content-Type, defaults to "application/x-www-form-urlencoded; charset=UTF-8"
        :param accept_type: Accept header information, defaults to "application/json"
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
        """Converts requests-style proxy configuration to httpx-compatible format.

        :param proxies: requests-style proxy configuration {"http": "http://proxy:port",
            "https": "http://proxy:port"}
        :return: httpx-compatible proxy string or None
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
        """Asynchronous response manager context manager, ensuring the response object
        is properly closed.

        :param method: HTTP method
        :param url: Request URL
        :param kwargs: Other request parameters
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
        """Initiates an asynchronous HTTP request.

        :param method: HTTP method, such as get, post, put, etc.
        :param url: Request URL
        :param raise_exception: Whether to raise an exception if one occurs, otherwise
            exceptions are caught and None is returned by default
        :param kwargs: Other request parameters, such as headers, cookies, proxies, etc.
        :return: HTTP response object
        :raises: httpx.RequestError only if raise_exception is True
        """
        if self._client is None:
            # Create a temporary client
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
        """Sends an asynchronous GET request.

        :param url: Request URL
        :param params: Request parameters
        :param kwargs: Other request parameters, such as headers, cookies, proxies, etc.
        :return: Response content, or None if a RequestError occurs
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
        """Sends an asynchronous POST request.

        :param url: Request URL
        :param data: Request data
        :param json: Request JSON data
        :param kwargs: Other request parameters, such as headers, cookies, proxies, etc.
        :return: HTTP response object, or None if a RequestError occurs
        """
        return await self.request(
            method="post", url=url, data=data, json=json, **kwargs
        )

    async def put(self, url: str, data: Any = None, **kwargs) -> httpx.Response | None:
        """Sends an asynchronous PUT request.

        :param url: Request URL
        :param data: Request data
        :param kwargs: Other request parameters, such as headers, cookies, proxies, etc.
        :return: HTTP response object, or None if a RequestError occurs
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
        """Sends an asynchronous GET request and returns the response object.

        :param url: Request URL
        :param params: Request parameters
        :param data: Request data
        :param json: Request JSON data
        :param allow_redirects: Whether to allow redirects
        :param raise_exception: Whether to raise an exception if one occurs, otherwise
            exceptions are caught and None is returned by default
        :param kwargs: Other request parameters, such as headers, cookies, proxies, etc.
        :return: HTTP response object, or None if a RequestError occurs
        :raises: httpx.RequestError only if raise_exception is True.
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
        """Context manager for obtaining an asynchronous streaming response, suitable
        for large file downloads.

        :param url: Request URL
        :param params: Request parameters
        :param kwargs: Other request parameters
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
        """Sends an asynchronous POST request and returns the response object.

        :param url: Request URL
        :param data: Request data
        :param params: Request parameters
        :param allow_redirects: Whether to allow redirects
        :param files: Request files
        :param json: Request JSON data
        :param raise_exception: Whether to raise an exception if one occurs, otherwise
            exceptions are caught and None is returned by default
        :param kwargs: Other request parameters, such as headers, cookies, proxies, etc.
        :return: HTTP response object, or None if a RequestError occurs
        :raises: httpx.RequestError only if raise_exception is True
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
        """Sends an asynchronous PUT request and returns the response object.

        :param url: Request URL
        :param data: Request data
        :param params: Request parameters
        :param allow_redirects: Whether to allow redirects
        :param files: Request files
        :param json: Request JSON data
        :param raise_exception: Whether to raise an exception if one occurs, otherwise
            exceptions are caught and None is returned by default
        :param kwargs: Other request parameters, such as headers, cookies, proxies, etc.
        :return: HTTP response object, or None if a RequestError occurs
        :raises: httpx.RequestError only if raise_exception is True.
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
        """Sends an asynchronous DELETE request and returns the response object.

        :param url: Request URL
        :param data: Request data
        :param params: Request parameters
        :param allow_redirects: Whether to allow redirects
        :param raise_exception: Whether to raise an exception if one occurs, otherwise
            exceptions are caught and None is returned by default
        :param kwargs: Other request parameters, such as headers, cookies, proxies, etc.
        :return: HTTP response object, or None if a RequestError occurs
        :raises: httpx.RequestError only if raise_exception is True.
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
        """Sends an asynchronous GET request and returns JSON data, automatically
        closing the connection.

        :param url: Request URL
        :param params: Request parameters
        :param kwargs: Other request parameters
        :return: JSON data, or None if an exception occurs
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
        """Sends an asynchronous POST request and returns JSON data, automatically
        closing the connection.

        :param url: Request URL
        :param data: Request data
        :param json: Request JSON data
        :param kwargs: Other request parameters
        :return: JSON data, or None if an exception occurs.
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
