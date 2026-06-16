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

"""DNF plugin for displaying package support information."""

import argparse
import contextlib
import hashlib
import logging
import os
import shutil
import site
import sys
import tempfile
from pathlib import Path
from typing import Optional

import dnf
import dnf.cli
from dnf.exceptions import Error as DnfError
from supportinfo.handler import SupportinfoHandler, SupportinfoSchemaVersions

from .config_reader import ConfigReader
from .const import (
    LEGACY_CONVERTED_FILENAME,
    LEGACY_DNF_PLUGINS_DIR,
    LEGACY_SOURCE_HASH_SUFFIX,
    LEGACY_SUPPORT_INFO_FILENAME,
)
from .dnf_package_service import DnfPackageService
from .file_cache import FileHandler
from .formatter_config import LEGACY_SCHEMA_CONFIG, SCHEMA_CONFIG
from .formatters import ConsoleFormatter, Formatter, JSONFormatter, XMLFormatter
from .legacy_converter import LegacyConverter
from .support_info_service import SupportInfoService

logger = logging.getLogger("dnf.plugin")


@dnf.plugin.register_command
class SupportInfoCommand(dnf.cli.Command):
    """Provides a manual command to check support statements for any package"""

    aliases = ("supportinfo",)
    summary = "Get support statements for DL packages"

    def __init__(self, cli: dnf.cli.Cli) -> None:
        """Initialize the command.

        Args:
            cli: DNF CLI instance
        """
        super().__init__(cli)
        self.dnf_service = DnfPackageService()
        self.service: Optional[SupportInfoService] = None
        self.file_cache: Optional[FileHandler] = None
        self.template_cache: Optional[FileHandler] = None

    @staticmethod
    def set_argparser(parser: argparse.ArgumentParser) -> None:
        """Configure command-line arguments for the supportinfo command.

        Args:
            parser: ArgumentParser instance to configure
        """
        parser.add_argument(
            "--pkg",
            help="Display support statements for one or more packages",
            dest="packages",
            nargs="+",
            metavar="PACKAGE",
        )
        parser.add_argument(
            "--showxml",
            help="Generate support info XML for a package",
            action="store_true",
            dest="show_xml",
        )
        parser.add_argument(
            "--showjson",
            help="Generate support info JSON for a package",
            action="store_true",
            dest="show_json",
        )
        parser.add_argument(
            "--show",
            help="Filter packages by state (installed/available/unavailable) and/or support level name. "
            "Use optional prefixes for disambiguation: state:NAME or support:NAME",
            dest="filters",
            nargs="+",
            metavar="FILTER",
        )
        parser.add_argument(
            "--clean-cache",
            help="Clear the remote file cache before running command",
            action="store_true",
            dest="clean_cache",
        )
        parser.add_argument(
            "--list-filters",
            help="List all available filter values that can be used with --show",
            action="store_true",
            dest="list_filters",
        )
        parser.add_argument(
            "--sync",
            help="Download and cache the latest support info XML. "
            "If legacy mode is enabled in config, also converts and places "
            "the legacy file.",
            action="store_true",
            dest="sync",
        )

    @property
    def _cache_dir(self) -> str:
        """Return the plugin cache directory derived from DNF's base cache directory.

        DNF automatically selects the right location based on the running user:
        - Root:     /var/cache/dnf/support-info/
        - Non-root: /var/tmp/dnf-<username>-<random>/support-info/

        The GPG pubring is stored inside this directory so keys are co-located
        with the data they verify, matching DNF's own repo metadata pattern.
        Keys are cleaned together with the cache via --clean-cache.
        """
        return os.path.join(self.base.conf.cachedir, "support-info")

    def _initialize_caches(self, config: Optional[ConfigReader] = None) -> bool:
        """Initialize file caches from configuration.

        Reads URLs from /etc/dnf/plugins/supportinfo.conf to create file handler caches.

        Args:
            config: Pre-loaded ConfigReader instance. If None, creates a new one.

        Returns:
            True if XML cache initialized successfully

        Raises:
            DnfError: If configuration is missing or invalid
        """
        if config is None:
            config = ConfigReader()

        # Create file cache with optional GPG verification.
        self.file_cache = FileHandler.create(
            url=config.baseurl,
            metadata_expire=config.metadata_expire,
            gpgcheck=config.gpgcheck,
            gpgkey=config.gpgkey,
            cache_dir=self._cache_dir,
        )

        # Create template cache (optional) — GPG verification applies if enabled.
        if config.templateurl:
            self.template_cache = FileHandler.create(
                url=config.templateurl,
                metadata_expire=config.metadata_expire,
                gpgcheck=config.gpgcheck,
                gpgkey=config.gpgkey,
                cache_dir=self._cache_dir,
            )

        return True

    def _get_support_info_files(
        self, config: Optional[ConfigReader] = None
    ) -> tuple[Optional[str], Optional[str]]:
        """Get paths to support_info.xml and support_info.xsd files.

        Initializes caches if needed and retrieves the file paths.

        Args:
            config: Pre-loaded ConfigReader instance. If None, creates a new one.

        Returns:
            Tuple of (file_cache, xsd_path) where file_cache is required and xsd_path is optional.
            Returns (None, None) if initialization or retrieval fails.
        """
        # Initialize caches if needed
        if not self.file_cache:
            if not self._initialize_caches(config):
                return None, None

        # Get XML file (get_file_path raises DnfError on failure)
        file_cache = self.file_cache.get_file_path()

        # Get XSD file (optional)
        xsd_path = None
        if self.template_cache:
            xsd_path = self.template_cache.get_file_path()
            if not xsd_path:
                logger.warning(
                    "Warning: Unable to retrieve XSD file, continuing without schema validation"
                )

        return file_cache, xsd_path

    def _get_dnf_output(self) -> dnf.cli.output.Output:
        """Get the DNF output formatter for console display.

        Returns:
            DNF output formatter instance
        """
        return dnf.cli.output.Output(self.cli.base, self.cli.base.conf)

    def _get_formatter(self, handler: Optional[SupportinfoHandler] = None) -> Formatter:
        """Get the appropriate formatter based on output format option.

        When a handler is provided, formatters use schema-specific
        configuration to match the output style expected for that format:
        - Console: Legacy handler → old field names, V1.0 → new field names
        - XML: Legacy handler → old-style marker/dates, V1.0 → new phases format
        - JSON: Unaffected by schema version

        Args:
            handler: Optional handler to determine schema-specific config.

        Returns:
            Formatter instance for the requested output format
        """
        if self.opts.show_json:
            return JSONFormatter()
        elif self.opts.show_xml:
            is_legacy = (
                handler is not None and handler.schema_version == SupportinfoSchemaVersions.LEGACY
            )
            return XMLFormatter(legacy=is_legacy)
        else:
            schema_config = None
            if handler is not None:
                schema_config = (
                    LEGACY_SCHEMA_CONFIG
                    if handler.schema_version == SupportinfoSchemaVersions.LEGACY
                    else SCHEMA_CONFIG
                )
            return ConsoleFormatter(self.base.output, schema_config)

    def _clean_cache(self) -> None:
        """Clear the cache directory including GPG pubring.

        Removes the entire cache directory (including cached files and GPG pubring).
        This matches DNF's behavior where repo metadata keys are cleaned with the
        repo cache.
        """
        if not os.path.exists(self._cache_dir):
            logger.info(f"Cache directory does not exist: {self._cache_dir}")
            return

        try:
            shutil.rmtree(self._cache_dir)
            logger.info(f"Cleaned cache directory: {self._cache_dir}")
        except OSError as e:
            raise DnfError(f"Failed to clean cache directory {self._cache_dir}: {e}")

    def _load_support_info(self, config: "ConfigReader") -> SupportinfoHandler:
        """Download, parse, and (if needed) convert support info XML.

        Shared helper for ``run()`` and ``_handle_sync()``. Fetches the XML
        via the file cache, parses it into a handler, and when legacy mode
        is enabled in the config converts a schema_version='1.0' XML to the
        legacy (unversioned) format and re-parses it. The returned handler
        always reflects the final format used downstream.

        Args:
            config: Pre-loaded ConfigReader instance.

        Returns:
            SupportinfoHandler for the (possibly converted) XML.

        Raises:
            DnfError: If the XML cannot be downloaded, parsed, or converted.
        """
        file_path, xsd_path = self._get_support_info_files(config)
        if file_path is None:
            raise DnfError(
                "Failed to retrieve support info XML: "
                "file cache initialization or download did not return a path"
            )
        handler = self._create_handler(file_path, xsd_path)

        if config.legacy:
            if handler.schema_version == SupportinfoSchemaVersions.V1_0:
                legacy_path = self._handle_legacy_conversion(file_path)
                handler = self._create_handler(legacy_path, None)
            else:
                logger.debug(
                    "Schema version %s does not require legacy conversion",
                    handler.schema_version,
                )

        return handler

    def _try_legacy_fallback(
        self, config: "ConfigReader", original_error: DnfError
    ) -> SupportinfoHandler:
        """Fall back to the on-disk legacy XML when fetching the source fails.

        When ``legacy = 1`` is set in the config and a previously-converted
        legacy XML exists at the path used by the old single-file plugin,
        load and parse that file instead of failing. This keeps queries
        useful when the network is offline, a baseurl returns 404/403, or
        the remote XML has been temporarily removed.

        The fallback is intentionally limited to legacy mode because that
        is the only path where a stable, plugin-managed XML file is
        guaranteed to live on disk (created by a prior ``--sync`` run).
        Cache files under ``/var/cache/dnf/...`` are not used as a fallback
        because they may be stale, evicted by ``dnf clean all``, or owned
        by a different user.

        Args:
            config: Pre-loaded ConfigReader instance.
            original_error: The DnfError raised by ``_load_support_info``.
                Re-raised when no usable legacy file exists.

        Returns:
            SupportinfoHandler parsed from the on-disk legacy XML.

        Raises:
            DnfError: ``original_error`` is re-raised when legacy mode is
                disabled, the legacy file does not exist, or parsing the
                legacy file itself fails.
        """
        if not config.legacy:
            raise original_error

        legacy_path = self._get_legacy_location()
        if not legacy_path.is_file():
            raise original_error

        logger.warning(
            "Failed to retrieve support info XML: %s. " "Using existing legacy file at %s instead.",
            original_error,
            legacy_path,
        )
        return self._create_handler(str(legacy_path), None)

    def _handle_sync(self, config: "ConfigReader") -> None:
        """Download and cache the latest support info XML.

        Fetches the support info XML (and optional XSD) from the configured
        URLs and populates the local file cache. When legacy mode is enabled
        in the configuration, also converts the schema_version='1.0' XML to
        the legacy (unversioned) format and places it at the path expected by
        the previous dnf-plugin-support-info package.

        This method is the sole handler for ``--sync`` and is designed to
        be called from RPM ``%post`` scripts or automation without requiring
        any query options (``--pkg``, ``--show``). It does not load the DNF
        sack or query package states.

        Args:
            config: Pre-loaded ConfigReader instance.

        Raises:
            DnfError: If the XML cannot be downloaded, cached, or converted.
        """
        self._load_support_info(config)
        logger.info("Support info sync complete")

    # ------------------------------------------------------------------
    # Legacy mode helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_legacy_location() -> Path:
        """Determine the old plugin's XML file path.

        The old dnf-plugin-support-info RPM bundled support_info.xml at:
            /usr/lib/python<version>/site-packages/dnf-plugins/support_info.xml

        We write the converted legacy file here so customer scripts
        that hardcode this path continue to work. The path varies by
        Python version, so we resolve it dynamically.

        Returns:
            Path to the legacy support_info.xml location.
        """
        # Pass 1: Find where dnf-plugins directory actually exists
        for site_dir in site.getsitepackages():
            candidate = Path(site_dir) / LEGACY_DNF_PLUGINS_DIR
            if candidate.is_dir():
                return candidate / LEGACY_SUPPORT_INFO_FILENAME

        # Pass 2: Fall back to first existing site-packages
        for site_dir in site.getsitepackages():
            if Path(site_dir).exists():
                return Path(site_dir) / LEGACY_DNF_PLUGINS_DIR / LEGACY_SUPPORT_INFO_FILENAME

        # Fallback: construct from Python version
        version = f"{sys.version_info.major}.{sys.version_info.minor}"
        fallback = (
            Path(f"/usr/lib/python{version}/site-packages")
            / LEGACY_DNF_PLUGINS_DIR
            / LEGACY_SUPPORT_INFO_FILENAME
        )
        logger.warning(
            "No site-packages found via site.getsitepackages(), " "using fallback: %s",
            fallback,
        )
        return fallback

    def _handle_legacy_conversion(self, file_path: str) -> str:
        """Convert 1.0 XML to legacy format, save to old location, create symlink.

        The conversion flow depends on whether the user has root privileges:

        **Root user:**
            1. Skip conversion if the legacy file already records the source
               XML's SHA-256 in the sidecar marker (identity check).
            2. Otherwise convert 1.0 XML → legacy XML using LegacyConverter.
            3. Save the legacy file atomically (tempfile + os.replace).
            4. Persist the source SHA-256 to the sidecar marker.
            5. Create a symlink in the cache directory pointing to the legacy file.

        **Non-root user:**
            1. Check if a legacy file already exists (created by a previous root run).
            2. If yes, use it as-is (read-only) with an info message.
            3. If the marker is missing or stale relative to the current source,
               warn that the file may be out of date.
            4. If no legacy file exists, raise DnfError with instructions to run as root.

        After this method, the legacy file is accessible from both:
            - Old location: /usr/lib/.../dnf-plugins/support_info.xml (real file)
            - Cache location: /var/cache/dnf/support-info/supportinfo-legacy.xml (symlink)

        Args:
            file_path: Path to the downloaded 1.0 XML file.

        Returns:
            Path to the legacy XML file (at old location).

        Raises:
            DnfError: If not running as root and no cached legacy file exists,
                      or if conversion fails.
        """
        legacy_location = self._get_legacy_location()

        # Non-root: can't write to system path, but can use existing file
        if os.geteuid() != 0:
            if legacy_location.exists():
                self._warn_if_legacy_marker_stale(legacy_location, file_path)
                logger.info(
                    "Using existing legacy file at %s "
                    "(run 'sudo dnf supportinfo --sync' to update)",
                    legacy_location,
                )
                return str(legacy_location)
            else:
                raise DnfError(
                    "Legacy mode requires root privileges to create the legacy file.\n"
                    "Run once with sudo to create it:\n"
                    "  sudo dnf supportinfo --sync\n"
                    "After that, non-root queries will use the cached legacy file."
                )

        # Root: convert and save
        symlink_path = Path(self._cache_dir) / LEGACY_CONVERTED_FILENAME

        # Skip conversion if the marker shows we already converted from this
        # exact source bytes. Identity is the SHA-256 of the source XML, which
        # is content-derived and immune to mtime / in-XML attribute quirks.
        source_hash = self._sha256_of_file(Path(file_path))
        if source_hash and self._legacy_marker_matches(legacy_location, source_hash):
            logger.debug(
                "Legacy file at %s already matches source SHA-256, skipping conversion",
                legacy_location,
            )
            # Still ensure the symlink exists (cheap, idempotent)
            self._create_legacy_symlink(symlink_path, legacy_location)
            return str(legacy_location)

        try:
            # Ensure the old plugin directory exists
            legacy_location.parent.mkdir(parents=True, exist_ok=True)

            # Convert to a temp file in the same directory, then atomically
            # replace the target. If conversion fails, the existing legacy
            # file and its marker are untouched, so the next run sees the
            # mismatch (or missing marker) and re-converts.
            tmp_fd, tmp_path = tempfile.mkstemp(
                dir=str(legacy_location.parent),
                prefix=f".{legacy_location.name}.",
                suffix=".tmp",
            )
            os.close(tmp_fd)
            try:
                converter = LegacyConverter(file_path)
                converter.convert(tmp_path)
                # mkstemp creates the file 0o600; non-root users must be able
                # to read legacy_location, so widen to 0o644 before replace.
                os.chmod(tmp_path, 0o644)
                os.replace(tmp_path, str(legacy_location))
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(tmp_path)
                raise

            # Persist the source SHA-256 to the marker only after the body
            # is in place. If this fails, the next run will see the mismatch
            # and re-convert (safe default; never serves the wrong content).
            if source_hash:
                self._write_legacy_marker(legacy_location, source_hash)
            logger.info("Saved legacy XML to %s", legacy_location)

            # Create symlink in cache dir pointing to the legacy file
            self._create_legacy_symlink(symlink_path, legacy_location)

            return str(legacy_location)

        except DnfError:
            raise
        except Exception as e:
            raise DnfError(
                f"Failed to convert to legacy format: {e}. " "Try: dnf supportinfo --clean-cache"
            ) from e

    def _warn_if_legacy_marker_stale(self, legacy_location: Path, source_path: str) -> None:
        """Warn (non-root path) if the legacy file's marker doesn't match the source.

        Best-effort, advisory only — the freshness decision belongs to the
        root-only conversion path. We just hint to the user that re-running
        with sudo would refresh the file.

        Args:
            legacy_location: Path to the converted legacy XML file.
            source_path: Path to the downloaded 1.0 source XML file.
        """
        source_hash = self._sha256_of_file(Path(source_path))
        if not source_hash:
            return
        if self._legacy_marker_matches(legacy_location, source_hash):
            return
        logger.warning(
            "Legacy file at %s does not match the latest source data. "
            "Run with sudo to update: sudo dnf supportinfo --sync",
            legacy_location,
        )

    @staticmethod
    def _sha256_of_file(path: Path) -> Optional[str]:
        """Return the SHA-256 hex digest of ``path``, or None on any read error.

        Streams the file in 64 KB chunks so memory stays flat regardless of
        size. Returning None on error is a safe default: the caller falls
        back to running the full conversion.

        Args:
            path: Path to the file to hash.

        Returns:
            Lower-case hex SHA-256 digest, or None if the file cannot be
            opened or read.
        """
        try:
            digest = hashlib.sha256()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(64 * 1024), b""):
                    digest.update(chunk)
            return digest.hexdigest()
        except OSError as e:
            logger.debug("Could not hash %s: %s", path, e)
            return None

    @staticmethod
    def _legacy_marker_path(legacy_location: Path) -> Path:
        """Return the sidecar path that records the source SHA-256 of the last conversion.

        The marker lives alongside the legacy file, e.g.
        ``support_info.xml`` -> ``support_info.xml.source-sha256``.

        Args:
            legacy_location: Path to the converted legacy XML file.

        Returns:
            Path to the SHA-256 marker sidecar.
        """
        return legacy_location.with_name(legacy_location.name + LEGACY_SOURCE_HASH_SUFFIX)

    def _legacy_marker_matches(self, legacy_location: Path, source_hash: str) -> bool:
        """Return True if the marker next to ``legacy_location`` records ``source_hash``.

        Returns False if the legacy file is missing, the marker is missing,
        the marker is unreadable, or the digest does not match — all of
        which mean the caller should re-convert.

        Args:
            legacy_location: Path to the converted legacy XML file.
            source_hash: SHA-256 hex digest of the source XML to compare against.

        Returns:
            True when the marker exists and its trimmed contents equal
            ``source_hash``; False otherwise.
        """
        if not legacy_location.exists():
            return False
        marker = self._legacy_marker_path(legacy_location)
        try:
            return marker.read_text().strip() == source_hash
        except OSError as e:
            logger.debug("Could not read legacy marker %s: %s", marker, e)
            return False

    def _write_legacy_marker(self, legacy_location: Path, source_hash: str) -> None:
        """Atomically write the source SHA-256 marker next to ``legacy_location``.

        Uses the same tempfile + os.replace pattern as the body write so a
        partial/failed write never leaves a wrong digest in place. Mode
        is set to 0o644 so non-root users can read the marker for the
        staleness warning.

        Marker write failure is logged but does not raise — the body has
        already been replaced atomically. The next invocation will simply
        re-convert (safe default; never serves the wrong content).

        Args:
            legacy_location: Path to the converted legacy XML file.
            source_hash: SHA-256 hex digest of the source XML to persist.
        """
        marker = self._legacy_marker_path(legacy_location)
        try:
            tmp_fd, tmp_path = tempfile.mkstemp(
                dir=str(marker.parent),
                prefix=f".{marker.name}.",
                suffix=".tmp",
            )
            try:
                with os.fdopen(tmp_fd, "w") as f:
                    f.write(source_hash + "\n")
                os.chmod(tmp_path, 0o644)
                os.replace(tmp_path, str(marker))
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(tmp_path)
                raise
        except OSError as e:
            logger.warning(
                "Could not persist legacy source-hash marker at %s: %s. "
                "Conversion will run again on the next invocation.",
                marker,
                e,
            )

    def _create_legacy_symlink(self, symlink_path: Path, target_path: Path) -> None:
        """Create a symlink from cache directory to the legacy file."""
        try:
            symlink_path.parent.mkdir(parents=True, exist_ok=True)
            # Idempotent: skip if the symlink already points at the target.
            if symlink_path.is_symlink() and symlink_path.resolve() == target_path.resolve():
                return
            if symlink_path.exists() or symlink_path.is_symlink():
                symlink_path.unlink()
            symlink_path.symlink_to(target_path)
            logger.debug(f"Created symlink {symlink_path} -> {target_path}")
        except OSError as e:
            logger.warning(
                f"Failed to create symlink {symlink_path} -> {target_path}: "
                f"{e}. The legacy file is still available at {target_path}."
            )

    def _create_handler(self, file_path: str, xsd_path: Optional[str]) -> SupportinfoHandler:
        """Create a SupportinfoHandler from the given file paths.

        Args:
            file_path: Path to support info XML file
            xsd_path: Optional path to XSD schema file

        Returns:
            SupportinfoHandler instance

        Raises:
            DnfError: If handler creation fails
        """
        try:
            handler = SupportinfoHandler.create(file_path, xsd_path)
            logger.debug(
                f"Using {handler.__class__.__name__} for schema version {handler.schema_version.value}"
            )
            return handler
        except ValueError as e:
            raise DnfError(f"XML validation failed: {e}") from e
        except FileNotFoundError as e:
            raise DnfError(f"File not found: {e}") from e
        except Exception as e:
            raise DnfError(f"Failed to create support info handler: {e}") from e

    def _handle_list_filters(self) -> None:
        """Print all available filter names and descriptions to stdout."""
        assert self.service is not None
        state_filters, support_level_filters = self.service.get_valid_filters()
        print("Available filters for --show:")
        print("\nOptional prefixes for disambiguation:")
        print("  state:NAME    - Explicitly filter by package state")
        print("  support:NAME  - Explicitly filter by support level")
        print("  NAME          - If NAME exists in both categories, matches both (OR logic)")

        print("\nState filters:")
        for filter_name in sorted(state_filters.keys()):
            description = state_filters[filter_name]
            if description:
                print(f"  {filter_name:<20} - {description}")
            else:
                print(f"  {filter_name}")

        if support_level_filters:
            print("\nSupport level filters:")
            for filter_name in sorted(support_level_filters.keys()):
                description = support_level_filters[filter_name]
                if description:
                    print(f"  {filter_name:<20} - {description}")
                else:
                    print(f"  {filter_name}")

    def _handle_pkg(self, formatter: object) -> None:
        """Display support info for the packages named in --pkg.

        Args:
            formatter: Formatter instance to render output

        Raises:
            DnfError: If all requested packages are not found in support info
        """
        assert self.service is not None
        # Deduplicate package names to avoid displaying same package multiple times
        packages = list(set(self.opts.packages))

        # Batch query all packages at once for better performance
        package_states = self.dnf_service.get_package_states(packages)

        packages_info = []
        not_found = []
        for package_name in packages:
            package_info = self.service.get_package_info(package_name, package_states)
            if package_info is None:
                not_found.append(package_name)
                continue
            packages_info.append(package_info)

        if not_found:
            if packages_info:
                for pkg in not_found:
                    logger.warning(f"Package '{pkg}' not found in support info.")
            else:
                raise DnfError(f"Package(s) not found in support info: {', '.join(not_found)}")

        if packages_info:
            print(formatter.format_packages(packages_info))

    def _handle_show(self, formatter: object) -> None:
        """Display filtered package list for --show.

        Args:
            formatter: Formatter instance to render output

        Raises:
            DnfError: If any supplied filter value is unknown
        """
        assert self.service is not None
        package_states = self.dnf_service.get_package_states()

        try:
            filtered_packages = self.service.filter_packages(self.opts.filters, package_states)
        except ValueError as e:
            state_filters, support_level_filters = self.service.get_valid_filters()
            raise DnfError(
                f"{e}. State filters: {', '.join(sorted(state_filters.keys()))}. "
                f"Support level filters: {', '.join(sorted(support_level_filters.keys()))}"
            )

        if filtered_packages:
            print(formatter.format_packages_table(filtered_packages))
        else:
            logger.info(f"No packages found for filters: {', '.join(self.opts.filters)}")

    def run(self) -> None:
        """Execute the supportinfo command.

        Dispatches to one of five focused handlers:
        - _clean_cache       - when --clean-cache is requested
        - _handle_sync       - when --sync is requested
        - _handle_list_filters - when --list-filters is requested
        - _handle_pkg        - when --pkg is requested
        - _handle_show       - when --show is requested

        When legacy mode is enabled in the config, the downloaded 1.0 XML
        is converted to legacy format before processing. This ensures all
        downstream output matches the old plugin's format.
        """
        # --clean-cache: wipe the cache and exit immediately — no download needed.
        if self.opts.clean_cache:
            self._clean_cache()
            return

        # Read config once, pass to methods that need it
        config = ConfigReader()

        # --sync is a standalone action — reject if combined with query options.
        if self.opts.sync:
            if self.opts.packages or self.opts.filters:
                raise DnfError("--sync cannot be combined with --pkg or --show")
            self._handle_sync(config)
            return

        # Download, parse, and convert (if legacy mode) in one step.
        # _load_support_info raises DnfError on failure. When legacy mode is
        # enabled and a previously-converted legacy file exists, fall back
        # to it with a warning so query operations remain useful when the
        # network or remote XML is unreachable.
        try:
            handler = self._load_support_info(config)
        except DnfError as exc:
            handler = self._try_legacy_fallback(config, exc)

        # Initialize service - thin wrapper around handler
        self.service = SupportInfoService(handler)

        if self.opts.list_filters:
            self._handle_list_filters()
            return

        formatter = self._get_formatter(handler)

        if self.opts.packages:
            self._handle_pkg(formatter)
        elif self.opts.filters:
            self._handle_show(formatter)
