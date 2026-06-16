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

"""Integration tests for formatters with PackageInfo and SupportStatement."""

import json
from unittest.mock import Mock

from supportinfo.handler import PhaseInfo, SupportLevelInfo, SupportStatement

from dnf_support_info_plugin.formatter_config import LEGACY_SCHEMA_CONFIG, SCHEMA_CONFIG
from dnf_support_info_plugin.formatters import ConsoleFormatter, JSONFormatter, XMLFormatter
from dnf_support_info_plugin.models import PackageInfo, PackageState


class TestFormatterBaseClass:
    """Test Formatter base class methods."""

    def test_json_formatter_output_includes_phases(self):
        """Test JSONFormatter output includes phase information."""
        statement = SupportStatement(
            current_phase="supported",
            phases={
                "supported": PhaseInfo(
                    name="supported",
                    start_date="2023-01-01",
                    support_level_info=SupportLevelInfo(
                        name="default",
                        severities="Low,Medium,Important,Critical",
                        description="Full security and bug fix support for all severities",
                    ),
                    milestone=None,
                ),
            },
            summary="",
            text="",
            link="",
        )

        pkg_info = PackageInfo(
            name="test",
            version="1.0",
            arch="x86_64",
            state=PackageState.INSTALLED,
            support_statement=statement,
            statement_id="test",
            note=None,
        )

        formatter = JSONFormatter()
        result = formatter.format_packages([pkg_info])

        parsed = json.loads(result)
        assert "current_phase" in parsed
        assert parsed["current_phase"] == statement.phases["supported"].name
        assert "phases" in parsed

    def test_json_formatter_handles_empty_phases(self):
        """Test JSONFormatter handles empty phases dict."""
        statement = SupportStatement(
            current_phase="supported",
            phases={},
            summary="",
            text="",
            link="",
        )

        pkg_info = PackageInfo(
            name="test",
            version="1.0",
            arch="x86_64",
            state=PackageState.INSTALLED,
            support_statement=statement,
            statement_id="test",
            note=None,
        )

        formatter = JSONFormatter()
        result = formatter.format_packages([pkg_info])

        parsed = json.loads(result)
        assert parsed["name"] == "test"


class TestConsoleFormatterIntegration:
    """Test ConsoleFormatter with PackageInfo."""

    def test_format_single_package(
        self, legacy_handler, supported_statement_legacy, mock_dnf_output
    ):
        """Test ConsoleFormatter formats package correctly."""
        pkg_info = PackageInfo(
            name="test-glibc",
            version="2.34-52",
            arch="x86_64",
            state=PackageState.INSTALLED,
            support_statement=supported_statement_legacy,
            statement_id="eol",
            note=None,
        )

        formatter = ConsoleFormatter(mock_dnf_output)
        result = formatter.format_packages([pkg_info])

        assert "test-glibc" in result
        assert "2.34-52" in result
        assert "installed" in result

    def test_format_packages_table_uses_get_field(
        self, legacy_handler, supported_statement_legacy, mock_dnf_output
    ):
        """Test format_packages_table uses PackageInfo.get_field() method."""
        pkg_info = PackageInfo(
            name="test-glibc",
            version="2.34-52",
            arch="x86_64",
            state=PackageState.INSTALLED,
            support_statement=supported_statement_legacy,
            statement_id="eol",
            note=None,
        )

        formatter = ConsoleFormatter(mock_dnf_output)
        result = formatter.format_packages_table([pkg_info])

        assert "test-glibc" in result
        assert "2.34-52" in result

    def test_format_with_empty_statement(self, mock_dnf_output):
        """Test ConsoleFormatter handles minimal statement gracefully."""
        statement = SupportStatement(
            current_phase="supported",
            phases={},
            summary="Test",
            text="",
            link="",
        )

        pkg_info = PackageInfo(
            name="test-pkg",
            version="1.0",
            arch="x86_64",
            state=PackageState.INSTALLED,
            support_statement=statement,
            statement_id="test",
            note=None,
        )

        formatter = ConsoleFormatter(mock_dnf_output)
        result = formatter.format_packages([pkg_info])

        assert "test-pkg" in result

    def test_format_packages_empty_list(self, mock_dnf_output):
        """Test ConsoleFormatter.format_packages with empty list returns empty string."""
        formatter = ConsoleFormatter(mock_dnf_output)
        result = formatter.format_packages([])
        assert result == ""

    def test_format_packages_table_empty_list(self, mock_dnf_output):
        """Test ConsoleFormatter.format_packages_table with empty list returns empty string."""
        formatter = ConsoleFormatter(mock_dnf_output)
        result = formatter.format_packages_table([])
        assert result == ""

    def test_console_formatter_output(
        self, legacy_handler, supported_statement_legacy, mock_dnf_output
    ):
        """Test ConsoleFormatter produces output."""
        pkg_info = PackageInfo(
            name="test-pkg",
            version="1.0",
            arch="x86_64",
            state=PackageState.INSTALLED,
            support_statement=supported_statement_legacy,
            statement_id="eol",
            note=None,
        )

        formatter = ConsoleFormatter(mock_dnf_output)

        result = formatter.format_packages([pkg_info])
        assert "test-pkg" in result

    def test_v1_unsupported_phase(self, mock_dnf_output, v1_eos_statement):
        """Test ConsoleFormatter handles V1.0 unsupported phase correctly."""
        pkg_info = PackageInfo(
            name="test-eos-pkg",
            version="1.0",
            arch="x86_64",
            state=PackageState.INSTALLED,
            support_statement=v1_eos_statement,
            statement_id="test_eos",
            note=None,
        )

        formatter = ConsoleFormatter(mock_dnf_output)
        result = formatter.format_packages([pkg_info])

        # Should show unsupported phase name
        assert "end_of_life" in result.lower() or "test-eos-pkg" in result

    def test_table_format_unsupported(self, mock_dnf_output, v1_eos_statement):
        """Test table format for unsupported package."""
        pkg_info = PackageInfo(
            name="test-pkg",
            version="1.0",
            arch="x86_64",
            state=PackageState.INSTALLED,
            support_statement=v1_eos_statement,
            statement_id="test_eos",
            note=None,
        )

        formatter = ConsoleFormatter(mock_dnf_output)
        result = formatter.format_packages_table([pkg_info])

        # Package name should be in output
        assert "test-pkg" in result


class TestJSONFormatterIntegration:
    """Test JSONFormatter with PackageInfo."""

    def test_format_includes_key_fields(self, legacy_handler, supported_statement_legacy):
        """Test JSONFormatter includes key fields from PackageInfo."""
        pkg_info = PackageInfo(
            name="test-glibc",
            version="2.34-52",
            arch="x86_64",
            state=PackageState.INSTALLED,
            support_statement=supported_statement_legacy,
            statement_id="eol",
            note=None,
        )

        formatter = JSONFormatter()
        result = formatter.format_packages([pkg_info])

        parsed = json.loads(result)
        assert parsed["name"] == "test-glibc"
        assert parsed["version"] == "2.34-52"
        assert parsed["state"] == "installed"

    def test_format_packages_table(self, legacy_handler, supported_statement_legacy):
        """Test format_packages_table outputs JSON array."""
        pkg_info = PackageInfo(
            name="test-glibc",
            version="2.34-52",
            arch="x86_64",
            state=PackageState.INSTALLED,
            support_statement=supported_statement_legacy,
            statement_id="eol",
            note=None,
        )

        formatter = JSONFormatter()
        result = formatter.format_packages_table([pkg_info])

        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert len(parsed) == 1
        assert parsed[0]["name"] == "test-glibc"

    def test_format_with_note(self, legacy_handler, supported_statement_legacy):
        """Test JSONFormatter includes note field when present."""
        pkg_info = PackageInfo(
            name="test-glibc",
            version="2.34-52",
            arch="x86_64",
            state=PackageState.INSTALLED,
            support_statement=supported_statement_legacy,
            statement_id="eol",
            note="This is a test note",
        )

        formatter = JSONFormatter()
        result = formatter.format_packages([pkg_info])

        parsed = json.loads(result)
        assert parsed["note"] == "This is a test note"

    def test_format_packages_empty_list(self):
        """Test JSONFormatter.format_packages with empty list returns empty array."""
        formatter = JSONFormatter()
        result = formatter.format_packages([])
        assert result == "[]"

    def test_format_packages_table_empty_list(self):
        """Test JSONFormatter.format_packages_table with empty list returns empty array."""
        formatter = JSONFormatter()
        result = formatter.format_packages_table([])
        assert result == "[]"

    def test_v1_unsupported_phase(self, v1_eos_statement):
        """Test JSONFormatter handles V1.0 unsupported phase correctly."""
        pkg_info = PackageInfo(
            name="test-eos-pkg",
            version="1.0",
            arch="x86_64",
            state=PackageState.INSTALLED,
            support_statement=v1_eos_statement,
            statement_id="test_eos",
            note=None,
        )

        formatter = JSONFormatter()
        result = formatter.format_packages([pkg_info])

        parsed = json.loads(result)
        assert "current_phase" in parsed
        assert parsed["current_phase"] == v1_eos_statement.phases["end_of_life"].name
        assert "phases" in parsed


class TestXMLFormatterIntegration:
    """Test XMLFormatter with PackageInfo."""

    def test_format_uses_statement_for_attributes(self, legacy_handler, supported_statement_legacy):
        """Test XMLFormatter builds attributes from statement."""
        pkg_info = PackageInfo(
            name="test-glibc",
            version="2.34-52",
            arch="x86_64",
            state=PackageState.INSTALLED,
            support_statement=supported_statement_legacy,
            statement_id="eol",
            note=None,
        )

        formatter = XMLFormatter()
        result = formatter.format_packages([pkg_info])

        assert "<?xml version=" in result
        assert 'id="eol"' in result
        assert '<package name="test-glibc"' in result
        assert 'nevra="2.34-52"' in result

    def test_format_multiple_packages(
        self, legacy_handler, supported_statement_legacy, unsupported_statement_legacy
    ):
        """Test XMLFormatter groups packages by statement."""
        pkg1 = PackageInfo(
            name="test-glibc",
            version="2.34-52",
            arch="x86_64",
            state=PackageState.INSTALLED,
            support_statement=supported_statement_legacy,
            statement_id="eol",
            note=None,
        )

        pkg2 = PackageInfo(
            name="test-python36",
            version="3.6.15",
            arch="x86_64",
            state=PackageState.AVAILABLE,
            support_statement=unsupported_statement_legacy,
            statement_id="eol_python36",
            note=None,
        )

        formatter = XMLFormatter()
        result = formatter.format_packages([pkg1, pkg2])

        assert '<package name="test-glibc"' in result
        assert '<package name="test-python36"' in result

    def test_format_packages_empty_list(self):
        """Test XMLFormatter.format_packages with empty list returns minimal valid XML."""
        formatter = XMLFormatter()
        result = formatter.format_packages([])
        assert "<?xml version=" in result
        assert "<package_support" in result
        assert "<statements" in result
        assert "statements" in result


def _make_mock_dnf_output():
    """Create a mock DNF output object."""
    output = Mock()
    output.fmtKeyValFill = lambda label, value: f"{label}{value}"
    return output


def _make_package_info(
    name="test-pkg",
    current_phase="supported",
    summary="Test summary",
    phases=None,
):
    """Create a minimal PackageInfo for formatter testing."""
    if phases is None:
        phase_mock = Mock()
        phase_mock.name = current_phase
        phase_mock.start_date = "2023-03-15"
        phase_mock.support_level = None
        phase_mock.severities = None
        phase_mock.support_level_info = None
        phase_mock.display_name = None
        phases = {current_phase: phase_mock}

    statement = SupportStatement(
        current_phase=current_phase,
        phases=phases,
        summary=summary,
        text="Test text",
        link=None,
        lifecycle_note=None,
        package_class=None,
        origin=None,
    )

    return PackageInfo(
        name=name,
        version="1.0-1.amzn2023",
        arch="x86_64",
        state=PackageState.INSTALLED,
        support_statement=statement,
        statement_id="test_statement",
        note=None,
    )


class TestConsoleFormatterSchemaConfig:
    """Test ConsoleFormatter respects schema-specific configuration."""

    def test_default_config_when_none(self):
        """Test formatter uses SCHEMA_CONFIG when no config provided."""
        output = _make_mock_dnf_output()
        formatter = ConsoleFormatter(output)
        assert formatter.config is SCHEMA_CONFIG

    def test_default_config_explicit(self):
        """Test formatter uses SCHEMA_CONFIG when explicitly passed."""
        output = _make_mock_dnf_output()
        formatter = ConsoleFormatter(output, schema_config=SCHEMA_CONFIG)
        assert formatter.config is SCHEMA_CONFIG

    def test_legacy_config(self):
        """Test formatter uses LEGACY_SCHEMA_CONFIG when passed."""
        output = _make_mock_dnf_output()
        formatter = ConsoleFormatter(output, schema_config=LEGACY_SCHEMA_CONFIG)
        assert formatter.config is LEGACY_SCHEMA_CONFIG

    def test_default_pkg_output_has_current_status_label(self):
        """Test default config shows 'Current Status' label."""
        output = _make_mock_dnf_output()
        formatter = ConsoleFormatter(output, schema_config=SCHEMA_CONFIG)
        pkg = _make_package_info()
        result = formatter.format_packages([pkg])
        assert "Current Status" in result

    def test_legacy_pkg_output_has_support_status_label(self):
        """Test legacy config shows 'Support Status' label."""
        output = _make_mock_dnf_output()
        formatter = ConsoleFormatter(output, schema_config=LEGACY_SCHEMA_CONFIG)
        pkg = _make_package_info()
        result = formatter.format_packages([pkg])
        assert "Support Status" in result

    def test_legacy_pkg_output_has_support_statement_label(self):
        """Test legacy config shows 'Support Statement' label."""
        output = _make_mock_dnf_output()
        formatter = ConsoleFormatter(output, schema_config=LEGACY_SCHEMA_CONFIG)
        pkg = _make_package_info(summary="Test summary text")
        result = formatter.format_packages([pkg])
        assert "Support Statement" in result

    def test_default_pkg_output_no_support_statement(self):
        """Test default config does NOT show 'Support Statement'."""
        output = _make_mock_dnf_output()
        formatter = ConsoleFormatter(output, schema_config=SCHEMA_CONFIG)
        pkg = _make_package_info(summary="Test summary text")
        result = formatter.format_packages([pkg])
        assert "Support Statement" not in result

    def test_legacy_pkg_output_no_support_level(self):
        """Test legacy config does NOT show 'Patch Priority'."""
        output = _make_mock_dnf_output()
        formatter = ConsoleFormatter(output, schema_config=LEGACY_SCHEMA_CONFIG)
        pkg = _make_package_info()
        result = formatter.format_packages([pkg])
        assert "Patch Priority" not in result

    def test_legacy_table_header_has_name(self):
        """Test legacy table header shows 'Name' not 'Package'."""
        output = _make_mock_dnf_output()
        formatter = ConsoleFormatter(output, schema_config=LEGACY_SCHEMA_CONFIG)
        pkg = _make_package_info()
        result = formatter.format_packages_table([pkg])
        header = result.split("\n")[0]
        assert "Name" in header

    def test_default_table_header_has_package(self):
        """Test default table header shows 'Package'."""
        output = _make_mock_dnf_output()
        formatter = ConsoleFormatter(output, schema_config=SCHEMA_CONFIG)
        pkg = _make_package_info()
        result = formatter.format_packages_table([pkg])
        header = result.split("\n")[0]
        assert "Package" in header

    def test_legacy_table_header_has_support_status(self):
        """Test legacy table header shows 'Support Status' not 'Current Status'."""
        output = _make_mock_dnf_output()
        formatter = ConsoleFormatter(output, schema_config=LEGACY_SCHEMA_CONFIG)
        pkg = _make_package_info()
        result = formatter.format_packages_table([pkg])
        header = result.split("\n")[0]
        assert "Support Status" in header

    def test_legacy_table_no_support_level_column(self):
        """Test legacy table does NOT have 'Support Level' column."""
        output = _make_mock_dnf_output()
        formatter = ConsoleFormatter(output, schema_config=LEGACY_SCHEMA_CONFIG)
        pkg = _make_package_info()
        result = formatter.format_packages_table([pkg])
        header = result.split("\n")[0]
        assert "Support Level" not in header

    def test_default_table_has_support_level_column(self):
        """Test default table has 'Support Level' column."""
        output = _make_mock_dnf_output()
        formatter = ConsoleFormatter(output, schema_config=SCHEMA_CONFIG)
        pkg = _make_package_info()
        result = formatter.format_packages_table([pkg])
        header = result.split("\n")[0]
        assert "Support Level" in header
