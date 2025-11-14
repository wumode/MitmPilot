import bisect
import datetime
import hashlib
import random
import re
import secrets
from collections.abc import Generator
from typing import Any
from urllib import parse

import dateparser
import dateutil.parser

# Built-in version conversion dictionary
_version_map = {"stable": -1, "rc": -2, "beta": -3, "alpha": -4}
# Non-compliant version number
_other_version = -5


class StringUtils:
    """A collection of utility functions for string manipulation."""

    @staticmethod
    def num_filesize(text: str | int | float) -> int:
        """Converts a file size string (e.g., '1.5MB') to bytes."""
        if not text:
            return 0
        if not isinstance(text, str):
            text = str(text)
        if text.isdigit():
            return int(text)
        text = text.replace(",", "").replace(" ", "").upper()
        size_str = re.sub(r"[KMGTPI]*B?", "", text, flags=re.IGNORECASE)
        try:
            size = float(size_str)
        except ValueError:
            return 0
        if "PB" in text or "PIB" in text:
            size *= 1024**5
        elif "TB" in text or "TIB" in text:
            size *= 1024**4
        elif "GB" in text or "GIB" in text:
            size *= 1024**3
        elif "MB" in text or "MIB" in text:
            size *= 1024**2
        elif "KB" in text or "KIB" in text:
            size *= 1024
        return round(size)

    @staticmethod
    def str_timelong(time_sec: str | int | float) -> str:
        """Converts a duration in seconds to a human-readable string."""
        if not isinstance(time_sec, (int, float)):
            try:
                time_sec = float(time_sec)
            except (ValueError, TypeError):
                return ""
        d = [(0, "s"), (60 - 1, "m"), (3600 - 1, "h"), (86400 - 1, "d")]
        s = [x[0] for x in d]
        index = bisect.bisect_left(s, int(time_sec)) - 1
        if index == -1:
            return str(time_sec)
        else:
            b, u = d[index]
        return str(round(time_sec / (b + 1))) + u

    @staticmethod
    def str_seconds(time_sec: str | int | float) -> str:
        """Converts seconds into a string of hours, minutes, and seconds."""
        time_sec = float(time_sec)
        hours = time_sec // 3600
        remainder_seconds = time_sec % 3600
        minutes = remainder_seconds // 60
        seconds = remainder_seconds % 60

        time_str: str = str(int(seconds)) + "s"
        if minutes:
            time_str = str(int(minutes)) + "m " + time_str
        if hours:
            time_str = str(int(hours)) + "h " + time_str
        return time_str

    @staticmethod
    def is_chinese(word: str | list) -> bool:
        """Checks if a string or list of strings contains Chinese characters."""
        if not word:
            return False
        if isinstance(word, list):
            word = " ".join(word)
        chn = re.compile(r"[\u4e00-\u9fff]")
        return bool(chn.search(word))

    @staticmethod
    def is_japanese(word: str) -> bool:
        """Checks if a string contains Japanese characters."""
        jap = re.compile(r"[\u3040-\u309F\u30A0-\u30FF]")
        return bool(jap.search(word))

    @staticmethod
    def is_korean(word: str) -> bool:
        """Checks if a string contains Korean characters."""
        kor = re.compile(r"[\uAC00-\uD7FF]")
        return bool(kor.search(word))

    @staticmethod
    def is_all_chinese(word: str) -> bool:
        """Checks if a string consists entirely of Chinese characters."""
        for ch in word:
            if ch == " ":
                continue
            if "\u4e00" <= ch <= "\u9fff":
                continue
            else:
                return False
        return True

    @staticmethod
    def is_english_word(word: str) -> bool:
        """Checks if a string is a single English word (no spaces)."""
        return word.encode().isalpha()

    @staticmethod
    def str_int(text: str) -> int:
        """Converts a web string (which may contain commas) to an integer.

        :param text: The web string.
        :return: The integer value, or 0 if conversion fails.
        """
        if text:
            text = text.strip()
        if not text:
            return 0
        try:
            return int(text.replace(",", ""))
        except ValueError:
            return 0

    @staticmethod
    def str_float(text: str) -> float:
        """Converts a web string (which may contain commas) to a float.

        :param text: The web string.
        :return: The float number, or 0.0 if conversion fails.
        """
        if text:
            text = text.strip()
        if not text:
            return 0.0
        try:
            text = text.replace(",", "")
            if text:
                return float(text)
        except ValueError:
            pass
        return 0.0

    @staticmethod
    def clear(
        text: list | str, replace_word: str = "", allow_space: bool = False
    ) -> list | str:
        """Removes special characters from a string or a list of strings.

        :param text: The input string or list of strings.
        :param replace_word: The word to replace special characters with.
        :param allow_space: If True, multiple spaces are converted to a single space.
        :return: The cleaned string or list of strings.
        """
        # Special characters to be ignored
        CONVERT_EMPTY_CHARS = (
            r"[、.。,，·:：;；!！'’\"\"()（）\[\]【】「」\-—―\+\|\\_/&#～~]"
        )
        if not text:
            return text
        if not isinstance(text, list):
            text = re.sub(
                r"[\u200B-\u200D\uFEFF]",
                "",
                re.sub(rf"{CONVERT_EMPTY_CHARS}", replace_word, text),
                flags=re.IGNORECASE,
            )
            if not allow_space:
                return re.sub(r"\s+", "", text)
            else:
                return re.sub(r"\s+", " ", text).strip()
        else:
            return [StringUtils.clear(x) for x in text]

    @staticmethod
    def clear_upper(text: str | None) -> str:
        """Removes special characters and converts the string to uppercase."""
        if not text:
            return ""
        return StringUtils.clear(text).upper().strip()

    @staticmethod
    def str_filesize(size: str | float | int, pre: int = 2) -> str:
        """Formats bytes into a human-readable filesize string with units."""
        if size is None:
            return ""
        size = re.sub(r"\s|B|iB", "", str(size), flags=re.I)
        if size.replace(".", "").isdigit():
            try:
                size = float(size)
                d = [
                    (1024 - 1, "K"),
                    (1024**2 - 1, "M"),
                    (1024**3 - 1, "G"),
                    (1024**4 - 1, "T"),
                ]
                s = [x[0] for x in d]
                index = bisect.bisect_left(s, size) - 1  # noqa
                if index == -1:
                    return str(size) + "B"
                else:
                    b, u = d[index]
                return str(round(size / (b + 1), pre)) + u
            except ValueError:
                return ""
        if re.findall(r"[KMGTP]", size, re.I):
            return size
        else:
            return size + "B"

    @staticmethod
    def url_equal(url1: str, url2: str) -> bool:
        """Compares two URLs to see if they belong to the same website."""
        if not url1 or not url2:
            return False
        if url1.startswith("http"):
            url1 = parse.urlparse(url1).netloc
        if url2.startswith("http"):
            url2 = parse.urlparse(url2).netloc
        return url1.replace("www.", "") == url2.replace("www.", "")

    @staticmethod
    def get_url_netloc(url: str) -> tuple[str, str]:
        """Gets the scheme and netloc (network location) of a URL."""
        if not url:
            return "", ""
        if not url.startswith("http"):
            return "http", url
        addr = parse.urlparse(url)
        return addr.scheme, addr.netloc

    @staticmethod
    def get_url_domain(url: str) -> str:
        """Gets the domain part of a URL, keeping only the last two levels."""
        if not url:
            return ""

        _, netloc = StringUtils.get_url_netloc(url)
        if netloc:
            locs = netloc.split(".")
            if len(locs) > 3:
                return netloc
            return ".".join(locs[-2:])
        return ""

    @staticmethod
    def get_url_sld(url: str) -> str:
        """Gets the second-level domain (SLD) of a URL, without the port.

        Returns the IP if it's an IP address.
        """
        if not url:
            return ""
        _, netloc = StringUtils.get_url_netloc(url)
        if not netloc:
            return ""
        netloc_parts = netloc.split(":")[0].split(".")
        if len(netloc_parts) >= 2:
            return netloc_parts[-2]
        return netloc_parts[0]

    @staticmethod
    def get_url_host(url: str) -> str:
        """Gets the main domain name from a URL (e.g., 'google' from
        'www.google.com')."""
        if not url:
            return ""
        _, netloc = StringUtils.get_url_netloc(url)
        if not netloc:
            return ""
        return netloc.split(".")[-2]

    @staticmethod
    def get_base_url(url: str) -> str:
        """Gets the base URL (scheme and netloc)."""
        if not url:
            return ""
        scheme, netloc = StringUtils.get_url_netloc(url)
        return f"{scheme}://{netloc}"

    @staticmethod
    def clear_file_name(name: str) -> str | None:
        """Removes characters that are invalid in filenames.

        Replaces standard colons with full-width colons.
        """
        if not name:
            return None
        return re.sub(r"[*\\/\"<>~|]", "", name, flags=re.IGNORECASE).replace(":", "：")

    @staticmethod
    def generate_random_str(length: int = 16, secure: bool = False) -> str:
        """Generates a random string of a specified length.

        :param length: The length of the random string. Defaults to 16.
        :param secure: If True, uses the `secrets` module for a cryptographically
                       secure string. If False, uses the `random` module for a
                       pseudo-random string (faster but less secure). Defaults to False.
        :return: The generated random string.
        """
        base_str = "ABCDEFGHIGKLMNOPQRSTUVWXYZabcdefghigklmnopqrstuvwxyz0123456789"

        if secure:
            # Use the secrets module to generate a cryptographically secure random string
            return "".join(secrets.choice(base_str) for _ in range(length))
        else:
            # Use the random module to generate a pseudo-random string (more efficient)
            return "".join(random.choices(base_str, k=length))

    @staticmethod
    def get_time(date: Any) -> datetime.datetime | None:
        """Parses a date string into a datetime object."""
        try:
            return dateutil.parser.parse(date)
        except dateutil.parser.ParserError:
            return None

    @staticmethod
    def unify_datetime_str(datetime_str: str) -> str:
        """Formats a datetime string into 'YYYY-MM-DD HH:MM:SS' format.

            - Scenario 1: Datetime string with timezone, e.g., 'Sat, 15 Oct 2022 14:02:54 +0800'
            - Scenario 2: Datetime string with 'T', e.g., '2020-10-14T07:48:04'
            - Scenario 3: Datetime string with 'T' and milliseconds, e.g., '2020-10-14T07:48:04.208'
            - Scenario 4: Datetime string ending with 'GMT', e.g., 'Fri, 14 Oct 2022 07:48:04 GMT'
            - Scenario 5: Datetime string ending with 'UTC', e.g., 'Fri, 14 Oct 2022 07:48:04 UTC'
            - Scenario 6: Datetime string ending with 'Z', e.g., 'Fri, 14 Oct 2022 07:48:04Z'
            - Scenario 7: Relative time string, e.g., '1 month, 2 days ago'

        :param datetime_str: The date string to format.
        :return: The formatted date string.
        """
        # If the input is None or an empty string, return it directly
        if not datetime_str:
            return datetime_str

        try:
            parsed_date = dateparser.parse(datetime_str)
            return (
                parsed_date.strftime("%Y-%m-%d %H:%M:%S")
                if parsed_date
                else datetime_str
            )
        except Exception as e:
            print(str(e))
            return datetime_str

    @staticmethod
    def format_timestamp(timestamp: str, date_format: str = "%Y-%m-%d %H:%M:%S") -> str:
        """Converts a timestamp to a formatted date string.

        :param timestamp: The timestamp to convert.
        :param date_format: The desired date format.
        :return: The formatted date string.
        """
        if isinstance(timestamp, str) and not timestamp.isdigit():
            return timestamp
        try:
            return datetime.datetime.fromtimestamp(int(timestamp)).strftime(date_format)
        except Exception as e:
            print(str(e))
            return timestamp

    @staticmethod
    def str_to_timestamp(date_str: str) -> float:
        """Converts a date string to a timestamp.

        :param date_str: The date string.
        :return: The timestamp, or 0 if conversion fails.
        """
        if not date_str:
            return 0
        try:
            parsed_date = dateparser.parse(date_str)
            return parsed_date.timestamp() if parsed_date else 0
        except Exception as e:
            print(str(e))
            return 0

    @staticmethod
    def to_bool(text: Any, default_val: bool = False) -> bool:
        """Converts a value to a boolean.

        :param text: The value to convert.
        :param default_val: The default value if the string is empty.
        :return: The boolean representation.
        """
        if isinstance(text, str) and not text:
            return default_val
        if isinstance(text, bool):
            return text
        if isinstance(text, (int, float)):
            return text > 0
        if isinstance(text, str) and text.lower() in ["y", "true", "1", "yes", "on"]:
            return True
        return False

    @staticmethod
    def str_from_cookiejar(cj: dict) -> str:
        """Converts a cookiejar dictionary to a string.

        :param cj: The cookiejar dictionary.
        :return: The cookie string.
        """
        return "; ".join([f"{key}={value}" for key, value in cj.items()])

    @staticmethod
    def md5_hash(data: Any) -> str:
        """Calculates the MD5 hash of the given data."""
        if not data:
            return ""
        return hashlib.md5(str(data).encode()).hexdigest()

    @staticmethod
    def str_timehours(minutes: int) -> str:
        """Converts minutes into a string of hours and minutes.

        :param minutes: The number of minutes.
        :return: A string representing hours and minutes (e.g., '2h 30m').
        """
        if not minutes:
            return ""
        hours = minutes // 60
        minutes = minutes % 60
        if hours:
            return f"{hours}h {minutes}m"
        else:
            return f"{minutes}m"

    @staticmethod
    def str_amount(amount: object, curr="$") -> str:
        """Formats an amount as a currency string (e.g., $1,234.56)."""
        if not amount:
            return "0"
        return curr + format(amount, ",")

    @staticmethod
    def count_words(text: str) -> int:
        """Counts the number of words (English) and characters (Chinese) in a string.

        :param text: The string to count.
        :return: The total count of words and characters.
        """
        if not text:
            return 0
        # Use regex to match Chinese characters and English words
        chinese_pattern = "[\u4e00-\u9fa5]"
        english_pattern = "[a-zA-Z]+"

        # Match Chinese characters and English words
        chinese_matches = re.findall(chinese_pattern, text)
        english_matches = re.findall(english_pattern, text)

        # Filter out spaces and numbers (already handled by regex)
        chinese_words = [word for word in chinese_matches if word.isalpha()]
        english_words = [word for word in english_matches if word.isalpha()]

        # Count the number of Chinese characters and English words
        chinese_count = len(chinese_words)
        english_count = len(english_words)

        return chinese_count + english_count

    @staticmethod
    def split_text(text: str, max_length: int) -> Generator[str]:
        """Splits text into chunks of a maximum byte length, prioritizing splitting at
        newlines and avoiding splitting within words."""
        if not text:
            yield ""
            return
        # Split by lines
        lines = text.split("\n")
        buf = ""
        for line in lines:
            if len(line.encode("utf-8")) > max_length:
                # Continue splitting oversized lines
                blank = ""
                if re.match(r"^[A-Za-z0-9.\s]+", line):
                    # Split English lines by space
                    parts = line.split()
                    blank = " "
                else:
                    # Split Chinese lines by character
                    parts = list(line)
                part = ""
                for p in parts:
                    if len((part + p).encode("utf-8")) > max_length:
                        # Yield if oversized
                        yield (buf + part).strip()
                        buf = ""
                        part = f"{blank}{p}"
                    else:
                        part = f"{part}{blank}{p}"
                if part:
                    # Append the last part to the buffer
                    buf += part
            else:
                if len((buf + "\n" + line).encode("utf-8")) > max_length:
                    # Yield if buffer is oversized
                    yield buf.strip()
                    buf = line
                else:
                    # Append short lines directly to the buffer
                    if buf:
                        buf = f"{buf}\n{line}"
                    else:
                        buf = line
        if buf:
            # Process the remaining part at the end of the text
            yield buf.strip()

    @staticmethod
    def escape_markdown(content: str) -> str:
        """Escapes Markdown characters in a string of Markdown.

        :param content: The string of Markdown to escape.
        :return: The escaped string.
        """

        parses = re.sub(r"([_*\[\]()~`>#+\-=|.!{}])", r"\\\1", content)
        reparse = re.sub(r"\\\\([_*\[\]()~`>#+\-=|.!{}])", r"\1", parses)
        return reparse

    @staticmethod
    def get_domain_address(
        address: str, prefix: bool = True
    ) -> tuple[str | None, int | None]:
        """Extracts the domain and port from an address.

        :param address: The address string.
        :param prefix: Whether the returned domain should include the protocol prefix.
        :return: A tuple containing the domain and port.
        """
        if not address:
            return None, None
        # Remove trailing slash
        address = address.rstrip("/")
        if prefix and not address.startswith("http"):
            # If prefix is required but not present, add it
            address = "http://" + address
        elif not prefix and address.startswith("http"):
            # If prefix is not required but is present, remove it
            address = address.split("://")[-1]

        # Split domain and port
        parts = address.split(":")
        if len(parts) > 3:
            # Handle cases with multiple colons (other than the one after the protocol)
            return None, None
        elif len(parts) == 3:
            port = int(parts[-1])
            # Address without port
            domain = ":".join(parts[:-1]).rstrip("/")
        elif len(parts) == 2:
            port = 443 if address.startswith("https") else 80
            domain = address
        else:
            return None, None
        return domain, port

    @staticmethod
    def str_series(array: list[int]) -> str:
        """Converts a list of integers into a compact string representation of series.

        e.g., [1, 2, 3, 5, 6, 8] -> '1-3,5-6,8'.
        """
        if not array:
            return ""
        # Ensure the array is sorted in ascending order
        array.sort()

        result = []
        start = array[0]
        end = array[0]

        for i in range(1, len(array)):
            if array[i] == end + 1:
                end = array[i]
            else:
                if start == end:
                    result.append(str(start))
                else:
                    result.append(f"{start}-{end}")
                start = array[i]
                end = array[i]

        # Handle the last sequence
        if start == end:
            result.append(str(start))
        else:
            result.append(f"{start}-{end}")

        return ",".join(result)

    @staticmethod
    def format_ep(nums: list[int]) -> str:
        """Formats a list of episode numbers into continuous ranges.

        e.g., [1, 2, 3, 5] -> 'E01-E03,E05'.
        """
        if not nums:
            return ""
        if len(nums) == 1:
            return f"E{nums[0]:02d}"
        # Sort the array in ascending order
        nums.sort()
        formatted_ranges = []
        start = nums[0]
        end = nums[0]

        for i in range(1, len(nums)):
            if nums[i] == end + 1:
                end = nums[i]
            else:
                if start == end:
                    formatted_ranges.append(f"E{start:02d}")
                else:
                    formatted_ranges.append(f"E{start:02d}-E{end:02d}")
                start = end = nums[i]

        if start == end:
            formatted_ranges.append(f"E{start:02d}")
        else:
            formatted_ranges.append(f"E{start:02d}-E{end:02d}")

        return ",".join(formatted_ranges)

    @staticmethod
    def is_number(text: str) -> bool:
        """Checks if a string can be converted to an integer or a float."""
        if not text:
            return False
        try:
            float(text)
            return True
        except ValueError:
            return False

    @staticmethod
    def find_common_prefix(str1: str, str2: str) -> str:
        """Finds the longest common prefix between two strings."""
        if not str1 or not str2:
            return ""
        common_prefix = []
        min_len = min(len(str1), len(str2))

        for i in range(min_len):
            if str1[i] == str2[i]:
                common_prefix.append(str1[i])
            else:
                break

        return "".join(common_prefix)

    @staticmethod
    def compare_version(
        v1: str, compare_type: str, v2: str, verbose: bool = False
    ) -> tuple[bool | None, str | Exception] | bool | None:
        """Compares two version numbers.

        :param v1: The source version number.
        :param v2: The target version number.
        :param verbose: If True, returns a tuple with a boolean and a detailed message.
            Defaults to False.
        :param compare_type: The comparison operator. Supports 'ge' or '>=', 'le' or
            '<=', 'eq' or '==', 'gt' or '>', 'lt' or '<'.
        :return: The result of the comparison.
        """

        def __preprocess_version(version: str) -> list:
            """Preprocesses the version string by stripping whitespace, removing a
            leading 'v' (case-insensitive), and splitting it."""
            return re.split(r"[.-]", version.strip().lstrip("vV"))

        def __conversion_version(version_list) -> list:
            """Converts string components (like 'beta', 'rc') to their numeric
            equivalents.

            :param version_list: A list of version components, e.g., ['1', '2', '3',
                  'beta']
            """
            result = []
            for item in version_list:
                # stable = -1, rc = -2, beta = -3, alpha = -4
                if item.isdigit():
                    result.append(int(item))
                # Others that do not match are set to -5
                else:
                    value = _version_map.get(item, _other_version)
                    result.append(value)
            return result

        try:
            if not v1 or not v2:
                raise ValueError("One or both version strings are missing")
            if not compare_type:
                raise ValueError("Comparison type is missing")
            if compare_type not in {
                "ge",
                "gt",
                "le",
                "lt",
                "eq",
                "==",
                ">=",
                ">",
                "<=",
                "<",
            }:
                raise ValueError(f"Invalid comparison type: {compare_type}")

            # Split and convert version strings into lists of numbers
            v1_list = __conversion_version(__preprocess_version(version=v1))
            v2_list = __conversion_version(__preprocess_version(version=v2))

            # Pad version lists with zeros to make them the same length
            max_length = max(len(v1_list), len(v2_list))
            v1_list += [0] * (max_length - len(v1_list))
            v2_list += [0] * (max_length - len(v2_list))

            ver_comparison, ver_comparison_err = None, None
            for v1_value, v2_value in zip(v1_list, v2_list, strict=False):
                # Source == Target
                if compare_type in {"eq", "=="}:
                    if v1_value != v2_value:
                        ver_comparison, ver_comparison_err = None, "not equal"
                        break
                    else:
                        ver_comparison, ver_comparison_err = "equal", None
                # Source >= Target
                elif compare_type in {"ge", ">="}:
                    if v1_value > v2_value:
                        ver_comparison, ver_comparison_err = "greater than", None
                        break
                    elif v1_value < v2_value:
                        ver_comparison, ver_comparison_err = None, "less than"
                        break
                    else:
                        ver_comparison, ver_comparison_err = "equal", None
                # Source > Target
                elif compare_type in {"gt", ">"}:
                    if v1_value > v2_value:
                        ver_comparison, ver_comparison_err = "greater than", None
                        break
                    elif v1_value < v2_value:
                        ver_comparison, ver_comparison_err = None, "less than"
                        break
                    else:
                        ver_comparison, ver_comparison_err = None, "equal"
                # Source <= Target
                elif compare_type in {"le", "<="}:
                    if v1_value > v2_value:
                        ver_comparison, ver_comparison_err = None, "greater than"
                        break
                    elif v1_value < v2_value:
                        ver_comparison, ver_comparison_err = "less than", None
                        break
                    else:
                        ver_comparison, ver_comparison_err = "equal", None
                # Source < Target
                elif compare_type in {"lt", "<"}:
                    if v1_value > v2_value:
                        ver_comparison, ver_comparison_err = None, "greater than"
                        break
                    elif v1_value < v2_value:
                        ver_comparison, ver_comparison_err = "less than", None
                        break
                    else:
                        ver_comparison, ver_comparison_err = None, "equal"

            msg = (
                f"Version {v1} is "
                f"{ver_comparison if ver_comparison else ver_comparison_err} "
                f"the target version {v2}!"
            )

            return (
                (True if ver_comparison else False, msg)
                if verbose
                else bool(ver_comparison)
            )

        except Exception as e:
            return (None, e) if verbose else None

    @staticmethod
    def diff_time_str(time_str: str) -> str:
        """Takes a 'YYYY-MM-DD HH:MM:SS' formatted string and returns the remaining time
        from now as 'xx days xx hours xx minutes'."""
        if not time_str:
            return ""
        try:
            time_obj = datetime.datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return time_str
        now = datetime.datetime.now()
        diff = time_obj - now
        if diff.total_seconds() < 0:
            return ""

        diff_days = diff.days
        diff_seconds = diff.seconds
        diff_hours = diff_seconds // 3600
        diff_minutes = (diff_seconds % 3600) // 60

        parts = []
        if diff_days > 0:
            parts.append(f"{diff_days} days")
        if diff_hours > 0:
            parts.append(f"{diff_hours} hours")
        if diff_minutes > 0:
            parts.append(f"{diff_minutes} minutes")

        return " ".join(parts) if parts else ""

    @staticmethod
    def safe_strip(value: str | None) -> str | None:
        """Safely strips whitespace from a string.

        :return: The stripped string, or None if the input is None.
        """
        return value.strip() if value is not None else None

    @staticmethod
    def is_valid_html_element(elem) -> bool:
        """Checks if an element is a valid HTML element (i.e., not None and has a non-
        zero length).

        :param elem: The HTML element to check.
        :return: True if the element is valid, False otherwise.
        """
        return elem is not None and len(elem) > 0

    @staticmethod
    def is_link(text: str) -> bool:
        """Checks if a string is a link, supporting various protocols.

        :param text: The text to check.
        :return: True if the text is a valid link, False otherwise.
        """
        if not text:
            return False
        # Check for protocols like http, https, ftp, etc.
        if re.match(r"^(http|https|ftp|ftps|sftp|ws|wss)://", text):
            return True
        # Check for IP address or domain name
        if re.match(r"^[a-zA-Z0-9.-]+(\.[a-zA-Z]{2,})?$", text):
            return True
        return False

    @staticmethod
    def is_magnet_link(content: str | bytes) -> bool:
        """Checks if the content is a magnet link."""
        if not content:
            return False
        if isinstance(content, str):
            return content.startswith("magnet:")
        if isinstance(content, bytes):
            return content.startswith(b"magnet:")
        return False

    @staticmethod
    def natural_sort_key(text: str) -> list[int | str]:
        """Provides a key for natural sorting. Splits the string into numeric and non-
        numeric parts, converting numbers to integers for proper sorting.

        :param text: The string to process.
        :return: A list of strings and integers for sorting.
        """
        if text is None:
            return []

        if not isinstance(text, str):
            text = str(text)

        return [
            int(part) if part.isdigit() else part.lower()
            for part in re.split(r"(\d+)", text)
        ]
