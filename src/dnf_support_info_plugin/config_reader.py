# Copyright Amazon.com, Inc. and its affiliates. All Rights Reserved.
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; version 2
# of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/gpl-2.0.html>.

"""Configuration reader for DNF Support Info plugin."""

import logging
import os
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

from dnf.conf.substitutions import Substitutions
from dnf.exceptions import Error as DnfError
from libdnf.conf import ConfigParser

from .const import DEFAULT_CACHE_DURATION_SECONDS, SUPPORT_INFO_CONFIG_PATH
from .file_cache import FileHandler
from .utils import validate_metadata_expire

logger = logging.getLogger("dnf.plugin")


class ConfigReader:
    """Read and hold DNF support info plugin configuration.

    Reads configuration from /etc/dnf/plugins/supportinfo.conf on initialization
    and exposes values as instance properties.
    """

    def __init__(self, config_path: str = SUPPORT_INFO_CONFIG_PATH) -> None:
        """Initialize and read configuration from file.

        Args:
            config_path: Path to config file (default: /etc/dnf/plugins/supportinfo.conf)

        Raises:
            DnfError: If config file is missing, invalid, or cannot be read
        """
        self.config_path = config_path

        # Initialize private attributes (will be set by _load_config)
        self._baseurl: str = ""
        self._templateurl: Optional[str] = None
        self._metadata_expire: int = DEFAULT_CACHE_DURATION_SECONDS
        self._gpgcheck: bool = False
        self._gpgkey: List[str] = []
        self._legacy: bool = False

        self._load_config()

    @property
    def baseurl(self) -> str:
        """URL to support info XML file."""
        return self._baseurl

    @property
    def templateurl(self) -> Optional[str]:
        """URL to support info XSD file (optional)."""
        return self._templateurl

    @property
    def metadata_expire(self) -> int:
        """Cache validity duration in seconds."""
        return self._metadata_expire

    @property
    def gpgcheck(self) -> bool:
        """Whether to verify downloaded supportinfo.xml against a GPG signature."""
        return self._gpgcheck

    @property
    def gpgkey(self) -> List[str]:
        """List of GPG key URLs used to verify downloaded files."""
        return self._gpgkey

    @property
    def legacy(self) -> bool:
        """Whether to convert downloaded XML to legacy format.

        When True, the plugin converts schema_version='1.0' XML to
        the legacy (unversioned) format used by the previous
        dnf-plugin-support-info package. This preserves backward
        compatibility for scripts reading the old XML file location
        or depending on the old output format.

        Requires root privileges (writes to system paths).
        """
        return self._legacy

    @staticmethod
    def _parse_bool_option(config_parser: ConfigParser, option: str, default: bool = False) -> bool:
        """Parse a boolean option from [main] section.

        Accepts 1/0, true/false, yes/no, on/off (case-insensitive).

        Args:
            config_parser: Parsed configuration
            option: Config option name
            default: Default value when option is not set

        Returns:
            Parsed boolean value

        Raises:
            DnfError: If the value is not a recognised boolean
        """
        if not config_parser.has_option("main", option):
            return default

        raw = config_parser.get("main", option).strip().lower()
        if raw in ("1", "true", "yes", "on"):
            return True
        if raw in ("0", "false", "no", "off"):
            return False

        raise DnfError(
            f"Invalid {option} value '{raw}': must be 1 or 0 " f"(or true/false, yes/no, on/off)"
        )

    def _load_config(self) -> None:
        """Load configuration from file and set instance attributes.

        Raises:
            DnfError: If config file is missing or invalid
        """
        if not Path(self.config_path).exists():
            logger.debug(f"Config file {self.config_path} not found")
            raise DnfError(
                f"Support info plugin requires configuration. Please create {self.config_path} with:\n\n"
                "[main]\n"
                "baseurl = https://your-url/supportinfo.xml\n"
                "# Optional settings:\n"
                "# templateurl = https://your-url/supportinfo.xsd\n"
                "# metadata_expire = 3600"
            )

        if not os.access(self.config_path, os.R_OK):
            raise DnfError(f"Error: Permission denied reading config file: {self.config_path}")

        logger.debug(f"Reading config from {self.config_path}")

        try:
            config_parser = ConfigParser()
            config_parser.read(self.config_path)

            # Require [main] section
            if not config_parser.has_section("main"):
                raise DnfError(f"Config file must have [main] section: {self.config_path}")

            # Parse and set configuration as private instance attributes
            self._baseurl = self._validate_and_get_baseurl(config_parser, self.config_path)
            self._templateurl = self._get_optional_templateurl(config_parser)
            self._metadata_expire = self._parse_metadata_expire(config_parser)
            self._gpgcheck = self._parse_gpgcheck(config_parser)
            self._gpgkey = self._parse_gpgkey(config_parser)
            self._legacy = self._parse_legacy(config_parser)

            # Validate gpgcheck requires gpgkey
            if self._gpgcheck and not self._gpgkey:
                raise DnfError("gpgcheck is enabled but no gpgkey URLs are configured")

            logger.debug(f"Loaded configuration from {self.config_path}")

        except DnfError:
            # Re-raise DnfError as-is
            raise
        except Exception as e:
            raise DnfError(f"Failed to read config file {self.config_path}: {e}") from e

    def _validate_url_scheme(self, url: str, field_name: str) -> None:
        """Validate that URL uses a supported scheme.

        Automatically detects supported schemes from registered FileHandler classes.

        Args:
            url: URL to validate
            field_name: Name of the config field (for error messages)

        Raises:
            DnfError: If URL scheme is not supported
        """
        # Get supported schemes from FileHandler registry
        supported_schemes = FileHandler.get_supported_schemes()

        parsed = urlparse(url)
        if not parsed.scheme:
            raise DnfError(f"{field_name} must include a URL scheme (e.g., https://)")

        if parsed.scheme not in supported_schemes:
            raise DnfError(
                f"Unsupported URL scheme '{parsed.scheme}' in {field_name}. "
                f"Supported schemes: {', '.join(sorted(supported_schemes))}"
            )

    def _resolve_dnf_variables(self, url_template: str) -> str:
        """Resolve DNF variables in URL template using DNF's substitution system.

        Args:
            url_template: URL template with DNF variables like $awsregion

        Returns:
            URL with resolved variables

        Raises:
            DnfError: If variable resolution fails and unresolved variables
                remain in the URL, which would cause downstream HTTP operations to fail.
        """
        try:
            # Create substitutions instance and load variables from /etc/dnf/vars/
            substitutions = Substitutions()
            substitutions.update_from_etc(installroot="/")

            # Use libdnf ConfigParser to substitute variables
            resolved_url = ConfigParser.substitute(url_template, substitutions)
            return resolved_url
        except Exception as e:
            if "$" in url_template:
                logger.error(
                    f"Failed to resolve DNF variables in URL '{url_template}': {e}. "
                    "Downstream operations will fail with unresolved variables."
                )
                raise DnfError(f"Failed to resolve DNF variables in URL: {e}") from e

            # If no variables present, URL might still be valid
            logger.warning(f"DNF variable resolution failed but URL contains no variables: {e}")
            return url_template

    def _validate_and_get_baseurl(self, config_parser: ConfigParser, config_path: str) -> str:
        """Validate and retrieve baseurl from config.

        Args:
            config_parser: Parsed configuration
            config_path: Path to config file for error messages

        Returns:
            Resolved baseurl string

        Raises:
            DnfError: If baseurl is missing, empty, or invalid
        """
        if not config_parser.has_option("main", "baseurl"):
            raise DnfError("Config must have 'baseurl' option in [main] section")

        baseurl = config_parser.get("main", "baseurl")
        if not baseurl or not baseurl.strip():
            raise DnfError("baseurl must not be empty")

        # Resolve DNF variables in baseurl first. The raw template may start
        # with a variable (e.g. "$amzn_proto://...") which urlparse cannot
        # recognise as a scheme, so validation must run on the resolved URL.
        resolved = self._resolve_dnf_variables(baseurl.strip())

        # Validate the resolved URL
        self._validate_url_scheme(resolved, "baseurl")

        return resolved

    def _get_optional_templateurl(self, config_parser: ConfigParser) -> Optional[str]:
        """Get and resolve optional templateurl from config.

        Args:
            config_parser: Parsed configuration

        Returns:
            Resolved templateurl string or None if not provided
        """
        if not config_parser.has_option("main", "templateurl"):
            return None

        templateurl = config_parser.get("main", "templateurl")
        if not templateurl or not templateurl.strip():
            return None

        # Resolve DNF variables first, then validate the resolved URL. See
        # _validate_and_get_baseurl for why the order matters with templates
        # like "$amzn_proto://...".
        resolved = self._resolve_dnf_variables(templateurl.strip())

        # Validate the resolved URL
        self._validate_url_scheme(resolved, "templateurl")

        return resolved

    def _parse_metadata_expire(self, config_parser: ConfigParser) -> int:
        """Parse and validate metadata_expire from config.

        Both non-integer strings (e.g. "abc") and out-of-range integers
        (e.g. -5) are treated the same: they raise DnfError so that a
        misconfigured file fails loudly rather than silently using a default.

        Args:
            config_parser: Parsed configuration

        Returns:
            Validated metadata_expire value in seconds

        Raises:
            DnfError: If metadata_expire value cannot be parsed or is out of range
        """
        if not config_parser.has_option("main", "metadata_expire"):
            return DEFAULT_CACHE_DURATION_SECONDS

        expire_str = config_parser.get("main", "metadata_expire")

        # Parse integer value
        try:
            metadata_expire = int(expire_str)
        except ValueError as e:
            raise DnfError(
                f"Invalid metadata_expire value '{expire_str}': must be an integer"
            ) from e

        # Validate the parsed value (raises ValueError for out-of-range)
        try:
            validate_metadata_expire(metadata_expire)
        except ValueError as e:
            raise DnfError(f"Invalid metadata_expire value '{metadata_expire}': {e}") from e

        return metadata_expire

    def _parse_gpgcheck(self, config_parser: ConfigParser) -> bool:
        """Parse gpgcheck from config. Defaults to False."""
        return self._parse_bool_option(config_parser, "gpgcheck")

    def _parse_legacy(self, config_parser: ConfigParser) -> bool:
        """Parse legacy mode from config. Defaults to False."""
        return self._parse_bool_option(config_parser, "legacy")

    def _parse_gpgkey(self, config_parser: ConfigParser) -> List[str]:
        """Parse gpgkey from config.

        Accepts a whitespace- or newline-separated list of GPG key URLs
        (``file://`` or ``https://``), matching the DNF repo ``gpgkey``
        option convention.  Returns an empty list when not set.

        Args:
            config_parser: Parsed configuration

        Returns:
            List of GPG key URL strings (may be empty if not configured).
        """
        if not config_parser.has_option("main", "gpgkey"):
            return []

        raw = config_parser.get("main", "gpgkey").strip()
        if not raw:
            return []

        # Split on whitespace/newlines, drop empty tokens
        keys = [token for token in raw.split() if token]

        # Validate each gpgkey URL scheme (only file:// and https:// allowed)
        allowed_schemes = {"file", "https"}
        for key_url in keys:
            parsed = urlparse(key_url)
            if not parsed.scheme:
                raise DnfError(
                    f"gpgkey URL must include a scheme (e.g., file:// or https://): {key_url}"
                )
            if parsed.scheme not in allowed_schemes:
                raise DnfError(
                    f"Unsupported URL scheme '{parsed.scheme}' in gpgkey. "
                    f"Supported schemes: {', '.join(sorted(allowed_schemes))}"
                )

        return keys
