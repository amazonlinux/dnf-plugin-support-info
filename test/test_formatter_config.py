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

"""Tests for formatter_config module."""

from dnf_support_info_plugin.formatter_config import LEGACY_SCHEMA_CONFIG, SCHEMA_CONFIG


class TestSchemaConfig:
    """Test default schema configuration."""

    def test_schema_config_has_detail_fields(self):
        """Test SCHEMA_CONFIG has detail fields."""
        assert len(SCHEMA_CONFIG.detail_fields) > 0

    def test_schema_config_has_table_columns(self):
        """Test SCHEMA_CONFIG has table columns."""
        assert len(SCHEMA_CONFIG.table_columns) > 0

    def test_schema_config_timeline_label(self):
        """Test SCHEMA_CONFIG uses 'Support Timeline' label."""
        assert SCHEMA_CONFIG.timeline_label == "Support Timeline"

    def test_schema_config_detail_has_current_phase(self):
        """Test SCHEMA_CONFIG detail fields include current_phase as 'Current Status'."""
        field = next(
            (f for f in SCHEMA_CONFIG.detail_fields if f.field_key == "current_phase"),
            None,
        )
        assert field is not None
        assert field.display_name == "Current Status"

    def test_schema_config_detail_has_support_level(self):
        """Test SCHEMA_CONFIG detail fields include support_level."""
        field = next(
            (f for f in SCHEMA_CONFIG.detail_fields if f.field_key == "support_level"),
            None,
        )
        assert field is not None

    def test_schema_config_table_has_support_level_column(self):
        """Test SCHEMA_CONFIG table has support_level column."""
        col = next(
            (c for c in SCHEMA_CONFIG.table_columns if c.field_key == "support_level"),
            None,
        )
        assert col is not None


class TestLegacySchemaConfig:
    """Test legacy schema configuration."""

    def test_legacy_config_has_detail_fields(self):
        """Test LEGACY_SCHEMA_CONFIG has detail fields."""
        assert len(LEGACY_SCHEMA_CONFIG.detail_fields) > 0

    def test_legacy_config_has_table_columns(self):
        """Test LEGACY_SCHEMA_CONFIG has table columns."""
        assert len(LEGACY_SCHEMA_CONFIG.table_columns) > 0

    def test_legacy_config_timeline_label(self):
        """Test LEGACY_SCHEMA_CONFIG uses 'Support Periods' label."""
        assert LEGACY_SCHEMA_CONFIG.timeline_label == "Support Periods"

    def test_legacy_detail_current_phase_label(self):
        """Test legacy detail uses 'Support Status' for current_phase."""
        field = next(
            (f for f in LEGACY_SCHEMA_CONFIG.detail_fields if f.field_key == "current_phase"),
            None,
        )
        assert field is not None
        assert field.display_name == "Support Status"

    def test_legacy_detail_has_summary(self):
        """Test legacy detail includes 'Support Statement' (summary)."""
        field = next(
            (f for f in LEGACY_SCHEMA_CONFIG.detail_fields if f.field_key == "summary"),
            None,
        )
        assert field is not None
        assert field.display_name == "Support Statement"

    def test_legacy_detail_no_support_level(self):
        """Test legacy detail does NOT include support_level."""
        field = next(
            (f for f in LEGACY_SCHEMA_CONFIG.detail_fields if f.field_key == "support_level"),
            None,
        )
        assert field is None

    def test_legacy_detail_no_severities(self):
        """Test legacy detail does NOT include severities."""
        field = next(
            (f for f in LEGACY_SCHEMA_CONFIG.detail_fields if f.field_key == "severities"),
            None,
        )
        assert field is None

    def test_legacy_detail_no_support_level_description(self):
        """Test legacy detail does NOT include support_level_description."""
        field = next(
            (
                f
                for f in LEGACY_SCHEMA_CONFIG.detail_fields
                if f.field_key == "support_level_description"
            ),
            None,
        )
        assert field is None

    def test_legacy_table_has_name_column(self):
        """Test legacy table uses 'Name' header for package column."""
        col = next(
            (c for c in LEGACY_SCHEMA_CONFIG.table_columns if c.field_key == "package"),
            None,
        )
        assert col is not None
        assert col.display_name == "Name"

    def test_legacy_table_has_support_status_column(self):
        """Test legacy table uses 'Support Status' header."""
        col = next(
            (c for c in LEGACY_SCHEMA_CONFIG.table_columns if c.field_key == "current_phase"),
            None,
        )
        assert col is not None
        assert col.display_name == "Support Status"

    def test_legacy_table_has_date_column(self):
        """Test legacy table uses 'Date' header for until_next."""
        col = next(
            (c for c in LEGACY_SCHEMA_CONFIG.table_columns if c.field_key == "until_next"),
            None,
        )
        assert col is not None
        assert col.display_name == "Date"

    def test_legacy_table_no_support_level_column(self):
        """Test legacy table does NOT have support_level column."""
        col = next(
            (c for c in LEGACY_SCHEMA_CONFIG.table_columns if c.field_key == "support_level"),
            None,
        )
        assert col is None


class TestConfigDifferences:
    """Test that legacy and default configs are actually different."""

    def test_different_detail_field_count(self):
        """Test legacy has fewer detail fields than default."""
        assert len(LEGACY_SCHEMA_CONFIG.detail_fields) < len(SCHEMA_CONFIG.detail_fields)

    def test_different_table_column_count(self):
        """Test legacy has fewer table columns than default."""
        assert len(LEGACY_SCHEMA_CONFIG.table_columns) < len(SCHEMA_CONFIG.table_columns)

    def test_different_timeline_labels(self):
        """Test configs use different timeline labels."""
        assert SCHEMA_CONFIG.timeline_label != LEGACY_SCHEMA_CONFIG.timeline_label

    def test_different_status_labels(self):
        """Test configs use different labels for current_phase."""
        default_field = next(
            f for f in SCHEMA_CONFIG.detail_fields if f.field_key == "current_phase"
        )
        legacy_field = next(
            f for f in LEGACY_SCHEMA_CONFIG.detail_fields if f.field_key == "current_phase"
        )
        assert default_field.display_name != legacy_field.display_name
