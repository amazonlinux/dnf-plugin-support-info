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

"""Configuration dataclasses for output formatters."""

from dataclasses import dataclass
from typing import Dict, List

# ============================================================================
# Configuration Dataclasses
# ============================================================================


@dataclass(frozen=True)
class DetailField:
    """Configuration for a detail field in single package display (--pkg command).

    Attributes:
        field_key: Key used to retrieve value from normalized_fields
        display_name: Human-readable label shown in output
    """

    field_key: str
    display_name: str


@dataclass(frozen=True)
class TableColumn:
    """Configuration for a table column in console output.

    Attributes:
        field_key: Key used internally to identify the column (or PackageInfo attribute)
        display_name: Human-readable column header name
        width: Column width in characters (0 = variable/no padding)
    """

    field_key: str
    display_name: str
    width: int


@dataclass(frozen=True)
class XMLOutputConfig:
    """Configuration for XML output formatting.

    Attributes:
        statement_attrs: Field keys to include as attributes on <statement> elements
        statement_elements: Field keys to include as child elements under <statement>
    """

    statement_attrs: List[str]
    statement_elements: List[str]


@dataclass(frozen=True)
class JSONFieldMapping:
    """Configuration for a JSON field mapping.

    Attributes:
        internal_key: Key used in normalized_fields
        output_key: Key used in JSON output
    """

    internal_key: str
    output_key: str


@dataclass(frozen=True)
class JSONOutputConfig:
    """Configuration for JSON output formatting.

    Attributes:
        field_mappings: List of field mappings from internal to output keys
    """

    field_mappings: List[JSONFieldMapping]

    def as_dict(self) -> Dict[str, str]:
        """Convert field mappings to a dictionary.

        Returns:
            Dict mapping internal_key to output_key
        """
        return {m.internal_key: m.output_key for m in self.field_mappings}


@dataclass(frozen=True)
class SchemaConfig:
    """Complete schema-specific formatter configuration.

    Attributes:
        detail_fields: Fields for single package display
        table_columns: Columns for table output
        timeline_label: Label for the support timeline/periods field
        detail_fill_width: Character width for field label alignment
    """

    detail_fields: List[DetailField]
    table_columns: List[TableColumn]
    timeline_label: str = "Support Timeline"
    detail_fill_width: int = 28
    legacy_date_format: bool = False


# ============================================================================
# Unified Schema Configuration (works for both Legacy and V1.0)
# ============================================================================

# Detail fields shown in single package display
DETAIL_FIELDS = [
    DetailField("current_phase", "Current Status"),
    DetailField("support_level", "Patch Priority"),
    DetailField("support_level_description", "Support Level Description"),
    DetailField("severities", "Covered Severities"),
    DetailField("origin", "Origin"),
    DetailField("link", "Link"),
    DetailField("text", "Other Info"),
]

# Table columns for package list display
TABLE_COLUMNS = [
    TableColumn("package", "Package", 32),
    TableColumn("version", "Version", 34),
    TableColumn("state", "State", 12),
    TableColumn("support_level", "Support Level", 16),
    TableColumn("current_phase", "Current Status", 22),
    TableColumn("until_next", "Until (Next Phase)", 28),
    TableColumn("note", "Note", 0),
]

SCHEMA_CONFIG = SchemaConfig(
    detail_fields=DETAIL_FIELDS,
    table_columns=TABLE_COLUMNS,
    timeline_label="Support Timeline",
    detail_fill_width=28,
    legacy_date_format=False,
)

# ============================================================================
# Legacy Schema Configuration
# ============================================================================
# When the handler detects legacy (unversioned) XML, these configs are
# used to match the old dnf-plugin-support-info output format.

LEGACY_DETAIL_FIELDS = [
    DetailField("current_phase", "Support Status"),
    DetailField("_support_periods", "Support Periods"),
    DetailField("summary", "Support Statement"),
    DetailField("link", "Link"),
    DetailField("text", "Other Info"),
]

LEGACY_TABLE_COLUMNS = [
    TableColumn("package", "Name", 32),
    TableColumn("version", "Version", 34),
    TableColumn("state", "State", 12),
    TableColumn("current_phase", "Support Status", 16),
    TableColumn("until_next", "Date", 28),
    TableColumn("note", "Note", 0),
]

LEGACY_SCHEMA_CONFIG = SchemaConfig(
    detail_fields=LEGACY_DETAIL_FIELDS,
    table_columns=LEGACY_TABLE_COLUMNS,
    timeline_label="Support Periods",
    detail_fill_width=20,
    legacy_date_format=True,
)

# ============================================================================
# XML Output Configuration
# ============================================================================

XML_CONFIG = XMLOutputConfig(
    statement_attrs=[],
    statement_elements=["link"],
)

# ============================================================================
# JSON Output Configuration
# ============================================================================

# Top-level fields for JSON output (phases list is handled separately)
JSON_CONFIG = JSONOutputConfig(
    field_mappings=[
        JSONFieldMapping("origin", "origin"),
        JSONFieldMapping("link", "link"),
    ]
)
