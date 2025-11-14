from hashlib import sha256
from pathlib import Path
from urllib.parse import quote, urlparse

from anyio import Path as AsyncPath

from app.log import logger


class SecurityUtils:
    @staticmethod
    def is_safe_path(
        base_path: Path,
        user_path: Path,
        allowed_suffixes: set[str] | list[str] | None = None,
    ) -> bool:
        """Validates if the user-provided path is within the base directory and checks
        if the file type is legal, preventing directory traversal attacks.

        :param base_path: The base directory, the root directory allowed to be accessed.
        :param user_path: The user-provided path, which needs to be checked if it is
            within the base directory.
        :param allowed_suffixes: A set of allowed file suffixes for validating the file
            type.
        :return: True if the user path is safe, within the base directory, and the file
            type is legal; otherwise, False.
        :raises Exception: Catches and logs exceptions if an error occurs during path
            parsing.
        """
        try:
            # resolve() converts relative paths to absolute paths and handles symbolic
            # links and '..'
            base_path_resolved = base_path.resolve()
            user_path_resolved = user_path.resolve()

            # Check if the user path is within the base directory or a subdirectory of
            # the base directory
            if (
                base_path_resolved != user_path_resolved
                and base_path_resolved not in user_path_resolved.parents
            ):
                return False

            if allowed_suffixes is not None:
                allowed_suffixes = set(allowed_suffixes)
                if user_path.suffix.lower() not in allowed_suffixes:
                    return False

            return True
        except Exception as e:
            logger.debug(f"Error occurred while validating paths: {e}")
            return False

    @staticmethod
    async def async_is_safe_path(
        base_path: AsyncPath,
        user_path: AsyncPath,
        allowed_suffixes: set[str] | list[str] | None = None,
    ) -> bool:
        """Asynchronously validates if the user-provided path is within the base
        directory and checks if the file type is legal, preventing directory traversal
        attacks.

        :param base_path: The base directory, the root directory allowed to be accessed.
        :param user_path: The user-provided path, which needs to be checked if it is
            within the base directory.
        :param allowed_suffixes: A set of allowed file suffixes for validating the file
            type.
        :return: True if the user path is safe, within the base directory, and the file
            type is legal; otherwise, False.
        :raises Exception: Catches and logs exceptions if an error occurs during path
            parsing.
        """
        try:
            # resolve() converts relative paths to absolute paths and handles symbolic
            # links and '..'
            base_path_resolved = await base_path.resolve()
            user_path_resolved = await user_path.resolve()

            # Check if the user path is within the base directory or a subdirectory of
            # the base directory
            if (
                base_path_resolved != user_path_resolved
                and base_path_resolved not in user_path_resolved.parents
            ):
                return False

            if allowed_suffixes is not None:
                allowed_suffixes = set(allowed_suffixes)
                if user_path.suffix.lower() not in allowed_suffixes:
                    return False

            return True
        except Exception as e:
            logger.debug(f"Error occurred while validating paths: {e}")
            return False

    @staticmethod
    def is_safe_url(
        url: str, allowed_domains: set[str] | list[str], strict: bool = False
    ) -> bool:
        """Validates if the URL is in the list of allowed domains, including domains
        with ports.

        :param url: The URL to validate.
        :param allowed_domains: A set of allowed domains, which can include ports.
        :param strict: Whether to strictly match the top-level domain (defaults to
            False, allowing subdomains).
        :return: True if the URL is valid and in the allowed domains list; otherwise,
            False.
        """
        try:
            # Parse the URL
            parsed_url = urlparse(url)

            # If the URL does not contain a valid scheme, or a valid netloc cannot be
            # extracted from it, the URL is considered invalid.
            if not parsed_url.scheme or not parsed_url.netloc:
                return False

            # Only http or https protocols are allowed
            if parsed_url.scheme not in {"http", "https"}:
                return False

            # Get the full netloc (including IP and port) and convert to lowercase
            netloc = parsed_url.netloc.lower()
            if not netloc:
                return False

            # Check each allowed domain
            allowed_domains = {d.lower() for d in allowed_domains}
            for domain in allowed_domains:
                parsed_allowed_url = urlparse(domain)
                allowed_netloc = parsed_allowed_url.netloc or parsed_allowed_url.path

                if strict:
                    # In strict mode, exact matching of domain and port is required
                    if netloc == allowed_netloc:
                        return True
                else:
                    # In non-strict mode, subdomain matching is allowed
                    if netloc == allowed_netloc or netloc.endswith(
                        "." + allowed_netloc
                    ):
                        return True

            return False
        except Exception as e:
            logger.debug(f"Error occurred while validating URL: {e}")
            return False

    @staticmethod
    def sanitize_url_path(url: str, max_length: int = 120) -> str:
        """Encodes the path portion of a URL, ensuring legal characters, and compresses
        the path length (if it exceeds the maximum length).

        :param url: The URL to process.
        :param max_length: The maximum allowed length for the path; compression occurs
            if exceeded.
        :return: The processed path string.
        """
        # Parse the URL to get the path part
        parsed_url = urlparse(url)
        path = parsed_url.path.lstrip("/")

        # Encode special characters in the path
        safe_path = quote(path)

        # If the path is too long, compress it
        if len(safe_path) > max_length:
            # Use SHA-256 to hash the path, take the first 16 bits as the compressed
            # path
            hash_value = sha256(safe_path.encode()).hexdigest()[:16]
            # Use the hash value to replace the overly long path, while retaining the
            # file extension
            file_extension = (
                Path(safe_path).suffix.lower() if Path(safe_path).suffix else ""
            )
            safe_path = f"compressed_{hash_value}{file_extension}"

        return safe_path
