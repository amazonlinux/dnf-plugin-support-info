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

"""Tests for config_reader module."""

import os
import tempfile
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from dnf.exceptions import Error as DnfError

from dnf_support_info_plugin.config_reader import ConfigReader
from dnf_support_info_plugin.const import DEFAULT_CACHE_DURATION_SECONDS


class MockConfigParser:
    """Mock ConfigParser that behaves like a real config parser for testing."""

    def __init__(self):
        self.sections = {}

    def read(self, path):
        """Read and parse the config file."""
        with open(path, "r") as f:
            content = f.read()

        # Simple INI parser for testing
        current_section = None
        for line in content.split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                current_section = line[1:-1]
                self.sections[current_section] = {}
            elif "=" in line and current_section:
                key, value = line.split("=", 1)
                self.sections[current_section][key.strip()] = value.strip()

    def has_section(self, section):
        """Check if section exists."""
        return section in self.sections

    def has_option(self, section, option):
        """Check if option exists in section."""
        return section in self.sections and option in self.sections[section]

    def get(self, section, option):
        """Get option value from section."""
        if section in self.sections and option in self.sections[section]:
            return self.sections[section][option]
        return ""

    @staticmethod
    def substitute(url, substitutions):
        """Default substitute method that returns URL unchanged."""
        return url


@pytest.fixture
def mock_config_parser():
    """Mock ConfigParser for all tests."""
    with patch("dnf_support_info_plugin.config_reader.ConfigParser", MockConfigParser):
        yield


@contextmanager
def create_config_file(content):
    """Create a temporary config file with given content."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False) as f:
        f.write(content)
        f.flush()
        try:
            yield f.name
        finally:
            os.unlink(f.name)


class TestConfigReader:
    """Test ConfigReader class."""

    def test_valid_config(self, mock_config_parser):
        """Test reading valid config file."""
        with create_config_file(
            """[main]
baseurl = https://example.com/support.xml
templateurl = https://example.com/support.xsd
metadata_expire = 7200
"""
        ) as config_path:
            config = ConfigReader(config_path)

            assert config.baseurl == "https://example.com/support.xml"
            assert config.templateurl == "https://example.com/support.xsd"
            assert config.metadata_expire == 7200

    def test_minimal_config(self, mock_config_parser):
        """Test reading minimal config file with only baseurl."""
        with create_config_file(
            """[main]
baseurl = https://example.com/support.xml
"""
        ) as config_path:
            config = ConfigReader(config_path)

            assert config.baseurl == "https://example.com/support.xml"
            assert config.templateurl is None
            assert config.metadata_expire == DEFAULT_CACHE_DURATION_SECONDS

    def test_missing_main_section(self, mock_config_parser):
        """Test error when config file missing [main] section."""
        with create_config_file(
            """[other]
baseurl = https://example.com/support.xml
"""
        ) as config_path:
            with pytest.raises(DnfError, match="Config file must have \\[main\\] section"):
                ConfigReader(config_path)

    def test_missing_baseurl(self, mock_config_parser):
        """Test error when config file missing baseurl."""
        with create_config_file(
            """[main]
templateurl = https://example.com/support.xsd
"""
        ) as config_path:
            with pytest.raises(DnfError, match="Config must have 'baseurl' option"):
                ConfigReader(config_path)

    def test_empty_baseurl(self, mock_config_parser):
        """Test error when baseurl is empty."""
        with create_config_file(
            """[main]
baseurl =
"""
        ) as config_path:
            with pytest.raises(DnfError, match="baseurl must not be empty"):
                ConfigReader(config_path)

    def test_invalid_metadata_expire_format(self, mock_config_parser):
        """Test invalid metadata_expire format (non-integer) raises DnfError."""
        with create_config_file(
            """[main]
baseurl = https://example.com/support.xml
metadata_expire = invalid_number
"""
        ) as config_path:
            with pytest.raises(DnfError, match="Invalid metadata_expire value 'invalid_number'"):
                ConfigReader(config_path)

    def test_invalid_metadata_expire_value(self, mock_config_parser):
        """Test invalid metadata_expire value (out of range) raises DnfError."""
        with create_config_file(
            """[main]
baseurl = https://example.com/support.xml
metadata_expire = -10
"""
        ) as config_path:
            with pytest.raises(
                DnfError, match="metadata_expire must be -1 \\(infinite\\) or non-negative"
            ):
                ConfigReader(config_path)

    def test_negative_metadata_expire(self, mock_config_parser):
        """Test negative metadata_expire (< -1) raises DnfError."""
        with create_config_file(
            """[main]
baseurl = https://example.com/support.xml
metadata_expire = -5
"""
        ) as config_path:
            with pytest.raises(
                DnfError, match="metadata_expire must be -1 \\(infinite\\) or non-negative"
            ):
                ConfigReader(config_path)

    def test_missing_config_file(self):
        """Test error when config file doesn't exist."""
        with pytest.raises(DnfError, match="Support info plugin requires configuration"):
            ConfigReader("/nonexistent/path.conf")

    def test_infinite_cache(self, mock_config_parser):
        """Test metadata_expire = -1 for infinite cache."""
        with create_config_file(
            """[main]
baseurl = https://example.com/support.xml
metadata_expire = -1
"""
        ) as config_path:
            config = ConfigReader(config_path)

            assert config.baseurl == "https://example.com/support.xml"
            assert config.metadata_expire == -1

    def test_less_than_negative_one(self, mock_config_parser):
        """Test metadata_expire < -1 raises DnfError."""
        with create_config_file(
            """[main]
baseurl = https://example.com/support.xml
metadata_expire = -5
"""
        ) as config_path:
            with pytest.raises(
                DnfError, match="metadata_expire must be -1 \\(infinite\\) or non-negative"
            ):
                ConfigReader(config_path)

    def test_exceeds_maximum(self, mock_config_parser):
        """Test metadata_expire > MAX_ABSOLUTE_CACHE_DURATION_SECONDS raises DnfError."""
        with create_config_file(
            """[main]
baseurl = https://example.com/support.xml
metadata_expire = 999999999999
"""
        ) as config_path:
            with pytest.raises(DnfError, match="exceeds maximum"):
                ConfigReader(config_path)

    def test_zero_metadata_expire(self, mock_config_parser):
        """Test metadata_expire = 0 (always check) is accepted."""
        with create_config_file(
            """[main]
baseurl = https://example.com/support.xml
metadata_expire = 0
"""
        ) as config_path:
            config = ConfigReader(config_path)

            assert config.baseurl == "https://example.com/support.xml"
            assert config.metadata_expire == 0

    def test_large_valid_metadata_expire(self, mock_config_parser):
        """Test large valid metadata_expire values (1 hour, 1 day) are accepted."""
        # Test 1 hour (3600 seconds)
        with create_config_file(
            """[main]
baseurl = https://example.com/support.xml
metadata_expire = 3600
"""
        ) as config_path:
            config = ConfigReader(config_path)

            assert config.baseurl == "https://example.com/support.xml"
            assert config.metadata_expire == 3600

        # Test 1 day (86400 seconds)
        with create_config_file(
            """[main]
baseurl = https://example.com/support.xml
metadata_expire = 86400
"""
        ) as config_path:
            config = ConfigReader(config_path)

            assert config.baseurl == "https://example.com/support.xml"
            assert config.metadata_expire == 86400

    def test_maximum_valid_metadata_expire(self, mock_config_parser):
        """Test maximum valid metadata_expire (90 days = 7776000) is accepted."""
        with create_config_file(
            """[main]
baseurl = https://example.com/support.xml
metadata_expire = 7776000
"""
        ) as config_path:
            config = ConfigReader(config_path)

            assert config.baseurl == "https://example.com/support.xml"
            assert config.metadata_expire == 7776000

    def test_config_with_dnf_variables(self, mock_config_parser):
        """Test config file with DNF variables like $awsregion."""
        with create_config_file(
            """[main]
baseurl = https://bucket-$awsregion.s3.amazonaws.com/supportinfo.xml
templateurl = https://bucket-$awsregion.s3.amazonaws.com/supportinfo.xsd
"""
        ) as config_path:
            # Mock _resolve_dnf_variables to return URL unchanged for testing
            # Note: Instance methods receive self as first arg even when mocked
            def mock_resolve(self, url):
                return url

            with patch.object(
                ConfigReader,
                "_resolve_dnf_variables",
                mock_resolve,
            ):
                config = ConfigReader(config_path)

                assert "supportinfo.xml" in config.baseurl
                assert config.templateurl is not None

    def test_properties_are_read_only(self, mock_config_parser):
        """Test that config properties are immutable after initialization."""
        with create_config_file(
            """[main]
baseurl = https://example.com/support.xml
templateurl = https://example.com/support.xsd
metadata_expire = 7200
"""
        ) as config_path:
            config = ConfigReader(config_path)

            # Verify properties cannot be modified
            with pytest.raises(AttributeError):
                config.baseurl = "https://evil.com/malicious.xml"

            with pytest.raises(AttributeError):
                config.templateurl = "https://evil.com/malicious.xsd"

            with pytest.raises(AttributeError):
                config.metadata_expire = 99999

            # Verify original values unchanged
            assert config.baseurl == "https://example.com/support.xml"
            assert config.templateurl == "https://example.com/support.xsd"
            assert config.metadata_expire == 7200

    def test_invalid_baseurl_scheme(self, mock_config_parser):
        """Test that invalid baseurl scheme raises DnfError."""
        with create_config_file(
            """[main]
baseurl = dttps://example.com/support.xml
"""
        ) as config_path:
            with pytest.raises(DnfError, match="Unsupported URL scheme 'dttps' in baseurl"):
                ConfigReader(config_path)

    def test_missing_baseurl_scheme(self, mock_config_parser):
        """Test that baseurl without scheme raises DnfError."""
        with create_config_file(
            """[main]
baseurl = example.com/support.xml
"""
        ) as config_path:
            with pytest.raises(DnfError, match="baseurl must include a URL scheme"):
                ConfigReader(config_path)

    def test_invalid_templateurl_scheme(self, mock_config_parser):
        """Test that invalid templateurl scheme raises DnfError."""
        with create_config_file(
            """[main]
baseurl = https://example.com/support.xml
templateurl = ftp://example.com/support.xsd
"""
        ) as config_path:
            with pytest.raises(DnfError, match="Unsupported URL scheme 'ftp' in templateurl"):
                ConfigReader(config_path)

    def test_missing_templateurl_scheme(self, mock_config_parser):
        """Test that templateurl without scheme raises DnfError."""
        with create_config_file(
            """[main]
baseurl = https://example.com/support.xml
templateurl = example.com/support.xsd
"""
        ) as config_path:
            with pytest.raises(DnfError, match="templateurl must include a URL scheme"):
                ConfigReader(config_path)

    def test_baseurl_scheme_variable_resolved_before_validation(self, mock_config_parser):
        """Regression: baseurl whose scheme is a DNF variable must resolve first.

        A template like "$amzn_proto://..." has no scheme that urlparse can
        recognise (it starts with '$'), so scheme validation must run on the
        resolved URL, not the raw template. Otherwise it wrongly fails with
        "baseurl must include a URL scheme".
        """
        with create_config_file(
            """[main]
baseurl = $amzn_proto://kingfisher$amzn_domain/v1/AL2023-supportinfo-1.0.xml
"""
        ) as config_path:

            def mock_substitute(url, substitutions):
                return url.replace("$amzn_proto", "https").replace("$amzn_domain", ".example.com")

            with patch.object(MockConfigParser, "substitute", mock_substitute):
                config = ConfigReader(config_path)
                assert config.baseurl == (
                    "https://kingfisher.example.com/v1/AL2023-supportinfo-1.0.xml"
                )

    def test_templateurl_scheme_variable_resolved_before_validation(self, mock_config_parser):
        """Regression: templateurl whose scheme is a DNF variable must resolve first."""
        with create_config_file(
            """[main]
baseurl = $amzn_proto://kingfisher$amzn_domain/v1/AL2023-supportinfo-1.0.xml
templateurl = $amzn_proto://kingfisher$amzn_domain/v1/supportinfo-1.0.xsd
"""
        ) as config_path:

            def mock_substitute(url, substitutions):
                return url.replace("$amzn_proto", "https").replace("$amzn_domain", ".example.com")

            with patch.object(MockConfigParser, "substitute", mock_substitute):
                config = ConfigReader(config_path)
                assert config.templateurl == (
                    "https://kingfisher.example.com/v1/supportinfo-1.0.xsd"
                )

    def test_baseurl_invalid_scheme_after_resolution_still_rejected(self, mock_config_parser):
        """A variable that resolves to an unsupported scheme is still rejected."""
        with create_config_file(
            """[main]
baseurl = $amzn_proto://example.com/support.xml
"""
        ) as config_path:

            def mock_substitute(url, substitutions):
                return url.replace("$amzn_proto", "ftp")

            with patch.object(MockConfigParser, "substitute", mock_substitute):
                with pytest.raises(DnfError, match="Unsupported URL scheme 'ftp' in baseurl"):
                    ConfigReader(config_path)

    def test_resolve_dnf_variables_fails_with_variables_present(self, mock_config_parser):
        """Test that DNF variable resolution failure with $ variables raises DnfError."""
        with create_config_file(
            """[main]
baseurl = https://bucket-$awsregion.s3.amazonaws.com/supportinfo.xml
"""
        ) as config_path:
            # Mock MockConfigParser.substitute to raise an exception
            def mock_substitute(url, substitutions):
                raise Exception("Variable resolution failed")

            with patch.object(MockConfigParser, "substitute", mock_substitute):
                with pytest.raises(DnfError, match="Failed to resolve DNF variables in URL"):
                    ConfigReader(config_path)

    def test_resolve_dnf_variables_fails_without_variables(self, mock_config_parser):
        """Test that DNF variable resolution failure without $ returns original URL."""
        with create_config_file(
            """[main]
baseurl = https://example.com/supportinfo.xml
"""
        ) as config_path:
            # Mock MockConfigParser.substitute to raise an exception
            def mock_substitute(url, substitutions):
                raise Exception("Substitution system failed")

            with patch.object(MockConfigParser, "substitute", mock_substitute):
                # Should not raise, but log warning and return original URL
                config = ConfigReader(config_path)
                assert config.baseurl == "https://example.com/supportinfo.xml"

    def test_resolve_dnf_variables_success(self, mock_config_parser):
        """Test successful DNF variable resolution."""
        with create_config_file(
            """[main]
baseurl = https://bucket-$awsregion.s3.amazonaws.com/supportinfo.xml
"""
        ) as config_path:
            # Mock MockConfigParser.substitute to resolve variables
            def mock_substitute(url, substitutions):
                return url.replace("$awsregion", "us-west-2")

            with patch.object(MockConfigParser, "substitute", mock_substitute):
                config = ConfigReader(config_path)
                assert config.baseurl == "https://bucket-us-west-2.s3.amazonaws.com/supportinfo.xml"

    def test_empty_templateurl(self, mock_config_parser):
        """Test that empty templateurl returns None."""
        with create_config_file(
            """[main]
baseurl = https://example.com/support.xml
templateurl =
"""
        ) as config_path:
            config = ConfigReader(config_path)
            assert config.baseurl == "https://example.com/support.xml"
            assert config.templateurl is None

    def test_whitespace_only_templateurl(self, mock_config_parser):
        """Test that templateurl with only whitespace returns None."""
        with create_config_file(
            """[main]
baseurl = https://example.com/support.xml
templateurl =                 """  # noqa: W291
        ) as config_path:
            config = ConfigReader(config_path)
            assert config.baseurl == "https://example.com/support.xml"
            assert config.templateurl is None


class TestGpgkeyValidation:
    """Test gpgkey URL scheme validation in ConfigReader."""

    def test_gpgkey_with_valid_file_scheme(self, mock_config_parser):
        """Test that gpgkey with file:// scheme is accepted."""
        with create_config_file(
            """[main]
baseurl = https://example.com/support.xml
gpgcheck = 1
gpgkey = file:///etc/pki/rpm-gpg/RPM-GPG-KEY-test
"""
        ) as config_path:
            config = ConfigReader(config_path)
            assert config.gpgcheck is True
            assert config.gpgkey == ["file:///etc/pki/rpm-gpg/RPM-GPG-KEY-test"]

    def test_gpgkey_with_valid_https_scheme(self, mock_config_parser):
        """Test that gpgkey with https:// scheme is accepted."""
        with create_config_file(
            """[main]
baseurl = https://example.com/support.xml
gpgcheck = 1
gpgkey = https://example.com/RPM-GPG-KEY-test
"""
        ) as config_path:
            config = ConfigReader(config_path)
            assert config.gpgcheck is True
            assert config.gpgkey == ["https://example.com/RPM-GPG-KEY-test"]

    def test_gpgkey_with_http_scheme_rejected(self, mock_config_parser):
        """Test that gpgkey with http:// scheme raises DnfError."""
        with create_config_file(
            """[main]
baseurl = https://example.com/support.xml
gpgcheck = 1
gpgkey = http://example.com/RPM-GPG-KEY-test
"""
        ) as config_path:
            with pytest.raises(DnfError, match="Unsupported URL scheme 'http' in gpgkey"):
                ConfigReader(config_path)

    def test_gpgkey_with_ftp_scheme_rejected(self, mock_config_parser):
        """Test that gpgkey with ftp:// scheme raises DnfError."""
        with create_config_file(
            """[main]
baseurl = https://example.com/support.xml
gpgcheck = 1
gpgkey = ftp://example.com/RPM-GPG-KEY-test
"""
        ) as config_path:
            with pytest.raises(DnfError, match="Unsupported URL scheme 'ftp' in gpgkey"):
                ConfigReader(config_path)

    def test_gpgkey_with_missing_scheme_rejected(self, mock_config_parser):
        """Test that gpgkey without scheme raises DnfError."""
        with create_config_file(
            """[main]
baseurl = https://example.com/support.xml
gpgcheck = 1
gpgkey = example.com/RPM-GPG-KEY-test
"""
        ) as config_path:
            with pytest.raises(DnfError, match="gpgkey URL must include a scheme"):
                ConfigReader(config_path)

    def test_gpgcheck_enabled_without_gpgkey_raises_error(self, mock_config_parser):
        """Test that gpgcheck=1 without gpgkey raises DnfError."""
        with create_config_file(
            """[main]
baseurl = https://example.com/support.xml
gpgcheck = 1
"""
        ) as config_path:
            with pytest.raises(
                DnfError, match="gpgcheck is enabled but no gpgkey URLs are configured"
            ):
                ConfigReader(config_path)

    def test_gpgcheck_enabled_with_empty_gpgkey_raises_error(self, mock_config_parser):
        """Test that gpgcheck=1 with empty gpgkey raises DnfError."""
        with create_config_file(
            """[main]
baseurl = https://example.com/support.xml
gpgcheck = 1
gpgkey =
"""
        ) as config_path:
            with pytest.raises(
                DnfError, match="gpgcheck is enabled but no gpgkey URLs are configured"
            ):
                ConfigReader(config_path)

    def test_gpgkey_with_multiple_valid_urls(self, mock_config_parser):
        """Test that multiple gpgkey URLs with valid schemes are accepted."""
        with create_config_file(
            """[main]
baseurl = https://example.com/support.xml
gpgcheck = 1
gpgkey = file:///etc/pki/rpm-gpg/RPM-GPG-KEY-test https://example.com/RPM-GPG-KEY-test2
"""
        ) as config_path:
            config = ConfigReader(config_path)
            assert config.gpgcheck is True
            assert len(config.gpgkey) == 2
            assert "file:///etc/pki/rpm-gpg/RPM-GPG-KEY-test" in config.gpgkey
            assert "https://example.com/RPM-GPG-KEY-test2" in config.gpgkey


class TestLegacyConfig:
    """Test legacy mode configuration parsing."""

    def test_legacy_enabled_with_1(self, mock_config_parser):
        """Test legacy = 1 enables legacy mode."""
        with create_config_file(
            """[main]
baseurl = https://example.com/support.xml
legacy = 1
"""
        ) as config_path:
            config = ConfigReader(config_path)
            assert config.legacy is True

    def test_legacy_enabled_with_true(self, mock_config_parser):
        """Test legacy = true enables legacy mode."""
        with create_config_file(
            """[main]
baseurl = https://example.com/support.xml
legacy = true
"""
        ) as config_path:
            config = ConfigReader(config_path)
            assert config.legacy is True

    def test_legacy_enabled_with_yes(self, mock_config_parser):
        """Test legacy = yes enables legacy mode."""
        with create_config_file(
            """[main]
baseurl = https://example.com/support.xml
legacy = yes
"""
        ) as config_path:
            config = ConfigReader(config_path)
            assert config.legacy is True

    def test_legacy_disabled_with_0(self, mock_config_parser):
        """Test legacy = 0 disables legacy mode."""
        with create_config_file(
            """[main]
baseurl = https://example.com/support.xml
legacy = 0
"""
        ) as config_path:
            config = ConfigReader(config_path)
            assert config.legacy is False

    def test_legacy_disabled_with_false(self, mock_config_parser):
        """Test legacy = false disables legacy mode."""
        with create_config_file(
            """[main]
baseurl = https://example.com/support.xml
legacy = false
"""
        ) as config_path:
            config = ConfigReader(config_path)
            assert config.legacy is False

    def test_legacy_disabled_with_no(self, mock_config_parser):
        """Test legacy = no disables legacy mode."""
        with create_config_file(
            """[main]
baseurl = https://example.com/support.xml
legacy = no
"""
        ) as config_path:
            config = ConfigReader(config_path)
            assert config.legacy is False

    def test_legacy_defaults_to_false(self, mock_config_parser):
        """Test legacy defaults to False when not specified."""
        with create_config_file(
            """[main]
baseurl = https://example.com/support.xml
"""
        ) as config_path:
            config = ConfigReader(config_path)
            assert config.legacy is False

    def test_legacy_invalid_value_raises_error(self, mock_config_parser):
        """Test legacy with invalid value raises DnfError."""
        with create_config_file(
            """[main]
baseurl = https://example.com/support.xml
legacy = banana
"""
        ) as config_path:
            with pytest.raises(DnfError, match="Invalid legacy value 'banana'"):
                ConfigReader(config_path)

    def test_legacy_case_insensitive(self, mock_config_parser):
        """Test legacy parsing is case-insensitive."""
        with create_config_file(
            """[main]
baseurl = https://example.com/support.xml
legacy = TRUE
"""
        ) as config_path:
            config = ConfigReader(config_path)
            assert config.legacy is True

    def test_legacy_property_is_read_only(self, mock_config_parser):
        """Test that legacy property cannot be modified after initialization."""
        with create_config_file(
            """[main]
baseurl = https://example.com/support.xml
legacy = 0
"""
        ) as config_path:
            config = ConfigReader(config_path)
            with pytest.raises(AttributeError):
                config.legacy = True
            assert config.legacy is False
