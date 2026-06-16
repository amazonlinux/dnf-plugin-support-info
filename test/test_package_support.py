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

"""Unit tests for package_support module."""

import os
from unittest.mock import MagicMock, Mock, patch

import pytest
from dnf.exceptions import Error as DnfError


# Mock the decorator and parent class BEFORE importing the module
def mock_decorator(cls):
    """Decorate by doing nothing - just return the class unchanged."""
    return cls


# Create a mock parent class for SupportInfoCommand
class MockCommand:
    """Mock dnf.cli.Command class."""

    def __init__(self, cli):
        """Initialize with CLI, storing base as the real dnf.cli.Command does."""
        self.cli = cli
        self.base = cli.base


patch("dnf.plugin.register_command", mock_decorator).start()
patch("dnf.cli.Command", MockCommand).start()

# THEN LOAD THE MODULE
from dnf_support_info_plugin.package_support import SupportInfoCommand


class TestSupportInfoCommand:
    """Test SupportInfoCommand class."""

    @pytest.fixture
    def mock_cli(self):
        """Create a mock DNF CLI instance."""
        cli = MagicMock()
        cli.base = MagicMock()
        cli.base.conf = MagicMock()
        return cli

    @pytest.fixture
    def command(self, mock_cli):
        """Create a SupportInfoCommand instance with mocked CLI."""
        return SupportInfoCommand(mock_cli)


class TestInitializeCaches(TestSupportInfoCommand):
    """Tests for _initialize_caches method."""

    @pytest.fixture
    def mock_config_reader(self):
        """Fixture to patch ConfigReader."""
        with patch("dnf_support_info_plugin.package_support.ConfigReader") as mock:
            yield mock

    @pytest.fixture
    def mock_file_handler_create(self):
        """Fixture to patch FileHandler.create."""
        with patch("dnf_support_info_plugin.package_support.FileHandler.create") as mock:
            yield mock

    def test_initialize_caches_with_both_urls(
        self, command, mock_config_reader, mock_file_handler_create
    ):
        """Test successful cache initialization with both baseurl and templateurl."""
        mock_config = Mock()
        mock_config.baseurl = "https://example.com/supportinfo.xml"
        mock_config.templateurl = "https://example.com/supportinfo.xsd"
        mock_config.metadata_expire = 3600
        mock_config.gpgcheck = False
        mock_config.gpgkey = []
        mock_config_reader.return_value = mock_config

        mock_file_handler = Mock()
        mock_template_handler = Mock()
        mock_file_handler_create.side_effect = [mock_file_handler, mock_template_handler]

        result = command._initialize_caches()

        expected_cache_dir = os.path.join(command.base.conf.cachedir, "support-info")
        assert result is True
        assert command.file_cache == mock_file_handler
        assert command.template_cache == mock_template_handler
        assert mock_file_handler_create.call_count == 2
        mock_file_handler_create.assert_any_call(
            url="https://example.com/supportinfo.xml",
            metadata_expire=3600,
            gpgcheck=False,
            gpgkey=[],
            cache_dir=expected_cache_dir,
        )
        mock_file_handler_create.assert_any_call(
            url="https://example.com/supportinfo.xsd",
            metadata_expire=3600,
            gpgcheck=False,
            gpgkey=[],
            cache_dir=expected_cache_dir,
        )

    def test_initialize_caches_without_templateurl(
        self, command, mock_config_reader, mock_file_handler_create
    ):
        """Test successful cache initialization with only baseurl (no templateurl)."""
        mock_config = Mock()
        mock_config.baseurl = "https://example.com/supportinfo.xml"
        mock_config.templateurl = None
        mock_config.metadata_expire = 7200
        mock_config.gpgcheck = False
        mock_config.gpgkey = []
        mock_config_reader.return_value = mock_config

        mock_file_handler = Mock()
        mock_file_handler_create.return_value = mock_file_handler

        result = command._initialize_caches()

        expected_cache_dir = os.path.join(command.base.conf.cachedir, "support-info")
        assert result is True
        assert command.file_cache == mock_file_handler
        assert command.template_cache is None
        mock_file_handler_create.assert_called_once_with(
            url="https://example.com/supportinfo.xml",
            metadata_expire=7200,
            gpgcheck=False,
            gpgkey=[],
            cache_dir=expected_cache_dir,
        )

    def test_initialize_caches_with_empty_templateurl(
        self, command, mock_config_reader, mock_file_handler_create
    ):
        """Test cache initialization when templateurl is empty string."""
        mock_config = Mock()
        mock_config.baseurl = "https://example.com/supportinfo.xml"
        mock_config.templateurl = ""
        mock_config.metadata_expire = 3600
        mock_config_reader.return_value = mock_config

        mock_file_handler = Mock()
        mock_file_handler_create.return_value = mock_file_handler

        result = command._initialize_caches()

        assert result is True
        assert command.file_cache == mock_file_handler
        assert command.template_cache is None
        mock_file_handler_create.assert_called_once()

    def test_initialize_caches_config_reader_error(
        self, command, mock_config_reader, mock_file_handler_create
    ):
        """Test that ConfigReader errors are propagated."""
        mock_config_reader.side_effect = DnfError("Config file not found")

        with pytest.raises(DnfError, match="Config file not found"):
            command._initialize_caches()

        assert command.file_cache is None
        assert command.template_cache is None

    def test_initialize_caches_file_handler_error(
        self, command, mock_config_reader, mock_file_handler_create
    ):
        """Test error handling when FileHandler.create fails."""
        mock_config = Mock()
        mock_config.baseurl = "https://example.com/supportinfo.xml"
        mock_config.templateurl = None
        mock_config.metadata_expire = 3600
        mock_config_reader.return_value = mock_config

        mock_file_handler_create.side_effect = Exception("Failed to create file handler")

        with pytest.raises(Exception, match="Failed to create file handler"):
            command._initialize_caches()

    def test_initialize_caches_with_different_metadata_expire_values(
        self, command, mock_config_reader, mock_file_handler_create
    ):
        """Test cache initialization with various metadata_expire values."""
        test_cases = [
            0,  # Always check
            -1,  # Infinite cache
            3600,  # 1 hour
            86400,  # 1 day
            7776000,  # 90 days
        ]

        for metadata_expire in test_cases:
            command.file_cache = None
            command.template_cache = None

            mock_config = Mock()
            mock_config.baseurl = "https://example.com/supportinfo.xml"
            mock_config.templateurl = "https://example.com/supportinfo.xsd"
            mock_config.metadata_expire = metadata_expire
            mock_config_reader.return_value = mock_config

            mock_file_handler = Mock()
            mock_template_handler = Mock()
            mock_file_handler_create.side_effect = [mock_file_handler, mock_template_handler]

            result = command._initialize_caches()

            assert result is True
            assert mock_file_handler_create.call_count == 2

            for call in mock_file_handler_create.call_args_list:
                assert call[1]["metadata_expire"] == metadata_expire

            mock_file_handler_create.reset_mock()

    def test_initialize_caches_called_multiple_times(
        self, command, mock_config_reader, mock_file_handler_create
    ):
        """Test that calling _initialize_caches multiple times overwrites caches."""
        mock_config = Mock()
        mock_config.baseurl = "https://example.com/supportinfo.xml"
        mock_config.templateurl = None
        mock_config.metadata_expire = 3600
        mock_config_reader.return_value = mock_config

        mock_handler_1 = Mock()
        mock_handler_2 = Mock()

        # First call
        mock_file_handler_create.return_value = mock_handler_1
        result1 = command._initialize_caches()
        assert result1 is True
        assert command.file_cache == mock_handler_1

        # Second call (should overwrite)
        mock_file_handler_create.return_value = mock_handler_2
        result2 = command._initialize_caches()
        assert result2 is True
        assert command.file_cache == mock_handler_2

        assert mock_file_handler_create.call_count == 2


class TestGetSupportInfoFiles(TestSupportInfoCommand):
    """Tests for _get_support_info_files method."""

    @pytest.fixture
    def mock_initialize_caches(self):
        """Fixture to mock _initialize_caches method."""
        with patch.object(SupportInfoCommand, "_initialize_caches") as mock:
            yield mock

    def test_get_support_info_files_with_both_caches(self, command):
        """Test getting both XML and XSD file paths."""
        command.file_cache = Mock()
        command.file_cache.get_file_path.return_value = "/path/to/support_info.xml"
        command.template_cache = Mock()
        command.template_cache.get_file_path.return_value = "/path/to/support_info.xsd"

        xml_path, xsd_path = command._get_support_info_files()

        assert xml_path == "/path/to/support_info.xml"
        assert xsd_path == "/path/to/support_info.xsd"
        command.file_cache.get_file_path.assert_called_once()
        command.template_cache.get_file_path.assert_called_once()

    def test_get_support_info_files_without_template_cache(self, command):
        """Test getting only XML file path when template_cache is None."""
        command.file_cache = Mock()
        command.file_cache.get_file_path.return_value = "/path/to/support_info.xml"
        command.template_cache = None

        xml_path, xsd_path = command._get_support_info_files()

        assert xml_path == "/path/to/support_info.xml"
        assert xsd_path is None
        command.file_cache.get_file_path.assert_called_once()

    def test_get_support_info_files_initializes_cache_if_needed(
        self, command, mock_initialize_caches
    ):
        """Test that caches are initialized if file_cache doesn't exist."""
        command.file_cache = None
        command.template_cache = None
        mock_initialize_caches.return_value = True

        # After initialization, set up the mock
        def init_side_effect(config=None):
            command.file_cache = Mock()
            command.file_cache.get_file_path.return_value = "/path/to/support_info.xml"
            return True

        mock_initialize_caches.side_effect = init_side_effect

        xml_path, xsd_path = command._get_support_info_files()

        mock_initialize_caches.assert_called_once()
        assert xml_path == "/path/to/support_info.xml"
        assert xsd_path is None

    def test_get_support_info_files_returns_none_when_init_fails(
        self, command, mock_initialize_caches
    ):
        """Test that (None, None) is returned when initialization fails."""
        command.file_cache = None
        mock_initialize_caches.return_value = False

        xml_path, xsd_path = command._get_support_info_files()

        assert xml_path is None
        assert xsd_path is None
        mock_initialize_caches.assert_called_once()

    def test_get_support_info_files_returns_none_when_xml_path_fails(self, command):
        """Test that (None, None) is returned when XML file path retrieval fails."""
        command.file_cache = Mock()
        command.file_cache.get_file_path.return_value = None

        xml_path, xsd_path = command._get_support_info_files()

        assert xml_path is None
        assert xsd_path is None
        command.file_cache.get_file_path.assert_called_once()

    def test_get_support_info_files_logs_warning_when_xsd_fails(self, command):
        """Test that warning is logged when XSD file path retrieval fails."""
        command.file_cache = Mock()
        command.file_cache.get_file_path.return_value = "/path/to/support_info.xml"
        command.template_cache = Mock()
        command.template_cache.get_file_path.return_value = None

        with patch("dnf_support_info_plugin.package_support.logger") as mock_logger:
            xml_path, xsd_path = command._get_support_info_files()

            assert xml_path == "/path/to/support_info.xml"
            assert xsd_path is None
            mock_logger.warning.assert_called_once()
            assert "Unable to retrieve XSD file" in mock_logger.warning.call_args[0][0]


class TestHandlePkg(TestSupportInfoCommand):
    """Tests for _handle_pkg method package-not-found behavior."""

    @pytest.fixture
    def command_with_service(self, command):
        """Create command with mocked service and formatter."""
        command.service = Mock()
        command.dnf_service = Mock()
        command.dnf_service.get_package_states.return_value = {}
        command.opts = Mock()
        return command

    def test_handle_pkg_all_found(self, command_with_service, capsys):
        """Test that all requested packages found results in no error."""
        command = command_with_service
        command.opts.packages = ["pkg1", "pkg2"]

        mock_pkg_info1 = Mock()
        mock_pkg_info2 = Mock()
        command.service.get_package_info.side_effect = [mock_pkg_info1, mock_pkg_info2]

        mock_formatter = Mock()
        mock_formatter.format_packages.return_value = "formatted output"

        command._handle_pkg(mock_formatter)

        mock_formatter.format_packages.assert_called_once_with([mock_pkg_info1, mock_pkg_info2])
        captured = capsys.readouterr()
        assert "formatted output" in captured.out

    def test_handle_pkg_all_not_found(self, command_with_service):
        """Test that all packages not found raises DnfError."""
        command = command_with_service
        command.opts.packages = ["missing1", "missing2"]

        command.service.get_package_info.return_value = None

        mock_formatter = Mock()

        with pytest.raises(DnfError, match="Package\\(s\\) not found in support info"):
            command._handle_pkg(mock_formatter)

        mock_formatter.format_packages.assert_not_called()

    def test_handle_pkg_partial_not_found(self, command_with_service, capsys):
        """Test partial miss: prints found packages, logs warning for missing, no DnfError."""
        command = command_with_service
        command.opts.packages = ["found_pkg", "missing_pkg"]

        mock_pkg_info = Mock()

        def get_info(name, states):
            return mock_pkg_info if name == "found_pkg" else None

        command.service.get_package_info.side_effect = get_info

        mock_formatter = Mock()
        mock_formatter.format_packages.return_value = "found package output"

        with patch("dnf_support_info_plugin.package_support.logger") as mock_logger:
            command._handle_pkg(mock_formatter)

            mock_formatter.format_packages.assert_called_once_with([mock_pkg_info])
            captured = capsys.readouterr()
            assert "found package output" in captured.out
            mock_logger.warning.assert_called_once()
            assert "missing_pkg" in mock_logger.warning.call_args[0][0]


class TestHandleLegacyConversion(TestSupportInfoCommand):
    """Tests for _handle_legacy_conversion with root/non-root behavior."""

    @pytest.fixture
    def mock_euid_root(self):
        """Mock os.geteuid to return 0 (root)."""
        with patch("dnf_support_info_plugin.package_support.os.geteuid", return_value=0):
            yield

    @pytest.fixture
    def mock_euid_nonroot(self):
        """Mock os.geteuid to return 1000 (non-root)."""
        with patch("dnf_support_info_plugin.package_support.os.geteuid", return_value=1000):
            yield

    @pytest.fixture
    def mock_legacy_location(self, tmp_path):
        """Mock _get_legacy_location to return a temp path."""
        legacy_path = tmp_path / "dnf-plugins" / "support_info.xml"
        with patch.object(
            SupportInfoCommand,
            "_get_legacy_location",
            return_value=legacy_path,
        ):
            yield legacy_path

    @pytest.fixture
    def mock_converter(self):
        """Mock LegacyConverter.

        By default, convert(target_path) writes a minimal valid legacy XML
        to the given path so the downstream os.replace() in the production
        code can atomically rename it onto legacy_location. Tests that need
        to simulate failure can override the side_effect.
        """

        def fake_convert(target_path: str) -> None:
            with open(target_path, "w") as f:
                f.write("<package_support/>")

        with patch("dnf_support_info_plugin.package_support.LegacyConverter") as mock:
            mock.return_value.convert.side_effect = fake_convert
            yield mock

    @pytest.fixture
    def mock_create_symlink(self):
        """Mock _create_legacy_symlink."""
        with patch.object(SupportInfoCommand, "_create_legacy_symlink") as mock:
            yield mock

    def test_root_converts_and_saves(
        self,
        command,
        mock_euid_root,
        mock_legacy_location,
        mock_converter,
        mock_create_symlink,
    ):
        """Test root user converts XML and saves to legacy location."""
        mock_legacy_location.parent.mkdir(parents=True, exist_ok=True)

        result = command._handle_legacy_conversion("/path/to/v1.xml")

        assert result == str(mock_legacy_location)
        mock_converter.assert_called_once_with("/path/to/v1.xml")
        # convert() receives a tempfile path (not legacy_location directly) —
        # writing goes through a tempfile + os.replace for atomicity.
        mock_converter.return_value.convert.assert_called_once()
        tmp_arg = mock_converter.return_value.convert.call_args.args[0]
        assert tmp_arg != str(mock_legacy_location)
        assert tmp_arg.startswith(str(mock_legacy_location.parent))
        # Legacy file exists with the converted content after os.replace
        assert mock_legacy_location.read_text() == "<package_support/>"

    def test_root_creates_symlink(
        self,
        command,
        mock_euid_root,
        mock_legacy_location,
        mock_converter,
        mock_create_symlink,
    ):
        """Test root user creates symlink after conversion."""
        mock_legacy_location.parent.mkdir(parents=True, exist_ok=True)

        command._handle_legacy_conversion("/path/to/v1.xml")

        mock_create_symlink.assert_called_once()

    def test_nonroot_uses_existing_legacy_file(
        self,
        command,
        mock_euid_nonroot,
        mock_legacy_location,
    ):
        """Test non-root user uses existing legacy file."""
        # Create the legacy file so it exists
        mock_legacy_location.parent.mkdir(parents=True, exist_ok=True)
        mock_legacy_location.write_text("<package_support/>")

        result = command._handle_legacy_conversion("/path/to/v1.xml")

        assert result == str(mock_legacy_location)

    def test_nonroot_no_legacy_file_raises(
        self,
        command,
        mock_euid_nonroot,
        mock_legacy_location,
    ):
        """Test non-root user without existing legacy file gets clear error."""
        # Don't create the file — it doesn't exist
        assert not mock_legacy_location.exists()

        with pytest.raises(DnfError, match="root privileges"):
            command._handle_legacy_conversion("/path/to/v1.xml")

    def test_nonroot_error_message_has_instructions(
        self,
        command,
        mock_euid_nonroot,
        mock_legacy_location,
    ):
        """Test error message includes sudo instructions."""
        with pytest.raises(DnfError, match=r"sudo dnf supportinfo --sync"):
            command._handle_legacy_conversion("/path/to/v1.xml")

    def test_nonroot_does_not_call_converter(
        self,
        command,
        mock_euid_nonroot,
        mock_legacy_location,
        mock_converter,
    ):
        """Test non-root user never triggers conversion."""
        # Create existing file
        mock_legacy_location.parent.mkdir(parents=True, exist_ok=True)
        mock_legacy_location.write_text("<package_support/>")

        command._handle_legacy_conversion("/path/to/v1.xml")

        mock_converter.assert_not_called()

    def test_root_conversion_error_raises_dnf_error(
        self,
        command,
        mock_euid_root,
        mock_legacy_location,
        mock_converter,
    ):
        """Test conversion failure raises DnfError with guidance."""
        mock_legacy_location.parent.mkdir(parents=True, exist_ok=True)
        mock_converter.return_value.convert.side_effect = Exception("parse error")

        with pytest.raises(DnfError, match="Failed to convert"):
            command._handle_legacy_conversion("/path/to/v1.xml")

    def test_root_conversion_writes_world_readable_file(
        self,
        command,
        mock_euid_root,
        mock_legacy_location,
        mock_converter,
        mock_create_symlink,
    ):
        """Legacy file must be world-readable so non-root users can read it.

        Regression guard: tempfile.mkstemp() creates files 0o600, and
        converter.convert() writes to the existing file, so without an
        explicit chmod the 0o600 mode survives os.replace() and breaks
        non-root reads.
        """
        mock_legacy_location.parent.mkdir(parents=True, exist_ok=True)

        command._handle_legacy_conversion("/path/to/v1.xml")

        mode = mock_legacy_location.stat().st_mode & 0o777
        assert mode == 0o644, f"Expected 0o644, got {oct(mode)}"

    def test_root_conversion_failure_does_not_corrupt_legacy_file(
        self,
        command,
        mock_euid_root,
        mock_legacy_location,
        mock_converter,
        mock_create_symlink,
    ):
        """Conversion failure must leave legacy_location untouched (atomic write).

        Regression guard: writing directly to legacy_location on failure
        could leave the file partially written or with the wrong contents.
        Atomic tempfile + os.replace ensures legacy_location is either the
        fully-converted content or unchanged.
        """
        mock_legacy_location.parent.mkdir(parents=True, exist_ok=True)
        # Simulate an existing good legacy file from a prior successful run
        mock_legacy_location.write_text("<package_support>good</package_support>")
        original_content = mock_legacy_location.read_text()
        original_mtime = mock_legacy_location.stat().st_mtime

        # Partial write: the converter writes garbage to the given path, then fails
        def bad_convert(target_path: str) -> None:
            with open(target_path, "w") as f:
                f.write("<partial garbage")
            raise Exception("parse error")

        mock_converter.return_value.convert.side_effect = bad_convert

        with pytest.raises(DnfError, match="Failed to convert"):
            command._handle_legacy_conversion("/path/to/v1.xml")

        # Legacy file is unchanged — not corrupted by the partial write
        assert mock_legacy_location.read_text() == original_content
        assert mock_legacy_location.stat().st_mtime == original_mtime
        # No leftover .tmp files in the directory
        tmp_files = list(mock_legacy_location.parent.glob(f".{mock_legacy_location.name}.*.tmp"))
        assert tmp_files == [], f"Tempfiles leaked: {tmp_files}"
        # Marker must not be advanced on a failed conversion — next run will
        # see the mismatch (or missing marker) and re-convert.
        marker = mock_legacy_location.with_name(mock_legacy_location.name + ".source-sha256")
        assert not marker.exists(), "Marker must not be written on failed conversion"

    def test_root_creates_parent_directory(
        self,
        command,
        mock_euid_root,
        mock_legacy_location,
        mock_converter,
        mock_create_symlink,
    ):
        """Test root user creates parent directory if it doesn't exist."""
        # Don't pre-create — the method should create it
        assert not mock_legacy_location.parent.exists()

        command._handle_legacy_conversion("/path/to/v1.xml")

        assert mock_legacy_location.parent.exists()

    def test_nonroot_stale_marker_logs_warning(
        self,
        command,
        mock_euid_nonroot,
        mock_legacy_location,
    ):
        """Non-root: warn when the source-hash marker doesn't match the source."""
        mock_legacy_location.parent.mkdir(parents=True, exist_ok=True)
        mock_legacy_location.write_text("<package_support/>")
        # Marker records a different hash than the live source's
        marker = mock_legacy_location.with_name(mock_legacy_location.name + ".source-sha256")
        marker.write_text("0" * 64 + "\n")

        source_file = mock_legacy_location.parent / "source.xml"
        source_file.write_text("<package_support schema_version='1.0'/>")

        with patch("dnf_support_info_plugin.package_support.logger") as mock_logger:
            result = command._handle_legacy_conversion(str(source_file))

            assert result == str(mock_legacy_location)
            mock_logger.warning.assert_called_once()
            assert "does not match the latest source data" in mock_logger.warning.call_args[0][0]

    def test_nonroot_marker_matches_no_warning(
        self,
        command,
        mock_euid_nonroot,
        mock_legacy_location,
    ):
        """Non-root: no warning when the marker matches the source's SHA-256."""
        import hashlib

        mock_legacy_location.parent.mkdir(parents=True, exist_ok=True)
        mock_legacy_location.write_text("<package_support/>")
        source_file = mock_legacy_location.parent / "source.xml"
        source_bytes = b"<package_support schema_version='1.0'/>"
        source_file.write_bytes(source_bytes)
        # Marker records the actual SHA-256 of the source bytes
        digest = hashlib.sha256(source_bytes).hexdigest()
        marker = mock_legacy_location.with_name(mock_legacy_location.name + ".source-sha256")
        marker.write_text(digest + "\n")

        with patch("dnf_support_info_plugin.package_support.logger") as mock_logger:
            result = command._handle_legacy_conversion(str(source_file))

            assert result == str(mock_legacy_location)
            mock_logger.warning.assert_not_called()

    def test_nonroot_missing_source_skips_warning(
        self,
        command,
        mock_euid_nonroot,
        mock_legacy_location,
    ):
        """Non-root: a missing source path is treated as 'unknown', no warning."""
        mock_legacy_location.parent.mkdir(parents=True, exist_ok=True)
        mock_legacy_location.write_text("<package_support/>")

        with patch("dnf_support_info_plugin.package_support.logger") as mock_logger:
            result = command._handle_legacy_conversion("/nonexistent/source.xml")

            assert result == str(mock_legacy_location)
            mock_logger.warning.assert_not_called()


class TestLegacyMarker(TestSupportInfoCommand):
    """Tests for the SHA-256 source-hash marker that tracks legacy freshness.

    The marker is content-derived: it records the SHA-256 of the source XML
    used for the last successful conversion. It does not depend on file
    mtime or any in-XML attribute (e.g. current_as), so it is immune to
    clock skew, manual touch, and schema-attribute deprecation.
    """

    @staticmethod
    def _sha256(data: bytes) -> str:
        import hashlib

        return hashlib.sha256(data).hexdigest()

    def test_sha256_matches_external_calculation(self, command, tmp_path):
        """_sha256_of_file returns the same digest as hashlib on the same bytes."""
        f = tmp_path / "x.xml"
        f.write_bytes(b"hello world\n")
        assert command._sha256_of_file(f) == self._sha256(b"hello world\n")

    def test_sha256_returns_none_on_missing_file(self, command, tmp_path):
        """Missing file -> None so the caller falls back to converting."""
        assert command._sha256_of_file(tmp_path / "nope.xml") is None

    def test_marker_matches_when_digests_equal(self, command, tmp_path):
        """Marker present, contents equal source digest -> True."""
        legacy = tmp_path / "support_info.xml"
        legacy.write_text("<package_support/>")
        digest = self._sha256(b"src")
        legacy.with_name(legacy.name + ".source-sha256").write_text(digest + "\n")

        assert command._legacy_marker_matches(legacy, digest) is True

    def test_marker_mismatch_when_digests_differ(self, command, tmp_path):
        """Marker present but different digest -> False (re-convert)."""
        legacy = tmp_path / "support_info.xml"
        legacy.write_text("<package_support/>")
        legacy.with_name(legacy.name + ".source-sha256").write_text("0" * 64 + "\n")

        assert command._legacy_marker_matches(legacy, "1" * 64) is False

    def test_marker_missing_returns_false(self, command, tmp_path):
        """No marker file -> False (re-convert)."""
        legacy = tmp_path / "support_info.xml"
        legacy.write_text("<package_support/>")
        # No sidecar written
        assert command._legacy_marker_matches(legacy, self._sha256(b"src")) is False

    def test_marker_legacy_missing_returns_false(self, command, tmp_path):
        """Legacy file itself missing -> False (re-convert)."""
        legacy = tmp_path / "missing.xml"
        # Both files absent
        assert command._legacy_marker_matches(legacy, self._sha256(b"src")) is False

    def test_write_marker_is_atomic_and_world_readable(self, command, tmp_path):
        """_write_legacy_marker writes 0o644 atomically (tempfile + os.replace)."""
        legacy = tmp_path / "support_info.xml"
        legacy.write_text("<package_support/>")
        digest = self._sha256(b"src")

        command._write_legacy_marker(legacy, digest)

        marker = legacy.with_name(legacy.name + ".source-sha256")
        assert marker.read_text().strip() == digest
        mode = marker.stat().st_mode & 0o777
        assert mode == 0o644, f"Expected 0o644, got {oct(mode)}"
        # No leftover .tmp files
        leftovers = [p for p in legacy.parent.iterdir() if p.name.endswith(".tmp")]
        assert leftovers == [], f"Tempfiles leaked: {leftovers}"

    def test_handle_legacy_conversion_skips_when_marker_matches(self, command, tmp_path):
        """Root: skip conversion when marker records the source's SHA-256."""
        source = tmp_path / "source.xml"
        legacy = tmp_path / "dnf-plugins" / "support_info.xml"
        legacy.parent.mkdir(parents=True)
        source_bytes = b"<package_support schema_version='1.0'/>"
        source.write_bytes(source_bytes)
        legacy.write_text("<package_support/>")
        digest = self._sha256(source_bytes)
        legacy.with_name(legacy.name + ".source-sha256").write_text(digest + "\n")

        with patch(
            "dnf_support_info_plugin.package_support.os.geteuid", return_value=0
        ), patch.object(SupportInfoCommand, "_get_legacy_location", return_value=legacy), patch(
            "dnf_support_info_plugin.package_support.LegacyConverter"
        ) as mock_converter, patch.object(
            SupportInfoCommand, "_create_legacy_symlink"
        ) as mock_symlink:
            result = command._handle_legacy_conversion(str(source))

            assert result == str(legacy)
            mock_converter.assert_not_called()
            # Symlink is still refreshed — it's cheap and idempotent
            mock_symlink.assert_called_once()

    def test_handle_legacy_conversion_writes_marker_after_replace(self, command, tmp_path):
        """Root: a successful conversion writes the marker with the source's SHA-256."""
        source = tmp_path / "source.xml"
        legacy = tmp_path / "dnf-plugins" / "support_info.xml"
        legacy.parent.mkdir(parents=True)
        source_bytes = b"<package_support schema_version='1.0'/>"
        source.write_bytes(source_bytes)

        # Default mock_converter writes a minimal legacy XML to the temp path
        def fake_convert(target_path: str) -> None:
            with open(target_path, "w") as f:
                f.write("<package_support/>")

        with patch(
            "dnf_support_info_plugin.package_support.os.geteuid", return_value=0
        ), patch.object(SupportInfoCommand, "_get_legacy_location", return_value=legacy), patch(
            "dnf_support_info_plugin.package_support.LegacyConverter"
        ) as mock_converter, patch.object(
            SupportInfoCommand, "_create_legacy_symlink"
        ):
            mock_converter.return_value.convert.side_effect = fake_convert
            command._handle_legacy_conversion(str(source))

        marker = legacy.with_name(legacy.name + ".source-sha256")
        assert marker.exists()
        assert marker.read_text().strip() == self._sha256(source_bytes)

    def test_immune_to_mtime_changes(self, command, tmp_path):
        """Marker comparison is unaffected by mtime games — only bytes matter."""
        legacy = tmp_path / "support_info.xml"
        legacy.write_text("<package_support/>")
        digest = self._sha256(b"src")
        marker = legacy.with_name(legacy.name + ".source-sha256")
        marker.write_text(digest + "\n")
        # Force legacy to look ancient and marker to look from the future
        os.utime(legacy, (1000, 1000))
        os.utime(marker, (9_999_999, 9_999_999))

        assert command._legacy_marker_matches(legacy, digest) is True

    def test_marker_path_appends_suffix(self, command, tmp_path):
        """_legacy_marker_path returns ``<legacy>.source-sha256`` next to the file."""
        legacy = tmp_path / "support_info.xml"
        marker = command._legacy_marker_path(legacy)
        assert marker == tmp_path / "support_info.xml.source-sha256"

    def test_marker_matches_tolerates_trailing_whitespace(self, command, tmp_path):
        """Marker contents are stripped before comparison (handles trailing newline)."""
        legacy = tmp_path / "support_info.xml"
        legacy.write_text("<package_support/>")
        digest = self._sha256(b"src")
        legacy.with_name(legacy.name + ".source-sha256").write_text(f"  {digest}  \n\n")

        assert command._legacy_marker_matches(legacy, digest) is True

    def test_marker_matches_returns_false_on_unreadable_marker(self, command, tmp_path):
        """IO error reading the marker -> False (re-convert).

        Make the marker unreadable via chmod 000. Skip on platforms where
        permission bits don't apply (e.g. running as root with effective
        bypass) or chmod has no effect.
        """
        legacy = tmp_path / "support_info.xml"
        legacy.write_text("<package_support/>")
        marker = legacy.with_name(legacy.name + ".source-sha256")
        marker.write_text("0" * 64 + "\n")
        marker.chmod(0o000)
        try:
            # If we can still read it (running as root, etc.), skip
            try:
                marker.read_text()
                pytest.skip("chmod 000 did not block read; running as root or non-Unix FS")
            except OSError:
                pass

            with patch("dnf_support_info_plugin.package_support.logger") as mock_logger:
                assert command._legacy_marker_matches(legacy, "0" * 64) is False
                mock_logger.debug.assert_called()
        finally:
            # Restore so tmp_path cleanup can remove the file
            marker.chmod(0o600)

    def test_sha256_streams_large_files(self, command, tmp_path):
        """SHA-256 is computed correctly across the streaming chunk boundary."""
        import hashlib

        f = tmp_path / "big.xml"
        # Two full 64 KB chunks plus a partial trailing chunk
        payload = (b"abcd" * 16384) + (b"xyz" * 10923)
        assert len(payload) > 64 * 1024
        f.write_bytes(payload)

        assert command._sha256_of_file(f) == hashlib.sha256(payload).hexdigest()

    def test_write_marker_logs_warning_on_failure_without_raising(self, command, tmp_path):
        """Marker write failure is logged but does not raise — body is already in place."""
        legacy = tmp_path / "support_info.xml"
        legacy.write_text("<package_support/>")

        with patch(
            "dnf_support_info_plugin.package_support.tempfile.mkstemp",
            side_effect=OSError("disk full"),
        ), patch("dnf_support_info_plugin.package_support.logger") as mock_logger:
            command._write_legacy_marker(legacy, self._sha256(b"src"))

            mock_logger.warning.assert_called_once()
            assert "Could not persist legacy source-hash marker" in (
                mock_logger.warning.call_args[0][0]
            )

    def test_handle_legacy_conversion_reconverts_on_marker_mismatch(self, command, tmp_path):
        """Root: a mismatched marker triggers conversion and updates the marker."""
        source = tmp_path / "source.xml"
        legacy = tmp_path / "dnf-plugins" / "support_info.xml"
        legacy.parent.mkdir(parents=True)
        source_bytes = b"<package_support schema_version='1.0'/>"
        source.write_bytes(source_bytes)
        legacy.write_text("<package_support>old</package_support>")
        # Marker records a stale digest from a previous source
        marker = legacy.with_name(legacy.name + ".source-sha256")
        marker.write_text("0" * 64 + "\n")

        def fake_convert(target_path: str) -> None:
            with open(target_path, "w") as f:
                f.write("<package_support>new</package_support>")

        with patch(
            "dnf_support_info_plugin.package_support.os.geteuid", return_value=0
        ), patch.object(SupportInfoCommand, "_get_legacy_location", return_value=legacy), patch(
            "dnf_support_info_plugin.package_support.LegacyConverter"
        ) as mock_converter, patch.object(
            SupportInfoCommand, "_create_legacy_symlink"
        ):
            mock_converter.return_value.convert.side_effect = fake_convert
            command._handle_legacy_conversion(str(source))

        # Body replaced with the new content
        assert legacy.read_text() == "<package_support>new</package_support>"
        # Marker advanced to the actual source's digest
        assert marker.read_text().strip() == self._sha256(source_bytes)


class TestHandleSync(TestSupportInfoCommand):
    """Tests for _handle_sync method."""

    @pytest.fixture
    def mock_get_support_info_files(self):
        """Mock _get_support_info_files to return controlled paths."""
        with patch.object(SupportInfoCommand, "_get_support_info_files") as mock:
            mock.return_value = ("/cache/supportinfo.xml", "/cache/supportinfo.xsd")
            yield mock

    @pytest.fixture
    def mock_create_handler(self):
        """Mock _create_handler to return a controlled handler."""
        with patch.object(SupportInfoCommand, "_create_handler") as mock:
            yield mock

    @pytest.fixture
    def mock_handle_legacy_conversion(self):
        """Mock _handle_legacy_conversion."""
        with patch.object(SupportInfoCommand, "_handle_legacy_conversion") as mock:
            mock.return_value = "/usr/lib/python3.9/site-packages/dnf-plugins/support_info.xml"
            yield mock

    def test_sync_downloads_and_caches_xml(
        self, command, mock_get_support_info_files, mock_create_handler
    ):
        """Test --sync downloads and caches the support info XML."""
        config = Mock()
        config.legacy = False

        command._handle_sync(config)

        mock_get_support_info_files.assert_called_once_with(config)

    def test_sync_no_legacy_skips_conversion(
        self,
        command,
        mock_get_support_info_files,
        mock_create_handler,
        mock_handle_legacy_conversion,
    ):
        """Test --sync with legacy=False does not trigger conversion."""
        config = Mock()
        config.legacy = False

        command._handle_sync(config)

        mock_handle_legacy_conversion.assert_not_called()

    def test_sync_legacy_v1_converts(
        self,
        command,
        mock_get_support_info_files,
        mock_create_handler,
        mock_handle_legacy_conversion,
    ):
        """Test --sync with legacy=True and V1.0 XML triggers conversion."""
        from supportinfo.handler import SupportinfoSchemaVersions

        config = Mock()
        config.legacy = True

        mock_handler = Mock()
        mock_handler.schema_version = SupportinfoSchemaVersions.V1_0
        mock_create_handler.return_value = mock_handler

        command._handle_sync(config)

        # First call parses the downloaded XML; second call re-parses the
        # converted legacy file (from _load_support_info).
        assert mock_create_handler.call_count == 2
        mock_create_handler.assert_any_call("/cache/supportinfo.xml", "/cache/supportinfo.xsd")
        mock_handle_legacy_conversion.assert_called_once_with("/cache/supportinfo.xml")

    def test_sync_legacy_already_legacy_skips_conversion(
        self,
        command,
        mock_get_support_info_files,
        mock_create_handler,
        mock_handle_legacy_conversion,
    ):
        """Test --sync with legacy=True but already-legacy XML skips conversion."""
        from supportinfo.handler import SupportinfoSchemaVersions

        config = Mock()
        config.legacy = True

        mock_handler = Mock()
        mock_handler.schema_version = SupportinfoSchemaVersions.LEGACY
        mock_create_handler.return_value = mock_handler

        command._handle_sync(config)

        mock_handle_legacy_conversion.assert_not_called()

    def test_sync_propagates_download_error(self, command):
        """Test that download errors from _get_support_info_files propagate."""
        with patch.object(
            SupportInfoCommand,
            "_get_support_info_files",
            side_effect=DnfError("Download failed"),
        ):
            config = Mock()
            config.legacy = False

            with pytest.raises(DnfError, match="Download failed"):
                command._handle_sync(config)

    def test_sync_propagates_legacy_conversion_error(
        self,
        command,
        mock_get_support_info_files,
        mock_create_handler,
    ):
        """Test that legacy conversion errors propagate."""
        from supportinfo.handler import SupportinfoSchemaVersions

        config = Mock()
        config.legacy = True

        mock_handler = Mock()
        mock_handler.schema_version = SupportinfoSchemaVersions.V1_0
        mock_create_handler.return_value = mock_handler

        with patch.object(
            SupportInfoCommand,
            "_handle_legacy_conversion",
            side_effect=DnfError("Conversion failed"),
        ):
            with pytest.raises(DnfError, match="Conversion failed"):
                command._handle_sync(config)

    def test_sync_logs_completion(self, command, mock_get_support_info_files, mock_create_handler):
        """Test that --sync logs a completion message."""
        config = Mock()
        config.legacy = False

        with patch("dnf_support_info_plugin.package_support.logger") as mock_logger:
            command._handle_sync(config)

            mock_logger.info.assert_any_call("Support info sync complete")

    def test_sync_without_xsd(self, command, mock_create_handler):
        """Test --sync works when templateurl is not configured (no XSD)."""
        with patch.object(
            SupportInfoCommand,
            "_get_support_info_files",
            return_value=("/cache/supportinfo.xml", None),
        ):
            config = Mock()
            config.legacy = False

            command._handle_sync(config)
            # No error — XSD is optional

    def test_sync_raises_when_file_path_is_none(self, command):
        """Test --sync raises DnfError when _get_support_info_files returns None."""
        with patch.object(
            SupportInfoCommand,
            "_get_support_info_files",
            return_value=(None, None),
        ):
            config = Mock()
            config.legacy = False

            with pytest.raises(DnfError, match="Failed to retrieve support info XML"):
                command._handle_sync(config)


class TestRunSyncDispatch(TestSupportInfoCommand):
    """Tests for --sync dispatch in run() method."""

    @pytest.fixture
    def mock_config_reader(self):
        """Fixture to patch ConfigReader."""
        with patch("dnf_support_info_plugin.package_support.ConfigReader") as mock:
            yield mock

    @pytest.fixture
    def mock_handle_sync(self):
        """Mock _handle_sync."""
        with patch.object(SupportInfoCommand, "_handle_sync") as mock:
            yield mock

    @pytest.fixture
    def mock_get_support_info_files(self):
        """Mock _get_support_info_files for non-sync paths."""
        with patch.object(SupportInfoCommand, "_get_support_info_files") as mock:
            mock.return_value = ("/cache/supportinfo.xml", None)
            yield mock

    @pytest.fixture
    def mock_create_handler(self):
        """Mock _create_handler for non-sync paths."""
        with patch.object(SupportInfoCommand, "_create_handler") as mock:
            yield mock

    def test_run_dispatches_to_sync(self, command, mock_config_reader, mock_handle_sync):
        """Test that run() dispatches to _handle_sync when --sync is set."""
        command.opts = Mock()
        command.opts.clean_cache = False
        command.opts.sync = True
        command.opts.packages = None
        command.opts.filters = None

        mock_config = Mock()
        mock_config_reader.return_value = mock_config

        command.run()

        mock_handle_sync.assert_called_once_with(mock_config)

    def test_run_sync_returns_early(
        self,
        command,
        mock_config_reader,
        mock_handle_sync,
        mock_get_support_info_files,
    ):
        """Test that --sync returns early without loading DNF sack."""
        command.opts = Mock()
        command.opts.clean_cache = False
        command.opts.sync = True
        command.opts.packages = None
        command.opts.filters = None

        mock_config_reader.return_value = Mock()

        command.run()

        # run() must dispatch to _handle_sync and NOT fall through to the
        # main query path (which would call _get_support_info_files directly).
        mock_handle_sync.assert_called_once()
        mock_get_support_info_files.assert_not_called()

    def test_run_sync_with_pkg_raises(self, command, mock_config_reader):
        """Test that --sync combined with --pkg raises DnfError."""
        command.opts = Mock()
        command.opts.clean_cache = False
        command.opts.sync = True
        command.opts.packages = ["bash"]
        command.opts.filters = None

        with pytest.raises(DnfError, match="--sync cannot be combined with --pkg or --show"):
            command.run()

    def test_run_sync_with_show_raises(self, command, mock_config_reader):
        """Test that --sync combined with --show raises DnfError."""
        command.opts = Mock()
        command.opts.clean_cache = False
        command.opts.sync = True
        command.opts.packages = None
        command.opts.filters = ["installed"]

        with pytest.raises(DnfError, match="--sync cannot be combined with --pkg or --show"):
            command.run()

    def test_run_sync_with_both_pkg_and_show_raises(self, command, mock_config_reader):
        """Test that --sync combined with both --pkg and --show raises DnfError."""
        command.opts = Mock()
        command.opts.clean_cache = False
        command.opts.sync = True
        command.opts.packages = ["bash"]
        command.opts.filters = ["installed"]

        with pytest.raises(DnfError, match="--sync cannot be combined with --pkg or --show"):
            command.run()

    def test_run_clean_cache_takes_priority_over_sync(self, command):
        """Test that --clean-cache is handled before --sync."""
        command.opts = Mock()
        command.opts.clean_cache = True
        command.opts.sync = True
        command.opts.packages = None
        command.opts.filters = None

        with patch.object(SupportInfoCommand, "_clean_cache") as mock_clean, patch.object(
            SupportInfoCommand, "_handle_sync"
        ) as mock_sync:
            command.run()

            mock_clean.assert_called_once()
            mock_sync.assert_not_called()

    def test_run_without_sync_does_not_call_handle_sync(
        self,
        command,
        mock_config_reader,
        mock_handle_sync,
        mock_get_support_info_files,
        mock_create_handler,
    ):
        """Test that run() without --sync does not call _handle_sync."""
        command.opts = Mock()
        command.opts.clean_cache = False
        command.opts.sync = False
        command.opts.packages = None
        command.opts.filters = None
        command.opts.list_filters = False
        command.opts.show_json = False
        command.opts.show_xml = False

        mock_config = Mock()
        mock_config.legacy = False
        mock_config_reader.return_value = mock_config

        mock_handler = Mock()
        mock_handler.schema_version = Mock()
        mock_create_handler.return_value = mock_handler

        command.run()

        mock_handle_sync.assert_not_called()

    def test_run_sync_propagates_config_error(self, command, mock_config_reader):
        """Test that ConfigReader errors propagate through --sync path."""
        command.opts = Mock()
        command.opts.clean_cache = False
        command.opts.sync = True
        command.opts.packages = None
        command.opts.filters = None

        mock_config_reader.side_effect = DnfError("Config file not found")

        with pytest.raises(DnfError, match="Config file not found"):
            command.run()


class TestSetArgparserSync:
    """Tests for --sync argument registration in set_argparser."""

    def test_sync_argument_registered(self):
        """Test that --sync is registered as a valid argument."""
        import argparse

        parser = argparse.ArgumentParser()
        SupportInfoCommand.set_argparser(parser)

        args = parser.parse_args(["--sync"])
        assert args.sync is True

    def test_sync_default_is_false(self):
        """Test that --sync defaults to False when not provided."""
        import argparse

        parser = argparse.ArgumentParser()
        SupportInfoCommand.set_argparser(parser)

        args = parser.parse_args([])
        assert args.sync is False

    def test_sync_with_pkg_parses(self):
        """Test that --sync and --pkg can be parsed (validation is in run())."""
        import argparse

        parser = argparse.ArgumentParser()
        SupportInfoCommand.set_argparser(parser)

        # argparse allows both — mutual exclusivity is enforced in run()
        args = parser.parse_args(["--sync", "--pkg", "bash"])
        assert args.sync is True
        assert args.packages == ["bash"]


class TestTryLegacyFallback(TestSupportInfoCommand):
    """Tests for _try_legacy_fallback used by run() when fetching fails."""

    def test_fallback_disabled_when_legacy_off(self, command, tmp_path):
        """If legacy mode is off, the original error is re-raised unchanged."""
        config = Mock()
        config.legacy = False
        original = DnfError("HTTP Error 403: Forbidden")

        # Even if a file happens to exist at the legacy path, legacy=False
        # means we never look at it.
        legacy = tmp_path / "dnf-plugins" / "support_info.xml"
        legacy.parent.mkdir(parents=True)
        legacy.write_text("<package_support/>")

        with patch.object(SupportInfoCommand, "_get_legacy_location", return_value=legacy):
            with pytest.raises(DnfError, match="HTTP Error 403: Forbidden"):
                command._try_legacy_fallback(config, original)

    def test_fallback_reraises_when_legacy_file_missing(self, command, tmp_path):
        """Legacy mode but no file on disk → re-raise the original error."""
        config = Mock()
        config.legacy = True
        original = DnfError("Failed to fetch content from https://example/x.xml")

        missing = tmp_path / "dnf-plugins" / "support_info.xml"

        with patch.object(SupportInfoCommand, "_get_legacy_location", return_value=missing):
            with pytest.raises(DnfError, match="Failed to fetch content"):
                command._try_legacy_fallback(config, original)

    def test_fallback_uses_legacy_file_when_present(self, command, tmp_path):
        """Legacy mode + legacy file present → warn and parse the legacy file."""
        config = Mock()
        config.legacy = True
        original = DnfError("HTTP Error 403: Forbidden")

        legacy = tmp_path / "dnf-plugins" / "support_info.xml"
        legacy.parent.mkdir(parents=True)
        legacy.write_text("<package_support/>")

        sentinel_handler = Mock()

        with patch.object(
            SupportInfoCommand, "_get_legacy_location", return_value=legacy
        ), patch.object(
            SupportInfoCommand, "_create_handler", return_value=sentinel_handler
        ) as mock_create, patch(
            "dnf_support_info_plugin.package_support.logger"
        ) as mock_logger:
            result = command._try_legacy_fallback(config, original)

        assert result is sentinel_handler
        # Parsed from the legacy file path, with no XSD (None).
        mock_create.assert_called_once_with(str(legacy), None)
        # User must see a warning explaining what happened.
        mock_logger.warning.assert_called_once()
        warn_msg = mock_logger.warning.call_args[0][0]
        assert "Failed to retrieve support info XML" in warn_msg
        assert "Using existing legacy file" in warn_msg

    def test_fallback_directory_at_legacy_path_reraises(self, command, tmp_path):
        """A directory at the legacy path is not a usable file → re-raise."""
        config = Mock()
        config.legacy = True
        original = DnfError("Failed to retrieve")

        # is_file() is False for directories, mirroring real-world misuse.
        legacy_dir = tmp_path / "dnf-plugins" / "support_info.xml"
        legacy_dir.mkdir(parents=True)

        with patch.object(SupportInfoCommand, "_get_legacy_location", return_value=legacy_dir):
            with pytest.raises(DnfError, match="Failed to retrieve"):
                command._try_legacy_fallback(config, original)


class TestRunLegacyFallback(TestSupportInfoCommand):
    """Tests for the run() integration of _try_legacy_fallback."""

    @pytest.fixture
    def base_opts(self):
        """Common opts for non-sync, non-clean-cache run() invocations."""
        opts = Mock()
        opts.clean_cache = False
        opts.sync = False
        opts.packages = ["bash"]
        opts.filters = None
        opts.list_filters = False
        opts.show_json = False
        opts.show_xml = False
        return opts

    def test_run_falls_back_to_legacy_on_fetch_error(self, command, base_opts, tmp_path):
        """run(): fetch failure with legacy file → continue with the legacy file."""
        command.opts = base_opts

        config = Mock()
        config.legacy = True

        legacy = tmp_path / "dnf-plugins" / "support_info.xml"
        legacy.parent.mkdir(parents=True)
        legacy.write_text("<package_support/>")

        fallback_handler = Mock()
        fallback_handler.schema_version = Mock()

        with patch(
            "dnf_support_info_plugin.package_support.ConfigReader", return_value=config
        ), patch.object(
            SupportInfoCommand,
            "_load_support_info",
            side_effect=DnfError("HTTP Error 403: Forbidden"),
        ), patch.object(
            SupportInfoCommand, "_get_legacy_location", return_value=legacy
        ), patch.object(
            SupportInfoCommand, "_create_handler", return_value=fallback_handler
        ), patch.object(
            SupportInfoCommand, "_handle_pkg"
        ) as mock_handle_pkg:
            command.run()

        # The query path runs to completion using the legacy handler.
        mock_handle_pkg.assert_called_once()
        assert command.service is not None

    def test_run_reraises_when_legacy_off_and_fetch_fails(self, command, base_opts):
        """run(): fetch failure with legacy=False → original error propagates."""
        command.opts = base_opts

        config = Mock()
        config.legacy = False

        with patch(
            "dnf_support_info_plugin.package_support.ConfigReader", return_value=config
        ), patch.object(
            SupportInfoCommand,
            "_load_support_info",
            side_effect=DnfError("HTTP Error 403: Forbidden"),
        ), patch.object(
            SupportInfoCommand, "_handle_pkg"
        ) as mock_handle_pkg:
            with pytest.raises(DnfError, match="HTTP Error 403: Forbidden"):
                command.run()

        mock_handle_pkg.assert_not_called()

    def test_run_reraises_when_legacy_on_but_no_file(self, command, base_opts, tmp_path):
        """run(): fetch failure with legacy=True but no legacy file → propagates."""
        command.opts = base_opts

        config = Mock()
        config.legacy = True

        # Path is returned but the file does not exist on disk.
        missing = tmp_path / "dnf-plugins" / "support_info.xml"

        with patch(
            "dnf_support_info_plugin.package_support.ConfigReader", return_value=config
        ), patch.object(
            SupportInfoCommand,
            "_load_support_info",
            side_effect=DnfError("HTTP Error 403: Forbidden"),
        ), patch.object(
            SupportInfoCommand, "_get_legacy_location", return_value=missing
        ), patch.object(
            SupportInfoCommand, "_handle_pkg"
        ) as mock_handle_pkg:
            with pytest.raises(DnfError, match="HTTP Error 403: Forbidden"):
                command.run()

        mock_handle_pkg.assert_not_called()

    def test_run_does_not_fall_back_for_sync(self, command, tmp_path):
        """run() with --sync must surface fetch errors (no fallback)."""
        opts = Mock()
        opts.clean_cache = False
        opts.sync = True
        opts.packages = None
        opts.filters = None
        command.opts = opts

        config = Mock()
        config.legacy = True

        # Even with a legacy file on disk, --sync must not silently succeed
        # when the remote fetch fails — its job is to refresh the data.
        legacy = tmp_path / "dnf-plugins" / "support_info.xml"
        legacy.parent.mkdir(parents=True)
        legacy.write_text("<package_support/>")

        with patch(
            "dnf_support_info_plugin.package_support.ConfigReader", return_value=config
        ), patch.object(
            SupportInfoCommand,
            "_handle_sync",
            side_effect=DnfError("HTTP Error 403: Forbidden"),
        ), patch.object(
            SupportInfoCommand, "_get_legacy_location", return_value=legacy
        ):
            with pytest.raises(DnfError, match="HTTP Error 403: Forbidden"):
                command.run()
