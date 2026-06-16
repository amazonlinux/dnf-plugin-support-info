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

"""Tests for FileCache class."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from test.conftest import MockDnfError
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

import pytest

from dnf_support_info_plugin.const import DEFAULT_CACHE_DURATION_SECONDS
from dnf_support_info_plugin.file_cache import (
    FetchResult,
    FileHandler,
    HttpsFileHandler,
    LocalFileHandler,
)


@pytest.fixture
def mock_logger():
    """Mock logger."""
    with patch("dnf_support_info_plugin.file_cache.logger") as mock_log:
        yield mock_log


@pytest.fixture
def temp_cache_dir(tmp_path):
    """Temporary cache directory."""
    return str(tmp_path / "cache")


@pytest.fixture
def cached_file_setup(temp_cache_dir):
    """Create a pre-populated cache: cached file + valid metadata JSON.

    Returns a callable ``setup(cache, content, etag, age_seconds)`` that writes
    to the handler's cache paths with *content* and a matching ``.metadata`` file
    whose timestamp is *age_seconds* in the past (default 0 → fresh).

    Usage:
        setup = cached_file_setup
        setup(cache)           # fresh cache, default content & etag
        setup(cache, age_seconds=2)  # expired cache
        # Access paths via handler: cache.cache.cached_file_path
    """

    def setup(
        cache,
        content="<xml>cached</xml>",
        etag="abc123",
        age_seconds=0,
    ):
        cached_file = cache.cache.cached_file_path
        metadata_file = cache.cache.metadata_file_path
        cached_file.parent.mkdir(parents=True, exist_ok=True)
        cached_file.write_text(content)
        timestamp = (datetime.now(timezone.utc) - timedelta(seconds=age_seconds)).isoformat()
        metadata = {
            "timestamp": timestamp,
            "etag": etag,
            "url": cache.url,
        }
        metadata_file.write_text(json.dumps(metadata))

    return setup


def test_init_creates_cache_directory(mock_logger, temp_cache_dir):
    """Test that initialization creates the cache directory."""
    cache = FileHandler.create(
        url="https://example.com/test.xml",
        metadata_expire=600,
        cache_dir=temp_cache_dir,
    )

    assert Path(temp_cache_dir).exists()
    assert cache.url == "https://example.com/test.xml"
    assert cache.cache.cache_filename == "test.xml_43dac9d6"
    assert cache.cache.metadata_expire == timedelta(seconds=600)


def test_get_file_path_exception_fallback_to_cache(mock_logger, temp_cache_dir):
    """Test that exceptions in caching logic fallback to cached file."""
    cache = FileHandler.create(url="https://example.com/test.xml", cache_dir=temp_cache_dir)

    # Create cached file at the handler's expected path
    cached_file = cache.cache.cached_file_path
    cached_file.parent.mkdir(parents=True, exist_ok=True)
    cached_file.write_text("<xml>cached content</xml>")

    # Mock _is_cache_valid to raise an exception after cache file is detected
    with patch.object(cache.cache, "_is_cache_valid", side_effect=Exception("File system error")):
        file_path = cache.get_file_path()

    # Should fallback to cached file path
    assert file_path == str(cached_file)
    mock_logger.warning.assert_called_with("Error in caching logic: File system error")
    mock_logger.info.assert_called_with("Using cached file as fallback")


def test_factory_creates_https_handler_for_https(mock_logger, temp_cache_dir):
    """Test that HTTPS URLs create HttpsFileHandler instances."""
    cache = FileHandler.create(url="https://example.com/test.xml", cache_dir=temp_cache_dir)
    assert isinstance(cache, HttpsFileHandler)


def test_factory_rejects_http_urls(mock_logger, temp_cache_dir):
    """Test that HTTP URLs are rejected (HTTPS only in 2025)."""
    with pytest.raises(ValueError, match="Unsupported URL scheme: http"):
        FileHandler.create(url="http://example.com/test.xml", cache_dir=temp_cache_dir)


def test_factory_creates_file_handler_for_file_urls(mock_logger, temp_cache_dir):
    """Test that file:// URLs create LocalFileHandler instances."""
    cache = FileHandler.create(url="file:///path/to/test.xml", cache_dir=temp_cache_dir)
    assert isinstance(cache, LocalFileHandler)


def test_factory_rejects_urls_without_scheme(mock_logger, temp_cache_dir):
    """Test that URLs without scheme are rejected (defaults to http which is unsupported)."""
    with pytest.raises(ValueError, match="Unsupported URL scheme: http"):
        FileHandler.create(url="example.com/test.xml", cache_dir=temp_cache_dir)


def test_factory_raises_error_for_unsupported_scheme(mock_logger, temp_cache_dir):
    """Test that unsupported URL schemes raise ValueError."""
    with pytest.raises(ValueError, match="Unsupported URL scheme: ftp"):
        FileHandler.create(url="ftp://example.com/test.xml", cache_dir=temp_cache_dir)


def test_https_handler_rejects_non_https_schemes(mock_logger, temp_cache_dir):
    """Test that HttpsFileHandler._make_http_request rejects non-https URLs."""
    # Create an HttpsFileHandler with a file:// URL (shouldn't normally happen, but we're testing defense)
    handler = HttpsFileHandler(
        url="file:///etc/test.xml",
        metadata_expire=timedelta(seconds=600),
        request_timeout=30,
        retries=0,
        cache_dir=temp_cache_dir,
    )

    # Attempt to make HTTP request should raise ValueError due to scheme validation
    with pytest.raises(
        ValueError, match="Only https scheme is allowed for HTTP requests, got: file"
    ):
        handler._make_http_request("file:///etc/test.xml", method="GET")

    # Test with another invalid scheme
    handler_ftp = HttpsFileHandler(
        url="ftp://example.com/test.xml",
        metadata_expire=timedelta(seconds=600),
        request_timeout=30,
        retries=0,
        cache_dir=temp_cache_dir,
    )

    with pytest.raises(
        ValueError, match="Only https scheme is allowed for HTTP requests, got: ftp"
    ):
        handler_ftp._make_http_request("ftp://example.com/test.xml", method="GET")

    # Test that HTTP (non-TLS) is also rejected
    handler_http = HttpsFileHandler(
        url="http://example.com/test.xml",
        metadata_expire=timedelta(seconds=600),
        request_timeout=30,
        retries=0,
        cache_dir=temp_cache_dir,
    )

    with pytest.raises(
        ValueError, match="Only https scheme is allowed for HTTP requests, got: http"
    ):
        handler_http._make_http_request("http://example.com/test.xml", method="GET")

    # Verify that only HTTPS scheme is accepted (should not raise on scheme check)
    # We'll use a mock to prevent actual network calls
    with patch("dnf_support_info_plugin.file_cache.urlopen") as mock_urlopen:
        mock_response = Mock()
        mock_urlopen.return_value = mock_response

        handler_https = HttpsFileHandler(
            url="https://example.com/test.xml",
            metadata_expire=timedelta(seconds=600),
            request_timeout=30,
            retries=0,
            cache_dir=temp_cache_dir,
        )

        # Should not raise ValueError for https scheme
        result = handler_https._make_http_request("https://example.com/test.xml", method="GET")
        assert result == mock_response


@patch("pathlib.Path.mkdir")
def test_init_use_default_values(mock_mkdir, mock_logger, temp_cache_dir):
    """Test that initialization uses default values."""
    cache = FileHandler.create(url="https://example.com/test.xml", cache_dir=temp_cache_dir)

    # Verify it tried to create the default cache directory
    mock_mkdir.assert_called_once_with(parents=True, exist_ok=True, mode=0o700)
    assert cache.cache.cache_dir == Path(temp_cache_dir)
    assert cache.url == "https://example.com/test.xml"
    assert cache.cache.cache_filename == "test.xml_43dac9d6"
    assert cache.cache.metadata_expire == timedelta(seconds=DEFAULT_CACHE_DURATION_SECONDS)


def test_download_file_on_first_access(mock_logger, temp_cache_dir):
    """Test that file is downloaded on first access."""
    with patch("dnf_support_info_plugin.file_cache.urlopen") as mock_urlopen:
        # Mock GET request for file download (metadata extracted from GET response)
        mock_get_response = Mock()
        mock_get_response.read.return_value = b"<xml>content</xml>"
        mock_get_response.headers = {
            "ETag": '"abc123"',
            "Last-Modified": "Mon, 01 Jan 2024 00:00:00 GMT",
            "Content-Length": "1024",
            "Content-Type": "application/xml",
        }

        mock_urlopen.return_value = mock_get_response

        cache = FileHandler.create(url="https://example.com/test.xml", cache_dir=temp_cache_dir)
        file_path = cache.get_file_path()

        assert file_path is not None
        assert Path(file_path).exists()
        assert Path(file_path).read_text() == "<xml>content</xml>"
        assert mock_urlopen.call_count == 1  # GET only (metadata from GET response)


def test_cache_reuse_within_duration(mock_logger, temp_cache_dir, cached_file_setup):
    """Test that cached file is reused if valid (within cache duration) without HTTP check."""
    setup = cached_file_setup
    with patch("dnf_support_info_plugin.file_cache.urlopen") as mock_urlopen:
        cache = FileHandler.create(
            url="https://example.com/test.xml",
            metadata_expire=7200,
            cache_dir=temp_cache_dir,
        )
        setup(cache)  # fresh cache (age_seconds=0, within 7200s expiry)

        file_path = cache.get_file_path()

        assert Path(file_path).read_text() == "<xml>cached</xml>"
        # With valid cache, should NOT make any HTTP calls (optimization)
        mock_urlopen.assert_not_called()


def test_cache_update_on_etag_change(mock_logger, temp_cache_dir, cached_file_setup):
    """Test that file is re-downloaded when ETag changes and cache expired."""
    setup = cached_file_setup
    with patch("dnf_support_info_plugin.file_cache.urlopen") as mock_urlopen:
        cache = FileHandler.create(
            url="https://example.com/test.xml",
            metadata_expire=1,
            cache_dir=temp_cache_dir,
        )
        setup(cache, content="<xml>old</xml>", etag="old123", age_seconds=2)

        # Mock HEAD to return different ETag (triggers re-download)
        mock_head_response = Mock()
        mock_head_response.headers = {
            "ETag": '"new456"',
            "Last-Modified": "Mon, 01 Jan 2024 00:00:00 GMT",
            "Content-Length": "1024",
        }

        # Mock GET with metadata in response
        mock_get_response = Mock()
        mock_get_response.read.return_value = b"<xml>new</xml>"
        mock_get_response.headers = {
            "ETag": '"new456"',
            "Last-Modified": "Mon, 01 Jan 2024 00:00:00 GMT",
            "Content-Length": "1024",
        }

        mock_urlopen.side_effect = [mock_head_response, mock_get_response]

        file_path = cache.get_file_path()

        assert Path(file_path).read_text() == "<xml>new</xml>"
        assert mock_urlopen.call_count == 2  # HEAD + GET


def test_expired_cache_triggers_download(mock_logger, temp_cache_dir, cached_file_setup):
    """Test that expired cache with changed ETag triggers re-download."""
    setup = cached_file_setup
    with patch("dnf_support_info_plugin.file_cache.urlopen") as mock_urlopen:
        cache = FileHandler.create(
            url="https://example.com/test.xml",
            metadata_expire=7200,
            cache_dir=temp_cache_dir,
        )
        # 3 hours old — well past the 7200s expiry
        setup(cache, content="<xml>old</xml>", age_seconds=10800)

        # Mock HTTP responses with DIFFERENT ETag (file changed)
        mock_head_response = Mock()
        mock_head_response.headers = {
            "ETag": '"xyz789"',
            "Last-Modified": "Mon, 01 Jan 2024 00:00:00 GMT",
            "Content-Length": "1024",
        }

        # Mock GET with metadata in response
        mock_get_response = Mock()
        mock_get_response.read.return_value = b"<xml>new</xml>"
        mock_get_response.headers = {
            "ETag": '"xyz789"',
            "Last-Modified": "Mon, 01 Jan 2024 00:00:00 GMT",
            "Content-Length": "1024",
        }

        mock_urlopen.side_effect = [mock_head_response, mock_get_response]

        file_path = cache.get_file_path()

        assert Path(file_path).read_text() == "<xml>new</xml>"
        assert mock_urlopen.call_count == 2  # HEAD + GET


def test_expired_cache_extends_on_matching_etag(mock_logger, temp_cache_dir, cached_file_setup):
    """Test that expired cache with matching ETag extends cache without downloading."""
    setup = cached_file_setup
    with patch("dnf_support_info_plugin.file_cache.urlopen") as mock_urlopen:
        cache = FileHandler.create(
            url="https://example.com/test.xml",
            metadata_expire=7200,
            cache_dir=temp_cache_dir,
        )
        # 3 hours old — expired; ETag stays at default "abc123"
        setup(cache, content="<xml>old</xml>", age_seconds=10800)

        # Mock HTTP responses with SAME ETag (file unchanged)
        mock_head_response = Mock()
        mock_head_response.headers = {
            "ETag": '"abc123"',
            "Last-Modified": "Mon, 01 Jan 2024 00:00:00 GMT",
            "Content-Length": "1024",
        }

        mock_urlopen.return_value = mock_head_response

        file_path = cache.get_file_path()

        # Should use cached file without downloading
        assert Path(file_path).read_text() == "<xml>old</xml>"
        assert mock_urlopen.call_count == 1  # Only HEAD, no GET

        # Verify metadata timestamp was updated
        updated_metadata = json.loads(cache.cache.metadata_file_path.read_text())
        updated_time = datetime.fromisoformat(updated_metadata["timestamp"])
        assert (datetime.now(timezone.utc) - updated_time).total_seconds() < 5


def test_fallback_to_cache_on_http_error(mock_logger, temp_cache_dir, cached_file_setup):
    """Test that cached file is used when HTTP is unavailable."""
    setup = cached_file_setup
    with patch("dnf_support_info_plugin.file_cache.urlopen") as mock_urlopen:
        cache = FileHandler.create(
            url="https://example.com/test.xml",
            metadata_expire=1,  # Short expiration to trigger check
            cache_dir=temp_cache_dir,
        )
        setup(cache, age_seconds=2)  # expired cache

        mock_urlopen.side_effect = URLError("Network unavailable")

        file_path = cache.get_file_path()

        # Should fall back to cached file
        assert Path(file_path).read_text() == "<xml>cached</xml>"


def test_clear_cache(mock_logger, temp_cache_dir, cached_file_setup):
    """Test that clear_cache removes cached file and metadata."""
    setup = cached_file_setup
    cache = FileHandler.create(url="https://example.com/test.xml", cache_dir=temp_cache_dir)
    setup(cache)  # creates cached file and metadata

    assert cache.cache.cached_file_path.exists()
    assert cache.cache.metadata_file_path.exists()

    cache.clear_cache()

    assert not cache.cache.cached_file_path.exists()
    assert not cache.cache.metadata_file_path.exists()


def test_infinite_cache_metadata_expire(mock_logger, temp_cache_dir):
    """Test that metadata_expire = -1 for infinite cache is accepted."""
    cache = FileHandler.create(
        url="https://example.com/test.xml",
        metadata_expire=-1,
        cache_dir=temp_cache_dir,
    )
    assert cache.metadata_expire.total_seconds() == -1


def test_less_than_negative_one_metadata_expire_raises_error(mock_logger, temp_cache_dir):
    """Test that metadata_expire < -1 raises ValueError."""
    with pytest.raises(
        ValueError, match="metadata_expire must be -1 \\(infinite\\) or non-negative"
    ):
        FileHandler.create(
            url="https://example.com/test.xml",
            metadata_expire=-5,
            cache_dir=temp_cache_dir,
        )


def test_exceeds_maximum_metadata_expire_raises_error(mock_logger, temp_cache_dir):
    """Test that metadata_expire > MAX_ABSOLUTE_CACHE_DURATION_SECONDS raises ValueError."""
    with pytest.raises(ValueError, match="exceeds maximum"):
        FileHandler.create(
            url="https://example.com/test.xml",
            metadata_expire=999999999999,
            cache_dir=temp_cache_dir,
        )


def test_infinite_cache_never_expires(mock_logger, temp_cache_dir, cached_file_setup):
    """Test that metadata_expire = -1 means cache never expires."""
    setup = cached_file_setup
    with patch("dnf_support_info_plugin.file_cache.urlopen") as mock_urlopen:
        cache = FileHandler.create(
            url="https://example.com/test.xml",
            metadata_expire=-1,  # Infinite cache
            cache_dir=temp_cache_dir,
        )
        # 10 years old — but with infinite cache it should never expire
        setup(cache, age_seconds=3650 * 24 * 3600)

        file_path = cache.get_file_path()

        # Should use cached file even though it's very old (infinite cache)
        assert Path(file_path).read_text() == "<xml>cached</xml>"
        # Should NOT make any HTTP calls since cache never expires
        mock_urlopen.assert_not_called()


def test_zero_metadata_expire_always_checks(mock_logger, temp_cache_dir, cached_file_setup):
    """Test that metadata_expire = 0 always checks for updates."""
    setup = cached_file_setup
    with patch("dnf_support_info_plugin.file_cache.urlopen") as mock_urlopen:
        cache = FileHandler.create(
            url="https://example.com/test.xml",
            metadata_expire=0,  # Always check
            cache_dir=temp_cache_dir,
        )
        # Fresh cache (1 second old) — but metadata_expire=0 means always check anyway
        setup(cache, age_seconds=1)

        # Mock HTTP to return same ETag (file unchanged)
        mock_head_response = Mock()
        mock_head_response.headers = {
            "ETag": '"abc123"',
        }
        mock_urlopen.return_value = mock_head_response

        file_path = cache.get_file_path()

        # Should use cached file (ETag matches)
        assert Path(file_path).read_text() == "<xml>cached</xml>"
        # But SHOULD make HTTP HEAD call to check (metadata_expire=0)
        mock_urlopen.assert_called_once()


def test_large_valid_metadata_expire_accepted(mock_logger, temp_cache_dir):
    """Test that large valid metadata_expire values are accepted."""
    # Test 1 hour (3600 seconds)
    cache_1h = FileHandler.create(
        url="https://example.com/test.xml",
        metadata_expire=3600,
        cache_dir=temp_cache_dir,
    )
    assert cache_1h.metadata_expire.total_seconds() == 3600

    # Test 1 day (86400 seconds)
    cache_1d = FileHandler.create(
        url="https://example.com/test.xml",
        metadata_expire=86400,
        cache_dir=temp_cache_dir,
    )
    assert cache_1d.metadata_expire.total_seconds() == 86400

    # Test 1 week (604800 seconds)
    cache_1w = FileHandler.create(
        url="https://example.com/test.xml",
        metadata_expire=604800,
        cache_dir=temp_cache_dir,
    )
    assert cache_1w.metadata_expire.total_seconds() == 604800


def test_maximum_valid_metadata_expire_accepted(mock_logger, temp_cache_dir):
    """Test that maximum valid metadata_expire (90 days) is accepted."""
    cache = FileHandler.create(
        url="https://example.com/test.xml",
        metadata_expire=7776000,  # Exactly 90 days
        cache_dir=temp_cache_dir,
    )
    assert cache.metadata_expire.total_seconds() == 7776000


def test_negative_retries_raises_error(mock_logger, temp_cache_dir):
    """Test that negative retries raises ValueError."""
    with pytest.raises(ValueError, match="retries must be non-negative"):
        FileHandler.create(
            url="https://example.com/test.xml",
            retries=-1,
            cache_dir=temp_cache_dir,
        )


def test_zero_request_timeout_raises_error(mock_logger, temp_cache_dir):
    """Test that zero request_timeout raises ValueError."""
    with pytest.raises(ValueError, match="request_timeout must be positive"):
        FileHandler.create(
            url="https://example.com/test.xml",
            request_timeout=0,
            cache_dir=temp_cache_dir,
        )


def test_negative_request_timeout_raises_error(mock_logger, temp_cache_dir):
    """Test that negative request_timeout raises ValueError."""
    with pytest.raises(ValueError, match="request_timeout must be positive"):
        FileHandler.create(
            url="https://example.com/test.xml",
            request_timeout=-10,
            cache_dir=temp_cache_dir,
        )


def test_empty_url_string_raises_error(mock_logger, temp_cache_dir):
    """Test initialization with empty URL string raises ValueError."""
    with pytest.raises(ValueError, match="url must not be empty"):
        FileHandler.create(url="", cache_dir=temp_cache_dir)


def test_whitespace_only_url_raises_error(mock_logger, temp_cache_dir):
    """Test initialization with whitespace-only URL raises ValueError."""
    with pytest.raises(ValueError, match="url must not be empty"):
        FileHandler.create(url="   ", cache_dir=temp_cache_dir)


def test_url_with_query_parameters(mock_logger, temp_cache_dir):
    """Test URL with query parameters extracts correct filename."""
    cache = FileHandler.create(
        url="https://example.com/test.xml?version=1.0&format=xml", cache_dir=temp_cache_dir
    )
    assert cache.cache.cache_filename == "test.xml_4ee3fc05"


def test_url_with_trailing_slash_generates_hash_filename(mock_logger, temp_cache_dir):
    """Test that URL ending with slash generates a hash-based filename."""
    cache = FileHandler.create(url="https://example.com/path/", cache_dir=temp_cache_dir)

    # Should generate a hash-based filename since basename is empty
    assert cache.cache.cache_filename.startswith("cached_")
    assert len(cache.cache.cache_filename) == len("cached_") + 8  # cached_ + 8 char hash

    # Verify it's deterministic - same URL should produce same filename
    cache2 = FileHandler.create(url="https://example.com/path/", cache_dir=temp_cache_dir)
    assert cache.cache.cache_filename == cache2.cache.cache_filename


def test_url_with_no_path_generates_hash_filename(mock_logger, temp_cache_dir):
    """Test that URL with no path generates a hash-based filename."""
    cache = FileHandler.create(url="https://example.com", cache_dir=temp_cache_dir)

    # Should generate a hash-based filename since there's no path
    assert cache.cache.cache_filename.startswith("cached_")
    assert len(cache.cache.cache_filename) == len("cached_") + 8  # cached_ + 8 char hash

    # Different URLs should produce different filenames
    cache2 = FileHandler.create(url="https://different.com", cache_dir=temp_cache_dir)
    assert cache.cache.cache_filename != cache2.cache.cache_filename


def test_url_with_only_domain_and_slash_generates_hash_filename(mock_logger, temp_cache_dir):
    """Test that URL with only domain and trailing slash generates hash-based filename."""
    cache = FileHandler.create(url="https://example.com/", cache_dir=temp_cache_dir)

    # Should generate a hash-based filename
    assert cache.cache.cache_filename.startswith("cached_")
    assert len(cache.cache.cache_filename) == len("cached_") + 8  # cached_ + 8 char hash


def test_hash_filename_collision_resistance(mock_logger, temp_cache_dir):
    """Test that similar URLs produce different hash-based filenames."""
    cache1 = FileHandler.create(url="https://example.com/", cache_dir=temp_cache_dir)
    cache2 = FileHandler.create(url="https://example.com/path/", cache_dir=temp_cache_dir)
    cache3 = FileHandler.create(url="https://other.com/", cache_dir=temp_cache_dir)

    # All should have hash-based filenames
    assert cache1.cache.cache_filename.startswith("cached_")
    assert cache2.cache.cache_filename.startswith("cached_")
    assert cache3.cache.cache_filename.startswith("cached_")

    # All should be different (collision resistance)
    assert cache1.cache.cache_filename != cache2.cache.cache_filename
    assert cache1.cache.cache_filename != cache3.cache.cache_filename
    assert cache2.cache.cache_filename != cache3.cache.cache_filename


def test_retry_on_500_error(mock_logger, temp_cache_dir):
    """Test that 5xx errors trigger retries and raise DnfError."""
    with patch("dnf_support_info_plugin.file_cache.urlopen") as mock_urlopen:
        # Simulate 500 error on all attempts
        mock_urlopen.side_effect = HTTPError(
            "https://example.com/test.xml", 500, "Internal Server Error", {}, None
        )

        cache = FileHandler.create(
            url="https://example.com/test.xml", retries=2, cache_dir=temp_cache_dir
        )

        # Should raise DnfError after exhausting retries
        with pytest.raises(MockDnfError):
            cache.get_file_path()

        # Should have tried: initial + 2 retries = 3 attempts
        assert mock_urlopen.call_count == 3


def test_retry_on_503_error(mock_logger, temp_cache_dir):
    """Test that 503 Service Unavailable triggers retries and raises DnfError."""
    with patch("dnf_support_info_plugin.file_cache.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = HTTPError(
            "https://example.com/test.xml", 503, "Service Unavailable", {}, None
        )

        cache = FileHandler.create(
            url="https://example.com/test.xml", retries=1, cache_dir=temp_cache_dir
        )

        # Should raise DnfError after exhausting retries
        with pytest.raises(MockDnfError):
            cache.get_file_path()

        assert mock_urlopen.call_count == 2


def test_no_retry_on_404_error(mock_logger, temp_cache_dir):
    """Test that 404 errors do NOT trigger retries and raise DnfError."""
    with patch("dnf_support_info_plugin.file_cache.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = HTTPError(
            "https://example.com/test.xml", 404, "Not Found", {}, None
        )

        cache = FileHandler.create(
            url="https://example.com/test.xml", retries=3, cache_dir=temp_cache_dir
        )

        # Should raise DnfError without retrying
        with pytest.raises(MockDnfError):
            cache.get_file_path()

        # Should NOT retry on 4xx errors - only 1 attempt
        assert mock_urlopen.call_count == 1


def test_no_retry_on_403_error(mock_logger, temp_cache_dir):
    """Test that 403 Forbidden does NOT trigger retries and raises DnfError."""
    with patch("dnf_support_info_plugin.file_cache.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = HTTPError(
            "https://example.com/test.xml", 403, "Forbidden", {}, None
        )

        cache = FileHandler.create(
            url="https://example.com/test.xml", retries=3, cache_dir=temp_cache_dir
        )

        # Should raise DnfError without retrying
        with pytest.raises(MockDnfError):
            cache.get_file_path()

        # Should NOT retry on 4xx errors - only 1 attempt
        assert mock_urlopen.call_count == 1


def test_retry_success_on_second_attempt(mock_logger, temp_cache_dir):
    """Test that retry succeeds on second attempt after transient error."""
    with patch("dnf_support_info_plugin.file_cache.urlopen") as mock_urlopen:
        # First call fails with 500, second succeeds
        mock_get_response = Mock()
        mock_get_response.read.return_value = b"<xml>content</xml>"
        mock_get_response.headers = {
            "ETag": '"abc123"',
            "Content-Length": "1024",
        }

        mock_urlopen.side_effect = [
            HTTPError("https://example.com/test.xml", 500, "Error", {}, None),
            mock_get_response,
        ]

        cache = FileHandler.create(
            url="https://example.com/test.xml", retries=2, cache_dir=temp_cache_dir
        )
        result = cache.get_file_path()

        assert result is not None
        assert Path(result).read_text() == "<xml>content</xml>"
        # First attempt failed, second succeeded (GET only)
        assert mock_urlopen.call_count == 2


def test_urllerror_triggers_retry(mock_logger, temp_cache_dir):
    """Test that URLError (network errors) trigger retries and raise DnfError."""
    with patch("dnf_support_info_plugin.file_cache.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = URLError("Network unreachable")

        cache = FileHandler.create(
            url="https://example.com/test.xml", retries=2, cache_dir=temp_cache_dir
        )

        # Should raise DnfError after exhausting retries
        with pytest.raises(MockDnfError):
            cache.get_file_path()

        # Should retry URLError: initial + 2 retries = 3
        assert mock_urlopen.call_count == 3


def test_zero_retries_no_retry_attempts(mock_logger, temp_cache_dir):
    """Test that retries=0 means no retry attempts and raises DnfError."""
    with patch("dnf_support_info_plugin.file_cache.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = HTTPError("https://example.com/test.xml", 500, "Error", {}, None)

        cache = FileHandler.create(
            url="https://example.com/test.xml", retries=0, cache_dir=temp_cache_dir
        )

        # Should raise DnfError without retrying
        with pytest.raises(MockDnfError):
            cache.get_file_path()

        # Only 1 attempt, no retries
        assert mock_urlopen.call_count == 1


def test_corrupted_metadata_json(mock_logger, temp_cache_dir):
    """Test handling of corrupted metadata JSON."""
    with patch("dnf_support_info_plugin.file_cache.urlopen") as mock_urlopen:
        cache = FileHandler.create(
            url="https://example.com/test.xml",
            metadata_expire=7200,
            cache_dir=temp_cache_dir,
        )

        # Create cached file at handler's expected path
        cached_file = cache.cache.cached_file_path
        cached_file.parent.mkdir(parents=True, exist_ok=True)
        cached_file.write_text("<xml>cached</xml>")

        # Create corrupted metadata
        metadata_file = cache.cache.metadata_file_path
        metadata_file.write_text("{ invalid json ]")

        # Mock HEAD for cache check, GET with metadata for download
        mock_head_response = Mock()
        mock_head_response.headers = {"ETag": '"new123"'}

        mock_get_response = Mock()
        mock_get_response.read.return_value = b"<xml>new</xml>"
        mock_get_response.headers = {"ETag": '"new123"'}

        mock_urlopen.side_effect = [mock_head_response, mock_get_response]

        # Should handle corrupted metadata and download fresh
        result = cache.get_file_path()
        assert result is not None
        assert Path(result).read_text() == "<xml>new</xml>"


def test_missing_metadata_with_cache_file(mock_logger, temp_cache_dir):
    """Test cache file exists but metadata is missing."""
    with patch("dnf_support_info_plugin.file_cache.urlopen") as mock_urlopen:
        cache = FileHandler.create(url="https://example.com/test.xml", cache_dir=temp_cache_dir)

        # Create cached file without metadata at handler's expected path
        cached_file = cache.cache.cached_file_path
        cached_file.parent.mkdir(parents=True, exist_ok=True)
        cached_file.write_text("<xml>cached</xml>")

        # Mock HEAD for cache check, GET with metadata for download
        mock_head_response = Mock()
        mock_head_response.headers = {"ETag": '"abc123"'}

        mock_get_response = Mock()
        mock_get_response.read.return_value = b"<xml>new</xml>"
        mock_get_response.headers = {"ETag": '"abc123"'}

        mock_urlopen.side_effect = [mock_head_response, mock_get_response]

        result = cache.get_file_path()
        # Should download fresh since metadata is missing
        assert result is not None
        assert Path(result).read_text() == "<xml>new</xml>"


def test_metadata_missing_timestamp_field(mock_logger, temp_cache_dir):
    """Test metadata without timestamp field."""
    with patch("dnf_support_info_plugin.file_cache.urlopen") as mock_urlopen:
        cache = FileHandler.create(url="https://example.com/test.xml", cache_dir=temp_cache_dir)

        # Create cached file at handler's expected path
        cached_file = cache.cache.cached_file_path
        cached_file.parent.mkdir(parents=True, exist_ok=True)
        cached_file.write_text("<xml>cached</xml>")

        # Metadata missing timestamp
        metadata_file = cache.cache.metadata_file_path
        metadata = {"etag": "abc123"}
        metadata_file.write_text(json.dumps(metadata))

        # Mock HTTP responses: HEAD (check), GET with metadata (download)
        mock_head_response = Mock()
        mock_head_response.headers = {"ETag": '"new123"'}

        mock_get_response = Mock()
        mock_get_response.read.return_value = b"<xml>new</xml>"
        mock_get_response.headers = {"ETag": '"new123"'}

        mock_urlopen.side_effect = [mock_head_response, mock_get_response]

        result = cache.get_file_path()
        # Should treat as invalid and download
        assert result is not None


def test_empty_cache_file(mock_logger, temp_cache_dir):
    """Test handling of empty cache file."""
    with patch("dnf_support_info_plugin.file_cache.urlopen") as mock_urlopen:
        cache = FileHandler.create(url="https://example.com/test.xml", cache_dir=temp_cache_dir)

        # Create empty cache file at handler's expected path
        cached_file = cache.cache.cached_file_path
        cached_file.parent.mkdir(parents=True, exist_ok=True)
        cached_file.write_text("")

        # Mock HTTP responses: HEAD (check), GET with metadata (download)
        mock_head_response = Mock()
        mock_head_response.headers = {"ETag": '"abc123"'}

        mock_get_response = Mock()
        mock_get_response.read.return_value = b"<xml>content</xml>"
        mock_get_response.headers = {"ETag": '"abc123"'}

        mock_urlopen.side_effect = [mock_head_response, mock_get_response]

        result = cache.get_file_path()
        assert result is not None
        assert Path(result).read_text() == "<xml>content</xml>"


def test_missing_etag_header(mock_logger, temp_cache_dir):
    """Test handling when ETag header is missing."""
    with patch("dnf_support_info_plugin.file_cache.urlopen") as mock_urlopen:
        # Mock GET response without ETag (metadata extracted from GET)
        mock_get_response = Mock()
        mock_get_response.read.return_value = b"<xml>content</xml>"
        mock_get_response.headers = {
            "Content-Length": "1024",
        }

        mock_urlopen.return_value = mock_get_response

        cache = FileHandler.create(url="https://example.com/test.xml", cache_dir=temp_cache_dir)
        result = cache.get_file_path()

        # Should still work, just with empty ETag
        assert result is not None
        metadata = json.loads(cache.cache.metadata_file_path.read_text())
        assert metadata["etag"] == ""


def test_empty_etag_header(mock_logger, temp_cache_dir):
    """Test handling of empty ETag header value."""
    with patch("dnf_support_info_plugin.file_cache.urlopen") as mock_urlopen:
        # Mock GET response with empty ETag (metadata extracted from GET)
        mock_get_response = Mock()
        mock_get_response.read.return_value = b"<xml>content</xml>"
        mock_get_response.headers = {
            "ETag": "",
            "Content-Length": "1024",
        }

        mock_urlopen.return_value = mock_get_response

        cache = FileHandler.create(url="https://example.com/test.xml", cache_dir=temp_cache_dir)
        result = cache.get_file_path()

        assert result is not None
        metadata = json.loads(cache.cache.metadata_file_path.read_text())
        assert metadata["etag"] == ""


def test_etag_with_quotes_stripped(mock_logger, temp_cache_dir):
    """Test that ETag quotes are properly stripped."""
    with patch("dnf_support_info_plugin.file_cache.urlopen") as mock_urlopen:
        # Mock GET response with quoted ETag (metadata extracted from GET)
        mock_get_response = Mock()
        mock_get_response.read.return_value = b"<xml>content</xml>"
        mock_get_response.headers = {
            "ETag": '"abc123def"',
        }

        mock_urlopen.return_value = mock_get_response

        cache = FileHandler.create(url="https://example.com/test.xml", cache_dir=temp_cache_dir)
        result = cache.get_file_path()

        assert result is not None
        metadata = json.loads(cache.cache.metadata_file_path.read_text())
        # Quotes should be stripped
        assert metadata["etag"] == "abc123def"


def test_missing_content_length_header(mock_logger, temp_cache_dir):
    """Test handling when Content-Length header is missing."""
    with patch("dnf_support_info_plugin.file_cache.urlopen") as mock_urlopen:
        # Mock GET response without Content-Length (metadata extracted from GET)
        mock_get_response = Mock()
        mock_get_response.read.return_value = b"<xml>content</xml>"
        mock_get_response.headers = {
            "ETag": '"abc123"',
        }

        mock_urlopen.return_value = mock_get_response

        cache = FileHandler.create(url="https://example.com/test.xml", cache_dir=temp_cache_dir)
        result = cache.get_file_path()

        # Should still work
        assert result is not None
        metadata = json.loads(cache.cache.metadata_file_path.read_text())
        assert metadata["size"] == ""


def test_all_headers_missing(mock_logger, temp_cache_dir):
    """Test handling when all optional headers are missing."""
    with patch("dnf_support_info_plugin.file_cache.urlopen") as mock_urlopen:
        # Mock GET response with no headers (metadata extracted from GET)
        mock_get_response = Mock()
        mock_get_response.read.return_value = b"<xml>content</xml>"
        mock_get_response.headers = {}

        mock_urlopen.return_value = mock_get_response

        cache = FileHandler.create(url="https://example.com/test.xml", cache_dir=temp_cache_dir)
        result = cache.get_file_path()

        # Should work with empty metadata
        assert result is not None
        metadata = json.loads(cache.cache.metadata_file_path.read_text())
        assert metadata["etag"] == ""
        assert metadata["last_modified"] == ""
        assert metadata["size"] == ""


def test_etag_case_insensitive_comparison(mock_logger, temp_cache_dir, cached_file_setup):
    """Test that ETag comparison is case-insensitive."""
    setup = cached_file_setup
    with patch("dnf_support_info_plugin.file_cache.urlopen") as mock_urlopen:
        cache = FileHandler.create(
            url="https://example.com/test.xml",
            metadata_expire=1,  # Short expiration
            cache_dir=temp_cache_dir,
        )
        # Expired cache with lowercase etag "abc123"
        setup(cache, age_seconds=2)

        # Mock HTTP to return uppercase ETag (should still match)
        mock_head_response = Mock()
        mock_head_response.headers = {
            "ETag": '"ABC123"',  # uppercase — must match case-insensitively
        }

        mock_urlopen.return_value = mock_head_response

        file_path = cache.get_file_path()

        # Should use cached file (ETags match case-insensitively)
        assert Path(file_path).read_text() == "<xml>cached</xml>"
        assert mock_urlopen.call_count == 1  # Only HEAD, no GET


# Tests for file:// URL support


def test_file_url_first_access(mock_logger, temp_cache_dir, tmp_path):
    """Test that local file is accessed directly without caching."""
    # Create a source file
    source_file = tmp_path / "source" / "test.xml"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text("<xml>source content</xml>")

    cache = FileHandler.create(
        url=f"file://{source_file}",
        cache_dir=temp_cache_dir,
    )

    file_path = cache.get_file_path()

    assert file_path is not None
    assert Path(file_path).exists()
    assert Path(file_path).read_text() == "<xml>source content</xml>"

    # Verify it returns the source path directly (not a cache path)
    assert file_path == str(source_file)

    # Verify NO cache files were created (local files don't cache)
    # Check that no files starting with "test.xml" exist in cache dir
    cache_dir = Path(temp_cache_dir)
    if cache_dir.exists():
        cache_files = list(cache_dir.glob("test.xml*"))
        assert len(cache_files) == 0, f"Unexpected cache files: {cache_files}"


def test_file_url_always_returns_source(mock_logger, temp_cache_dir, tmp_path):
    """Test that local files always return source path, ignoring any existing cache."""
    # Create a source file
    source_file = tmp_path / "source" / "test.xml"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text("<xml>source content</xml>")

    cache = FileHandler.create(
        url=f"file://{source_file}",
        metadata_expire=7200,  # 2 hours (ignored for local files)
        cache_dir=temp_cache_dir,
    )

    file_path = cache.get_file_path()

    # Should always use source file directly
    assert file_path == str(source_file)
    assert Path(file_path).read_text() == "<xml>source content</xml>"


def test_file_url_source_file_changes_reflected(mock_logger, temp_cache_dir, tmp_path):
    """Test that local file changes are immediately reflected (no caching)."""
    # Create a source file
    source_file = tmp_path / "source" / "test.xml"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text("<xml>original content</xml>")

    cache = FileHandler.create(
        url=f"file://{source_file}",
        metadata_expire=1,  # 1 second (ignored for local files)
        cache_dir=temp_cache_dir,
    )

    # First access
    file_path = cache.get_file_path()
    assert Path(file_path).read_text() == "<xml>original content</xml>"

    # Update source file immediately
    source_file.write_text("<xml>updated content</xml>")

    # Second access should reflect the change immediately (no caching)
    file_path = cache.get_file_path()
    assert Path(file_path).read_text() == "<xml>updated content</xml>"


def test_file_url_source_changes_reflected_immediately(mock_logger, temp_cache_dir, tmp_path):
    """Test that local file changes are immediately reflected (no caching)."""
    # Create a source file
    source_file = tmp_path / "source" / "test.xml"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text("<xml>old content</xml>")

    cache = FileHandler.create(
        url=f"file://{source_file}",
        metadata_expire=1,  # 1 second (ignored for local files)
        cache_dir=temp_cache_dir,
    )

    # First access
    file_path = cache.get_file_path()
    assert Path(file_path).read_text() == "<xml>old content</xml>"

    # Update source file
    source_file.write_text("<xml>new content</xml>")

    # Second access should see new content immediately
    file_path = cache.get_file_path()
    assert Path(file_path).read_text() == "<xml>new content</xml>"


def test_file_url_nonexistent_source_file(mock_logger, temp_cache_dir):
    """Test handling when source file doesn't exist."""
    from dnf.exceptions import Error as DnfError

    cache = FileHandler.create(url="file:///nonexistent/path/test.xml", cache_dir=temp_cache_dir)

    with pytest.raises(DnfError, match="File not found: file:///nonexistent/path/test.xml"):
        cache.get_file_path()


def test_file_url_with_url_encoding(mock_logger, temp_cache_dir, tmp_path):
    """Test file:// URL with URL-encoded characters."""
    # Create a source file with spaces in the path
    source_dir = tmp_path / "source dir"
    source_dir.mkdir(parents=True, exist_ok=True)
    source_file = source_dir / "test file.xml"
    source_file.write_text("<xml>content</xml>")

    # URL encode the path
    from urllib.parse import quote

    encoded_path = quote(str(source_file))

    cache = FileHandler.create(
        url=f"file://{encoded_path}",
        cache_dir=temp_cache_dir,
    )

    file_path = cache.get_file_path()

    assert file_path is not None
    assert Path(file_path).read_text() == "<xml>content</xml>"


def test_file_url_error_raises_dnf_error(mock_logger, temp_cache_dir, tmp_path):
    """Test that errors accessing local files raise DnfError."""
    from dnf.exceptions import Error as DnfError

    # Create a source file
    source_file = tmp_path / "source" / "test.xml"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text("<xml>source content</xml>")

    cache = FileHandler.create(
        url=f"file://{source_file}",
        cache_dir=temp_cache_dir,
    )

    # Mock exists() to raise an exception
    with patch("pathlib.Path.exists", side_effect=PermissionError("Access denied")):
        with pytest.raises(DnfError, match=f"Failed to access file: file://{source_file}"):
            cache.get_file_path()


def test_file_url_direct_access_success(mock_logger, temp_cache_dir, tmp_path):
    """Test that local files are accessed directly without copying."""
    # Create a source file
    source_file = tmp_path / "source" / "test.xml"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text("<xml>source content</xml>")

    cache = FileHandler.create(
        url=f"file://{source_file}",
        cache_dir=temp_cache_dir,
    )

    # Access the file - should work without any copying
    result = cache.get_file_path()

    # Should succeed with direct access (returns source path, not cache path)
    assert result == str(source_file)
    assert Path(result).read_text() == "<xml>source content</xml>"

    # Verify no cache files were created
    cache_dir = Path(temp_cache_dir)
    if cache_dir.exists():
        cache_files = list(cache_dir.glob("test.xml*"))
        assert len(cache_files) == 0, f"Unexpected cache files: {cache_files}"


def test_file_url_clear_cache_no_op(mock_logger, temp_cache_dir, tmp_path):
    """Test that clear_cache is a no-op for file:// URLs (no cache created)."""
    # Create a source file
    source_file = tmp_path / "source" / "test.xml"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text("<xml>source content</xml>")

    cache = FileHandler.create(
        url=f"file://{source_file}",
        cache_dir=temp_cache_dir,
    )

    # Access the file (no cache created)
    file_path = cache.get_file_path()
    assert file_path == str(source_file)

    cache_dir = Path(temp_cache_dir)

    # Verify no cache files were created
    if cache_dir.exists():
        cache_files = list(cache_dir.glob("test.xml*"))
        assert len(cache_files) == 0, f"Unexpected cache files: {cache_files}"

    # clear_cache should be a no-op (no errors)
    cache.clear_cache()

    # Still no cache files
    if cache_dir.exists():
        cache_files = list(cache_dir.glob("test.xml*"))
        assert len(cache_files) == 0, f"Unexpected cache files after clear: {cache_files}"


def test_fetch_failure_no_cache_raises_dnf_error(mock_logger, temp_cache_dir):
    """Test that fetch failure with no existing cache raises DnfError."""
    with patch("dnf_support_info_plugin.file_cache.urlopen") as mock_urlopen:
        # Mock fetch to fail
        mock_urlopen.side_effect = URLError("Network error")

        cache = FileHandler.create(
            url="https://example.com/test.xml", retries=0, cache_dir=temp_cache_dir
        )

        # No cache exists, fetch fails, should raise DnfError
        with pytest.raises(MockDnfError):
            cache.get_file_path()


def test_check_update_exception_with_cache_fallback(mock_logger, temp_cache_dir, cached_file_setup):
    """Test that exception in _check_and_update falls back to cached file."""
    setup = cached_file_setup
    with patch("dnf_support_info_plugin.file_cache.urlopen") as mock_urlopen:
        cache = FileHandler.create(
            url="https://example.com/test.xml",
            metadata_expire=1,  # Short expiration to trigger check
            cache_dir=temp_cache_dir,
        )
        setup(cache, age_seconds=2)  # expired cache

        # Mock HTTP to fail during HEAD request
        mock_urlopen.side_effect = URLError("Network unavailable")

        file_path = cache.get_file_path()

        # Should fall back to cached file
        assert file_path == str(cache.cache.cached_file_path)
        assert Path(file_path).read_text() == "<xml>cached</xml>"
        mock_logger.info.assert_called_with("Using cached file as fallback")


def test_save_metadata_write_failure_causes_fetch_to_fail(mock_logger, temp_cache_dir):
    """Test that metadata save failure causes _persist_content to raise DnfError.

    Because _save_metadata now raises OSError on failure, the exception propagates
    to _persist_content's except block.  The download itself succeeded (data is on
    disk), but without valid metadata subsequent cache-validity checks cannot use
    the file reliably, so DnfError is raised to signal the failure to the caller.
    """
    with patch("dnf_support_info_plugin.file_cache.urlopen") as mock_urlopen:
        cache = FileHandler.create(url="https://example.com/test.xml", cache_dir=temp_cache_dir)

        # Mock GET response with metadata (metadata extracted from GET)
        mock_get_response = Mock()
        mock_get_response.read.return_value = b"<xml>content</xml>"
        mock_get_response.headers = {"ETag": '"abc123"'}

        mock_urlopen.return_value = mock_get_response

        # Mock os.replace to fail (simulating a permission error on the cache dir)
        with patch("os.replace", side_effect=PermissionError("Permission denied")):
            # _save_metadata raised OSError → _persist_content raises DnfError
            with pytest.raises(MockDnfError):
                cache.get_file_path()


def test_save_metadata_cleanup_failure_is_logged_as_debug(mock_logger, temp_cache_dir):
    """Test that temp-file cleanup failure during metadata write is logged at DEBUG.

    When os.replace raises *and* the subsequent unlink also fails, the original
    OSError is still re-raised (so callers know the save failed) and the cleanup
    problem is recorded at DEBUG level rather than silently ignored.
    """
    with patch("dnf_support_info_plugin.file_cache.urlopen") as mock_urlopen:
        cache = FileHandler.create(url="https://example.com/test.xml", cache_dir=temp_cache_dir)

        # Mock GET response with metadata (metadata extracted from GET)
        mock_get_response = Mock()
        mock_get_response.read.return_value = b"<xml>content</xml>"
        mock_get_response.headers = {"ETag": '"abc123"'}

        mock_urlopen.return_value = mock_get_response

        with patch("os.replace", side_effect=PermissionError("Write failed")):
            with patch("pathlib.Path.unlink", side_effect=OSError("Cleanup failed")):
                # The fetch raises DnfError (metadata could not be saved)
                with pytest.raises(MockDnfError):
                    cache.get_file_path()

        # Cleanup problem must be visible at DEBUG level
        debug_calls = [str(call) for call in mock_logger.debug.call_args_list]
        assert any("Failed to clean up temp file" in msg for msg in debug_calls)


def test_save_metadata_raises_propagates_through_update_timestamp(
    mock_logger, temp_cache_dir, cached_file_setup
):
    """Test that _save_metadata raising OSError propagates through _update_timestamp.

    When the cache is expired but the ETag is unchanged, _check_and_update calls
    _update_timestamp → _save_metadata.  If that write fails the OSError must
    surface so that _check_and_update can fall back to the cached file rather than
    silently leaving a stale timestamp on disk.
    """
    setup = cached_file_setup
    with patch("dnf_support_info_plugin.file_cache.urlopen") as mock_urlopen:
        cache = FileHandler.create(
            url="https://example.com/test.xml",
            metadata_expire=1,  # Short expiry so cache is considered expired
            cache_dir=temp_cache_dir,
        )
        # Expired cache with known ETag "abc123"
        setup(cache, age_seconds=2)

        # Server returns the same ETag → _update_timestamp will be called
        mock_head_response = Mock()
        mock_head_response.headers = {"ETag": '"abc123"'}
        mock_urlopen.return_value = mock_head_response

        with patch("os.replace", side_effect=PermissionError("Disk full")):
            file_path = cache.get_file_path()

        # _check_and_update must fall back to the existing cached file
        assert file_path == str(cache.cache.cached_file_path)
        assert Path(file_path).read_text() == "<xml>cached</xml>"

        # A warning about the failed check must be logged
        mock_logger.warning.assert_called()
        warning_msg = mock_logger.warning.call_args[0][0]
        assert "Failed to check source" in warning_msg


def test_is_transient_error_http_429(mock_logger, temp_cache_dir):
    """Test that HTTP 429 (Too Many Requests) is treated as transient error and raises DnfError."""
    with patch("dnf_support_info_plugin.file_cache.urlopen") as mock_urlopen:
        # Simulate 429 error
        mock_urlopen.side_effect = HTTPError(
            "https://example.com/test.xml", 429, "Too Many Requests", {}, None
        )

        cache = FileHandler.create(
            url="https://example.com/test.xml", retries=1, cache_dir=temp_cache_dir
        )

        # Should retry on 429 and raise DnfError after exhausting retries
        with pytest.raises(MockDnfError):
            cache.get_file_path()

        # Should have retried: initial + 1 retry = 2 attempts
        assert mock_urlopen.call_count == 2


def test_http_request_exhausts_retries_raises_dnf_error(mock_logger, temp_cache_dir):
    """Test that exhausting retries raises DnfError when no cache exists."""
    with patch("dnf_support_info_plugin.file_cache.urlopen") as mock_urlopen:
        # All attempts fail with transient errors
        mock_urlopen.side_effect = URLError("Connection timeout")

        cache = FileHandler.create(
            url="https://example.com/test.xml", retries=2, cache_dir=temp_cache_dir
        )

        # Should raise DnfError after exhausting retries
        with pytest.raises(MockDnfError):
            cache.get_file_path()

        # Should have tried: initial + 2 retries = 3 attempts
        assert mock_urlopen.call_count == 3


# ---------------------------------------------------------------------------
# FetchResult and _extract_metadata tests
# ---------------------------------------------------------------------------


def test_extract_metadata_from_response(mock_logger, temp_cache_dir):
    """Test that _extract_metadata correctly extracts headers from HTTP response."""
    from datetime import timedelta

    handler = HttpsFileHandler(
        url="https://example.com/test.xml",
        metadata_expire=timedelta(seconds=600),
        request_timeout=30,
        retries=0,
        cache_dir=temp_cache_dir,
    )

    # Create a mock response with various headers
    mock_response = Mock()
    mock_response.headers = {
        "ETag": '"quoted-etag-value"',
        "Last-Modified": "Mon, 01 Jan 2024 00:00:00 GMT",
        "Content-Length": "1024",
        "Content-Type": "application/xml",
    }

    metadata = handler._extract_metadata(mock_response)

    # ETag quotes should be stripped
    assert metadata["etag"] == "quoted-etag-value"
    assert metadata["last_modified"] == "Mon, 01 Jan 2024 00:00:00 GMT"
    assert metadata["size"] == "1024"
    assert metadata["content_type"] == "application/xml"
    assert metadata["url"] == "https://example.com/test.xml"


def test_extract_metadata_strips_etag_quotes(mock_logger, temp_cache_dir):
    """Test that _extract_metadata strips surrounding quotes from ETag."""
    from datetime import timedelta

    handler = HttpsFileHandler(
        url="https://example.com/test.xml",
        metadata_expire=timedelta(seconds=600),
        request_timeout=30,
        retries=0,
        cache_dir=temp_cache_dir,
    )

    # Test with double-quoted ETag
    mock_response = Mock()
    mock_response.headers = {"ETag": '"abc123"'}
    metadata = handler._extract_metadata(mock_response)
    assert metadata["etag"] == "abc123"

    # Test with unquoted ETag (some servers don't quote)
    mock_response.headers = {"ETag": "abc123"}
    metadata = handler._extract_metadata(mock_response)
    assert metadata["etag"] == "abc123"


def test_extract_metadata_handles_missing_headers(mock_logger, temp_cache_dir):
    """Test that _extract_metadata handles missing headers gracefully."""
    from datetime import timedelta

    handler = HttpsFileHandler(
        url="https://example.com/test.xml",
        metadata_expire=timedelta(seconds=600),
        request_timeout=30,
        retries=0,
        cache_dir=temp_cache_dir,
    )

    mock_response = Mock()
    mock_response.headers = {}

    metadata = handler._extract_metadata(mock_response)

    assert metadata["etag"] == ""
    assert metadata["last_modified"] == ""
    assert metadata["size"] == ""
    assert metadata["content_type"] == ""


def test_persist_content_cleans_up_on_metadata_failure(mock_logger, temp_cache_dir):
    """Test that _persist_content cleans up orphaned content file when metadata save fails and raises DnfError."""
    from datetime import timedelta

    handler = HttpsFileHandler(
        url="https://example.com/test.xml",
        metadata_expire=timedelta(seconds=600),
        request_timeout=30,
        retries=0,
        cache_dir=temp_cache_dir,
    )

    # Create a FetchResult with valid data and metadata
    result = FetchResult(
        data=b"<xml>content</xml>",
        metadata={
            "url": "https://example.com/test.xml",
            "etag": "abc123",
            "last_modified": "",
            "size": "17",
            "content_type": "application/xml",
        },
    )

    # Mock os.replace to fail (simulating metadata write failure)
    with patch("os.replace", side_effect=PermissionError("Permission denied")):
        # Should raise DnfError on failure
        with pytest.raises(MockDnfError):
            handler._persist_content(result)

    # Content file should be cleaned up (not left orphaned)
    assert not handler.cache.cached_file_path.exists()


def test_persist_content_asserts_metadata_for_https(mock_logger, temp_cache_dir):
    """Test that _persist_content raises AssertionError if FetchResult.metadata is None."""
    from datetime import timedelta

    handler = HttpsFileHandler(
        url="https://example.com/test.xml",
        metadata_expire=timedelta(seconds=600),
        request_timeout=30,
        retries=0,
        cache_dir=temp_cache_dir,
    )

    # Create a FetchResult with None metadata (invalid for HTTPS handler)
    result = FetchResult(data=b"<xml>content</xml>", metadata=None)

    # Should raise AssertionError
    with pytest.raises(ValueError, match="HttpsFileHandler requires metadata"):
        handler._persist_content(result)


def test_fetch_result_dataclass(mock_logger, temp_cache_dir):
    """Test FetchResult dataclass basic functionality."""
    # Test with data only (metadata defaults to None)
    result1 = FetchResult(data=b"test data")
    assert result1.data == b"test data"
    assert result1.metadata is None

    # Test with data and metadata
    metadata = {"etag": "abc123", "url": "https://example.com/test.xml"}
    result2 = FetchResult(data=b"test data", metadata=metadata)
    assert result2.data == b"test data"
    assert result2.metadata == metadata
