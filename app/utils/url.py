import mimetypes
from pathlib import Path
from urllib import parse
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

from app.log import logger


class UrlUtils:
    @staticmethod
    def standardize_base_url(host: str) -> str:
        """
        Standardizes the provided host address, ensuring it starts with 'http://'
        or 'https://' and ends with a slash (/).

        :param host: The host address string to standardize.
        :return: The standardized host address string.
        """
        if not host:
            return host
        if not host.endswith("/"):
            host += "/"
        if not host.startswith("http://") and not host.startswith("https://"):
            host = "http://" + host
        return host

    @staticmethod
    def adapt_request_url(host: str, endpoint: str) -> str | None:
        """Adapts the request URL based on the incoming host, ensuring each request URL
        is complete, used to automatically process and correct the request URL before
        sending the request.

        :param host: The host header.
        :param endpoint: The endpoint.
        :return: The complete request URL string.
        """
        if not host and not endpoint:
            return None
        if endpoint.startswith(("http://", "https://")):
            return endpoint
        host = UrlUtils.standardize_base_url(host)
        return urljoin(host, endpoint) if host else endpoint

    @staticmethod
    def combine_url(
        host: str, path: str | None = None, query: dict | None = None
    ) -> str | None:
        """Generates a complete URL using the given host header, path, and query
        parameters.

        :param host: str, Host header, e.g., https://example.com
        :param path: Optional[str], Endpoint containing the path and possibly already
            included query parameters, e.g., /path/to/resource?current=1
        :param query: Optional[dict], Optional, additional query parameters, e.g.,
            {"key": "value"}
        :return: str, The complete request URL string.
        """
        try:
            # If the path is empty, default to '/'
            if path is None:
                path = "/"
            host = UrlUtils.standardize_base_url(host)
            # Use urljoin to combine host and path
            url = urljoin(host, path)
            # Parse the components of the current URL
            url_parts = urlparse(url)
            # Parse existing query parameters and merge with additional query parameters
            query_params = parse_qs(url_parts.query)
            if query:
                for key, value in query.items():
                    query_params[key] = value

            # Reconstruct the query string
            query_string = urlencode(query_params, doseq=True)
            # Build the complete URL
            new_url_parts = url_parts._replace(query=query_string)
            complete_url = urlunparse(new_url_parts)
            return str(complete_url)
        except Exception as e:
            logger.debug(f"Error combining URL: {e}")
            return None

    @staticmethod
    def get_mime_type(
        path_or_url: str | Path, default_type: str = "application/octet-stream"
    ) -> str:
        """Gets the MIME type based on the file path or URL, returns the default type if
        it cannot be obtained.

        :param path_or_url: File path (Path) or URL (str)
        :param default_type: Default MIME type to return if the type cannot be obtained.
        :return: The obtained MIME type or the default type.
        """
        try:
            # If it is a Path type, convert to string
            if isinstance(path_or_url, Path):
                path_or_url = str(path_or_url)

            # Try to get the MIME type based on the path or URL
            mime_type, _ = mimetypes.guess_type(path_or_url)
            # If the type cannot be inferred, return the default type
            if not mime_type:
                return default_type
            return mime_type
        except Exception as e:
            logger.debug(f"Error get_mime_type: {e}")
            return default_type

    @staticmethod
    def quote(s: str) -> str:
        """Encodes a string into a URL-safe format.

        :param s: The string to encode.
        :return: The encoded string.
        """
        return parse.quote(s)

    @staticmethod
    def parse_url_params(url: str) -> tuple[str, str, int, str] | None:
        """Parses the given URL and extracts protocol, hostname, port, and path
        information.

        :param url: str
            The URL string to parse.
            Can be a complete URL (e.g., "http://example.com:8080/path") or an
            address without a protocol (e.g., "example.com:1234").
        :return: Optional[Tuple[str, str, int, str]]
            - str: Protocol (e.g., "http", "https")
            - str: Hostname or IP address (e.g., "example.com", "192.168.1.1")
            - int: Port number (e.g., 80, 443)
            - str: Path part of the URL (e.g., "/", "/path")
            Returns None if the input address is invalid or cannot be parsed.
        """
        try:
            if not url:
                return None

            url = UrlUtils.standardize_base_url(host=url)
            parsed = urlparse(url)
            hostname = parsed.hostname
            if not hostname:
                return None
            protocol = parsed.scheme
            port = parsed.port
            if port is None:
                port = 443 if protocol == "https" else 80
            path = parsed.path or "/"

            return protocol, hostname, port, path
        except Exception as e:
            logger.debug(f"Error parse_url_params: {e}")
            return None
