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

"""Tests for GpgVerifier and GPG-enabled HttpsFileHandler."""

from pathlib import Path
from test.conftest import MockDnfError
from unittest.mock import MagicMock, Mock, patch

import pytest

from dnf_support_info_plugin.file_cache import FileHandler, GpgVerifier

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_logger():
    with patch("dnf_support_info_plugin.file_cache.logger") as mock_log:
        yield mock_log


@pytest.fixture
def pubring_dir(tmp_path):
    """A temporary directory acting as the GPG pubring."""
    d = tmp_path / "pubring"
    d.mkdir()
    return d


@pytest.fixture
def key_url(tmp_path):
    """A file:// URL pointing to a fake key file."""
    kf = tmp_path / "RPM-GPG-KEY-test"
    kf.write_bytes(b"fake-key-data")
    return f"file://{kf}"


# ---------------------------------------------------------------------------
# GpgVerifier._ensure_keys_imported tests
# ---------------------------------------------------------------------------


class TestEnsureKeysImported:
    """Unit tests for GpgVerifier._ensure_keys_imported()."""

    def test_imports_new_key_when_pubring_empty(self, pubring_dir, key_url, mock_logger):
        """Keys not in the pubring are fetched and imported."""
        fake_keyinfo = MagicMock()
        fake_keyinfo.id_ = "DEADBEEF12345678"
        fake_keyinfo.short_id = "12345678"
        fake_keyinfo.raw_key = b"raw-key-bytes"

        with (
            patch("dnf_support_info_plugin.file_cache.dnf.crypto") as mock_crypto,
            patch("dnf_support_info_plugin.file_cache.dnf.yum.misc") as mock_misc,
        ):
            mock_crypto.keyids_from_pubring.return_value = []
            mock_crypto.retrieve.return_value = [fake_keyinfo]
            mock_crypto.log_key_import = MagicMock()

            verifier = GpgVerifier(gpgkey=[key_url], pubring_dir=str(pubring_dir))
            result = verifier._ensure_keys_imported()

        assert result is True
        mock_crypto.retrieve.assert_called_once_with(key_url)
        mock_misc.import_key_to_pubring.assert_called_once_with(
            b"raw-key-bytes", "12345678", gpgdir=str(pubring_dir), make_ro_copy=False
        )

    def test_skips_already_imported_key(self, pubring_dir, key_url, mock_logger):
        """Keys already in the pubring are not re-imported."""
        fake_keyinfo = MagicMock()
        fake_keyinfo.id_ = "EXISTINGKEY12345"

        with (
            patch("dnf_support_info_plugin.file_cache.dnf.crypto") as mock_crypto,
            patch("dnf_support_info_plugin.file_cache.dnf.yum.misc") as mock_misc,
        ):
            mock_crypto.keyids_from_pubring.return_value = ["EXISTINGKEY12345"]
            mock_crypto.retrieve.return_value = [fake_keyinfo]

            verifier = GpgVerifier(gpgkey=[key_url], pubring_dir=str(pubring_dir))
            result = verifier._ensure_keys_imported()

        assert result is True
        mock_misc.import_key_to_pubring.assert_not_called()

    def test_returns_false_when_no_keys_available(self, pubring_dir, mock_logger):
        """Returns False when retrieve fails for all URLs and pubring is empty."""
        with patch("dnf_support_info_plugin.file_cache.dnf.crypto") as mock_crypto:
            mock_crypto.keyids_from_pubring.return_value = []
            mock_crypto.retrieve.side_effect = Exception("network error")

            verifier = GpgVerifier(
                gpgkey=["https://example.com/key.asc"], pubring_dir=str(pubring_dir)
            )
            result = verifier._ensure_keys_imported()

        assert result is False
        mock_logger.error.assert_called()
        assert "No GPG keys available" in mock_logger.error.call_args[0][0]

    def test_returns_true_when_keys_already_present(self, pubring_dir, mock_logger):
        """Returns True immediately when pubring already has keys (no import needed)."""
        with patch("dnf_support_info_plugin.file_cache.dnf.crypto") as mock_crypto:
            mock_crypto.keyids_from_pubring.return_value = ["PREEXISTING123456"]
            mock_crypto.retrieve.return_value = []

            verifier = GpgVerifier(gpgkey=[], pubring_dir=str(pubring_dir))
            result = verifier._ensure_keys_imported()

        assert result is True

    def test_warns_on_retrieve_failure_but_continues(self, pubring_dir, mock_logger):
        """A failed retrieve for one URL logs a warning and continues to the next."""
        good_keyinfo = MagicMock()
        good_keyinfo.id_ = "GOODKEY123456789"
        good_keyinfo.short_id = "23456789"
        good_keyinfo.raw_key = b"good-key"

        urls = ["https://bad.example.com/key.asc", "https://good.example.com/key.asc"]

        with (
            patch("dnf_support_info_plugin.file_cache.dnf.crypto") as mock_crypto,
            patch("dnf_support_info_plugin.file_cache.dnf.yum.misc"),
        ):
            mock_crypto.keyids_from_pubring.return_value = []
            mock_crypto.retrieve.side_effect = [Exception("timeout"), [good_keyinfo]]
            mock_crypto.log_key_import = MagicMock()

            verifier = GpgVerifier(gpgkey=urls, pubring_dir=str(pubring_dir))
            result = verifier._ensure_keys_imported()

        assert result is True
        mock_logger.warning.assert_called()
        assert "bad.example.com" in mock_logger.warning.call_args_list[0][0][0]


# ---------------------------------------------------------------------------
# GpgVerifier.verify tests
# ---------------------------------------------------------------------------


class TestGpgVerifier:
    """Unit tests for GpgVerifier.verify()."""

    def test_returns_true_on_successful_verification(self, pubring_dir, key_url, mock_logger):
        """verify() returns True when gpg.Context.verify() succeeds."""
        verifier = GpgVerifier(gpgkey=[key_url], pubring_dir=str(pubring_dir))

        with (
            patch("dnf_support_info_plugin.file_cache.dnf.crypto") as mock_crypto,
            patch("dnf_support_info_plugin.file_cache.dnf.yum.misc"),
            patch("dnf_support_info_plugin.file_cache.gpg") as mock_gpg_module,
        ):
            mock_crypto.keyids_from_pubring.return_value = ["SOMEKEY123456789"]
            mock_crypto.pubring_dir.return_value.__enter__ = lambda s: None
            mock_crypto.pubring_dir.return_value.__exit__ = MagicMock(return_value=False)

            mock_context = MagicMock()
            mock_gpg_module.Context.return_value = mock_context
            mock_context.verify.return_value = (None, MagicMock())

            result = verifier.verify(b"xml data", b"sig data")

        assert result is True
        mock_context.verify.assert_called_once()

    def test_returns_false_on_bad_signatures(self, pubring_dir, key_url, mock_logger):
        """verify() returns False when gpg.errors.BadSignatures is raised."""
        verifier = GpgVerifier(gpgkey=[key_url], pubring_dir=str(pubring_dir))

        class FakeBadSignatures(Exception):
            pass

        with (
            patch("dnf_support_info_plugin.file_cache.dnf.crypto") as mock_crypto,
            patch("dnf_support_info_plugin.file_cache.dnf.yum.misc"),
            patch("dnf_support_info_plugin.file_cache.gpg") as mock_gpg_module,
            patch("dnf_support_info_plugin.file_cache.gpg.errors") as mock_errors,
        ):
            mock_crypto.keyids_from_pubring.return_value = ["SOMEKEY123456789"]
            mock_crypto.pubring_dir.return_value.__enter__ = lambda s: None
            mock_crypto.pubring_dir.return_value.__exit__ = MagicMock(return_value=False)

            mock_gpg_module.errors.BadSignatures = FakeBadSignatures
            mock_errors.BadSignatures = FakeBadSignatures

            mock_context = MagicMock()
            mock_gpg_module.Context.return_value = mock_context
            mock_context.verify.side_effect = FakeBadSignatures("bad sig")

            result = verifier.verify(b"tampered xml", b"sig data")

        assert result is False
        mock_logger.error.assert_called()
        assert "GPG signature verification failed" in mock_logger.error.call_args[0][0]

    def test_returns_false_when_ensure_keys_fails(self, pubring_dir, mock_logger):
        """verify() returns False immediately if _ensure_keys_imported() returns False."""
        verifier = GpgVerifier(gpgkey=[], pubring_dir=str(pubring_dir))

        with patch("dnf_support_info_plugin.file_cache.dnf.crypto") as mock_crypto:
            mock_crypto.keyids_from_pubring.return_value = []

            result = verifier.verify(b"data", b"sig")

        assert result is False

    def test_returns_false_on_unexpected_exception(self, pubring_dir, key_url, mock_logger):
        """verify() returns False (does not propagate) on unexpected GPG errors."""
        verifier = GpgVerifier(gpgkey=[key_url], pubring_dir=str(pubring_dir))

        with (
            patch("dnf_support_info_plugin.file_cache.dnf.crypto") as mock_crypto,
            patch("dnf_support_info_plugin.file_cache.dnf.yum.misc"),
            patch("dnf_support_info_plugin.file_cache.gpg") as mock_gpg_module,
        ):
            mock_crypto.keyids_from_pubring.return_value = ["SOMEKEY123456789"]
            mock_crypto.pubring_dir.return_value.__enter__ = lambda s: None
            mock_crypto.pubring_dir.return_value.__exit__ = MagicMock(return_value=False)

            mock_gpg_module.errors.BadSignatures = type("BadSig", (Exception,), {})
            mock_context = MagicMock()
            mock_gpg_module.Context.return_value = mock_context
            mock_context.verify.side_effect = RuntimeError("unexpected crash")

            result = verifier.verify(b"data", b"sig")

        assert result is False
        mock_logger.error.assert_called()
        assert "Unexpected error" in mock_logger.error.call_args[0][0]

    def test_uses_pubring_dir_as_gnupghome(self, pubring_dir, key_url, mock_logger):
        """verify() calls dnf.crypto.pubring_dir() with the -ro pubring path."""
        verifier = GpgVerifier(gpgkey=[key_url], pubring_dir=str(pubring_dir))

        with (
            patch("dnf_support_info_plugin.file_cache.dnf.crypto") as mock_crypto,
            patch("dnf_support_info_plugin.file_cache.dnf.yum.misc"),
            patch("dnf_support_info_plugin.file_cache.gpg") as mock_gpg_module,
        ):
            mock_crypto.keyids_from_pubring.return_value = ["SOMEKEY123456789"]
            ctx_mgr = MagicMock()
            ctx_mgr.__enter__ = lambda s: None
            ctx_mgr.__exit__ = MagicMock(return_value=False)
            mock_crypto.pubring_dir.return_value = ctx_mgr

            mock_context = MagicMock()
            mock_gpg_module.Context.return_value = mock_context
            mock_context.verify.return_value = (None, MagicMock())

            verifier.verify(b"data", b"sig")

        mock_crypto.pubring_dir.assert_called_once_with(str(pubring_dir))


# ---------------------------------------------------------------------------
# HttpsFileHandler GPG integration tests
# ---------------------------------------------------------------------------


class TestHttpsFileHandlerGpg:
    """Integration tests for GPG verification in HttpsFileHandler."""

    def test_gpgcheck_false_skips_signature_download(self, mock_logger, tmp_path):
        """When gpgcheck=False, no signature is downloaded and file is cached normally."""
        with patch("dnf_support_info_plugin.file_cache.urlopen") as mock_urlopen:
            # Mock GET response with metadata (metadata extracted from GET)
            mock_get = Mock()
            mock_get.read.return_value = b"<xml>content</xml>"
            mock_get.headers = {"ETag": '"abc123"'}
            mock_urlopen.return_value = mock_get

            handler = FileHandler.create(
                url="https://example.com/supportinfo.xml",
                gpgcheck=False,
                cache_dir=str(tmp_path),
            )
            result = handler.get_file_path()

        assert result is not None
        assert Path(result).read_bytes() == b"<xml>content</xml>"
        # No extra .asc download — only GET (metadata from GET response)
        assert mock_urlopen.call_count == 1

    def test_gpgcheck_true_downloads_and_verifies_signature(self, mock_logger, tmp_path):
        """When gpgcheck=True and signature is valid, file is cached and path returned."""
        with patch("dnf_support_info_plugin.file_cache.urlopen") as mock_urlopen:
            # Mock GET response with metadata (metadata extracted from GET)
            mock_get = Mock()
            mock_get.read.return_value = b"<xml>content</xml>"
            mock_get.headers = {"ETag": '"abc123"'}
            mock_asc = Mock()
            mock_asc.read.return_value = (
                b"-----BEGIN PGP SIGNATURE-----\nfakesig\n-----END PGP SIGNATURE-----"
            )
            # GET xml, GET asc (metadata from GET response)
            mock_urlopen.side_effect = [mock_get, mock_asc]

            handler = FileHandler.create(
                url="https://example.com/supportinfo.xml",
                gpgcheck=True,
                gpgkey=["file:///etc/pki/rpm-gpg/RPM-GPG-KEY-test"],
                cache_dir=str(tmp_path),
            )

            # Mock GpgVerifier.verify to return True (valid signature)
            with patch.object(handler.gpg_verifier, "verify", return_value=True) as mock_verify:
                result = handler.get_file_path()

        assert result is not None
        assert Path(result).read_bytes() == b"<xml>content</xml>"
        mock_verify.assert_called_once_with(b"<xml>content</xml>", mock_asc.read.return_value)

    def test_gpgcheck_true_bad_signature_raises_dnf_error(self, mock_logger, tmp_path):
        """When gpgcheck=True and signature is invalid, DnfError is raised and file is NOT cached."""
        with patch("dnf_support_info_plugin.file_cache.urlopen") as mock_urlopen:
            # Mock GET response with metadata (metadata extracted from GET)
            mock_get = Mock()
            mock_get.read.return_value = b"<xml>tampered</xml>"
            mock_get.headers = {"ETag": '"abc123"'}
            mock_asc = Mock()
            mock_asc.read.return_value = b"bad sig"
            # GET xml, GET asc repeated for 3 retries (metadata from GET response)
            mock_urlopen.side_effect = [mock_get, mock_asc, mock_get, mock_asc, mock_get, mock_asc]

            handler = FileHandler.create(
                url="https://example.com/supportinfo.xml",
                gpgcheck=True,
                gpgkey=["file:///etc/pki/rpm-gpg/RPM-GPG-KEY-test"],
                cache_dir=str(tmp_path),
            )

            # Mock GpgVerifier.verify to return False (tampered content)
            with patch.object(handler.gpg_verifier, "verify", return_value=False):
                # GPG verification failed after retries → raises DnfError
                with pytest.raises(MockDnfError):
                    handler.get_file_path()

    def test_gpgcheck_true_signature_download_failure(self, mock_logger, tmp_path):
        """When signature download fails, DnfError is raised and file is NOT cached."""
        from urllib.error import URLError

        with patch("dnf_support_info_plugin.file_cache.urlopen") as mock_urlopen:
            # Mock GET response with metadata (metadata extracted from GET)
            mock_get = Mock()
            mock_get.read.return_value = b"<xml>content</xml>"
            mock_get.headers = {"ETag": '"abc123"'}
            # GET xml, .asc download fails - repeated for 3 retries
            mock_urlopen.side_effect = [
                mock_get,
                URLError("403 Forbidden"),
                mock_get,
                URLError("403 Forbidden"),
                mock_get,
                URLError("403 Forbidden"),
            ]

            handler = FileHandler.create(
                url="https://example.com/supportinfo.xml",
                gpgcheck=True,
                gpgkey=["file:///etc/pki/rpm-gpg/RPM-GPG-KEY-test"],
                cache_dir=str(tmp_path),
            )

            # DnfError from _fetch_signature → raises DnfError
            with pytest.raises(MockDnfError):
                handler.get_file_path()

        mock_logger.error.assert_called()

    def test_gpgcheck_always_derives_asc_url_from_base(self, mock_logger, tmp_path):
        """The handler always appends '.asc' to the base URL for the signature."""
        handler = FileHandler.create(
            url="https://example.com/supportinfo.xml",
            gpgcheck=True,
            cache_dir=str(tmp_path),
        )
        assert handler.asc_url == "https://example.com/supportinfo.xml.asc"

    def test_gpgcheck_false_does_not_create_gpg_verifier(self, mock_logger, tmp_path):
        """When gpgcheck=False, gpg_verifier is None (no GPG library overhead)."""
        handler = FileHandler.create(
            url="https://example.com/supportinfo.xml",
            gpgcheck=False,
            cache_dir=str(tmp_path),
        )
        assert handler.gpg_verifier is None

    def test_gpgcheck_true_creates_gpg_verifier_with_gpgkey_list(self, mock_logger, tmp_path):
        """When gpgcheck=True with gpgkey, verifier stores the key list."""
        keys = ["file:///etc/pki/rpm-gpg/RPM-GPG-KEY-test"]
        handler = FileHandler.create(
            url="https://example.com/supportinfo.xml",
            gpgcheck=True,
            gpgkey=keys,
            cache_dir=str(tmp_path),
        )
        assert handler.gpg_verifier is not None
        assert handler.gpg_verifier.gpgkey == keys

    def test_gpgcheck_true_no_gpgkey_creates_verifier_with_empty_list(self, mock_logger, tmp_path):
        """When gpgcheck=True with no gpgkey, verifier uses an empty list."""
        handler = FileHandler.create(
            url="https://example.com/supportinfo.xml",
            gpgcheck=True,
            cache_dir=str(tmp_path),
        )
        assert handler.gpg_verifier is not None
        assert handler.gpg_verifier.gpgkey == []

    def test_valid_cache_skips_gpg_reverification(self, mock_logger, tmp_path):
        """When cache is still valid, GPG verification is NOT re-run (cached = trusted)."""
        import json
        from datetime import datetime, timezone

        with patch("dnf_support_info_plugin.file_cache.urlopen") as mock_urlopen:
            handler = FileHandler.create(
                url="https://example.com/supportinfo.xml",
                gpgcheck=True,
                gpgkey=["file:///etc/pki/rpm-gpg/RPM-GPG-KEY-test"],
                metadata_expire=7200,
                cache_dir=str(tmp_path),
            )

            # Manually seed a fresh cache
            cached_file = handler.cache.cached_file_path
            cached_file.parent.mkdir(parents=True, exist_ok=True)
            cached_file.write_bytes(b"<xml>cached</xml>")
            metadata_file = handler.cache.metadata_file_path
            metadata = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "etag": "abc123",
                "url": handler.url,
            }
            metadata_file.write_text(json.dumps(metadata))

            with patch.object(handler, "gpg_verifier") as mock_verifier:
                result = handler.get_file_path()

        # Cache is valid — no HTTP calls, no GPG verification
        assert result is not None
        assert Path(result).read_bytes() == b"<xml>cached</xml>"
        mock_urlopen.assert_not_called()
        mock_verifier.verify.assert_not_called()


# ---------------------------------------------------------------------------
# LocalFileHandler GPG integration tests
# ---------------------------------------------------------------------------


class TestLocalFileHandlerGpg:
    """Integration tests for GPG verification in LocalFileHandler using file:// protocol."""

    def test_gpgcheck_true_verifies_signature_and_returns_path(self, mock_logger, tmp_path):
        """When gpgcheck=True and signature is valid, file path is returned."""
        # Create temp XML file and signature file
        xml_file = tmp_path / "supportinfo.xml"
        xml_file.write_bytes(b"<xml>content</xml>")
        asc_file = tmp_path / "supportinfo.xml.asc"
        asc_file.write_bytes(b"-----BEGIN PGP SIGNATURE-----\nfakesig\n-----END PGP SIGNATURE-----")

        handler = FileHandler.create(
            url=f"file://{xml_file}",
            gpgcheck=True,
            gpgkey=["file:///etc/pki/rpm-gpg/RPM-GPG-KEY-test"],
            cache_dir=str(tmp_path),
        )

        # Mock GpgVerifier.verify to return True (valid signature)
        with patch.object(handler.gpg_verifier, "verify", return_value=True) as mock_verify:
            result = handler.get_file_path()

        assert result is not None
        assert result == str(xml_file)
        mock_verify.assert_called_once_with(
            b"<xml>content</xml>",
            b"-----BEGIN PGP SIGNATURE-----\nfakesig\n-----END PGP SIGNATURE-----",
        )

    def test_gpgcheck_true_bad_signature_raises_dnf_error(self, mock_logger, tmp_path):
        """When gpgcheck=True and signature is invalid, DnfError is raised."""
        xml_file = tmp_path / "supportinfo.xml"
        xml_file.write_bytes(b"<xml>tampered</xml>")
        asc_file = tmp_path / "supportinfo.xml.asc"
        asc_file.write_bytes(b"bad sig")

        handler = FileHandler.create(
            url=f"file://{xml_file}",
            gpgcheck=True,
            gpgkey=["file:///etc/pki/rpm-gpg/RPM-GPG-KEY-test"],
            cache_dir=str(tmp_path),
        )

        # Mock GpgVerifier.verify to return False (tampered content)
        with patch.object(handler.gpg_verifier, "verify", return_value=False):
            with pytest.raises(MockDnfError):
                handler.get_file_path()

    def test_gpgcheck_true_missing_asc_file_raises_dnf_error(self, mock_logger, tmp_path):
        """When gpgcheck=True and .asc file is missing, DnfError is raised."""
        xml_file = tmp_path / "supportinfo.xml"
        xml_file.write_bytes(b"<xml>content</xml>")
        # No .asc file created

        handler = FileHandler.create(
            url=f"file://{xml_file}",
            gpgcheck=True,
            gpgkey=["file:///etc/pki/rpm-gpg/RPM-GPG-KEY-test"],
            cache_dir=str(tmp_path),
        )

        with pytest.raises(MockDnfError):
            handler.get_file_path()

    def test_gpgcheck_false_skips_signature_verification(self, mock_logger, tmp_path):
        """When gpgcheck=False, no signature verification is performed."""
        xml_file = tmp_path / "supportinfo.xml"
        xml_file.write_bytes(b"<xml>content</xml>")
        # No .asc file needed when gpgcheck=False

        handler = FileHandler.create(
            url=f"file://{xml_file}",
            gpgcheck=False,
            cache_dir=str(tmp_path),
        )

        result = handler.get_file_path()

        assert result is not None
        assert result == str(xml_file)
        assert handler.gpg_verifier is None

    def test_gpgcheck_calls_methods_in_correct_order(self, mock_logger, tmp_path):
        """Verify that get_file_path calls _fetch_content, _fetch_signature, and verify in order."""
        xml_file = tmp_path / "supportinfo.xml"
        xml_file.write_bytes(b"<xml>content</xml>")
        asc_file = tmp_path / "supportinfo.xml.asc"
        asc_file.write_bytes(b"signature")

        handler = FileHandler.create(
            url=f"file://{xml_file}",
            gpgcheck=True,
            gpgkey=["file:///etc/pki/rpm-gpg/RPM-GPG-KEY-test"],
            cache_dir=str(tmp_path),
        )

        call_order = []

        original_fetch_content = handler._fetch_content
        original_fetch_signature = handler._fetch_signature

        def mock_fetch_content():
            call_order.append("fetch_content")
            return original_fetch_content()

        def mock_fetch_signature():
            call_order.append("fetch_signature")
            return original_fetch_signature()

        def mock_verify(data, sig):
            call_order.append("verify")
            return True

        with (
            patch.object(handler, "_fetch_content", mock_fetch_content),
            patch.object(handler, "_fetch_signature", mock_fetch_signature),
            patch.object(handler.gpg_verifier, "verify", mock_verify),
        ):
            result = handler.get_file_path()

        assert result is not None
        assert call_order == ["fetch_content", "fetch_signature", "verify"]


# ---------------------------------------------------------------------------
# GPG Retry and Fallback tests
# ---------------------------------------------------------------------------


class TestGpgRetryFallback:
    """Tests for GPG verification retry logic and stale cache fallback."""

    def test_gpg_verify_retries_on_failure_then_succeeds(self, mock_logger, tmp_path):
        """GPG verification retries on failure and succeeds on second attempt."""
        with (
            patch("dnf_support_info_plugin.file_cache.urlopen") as mock_urlopen,
            patch("dnf_support_info_plugin.file_cache.time") as mock_time,
        ):
            # Setup urlopen to return content with metadata, and sig on each attempt
            mock_get = Mock()
            mock_get.read.return_value = b"<xml>content</xml>"
            mock_get.headers = {"ETag": '"abc123"'}
            mock_asc = Mock()
            mock_asc.read.return_value = b"signature"
            # First attempt: GET xml, GET asc; Second attempt: GET xml, GET asc
            mock_urlopen.side_effect = [mock_get, mock_asc, mock_get, mock_asc]

            handler = FileHandler.create(
                url="https://example.com/supportinfo.xml",
                gpgcheck=True,
                gpgkey=["file:///etc/pki/rpm-gpg/RPM-GPG-KEY-test"],
                cache_dir=str(tmp_path),
            )

            # Mock verify to fail first, succeed second
            with patch.object(
                handler.gpg_verifier, "verify", side_effect=[False, True]
            ) as mock_verify:
                result = handler.get_file_path()

        assert result is not None
        assert mock_verify.call_count == 2
        mock_time.sleep.assert_called_once_with(1)

    def test_gpg_verify_all_retries_fail_falls_back_to_stale_cache(self, mock_logger, tmp_path):
        """When all GPG retries fail, falls back to stale cached file."""
        import json
        from datetime import datetime, timedelta, timezone

        with (
            patch("dnf_support_info_plugin.file_cache.urlopen") as mock_urlopen,
            patch("dnf_support_info_plugin.file_cache.time") as mock_time,
        ):
            handler = FileHandler.create(
                url="https://example.com/supportinfo.xml",
                gpgcheck=True,
                gpgkey=["file:///etc/pki/rpm-gpg/RPM-GPG-KEY-test"],
                metadata_expire=1,  # 1 second so cache is stale
                cache_dir=str(tmp_path),
            )

            # Seed stale cache (timestamp in the past)
            cached_file = handler.cache.cached_file_path
            cached_file.parent.mkdir(parents=True, exist_ok=True)
            cached_file.write_bytes(b"<xml>stale_cached</xml>")
            metadata_file = handler.cache.metadata_file_path
            stale_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
            metadata = {"timestamp": stale_time, "etag": "old_etag", "url": handler.url}
            metadata_file.write_text(json.dumps(metadata))

            # Mock urlopen for fresh fetch attempts (metadata from GET response)
            mock_get = Mock()
            mock_get.read.return_value = b"<xml>new_content</xml>"
            mock_get.headers = {"ETag": '"new_etag"'}
            mock_asc = Mock()
            mock_asc.read.return_value = b"signature"
            mock_head = Mock()
            mock_head.headers = {"ETag": '"new_etag"'}  # Different ETag triggers re-fetch
            # HEAD to check, then 3 retry attempts (GET xml, GET asc each)
            mock_urlopen.side_effect = [
                mock_head,  # _get_cached_path HEAD check
                mock_get,
                mock_asc,  # attempt 1
                mock_get,
                mock_asc,  # attempt 2
                mock_get,
                mock_asc,  # attempt 3
            ]

            with patch.object(handler.gpg_verifier, "verify", return_value=False) as mock_verify:
                result = handler.get_file_path()

        assert result is not None
        assert Path(result).read_bytes() == b"<xml>stale_cached</xml>"
        assert mock_verify.call_count == 3  # GPG_VERIFY_RETRIES

    def test_gpg_verify_all_retries_fail_no_cache_raises_dnf_error(self, mock_logger, tmp_path):
        """When all GPG retries fail and no cache exists, DnfError is raised."""
        with (
            patch("dnf_support_info_plugin.file_cache.urlopen") as mock_urlopen,
            patch("dnf_support_info_plugin.file_cache.time") as mock_time,
        ):
            # Mock GET response with metadata (metadata extracted from GET)
            mock_get = Mock()
            mock_get.read.return_value = b"<xml>content</xml>"
            mock_get.headers = {"ETag": '"abc123"'}
            mock_asc = Mock()
            mock_asc.read.return_value = b"signature"
            # 3 retry attempts (GET xml, GET asc each)
            mock_urlopen.side_effect = [
                mock_get,
                mock_asc,
                mock_get,
                mock_asc,
                mock_get,
                mock_asc,
            ]

            handler = FileHandler.create(
                url="https://example.com/supportinfo.xml",
                gpgcheck=True,
                gpgkey=["file:///etc/pki/rpm-gpg/RPM-GPG-KEY-test"],
                cache_dir=str(tmp_path),
            )

            with patch.object(handler.gpg_verifier, "verify", return_value=False) as mock_verify:
                with pytest.raises(MockDnfError):
                    handler.get_file_path()

            assert mock_verify.call_count == 3

    def test_local_handler_gpg_retries_is_one(self, mock_logger, tmp_path):
        """LocalFileHandler._gpg_retries returns 1 (no retry for local files)."""
        xml_file = tmp_path / "supportinfo.xml"
        xml_file.write_bytes(b"<xml>content</xml>")

        handler = FileHandler.create(
            url=f"file://{xml_file}",
            gpgcheck=True,
            cache_dir=str(tmp_path),
        )

        assert handler._gpg_retries == 1

    def test_https_handler_gpg_retries_is_default(self, mock_logger, tmp_path):
        """HttpsFileHandler._gpg_retries returns GPG_VERIFY_RETRIES (3)."""
        from dnf_support_info_plugin.file_cache import GPG_VERIFY_RETRIES

        handler = FileHandler.create(
            url="https://example.com/supportinfo.xml",
            gpgcheck=True,
            cache_dir=str(tmp_path),
        )

        assert handler._gpg_retries == GPG_VERIFY_RETRIES
        assert handler._gpg_retries == 3

    def test_gpg_retry_backoff_timing(self, mock_logger, tmp_path):
        """GPG retry uses exponential backoff (sleep 1, 2 for attempts 1, 2), then raises DnfError."""
        with (
            patch("dnf_support_info_plugin.file_cache.urlopen") as mock_urlopen,
            patch("dnf_support_info_plugin.file_cache.time") as mock_time,
        ):
            # Mock GET response with metadata (metadata extracted from GET)
            mock_get = Mock()
            mock_get.read.return_value = b"<xml>content</xml>"
            mock_get.headers = {"ETag": '"abc123"'}
            mock_asc = Mock()
            mock_asc.read.return_value = b"signature"
            mock_urlopen.side_effect = [
                mock_get,
                mock_asc,
                mock_get,
                mock_asc,
                mock_get,
                mock_asc,
            ]

            handler = FileHandler.create(
                url="https://example.com/supportinfo.xml",
                gpgcheck=True,
                gpgkey=["file:///etc/pki/rpm-gpg/RPM-GPG-KEY-test"],
                cache_dir=str(tmp_path),
            )

            with patch.object(handler.gpg_verifier, "verify", return_value=False):
                with pytest.raises(MockDnfError):
                    handler.get_file_path()

        # Backoff: sleep(1) after attempt 0, sleep(2) after attempt 1
        assert mock_time.sleep.call_count == 2
        mock_time.sleep.assert_any_call(1)
        mock_time.sleep.assert_any_call(2)
