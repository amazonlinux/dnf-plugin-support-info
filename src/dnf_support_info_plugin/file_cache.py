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

"""Remote file caching with metadata validation."""

import hashlib
import io
import json
import logging
import os
import tempfile
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http.client import HTTPResponse
from pathlib import Path
from typing import Dict, List, Optional, TypedDict
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

import dnf.crypto
import dnf.yum.misc
import gpg
import gpg.errors
from dnf.exceptions import Error as DnfError

from .const import DEFAULT_CACHE_DURATION_SECONDS
from .utils import validate_metadata_expire

logger = logging.getLogger("dnf.plugin")

GPG_VERIFY_RETRIES = 3


class HttpMetadata(TypedDict):
    """HTTP response metadata for cache validation.

    Attributes:
        url: The source URL
        etag: HTTP ETag header value (for cache validation)
        last_modified: HTTP Last-Modified header value
        size: HTTP Content-Length header value
        content_type: HTTP Content-Type header value
    """

    url: str
    etag: str
    last_modified: str
    size: str
    content_type: str


class CachedMetadata(HttpMetadata):
    """Cached metadata stored on disk, extends HttpMetadata with timestamp.

    Attributes:
        timestamp: ISO format timestamp when cache was last updated
        (inherits: url, etag, last_modified, size, content_type)
    """

    timestamp: str


@dataclass
class FetchResult:
    """Result from fetching file content, bundling data with metadata."""

    data: bytes
    metadata: Optional[HttpMetadata] = None


class GpgVerifier:
    """Verifies detached GPG signatures against a set of trusted GPG keys.

    Keys are specified as URLs (``file://`` or ``https://``) matching the
    ``gpgkey`` config option convention.  On first use each key is fetched and
    imported into a persistent pubring directory; subsequent runs skip keys
    that are already present (Trust On First Use).
    """

    def __init__(self, gpgkey: List[str], pubring_dir: str) -> None:
        """Initialize the verifier.

        Args:
            gpgkey: List of GPG key URLs (``file://`` or ``https://``).
            pubring_dir: Path to the persistent GPG pubring directory.
        """
        self.gpgkey = gpgkey
        self.pubring_dir = pubring_dir

    def _ensure_keys_imported(self) -> bool:
        """Import any keys from gpgkey URLs that are not yet in the pubring.

        Uses ``dnf.crypto.retrieve()`` to fetch each key URL and
        ``dnf.yum.misc.import_key_to_pubring()`` to store it.  Keys that are
        already present are skipped.

        Returns:
            True if at least one key is available in the pubring.
            False if the pubring is empty after attempting all imports.
        """
        known_keys = dnf.crypto.keyids_from_pubring(self.pubring_dir)

        allowed_schemes = FileHandler.get_supported_schemes()
        for url in self.gpgkey:
            scheme = urlparse(url).scheme
            if scheme not in allowed_schemes:
                logger.warning(f"Skipping gpgkey URL with unsupported scheme '{scheme}': {url}")
                continue
            try:
                keyinfos = dnf.crypto.retrieve(url)
            except Exception as e:
                logger.warning(f"Failed to retrieve GPG key from {url}: {e}")
                continue

            for keyinfo in keyinfos:
                if keyinfo.id_ in known_keys:
                    logger.debug(f"GPG key 0x{keyinfo.id_} already imported, skipping")
                    continue
                dnf.crypto.log_key_import(keyinfo)
                try:
                    dnf.yum.misc.import_key_to_pubring(
                        keyinfo.raw_key,
                        keyinfo.short_id,
                        gpgdir=self.pubring_dir,
                        make_ro_copy=False,
                    )
                    known_keys.append(keyinfo.id_)
                    logger.debug(f"Imported GPG key 0x{keyinfo.id_} into pubring")
                except Exception as e:
                    logger.warning(f"Failed to import key 0x{keyinfo.id_}: {e}")

        if not known_keys:
            logger.error(
                f"No GPG keys available in pubring {self.pubring_dir}. "
                "Ensure gpgkey URLs are correct and reachable."
            )
            return False
        return True

    def verify(self, data: bytes, signature: bytes) -> bool:
        """Verify that *data* matches the detached *signature*.

        Ensures keys are imported into the pubring, then verifies the
        signature using ``gpg.Context`` with GNUPGHOME set to the pubring
        directory so that only the plugin's trusted keys are consulted.

        Args:
            data: Raw bytes of the file to verify.
            signature: Raw bytes of the detached signature.

        Returns:
            True if the signature is valid and was made by a trusted key.
            False if verification fails for any reason.
        """
        if not self._ensure_keys_imported():
            return False

        try:
            with io.BytesIO(data) as data_io, io.BytesIO(signature) as sig_io:
                with dnf.crypto.pubring_dir(self.pubring_dir):
                    gpg_context = gpg.Context()
                    _, result = gpg_context.verify(data_io, sig_io)
            logger.debug(f"GPG signature verification succeeded: {result}")
            return True
        except gpg.errors.BadSignatures as e:
            logger.error(f"GPG signature verification failed: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error during GPG verification: {e}")
            return False


class FileCache:
    """Standalone file cache manager with metadata validation.

    This class encapsulates all caching logic and can be used by
    any handler that needs caching capabilities.
    """

    def __init__(self, url: str, metadata_expire: timedelta, cache_dir: Path) -> None:
        """Initialize cache for a specific URL.

        Args:
            url: The URL to cache
            metadata_expire: How long cache is valid before revalidation
            cache_dir: Directory for storing cached files
        """
        self.url = url
        self.cache_dir = cache_dir
        self.metadata_expire = metadata_expire

        # Setup cache paths — use 0o700 so cached data is only accessible by
        # the owning user (defense-in-depth alongside per-file 0o600 perms).
        self.cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        logger.debug(f"Using cache directory: {self.cache_dir}")

        # Log cache expiration
        seconds = metadata_expire.total_seconds()
        cache_messages = {
            -1: "never expires (infinite)",
            0: "always checks for updates",
        }
        expiry_msg = cache_messages.get(seconds, f"expires after {seconds:.0f} seconds")
        logger.debug(f"Cache {expiry_msg} for {url}")

        parsed_url = urlparse(self.url)
        basename = os.path.basename(parsed_url.path)
        url_hash = hashlib.sha256(self.url.encode()).hexdigest()[:8]

        # Include URL hash to prevent collisions between different URLs with same basename
        if basename:
            self.cache_filename = f"{basename}_{url_hash}"
        else:
            self.cache_filename = f"cached_{url_hash}"

        self.cached_file_path = self.cache_dir / self.cache_filename
        self.metadata_file_path = self.cache_dir / f"{self.cache_filename}.metadata"

    def clear(self) -> None:
        """Remove cached file and metadata from disk."""
        self.cached_file_path.unlink(missing_ok=True)
        self.metadata_file_path.unlink(missing_ok=True)

    def _is_cache_valid(self) -> bool:
        """Check if the cached file is within the cache duration.

        Returns:
            True if cache is still valid, False otherwise
        """
        metadata = self._load_metadata()
        if not metadata or "timestamp" not in metadata:
            return False

        # Special case: -1 seconds means infinite cache (never expires)
        if self.metadata_expire.total_seconds() == -1:
            return True

        cache_time = datetime.fromisoformat(metadata["timestamp"])
        return datetime.now(timezone.utc) - cache_time < self.metadata_expire

    def _load_metadata(self) -> Optional[CachedMetadata]:
        """Load cached metadata from disk.

        Returns:
            Cached metadata dictionary if file exists and is valid, None otherwise
        """
        if not self.metadata_file_path.exists():
            return None

        try:
            return json.loads(self.metadata_file_path.read_text())
        except Exception as e:
            logger.warning(f"Failed to load metadata: {e}")
            return None

    def _save_metadata(self, metadata: HttpMetadata) -> None:
        """Write metadata to disk with current timestamp using atomic write.

        Args:
            metadata: HTTP response metadata to save

        Raises:
            OSError: If the metadata file cannot be written to disk.
        """
        metadata_with_timestamp = dict(metadata)
        metadata_with_timestamp["timestamp"] = datetime.now(timezone.utc).isoformat()

        tmp_path: Optional[str] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", dir=self.metadata_file_path.parent, delete=False, suffix=".tmp"
            ) as tmp_file:
                tmp_file.write(json.dumps(metadata_with_timestamp, indent=2))
                tmp_file.flush()
                os.fsync(tmp_file.fileno())
                tmp_path = tmp_file.name

            os.chmod(tmp_path, 0o600)
            os.replace(tmp_path, self.metadata_file_path)
        except Exception as e:
            # Clean up temp file before re-raising so we don't leave stale .tmp files
            if tmp_path is not None:
                try:
                    Path(tmp_path).unlink(missing_ok=True)
                except Exception as cleanup_error:
                    logger.debug(f"Failed to clean up temp file: {cleanup_error}")
            raise OSError(f"Failed to write metadata: {e}") from e

    def _update_timestamp(self) -> None:
        """Update the cache timestamp to extend cache validity.

        Reads current metadata, removes the timestamp field, and saves it again
        to trigger creation of a fresh timestamp.
        """
        metadata = self._load_metadata()
        if metadata:
            # Remove timestamp so _save_metadata adds a fresh one
            metadata_without_timestamp: HttpMetadata = {
                "url": metadata.get("url", ""),
                "etag": metadata.get("etag", ""),
                "last_modified": metadata.get("last_modified", ""),
                "size": metadata.get("size", ""),
                "content_type": metadata.get("content_type", ""),
            }
            self._save_metadata(metadata_without_timestamp)

    def _metadata_matches(
        self, cached_metadata: Optional[CachedMetadata], remote_metadata: HttpMetadata
    ) -> bool:
        """Check if cached and remote ETags match (case-insensitive for safety).

        Args:
            cached_metadata: Cached metadata loaded from disk
            remote_metadata: Fresh metadata from HTTP HEAD request

        Returns:
            True if ETags match (indicating unchanged content), False otherwise
        """
        if cached_metadata is None:
            return False
        # Normalize ETags to lowercase for comparison (defensive against non-compliant servers)
        remote_etag = remote_metadata.get("etag", "").lower()
        cached_etag = cached_metadata.get("etag", "").lower()
        return remote_etag == cached_etag and remote_etag != ""


class FileHandler(ABC):
    """Abstract base class for file protocol handlers.

    Implements the Template Method pattern for GPG-verified file access:

    1. ``get_file_path()`` (defined here) orchestrates the full flow —
       fetching content, verifying the GPG signature when requested, and
       persisting/returning the file path.
    2. Subclasses implement the protocol-specific primitives:
       ``_fetch_content()``, ``_fetch_signature()``, and ``_persist_content()``.

    GPG state (``gpgcheck``, ``gpg_verifier``, ``asc_url``) is stored on the
    base class so the policy is always enforced in one place regardless of
    which handler is active.
    """

    # Class-level registry mapping URL schemes to handler classes
    _handlers: Dict[str, type["FileHandler"]] = {}

    def __init__(
        self,
        url: str,
        gpgcheck: bool = False,
        gpgkey: Optional[List[str]] = None,
        cache_dir: Optional[str] = None,
    ) -> None:
        """Initialize file handler.

        Args:
            url: The URL to access.
            gpgcheck: When True, verify file content against a detached GPG
                      signature before returning the path.  The signature
                      location is protocol-specific (``url + ".asc"`` for HTTPS,
                      ``<local_path>.asc`` for file://).
            gpgkey: List of GPG key URLs used when gpgcheck is True.
            cache_dir: Directory for storing cached files.
                       The GPG pubring is stored at ``<cache_dir>/pubring/`` so that keys
                       are co-located with the data they verify (matching DNF's repo
                       metadata pattern) and are cleaned together with the cache.
        """
        self.url = url
        self.gpgcheck = gpgcheck
        self.asc_url = url + ".asc"
        if gpgcheck:
            if not cache_dir:
                raise ValueError("cache_dir is required when gpgcheck is enabled")
            pubring_dir = os.path.join(cache_dir, "pubring")
            self.gpg_verifier = GpgVerifier(gpgkey or [], pubring_dir=pubring_dir)
        else:
            self.gpg_verifier = None

    # ------------------------------------------------------------------
    # Template method — NOT overridden by subclasses
    # ------------------------------------------------------------------

    def get_file_path(self) -> Optional[str]:
        """Return a path to the file, verifying its GPG signature when enabled.

        First checks whether a valid cached copy is available via
        ``_get_cached_path()``.  If so, returns it immediately — no network
        request or GPG re-verification is performed (the file was already
        verified when it was first fetched and cached).

        For a cache miss (or non-caching handlers like ``LocalFileHandler``),
        calls ``_fetch_content()`` to obtain the raw bytes, then (if
        ``gpgcheck`` is True) calls ``_fetch_signature()`` and verifies before
        delegating to ``_persist_content()`` to write/return the path.

        Returns:
            Path to the verified file, or None if the content could not be
            fetched or GPG verification failed.
        """
        # Fast path: return cached copy without GPG re-verification.
        # Let the subclass decide how to handle caching errors — exceptions
        # from _get_cached_path (e.g. filesystem errors in _is_cache_valid)
        # are caught here so the template method can fall back gracefully.
        try:
            cached = self._get_cached_path()
        except Exception as e:
            logger.warning(f"Error in caching logic: {e}")
            # Give subclasses a chance to return a stale cached file
            try:
                cached = self._get_stale_cached_path()
            except Exception as cleanup_error:
                logger.debug(f"Failed to get stale cached path: {cleanup_error}")
                cached = None
            if cached is not None:
                logger.info("Using cached file as fallback")
                return cached
            cached = None
        if cached is not None:
            return cached

        retries = self._gpg_retries if self.gpgcheck else 1
        last_error = None
        for attempt in range(retries):
            if attempt > 0:
                time.sleep(attempt)
            try:
                result = self._fetch_content()
            except DnfError:
                raise
            except Exception as e:
                last_error = f"Failed to fetch content from {self.url}: {e}"
                continue
            if not self.gpgcheck:
                return self._persist_content(result)
            try:
                signature = self._fetch_signature()
            except DnfError as e:
                last_error = str(e)
                continue
            except Exception as e:
                last_error = f"Failed to fetch GPG signature from {self.asc_url}: {e}"
                continue
            if self.gpg_verifier.verify(result.data, signature):
                logger.debug(f"GPG verification passed for {self.url}")
                return self._persist_content(result)
            last_error = "GPG signature verification failed. The file may have been tampered with."
            if attempt < retries - 1:
                logger.warning(f"GPG verification failed, retrying ({attempt + 1}/{retries})...")

        # All retries exhausted - try stale cache fallback
        stale = self._get_stale_cached_path()
        if stale:
            logger.info("Falling back to previously verified cached copy")
            return stale
        raise DnfError(f"Failed to retrieve {self.url}: {last_error}")

    def _get_cached_path(self) -> Optional[str]:
        """Return a path to the cached file if it is still valid, else None.

        The default implementation returns None (no caching).  Subclasses
        that maintain a local cache override this to short-circuit the
        fetch/verify/persist pipeline when fresh content is already on disk.
        """
        return None

    def _get_stale_cached_path(self) -> Optional[str]:
        """Return the path to any cached file, even if stale/expired.

        Called only when ``_get_cached_path`` raises an exception, to allow
        fallback to a stale copy rather than failing completely.  The default
        implementation returns None (no cache).  Subclasses with a cache
        override this.
        """
        return None

    # ------------------------------------------------------------------
    # Abstract primitives — implemented by each subclass
    # ------------------------------------------------------------------

    @abstractmethod
    def _fetch_content(self) -> FetchResult:
        """Fetch file content and metadata from the source.

        For cached handlers this may return already-cached bytes or trigger
        a download.  For local handlers it reads directly from disk.

        Returns:
            FetchResult with data bytes and optional metadata.

        Raises:
            DnfError: If the file cannot be found or accessed.
        """
        pass

    @abstractmethod
    def _fetch_signature(self) -> bytes:
        """Return the raw bytes of the detached GPG signature (.asc).

        Only called when gpgcheck=True.

        Raises:
            DnfError: If the signature file cannot be found or fetched.
        """
        pass

    @abstractmethod
    def _persist_content(self, result: FetchResult) -> Optional[str]:
        """Persist verified content and return its path.

        For HTTPS handlers this writes to the cache and returns the cache path.
        For local handlers this simply returns the original local path (no
        copy needed).

        Args:
            result: FetchResult containing verified data and metadata.

        Returns:
            Path to the persisted file, or None on error.
        """
        pass

    def clear_cache(self) -> None:
        """Clear cached files for this handler.

        Default implementation does nothing (safe for handlers without caching).
        Handlers with caching override this to clear their cache.
        """
        pass

    @property
    def _gpg_retries(self) -> int:
        """Number of GPG verification retry attempts.

        Returns GPG_VERIFY_RETRIES by default. LocalFileHandler overrides
        to return 1 (no retry) since local files don't change between attempts.
        """
        return GPG_VERIFY_RETRIES

    @classmethod
    def register_handler(cls, scheme: str, handler_class: type["FileHandler"]) -> None:
        """Register a handler class for a specific URL scheme.

        Args:
            scheme: The URL scheme (e.g., 'http', 'https', 'file', etc.)
            handler_class: The FileHandler subclass to handle this scheme
        """
        cls._handlers[scheme] = handler_class
        logger.debug(f"Registered handler {handler_class.__name__} for scheme '{scheme}'")

    @classmethod
    def get_supported_schemes(cls) -> set:
        """Return the set of URL schemes supported by registered handlers.

        Returns:
            Set of scheme strings (e.g. {'https', 'file'})
        """
        return set(cls._handlers.keys())

    @classmethod
    def create(
        cls,
        url: str,
        metadata_expire: int = DEFAULT_CACHE_DURATION_SECONDS,
        request_timeout: int = 30,
        retries: int = 3,
        gpgcheck: bool = False,
        gpgkey: Optional[List[str]] = None,
        cache_dir: Optional[str] = None,
    ) -> "FileHandler":
        """Factory method to create appropriate file handler based on URL scheme.

        Args:
            url: HTTP(S) or file:// URL (variables should already be resolved)
            metadata_expire: Cache validity duration in seconds
            request_timeout: HTTP request timeout in seconds (ignored for file:// URLs)
            retries: Number of retry attempts for transient errors (ignored for file:// URLs)
            gpgcheck: When True, verify downloaded content against a detached GPG
                      signature before caching (HTTPS handlers only). The signature
                      is always fetched from url + ".asc".
            gpgkey: List of GPG key URLs (``file://`` or ``https://``) used when
                    gpgcheck is True. Matches the ``gpgkey`` config option convention.
            cache_dir: Directory for storing cached files. The GPG pubring is stored
                    at ``<cache_dir>/pubring/``.

        Returns:
            FileHandler instance for the appropriate URL scheme

        Raises:
            ValueError: If parameters are invalid or unsupported URL scheme
        """
        # Validate inputs
        if not url or not url.strip():
            raise ValueError("url must not be empty")

        validate_metadata_expire(metadata_expire)

        if request_timeout <= 0:
            raise ValueError("request_timeout must be positive")
        if retries < 0:
            raise ValueError("retries must be non-negative")

        # Determine scheme
        parsed_url = urlparse(url)
        scheme = parsed_url.scheme or "http"

        # Look up handler in registry
        handler_class = cls._handlers.get(scheme)
        if not handler_class:
            raise ValueError(f"Unsupported URL scheme: {scheme}")

        # Build kwargs common to all handlers
        kwargs: Dict = {
            "url": url,
            "metadata_expire": timedelta(seconds=metadata_expire),
            "request_timeout": request_timeout,
            "retries": retries,
            "gpgcheck": gpgcheck,
            "gpgkey": gpgkey or [],
            "cache_dir": cache_dir,
        }

        return handler_class(**kwargs)


class LocalFileHandler(FileHandler):
    """Handler for file:// URLs with optional GPG signature verification.

    Local files are accessed directly (no caching) since they already reside
    on disk.  When ``gpgcheck=True`` the detached signature is read from
    ``<path>.asc`` and verified via the base-class template method before the
    file path is returned.
    """

    def __init__(
        self,
        url: str,
        metadata_expire: timedelta,
        request_timeout: int = 30,
        retries: int = 3,
        gpgcheck: bool = False,
        gpgkey: Optional[List[str]] = None,
        cache_dir: Optional[str] = None,
    ) -> None:
        """Initialize local file handler.

        Args:
            url: file:// URL to access
            metadata_expire: Cache validity duration (not used, for API consistency)
            request_timeout: HTTP request timeout (not used, for API consistency)
            retries: Number of retry attempts (not used, for API consistency)
            gpgcheck: When True, verify the file against a detached GPG signature
                      read from ``<local_path>.asc`` before returning the path.
            gpgkey: List of GPG key URLs used for signature verification.
            cache_dir: Cache directory path (required when gpgcheck is True).
                       The GPG pubring is stored at ``<cache_dir>/pubring/``.
        """
        super().__init__(url, gpgcheck=gpgcheck, gpgkey=gpgkey, cache_dir=cache_dir)

        # Store cache_dir for consistency (local files don't cache but may need pubring)
        if not cache_dir:
            raise ValueError("cache_dir is required")
        self.cache_dir = Path(cache_dir)
        self.metadata_expire = metadata_expire

        # Convert file:// URL to local path
        parsed_url = urlparse(self.url)
        self.source_file_path = Path(unquote(parsed_url.path))
        logger.debug(f"Detected file:// URL, source path: {self.source_file_path}")

    def _fetch_content(self) -> FetchResult:
        """Read and return the local file content.

        Returns:
            FetchResult with file data (metadata is None for local files).

        Raises:
            DnfError: If the file does not exist or cannot be accessed.
        """
        try:
            if not self.source_file_path.exists():
                raise DnfError(f"File not found: {self.url}")
            logger.debug(f"Reading local file: {self.source_file_path}")
            return FetchResult(data=self.source_file_path.read_bytes(), metadata=None)
        except DnfError:
            raise
        except Exception as e:
            raise DnfError(f"Failed to access file: {self.url}") from e

    def _fetch_signature(self) -> bytes:
        """Read the detached GPG signature from ``<source_file_path>.asc``.

        Returns:
            Raw signature bytes.

        Raises:
            DnfError: If the ``.asc`` sidecar file does not exist or cannot be read.
        """
        asc_path = Path(str(self.source_file_path) + ".asc")
        if not asc_path.exists():
            raise DnfError(
                f"GPG signature file not found: {asc_path}. "
                f"Expected alongside {self.source_file_path}"
            )
        return asc_path.read_bytes()

    def _persist_content(self, result: FetchResult) -> Optional[str]:
        """Return the original local file path — no copy needed.

        Args:
            result: FetchResult (not used; file is already on disk).

        Returns:
            Path to the local source file.
        """
        return str(self.source_file_path)

    @property
    def _gpg_retries(self) -> int:
        """Return 1 (no retry) since local files don't change between attempts."""
        return 1


class HttpsFileHandler(FileHandler):
    """Handler for HTTPS URLs with ETag-based caching and optional GPG verification.

    Only HTTPS URLs are supported; plain HTTP is rejected at request time
    to enforce secure transport.  Uses FileCache to handle caching logic.
    """

    def __init__(
        self,
        url: str,
        metadata_expire: timedelta,
        request_timeout: int,
        retries: int,
        gpgcheck: bool = False,
        gpgkey: Optional[List[str]] = None,
        cache_dir: Optional[str] = None,
    ) -> None:
        """Initialize HTTPS file handler with caching.

        Args:
            url: HTTPS URL to cache
            metadata_expire: Cache validity duration
            request_timeout: HTTP request timeout in seconds
            retries: Number of retry attempts for transient errors
            gpgcheck: When True, verify the downloaded file against a detached
                      GPG signature before caching it. The signature is always
                      fetched from url + ".asc".
            gpgkey: List of GPG key URLs used for signature verification.
            cache_dir: Directory for storing cached files.
                       The GPG pubring is stored at ``<cache_dir>/pubring/``.
        """
        super().__init__(url, gpgcheck=gpgcheck, gpgkey=gpgkey, cache_dir=cache_dir)

        if not cache_dir:
            raise ValueError("cache_dir is required")
        self.cache = FileCache(url, metadata_expire, cache_dir=Path(cache_dir))

        # HTTP-specific settings
        self.request_timeout = request_timeout
        self.retries = retries

    @property
    def cache_dir(self) -> Path:
        """Get the cache directory path."""
        return self.cache.cache_dir

    @property
    def metadata_expire(self) -> timedelta:
        """Get the metadata expiration duration."""
        return self.cache.metadata_expire

    # ------------------------------------------------------------------
    # FileHandler abstract primitive implementations
    # ------------------------------------------------------------------

    def _get_cached_path(self) -> Optional[str]:
        """Return the cached file path if the cache is still valid, else None.

        Overrides the base-class no-op so that valid cached files bypass the
        full fetch/verify/persist pipeline in ``get_file_path()``.

        Exceptions from ``_is_cache_valid()`` (e.g. corrupt metadata or
        filesystem errors) propagate to ``get_file_path()`` which logs them as
        "Error in caching logic" and falls back via ``_get_stale_cached_path``.

        Exceptions from the remote HEAD check are caught here and logged as
        "Failed to check source" before falling back to the stale cached file.

        When the cache is stale and the remote ETag check succeeds, the
        cache timestamp is extended.  When the ETag differs, None is returned
        so ``get_file_path`` proceeds to a fresh fetch via ``_fetch_content``.
        """
        if not self.cache.cached_file_path.exists():
            return None

        # _is_cache_valid exceptions intentionally propagate to get_file_path
        if self.cache._is_cache_valid():
            logger.debug("Cache is valid, using cached file")
            return str(self.cache.cached_file_path)

        # Cache exists but is stale — check if the remote content changed.
        # Network / metadata errors are caught here; on failure, fall back to
        # the stale cached file rather than propagating a transient error.
        logger.debug("Cache expired, checking if source has changed")
        try:
            remote_metadata = self._get_metadata()
            cached_metadata = self.cache._load_metadata()
            if self.cache._metadata_matches(cached_metadata, remote_metadata):
                logger.debug("Source unchanged, extending cache timestamp")
                self.cache._update_timestamp()
                return str(self.cache.cached_file_path)
            # Remote content changed — _fetch_content will capture fresh metadata
            return None
        except Exception as e:
            logger.warning(f"Failed to check source: {e}")
            # Fallback to stale cached file rather than failing completely
            if self.cache.cached_file_path.exists():
                logger.info("Using cached file as fallback")
                return str(self.cache.cached_file_path)
            return None

    def _get_stale_cached_path(self) -> Optional[str]:
        """Return the stale cached file path if one exists on disk, else None.

        Called by ``FileHandler.get_file_path`` when ``_get_cached_path``
        raises an unexpected exception (e.g. filesystem error in
        ``_is_cache_valid``).  Allows the handler to serve a stale copy rather
        than failing completely.
        """
        if self.cache.cached_file_path.exists():
            return str(self.cache.cached_file_path)
        return None

    def _fetch_content(self) -> FetchResult:
        """Download the file from the HTTPS URL.

        Returns:
            FetchResult with file data and HTTP metadata from the response.
        """
        logger.debug(f"Downloading file from {self.url}")
        response = self._make_http_request(self.url, method="GET")
        data = response.read()
        metadata = self._extract_metadata(response)
        return FetchResult(data=data, metadata=metadata)

    def _fetch_signature(self) -> bytes:
        """Download the detached GPG signature from ``asc_url``.

        Raises:
            DnfError: If the signature cannot be fetched or exceeds size limit.
        """
        logger.debug(f"Downloading GPG signature from {self.asc_url}")
        try:
            response = self._make_http_request(self.asc_url, method="GET")
            return response.read()
        except DnfError:
            raise
        except Exception as e:
            raise DnfError(f"Unable to retrieve GPG signature from {self.asc_url}: {e}") from e

    def _persist_content(self, result: FetchResult) -> Optional[str]:
        """Write verified bytes to the cache and record metadata.

        Args:
            result: FetchResult containing verified data and metadata.

        Returns:
            Path to the cached file, or None on write error.
        """
        if result.metadata is None:
            raise ValueError("HttpsFileHandler requires metadata in FetchResult")
        tmp_path: Optional[str] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=self.cache.cached_file_path.parent, delete=False, suffix=".tmp"
            ) as tmp_file:
                tmp_file.write(result.data)
                tmp_file.flush()
                os.fsync(tmp_file.fileno())
                tmp_path = tmp_file.name
            os.chmod(tmp_path, 0o600)
            os.replace(tmp_path, self.cache.cached_file_path)
            self.cache._save_metadata(result.metadata)
            return str(self.cache.cached_file_path)
        except Exception as e:
            if tmp_path is not None:
                try:
                    Path(tmp_path).unlink(missing_ok=True)
                except OSError as cleanup_error:
                    logger.debug(f"Failed to clean up temp file: {cleanup_error}")
            try:
                self.cache.cached_file_path.unlink(missing_ok=True)
            except OSError as cleanup_error:
                logger.debug(f"Failed to clean up cached file: {cleanup_error}")
            raise DnfError(f"Failed to persist {self.url} to cache: {e}") from e

    def clear_cache(self) -> None:
        """Clear cached files and metadata via the composed cache object."""
        self.cache.clear()

    def _extract_metadata(self, response: HTTPResponse) -> HttpMetadata:
        """Extract metadata from an HTTP response.

        Args:
            response: HTTP response (from GET or HEAD request).

        Returns:
            Metadata dictionary with ETag, Last-Modified, etc.
        """
        etag = response.headers.get("ETag", "")
        etag = etag.strip('"') if etag else ""
        return {
            "url": self.url,
            "etag": etag,
            "last_modified": response.headers.get("Last-Modified", ""),
            "size": response.headers.get("Content-Length", ""),
            "content_type": response.headers.get("Content-Type", ""),
        }

    def _get_metadata(self) -> HttpMetadata:
        """Get metadata from HTTP URL using HEAD request.

        Returns:
            Metadata dictionary extracted from HTTP headers
        """
        logger.debug(f"Fetching HTTP metadata for {self.url}")
        response = self._make_http_request(self.url, method="HEAD")
        return self._extract_metadata(response)

    def _is_transient_error(self, error: Exception) -> bool:
        """Determine if an error is transient and worth retrying.

        Args:
            error: The exception to evaluate

        Returns:
            True if error is transient and retry should be attempted, False otherwise
        """
        if isinstance(error, HTTPError):
            # Retry on server errors (5xx) and 429 (Too Many Requests)
            return error.code >= 500 or error.code == 429
        if isinstance(error, URLError):
            # Network errors are generally transient
            return True
        return False

    def _make_http_request(self, url: str, method: str = "GET") -> HTTPResponse:
        """Make an HTTP request with retry logic.

        Args:
            url: The URL to request
            method: HTTP method (GET or HEAD)

        Returns:
            Response from the server

        Raises:
            ValueError: If URL scheme is not https
            HTTPError: On HTTP protocol errors (non-transient or after exhausting retries)
            URLError: On network errors (non-transient or after exhausting retries)
        """
        # Validate URL scheme for security (prevents file:// and other schemes)
        parsed_url = urlparse(url)
        if parsed_url.scheme != "https":
            raise ValueError(
                f"Only https scheme is allowed for HTTP requests, got: {parsed_url.scheme}"
            )

        last_exception = None
        attempts = self.retries + 1

        for attempt in range(attempts):
            try:
                request = Request(url, method=method)
                request.add_header("User-Agent", "DNFSupportInfoPlugin/1.0")
                return urlopen(request, timeout=self.request_timeout)
            except Exception as e:
                last_exception = e

                if not self._is_transient_error(e):
                    logger.debug(f"Non-transient error: {e}")
                    raise

                if attempt >= self.retries:
                    logger.debug(f"Max retries ({self.retries}) exhausted: {e}")
                    raise

                logger.debug(
                    f"Transient error on attempt {attempt + 1}/{attempts}: {e}. Retrying..."
                )

        if last_exception:
            raise last_exception
        raise DnfError("Unexpected state in retry logic")


# Register handlers at module level
FileHandler.register_handler("file", LocalFileHandler)
FileHandler.register_handler("https", HttpsFileHandler)
