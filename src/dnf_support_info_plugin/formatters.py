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

"""Output formatting for package support information."""

import json
from abc import ABC, abstractmethod
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree
from xml.etree.ElementTree import Element, SubElement

import dnf.cli.output
import dnf.i18n

from .const import PHASE_SUPPORTED, PHASE_UNSUPPORTED
from .formatter_config import JSON_CONFIG, SCHEMA_CONFIG, XML_CONFIG, SchemaConfig
from .models import PackageInfo


class Formatter(ABC):
    """Abstract base class for all formatters."""

    @staticmethod
    def _is_valid_value(value: Optional[str]) -> bool:
        """Check if a value is valid for output.

        Validates that a value should be included in output by checking:
        - Not Python None (falsy check)
        - Not empty or whitespace-only string

        Args:
            value: Value to check. Non-string truthy values (e.g. int, bool)
                are accepted as-is without stripping.

        Returns:
            True if value is valid for output
        """
        if not value:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        return True

    def _extract_phase_data(self, phase: Any) -> Dict[str, str]:
        """Extract validated phase metadata into a flat dict.

        Args:
            phase: A phase object (e.g. from ``support_statement.phases``).

        Returns:
            Dict with validated fields: start_date, patch_priority,
            support_level_description, covered_severities
        """
        data: Dict[str, str] = {}
        start_date = getattr(phase, "start_date", None)
        if start_date and isinstance(start_date, str) and start_date.strip():
            data["start_date"] = start_date
        info = getattr(phase, "support_level_info", None)
        if info:
            if self._is_valid_value(getattr(info, "display_name", None)):
                data["patch_priority"] = info.display_name
            if self._is_valid_value(getattr(info, "description", None)):
                data["support_level_description"] = info.description
            if self._is_valid_value(getattr(info, "severities", None)):
                data["covered_severities"] = info.severities
        return data

    @abstractmethod
    def format_packages(self, package_info: List[PackageInfo]) -> str:
        """
        Format package(s) information.

        Args:
            package_info: List of package information objects

        Returns:
            Formatted string representation, or empty string if input is empty
        """
        pass

    @abstractmethod
    def format_packages_table(self, packages: List[PackageInfo]) -> str:
        """
        Format multiple packages' information as a table.

        Args:
            packages: List of package information objects

        Returns:
            Formatted string representation, or empty string if input is empty
        """
        pass


class ConsoleFormatter(Formatter):
    """Formatter for console/terminal output."""

    def __init__(
        self,
        dnf_output: dnf.cli.output.Output,
        schema_config: Optional["SchemaConfig"] = None,
    ) -> None:
        """Initialize the formatter with DNF output object.

        Args:
            dnf_output: DNF CLI output object for formatting
            schema_config: Schema-specific configuration. If None,
                uses the default SCHEMA_CONFIG.
        """
        self.dnf_output = dnf_output
        self.config = schema_config or SCHEMA_CONFIG

    def _format_field(self, key: str, value: str, fill: int = 20) -> str:
        """Format a key-value field for display.

        Args:
            key: Field label/name
            value: Field value
            fill: Width for label alignment

        Returns:
            Formatted key-value string
        """
        return self.dnf_output.fmtKeyValFill(
            dnf.i18n.fill_exact_width(key, fill) + " : ", value or ""
        )

    def _format_support_periods(self, package_info: PackageInfo, fill: int = 20) -> List[str]:
        """Format Support Periods as multi-line display.

        Args:
            package_info: Package information object
            fill: Field label width for alignment

        Returns:
            List of formatted lines for support periods
        """
        phases = package_info.support_statement.phases
        if not phases:
            return []

        # Filter phases with dates and format as "from {date} : {name} (severities)"
        period_lines = []
        for phase in phases.values():
            attrs = self._extract_phase_data(phase)
            start_date = attrs.get("start_date")
            if not start_date:
                continue
            line = f"from {start_date:<14} : {phase.name}"
            if attrs.get("severities"):
                line += f" ({attrs['severities']})"
            period_lines.append(line)

        if not period_lines:
            return []

        # First line with label, rest with spacing
        lines = [self._format_field(self.config.timeline_label, period_lines[0], fill)]
        label_spacing = " " * fill + " : "
        lines.extend(f"{label_spacing}{line}" for line in period_lines[1:])

        return lines

    def _format_single_package(self, package_info: PackageInfo, fill: int) -> str:
        """Format a single package's support information.

        Args:
            package_info: Package information to format
            fill: Column width for label alignment

        Returns:
            Formatted string for one package
        """
        lines = []
        lines.append(self._format_field("Name", package_info.name, fill))
        lines.append(self._format_field("Version", package_info.version, fill))
        lines.append(self._format_field("State", package_info.state.value, fill))

        periods_rendered = False
        for field in self.config.detail_fields:
            # Sentinel: render support periods inline at this position
            if field.field_key == "_support_periods":
                period_lines = self._format_support_periods(package_info, fill)
                if period_lines:
                    lines.extend(period_lines)
                    periods_rendered = True
                continue

            value = package_info.get_field(field.field_key) or ""
            if self._is_valid_value(value):
                lines.append(self._format_field(field.display_name, value, fill))

        # Default: if periods weren't rendered inline, append at end
        if not periods_rendered:
            period_lines = self._format_support_periods(package_info, fill)
            if period_lines:
                lines.extend(period_lines)

        # Package note
        if package_info.note:
            lines.append(self._format_field("Package Note", package_info.note, fill))

        return "\n".join(lines)

    def format_packages(self, package_info: List[PackageInfo]) -> str:
        """
        Format package(s) information for display.

        Args:
            package_info: List of package information objects

        Returns:
            Formatted package information as string, or empty string if no packages
        """
        if not package_info:
            return ""
        fill = self.config.detail_fill_width
        return "\n\n".join(self._format_single_package(pkg, fill) for pkg in package_info)

    def _get_until_next(self, pkg: PackageInfo) -> str:
        """Get combined 'until date + next phase name' string.

        Finds the next phase after current and returns "{date} ({phase_name})".
        In legacy mode, returns just the date for the relevant transition:
        - supported: end date (when support ends)
        - unsupported: start date (when it became unsupported)

        Args:
            pkg: PackageInfo object

        Returns:
            String like "2029-06-30 (unsupported)" for default mode,
            or "2029-06-30" for legacy mode, or empty if no data
        """
        statement = pkg.support_statement
        if not statement.phases or not statement.current_phase:
            return ""

        # Phases are sorted by start_date, find index of current phase
        phase_list = list(statement.phases.values())
        current_idx = next(
            (i for i, p in enumerate(phase_list) if p.name == statement.current_phase), None
        )

        if current_idx is None:
            return ""

        # Legacy mode: different date display
        if self.config.legacy_date_format:
            return self._get_legacy_date(phase_list, current_idx)

        # Default mode: show next phase date + name
        if current_idx >= len(phase_list) - 1:
            return ""

        next_phase = phase_list[current_idx + 1]
        next_start_date = getattr(next_phase, "start_date", None)
        if next_start_date:
            return f"{next_start_date} ({next_phase.name})"
        return f"({next_phase.name})"

    def _get_legacy_date(self, phase_list, current_idx) -> str:
        """Get date for legacy mode table display.

        Matches old plugin behavior:
        - Supported: shows the end date (next phase's start_date)
        - Unsupported: shows the start date of the current phase

        Args:
            phase_list: List of phase objects sorted by date
            current_idx: Index of the current phase

        Returns:
            Date string, or empty if no date available
        """
        current_phase = phase_list[current_idx]

        # If there's a next phase, show its start date (= end of current)
        if current_idx < len(phase_list) - 1:
            next_phase = phase_list[current_idx + 1]
            next_start_date = getattr(next_phase, "start_date", None)
            if next_start_date:
                return next_start_date

        # Last phase (unsupported): show its own start date
        start_date = getattr(current_phase, "start_date", None)
        if start_date:
            return start_date

        return ""

    def _get_last_phase_date(self, pkg: PackageInfo) -> str:
        """Get the start date of the last phase from phases dict.

        Phases are already sorted by start_date in the handler.

        Args:
            pkg: PackageInfo object

        Returns:
            Date string of last phase, or empty string
        """
        phases = pkg.support_statement.phases
        if not phases:
            return ""

        # Phases are sorted, get the last one
        phase_list = list(phases.values())
        if phase_list:
            last_start_date = getattr(phase_list[-1], "start_date", None)
            if last_start_date:
                return last_start_date
        return ""

    def _build_table_values(self, pkg: PackageInfo) -> Dict[str, str]:
        """Build values dict for table row from PackageInfo using table_columns config.

        Args:
            pkg: PackageInfo object

        Returns:
            Dict mapping field_key to resolved value
        """
        # Special fields that come directly from PackageInfo attributes
        special_fields: Dict[str, str] = {
            "package": pkg.name,
            "version": pkg.version,
            "state": pkg.state.value,
            "note": pkg.note or "",
            "until_next": self._get_until_next(pkg),
        }

        values: Dict[str, str] = {}
        for col in self.config.table_columns:
            if col.field_key in special_fields:
                values[col.field_key] = special_fields[col.field_key]
            else:
                values[col.field_key] = pkg.get_field(col.field_key) or ""

        return values

    def _format_table_row(self, values: Dict[str, str]) -> str:
        """Format a single row for the package table using table_columns configuration.

        Args:
            values: Dict mapping field_key to value for each column

        Returns:
            Formatted row string
        """
        parts = []
        for col in self.config.table_columns:
            value = values.get(col.field_key, "")
            if col.width > 0:
                parts.append(f"{value:<{col.width}}")
            else:
                parts.append(value)
        return " ".join(parts)

    def _format_table_header(self) -> str:
        """Format the table header row.

        Returns:
            Formatted header string
        """
        parts = []
        for col in self.config.table_columns:
            if col.width > 0:
                parts.append(f"{col.display_name:<{col.width}}")
            else:
                parts.append(col.display_name)
        return " ".join(parts)

    def format_packages_table(self, packages: List[PackageInfo]) -> str:
        """
        Format list of packages as a table using schema-appropriate column configuration.

        Packages are sorted by end_date (earliest first) to show packages losing
        support soonest at the top, then by statement_id to group packages with
        the same support statement together, then by package name.

        Args:
            packages: List of package information objects

        Returns:
            Formatted table as string, or empty string if no packages
        """
        if not packages:
            return ""

        statement_end_dates: Dict[str, str] = {}
        for pkg in packages:
            statement_id = pkg.statement_id or ""
            if statement_id not in statement_end_dates:
                end_date = self._get_last_phase_date(pkg)
                statement_end_dates[statement_id] = end_date or "9999-99-99"

        keyed_packages = []
        for pkg in packages:
            statement_id = pkg.statement_id or ""
            sort_key = (statement_end_dates[statement_id], statement_id, pkg.name)
            keyed_packages.append((sort_key, pkg))
        keyed_packages.sort(key=lambda x: x[0])

        lines: List[str] = [self._format_table_header()]
        for _, pkg in keyed_packages:
            # Build values dict using TABLE_COLUMNS configuration
            values = self._build_table_values(pkg)
            lines.append(self._format_table_row(values))

        return "\n".join(lines)


class XMLFormatter(Formatter):
    """Formatter for XML output."""

    def __init__(self, legacy: bool = False) -> None:
        """Initialize the XML formatter.

        Args:
            legacy: If True, output old-style legacy XML format
                with marker/start_date/end_date attributes and
                <summary>, <text>, <link> child elements.
        """
        self.legacy = legacy

    def _prettify(self, elem: Element) -> str:
        """Return a pretty-printed XML string using ElementTree's built-in indentation.

        Args:
            elem: XML Element to format

        Returns:
            Pretty-printed XML string with declaration
        """
        ElementTree.indent(elem, space="  ", level=0)
        return ElementTree.tostring(elem, encoding="unicode", xml_declaration=True)

    def _build_statement_attrs(self, package_info: PackageInfo) -> Dict[str, str]:
        """Build statement attributes from explicit list.

        Args:
            package_info: Package information object

        Returns:
            Dict of attribute name to value for XML statement element
        """
        attrs: Dict[str, str] = {"id": package_info.statement_id or ""}

        current_phase = package_info.support_statement.current_phase
        if current_phase:
            attrs["current_phase"] = current_phase

        for attr in XML_CONFIG.statement_attrs:
            value = package_info.get_field(attr)
            if self._is_valid_value(value):
                attrs[attr] = value

        return attrs

    def _add_phases_element(self, parent: Element, package_info: PackageInfo) -> None:
        """Add phases as child element.

        Args:
            parent: Parent XML element to add phases to
            package_info: Package information object
        """
        phases = package_info.support_statement.phases
        if not phases:
            return

        phases_elem = SubElement(parent, "phases")
        for phase in phases.values():
            phase_attrs: Dict[str, str] = {"name": phase.name}
            phase_data = self._extract_phase_data(phase)
            if "start_date" in phase_data:
                phase_attrs["start_date"] = phase_data.pop("start_date")
            phase_elem = SubElement(phases_elem, "phase", phase_attrs)
            for key, value in phase_data.items():
                SubElement(phase_elem, key).text = value

    def _add_statement_details(self, statement_elem: Element, package_info: PackageInfo) -> None:
        """Add child elements from explicit list.

        Args:
            statement_elem: Parent XML element to add children to
            package_info: Package information object
        """
        for field_name in XML_CONFIG.statement_elements:
            value = package_info.get_field(field_name)
            if self._is_valid_value(value):
                SubElement(statement_elem, field_name).text = value

    def _add_statement_with_packages(self, parent: Element, packages: List[PackageInfo]) -> None:
        """Add a statement element with associated packages.

        In legacy mode, outputs old-style attributes (marker, start_date, end_date)
        with <summary>, <text>, <link> child elements.
        In default mode, outputs current_phase attribute with <phases> child element.

        Args:
            parent: Parent XML element to add statement to
            packages: List of packages sharing the same statement
        """

        first_pkg = packages[0]

        if self.legacy:
            statement_elem = SubElement(
                parent, "statement", self._build_legacy_statement_attrs(first_pkg)
            )
            self._add_legacy_statement_details(statement_elem, first_pkg)
        else:
            statement_elem = SubElement(parent, "statement", self._build_statement_attrs(first_pkg))
            self._add_statement_details(statement_elem, first_pkg)
            self._add_phases_element(statement_elem, first_pkg)

        # Packages block (same for both formats)
        packages_elem = SubElement(statement_elem, "packages")
        for pkg in packages:
            pkg_attrs = {"name": pkg.name, "nevra": pkg.version, "state": pkg.state.value}

            if not self.legacy:
                # Add package-level fields using get_field to access properties
                for field in ["package_class", "origin"]:
                    value = pkg.get_field(field)
                    if self._is_valid_value(value):
                        pkg_attrs[field] = value

            SubElement(packages_elem, "package", pkg_attrs)

    def _group_packages_by_statement(
        self, package_info: List[PackageInfo]
    ) -> Dict[str, List[PackageInfo]]:
        """Group packages by their support statement.

        Args:
            package_info: List of package information objects

        Returns:
            Dict mapping statement_id to list of packages
        """
        groups: Dict[str, List[PackageInfo]] = defaultdict(list)
        for pkg in package_info:
            # Group by statement_id from PackageInfo
            statement_id = pkg.statement_id
            groups[statement_id].append(pkg)
        return dict(groups)

    def format_packages(self, package_info: List[PackageInfo]) -> str:
        """
        Generate XML output for package(s) support information.

        Args:
            package_info: List of package information objects

        Returns:
            XML string (single document with all packages), or empty XML if no packages
        """
        if not package_info:
            # Return minimal valid XML for empty input
            package_support = Element(
                "package_support", {"current_as": datetime.now(timezone.utc).strftime("%Y-%m-%d")}
            )
            SubElement(package_support, "statements")
            return self._prettify(package_support)

        package_support = Element(
            "package_support", {"current_as": datetime.now(timezone.utc).strftime("%Y-%m-%d")}
        )
        statements = SubElement(package_support, "statements")

        # Group packages by statement and add each group
        statement_groups = self._group_packages_by_statement(package_info)
        for packages in statement_groups.values():
            self._add_statement_with_packages(statements, packages)

        return self._prettify(package_support)

    def format_packages_table(self, packages: List[PackageInfo]) -> str:
        """
        Format multiple packages as XML.

        Args:
            packages: List of package information objects

        Returns:
            Single XML document with all packages grouped by statement
        """
        return self.format_packages(packages)

    def _build_legacy_statement_attrs(self, package_info: PackageInfo) -> Dict[str, str]:
        """Build legacy statement attributes (marker, start_date, end_date).

        Args:
            package_info: Package information object

        Returns:
            Dict of attribute name to value for legacy XML statement element
        """
        statement = package_info.support_statement
        attrs: Dict[str, str] = {}

        # Calculate marker, start_date, end_date from phases
        phases = statement.phases if statement else {}
        marker = statement.current_phase or "unknown" if statement else "unknown"

        supported_date = None
        unsupported_date = None
        for phase_name, phase_info in phases.items():
            if phase_name == PHASE_SUPPORTED:
                supported_date = phase_info.start_date
            elif phase_name == PHASE_UNSUPPORTED:
                unsupported_date = phase_info.start_date

        # Single unsupported phase
        if unsupported_date and not supported_date:
            if unsupported_date:
                attrs["end_date"] = unsupported_date  # not used but keep for compat
            attrs["id"] = package_info.statement_id or ""
            attrs["marker"] = PHASE_UNSUPPORTED
            if unsupported_date:
                attrs["start_date"] = unsupported_date
            return attrs

        # Alphabetical order
        if marker == PHASE_SUPPORTED and unsupported_date:
            attrs["end_date"] = unsupported_date
        attrs["id"] = package_info.statement_id or ""
        attrs["marker"] = marker
        if marker == PHASE_SUPPORTED and supported_date:
            attrs["start_date"] = supported_date
        elif marker == PHASE_UNSUPPORTED and unsupported_date:
            attrs["start_date"] = unsupported_date

        return attrs

    def _add_legacy_statement_details(
        self, statement_elem: Element, package_info: PackageInfo
    ) -> None:
        """Add legacy child elements: <summary>, <text>, <link>.

        Args:
            statement_elem: Parent XML element to add children to
            package_info: Package information object
        """
        statement = package_info.support_statement
        if not statement:
            return

        # <summary>
        summary = statement.summary or ""
        if summary:
            SubElement(statement_elem, "summary").text = summary

        # <text>
        text = statement.text or ""
        if text:
            SubElement(statement_elem, "text").text = text

        # <link>
        link = statement.link or ""
        if link:
            SubElement(statement_elem, "link").text = link


class JSONFormatter(Formatter):
    """Formatter for JSON output."""

    def _format_phases(self, package_info: PackageInfo) -> List[Dict[str, str]]:
        """Format phases list with full details for JSON output.

        Args:
            package_info: Package information object

        Returns:
            List of phase dictionaries with name, start_date, support_level, severities
        """
        phases = package_info.support_statement.phases
        if not phases:
            return []

        phases_data = []
        for phase in phases.values():
            phase_obj: Dict[str, str] = {"name": phase.name}
            phase_obj.update(self._extract_phase_data(phase))
            phases_data.append(phase_obj)
        return phases_data

    def _format_single_package_json(self, package_info: PackageInfo) -> Dict[str, Any]:
        """
        Generate JSON data for a single package using support_statement fields.

        Args:
            package_info: Package information object

        Returns:
            Dictionary with package data
        """
        data: Dict[str, Any] = {
            "name": package_info.name,
            "version": package_info.version,
            "state": package_info.state.value,
        }

        # Add current_phase directly from support_statement (raw lowercase name)
        current_phase = package_info.support_statement.current_phase
        if current_phase:
            data["current_phase"] = current_phase

        # Add top-level fields from JSON_CONFIG
        for mapping in JSON_CONFIG.field_mappings:
            value = package_info.get_field(mapping.internal_key)
            if self._is_valid_value(value):
                data[mapping.output_key] = value

        # Add phases list with full details
        phases_data = self._format_phases(package_info)
        if phases_data:
            data["phases"] = phases_data

        if package_info.note:
            data["note"] = package_info.note

        return data

    def format_packages(self, package_info: List[PackageInfo]) -> str:
        """
        Generate JSON output for package(s) support information.

        Args:
            package_info: List of package information objects

        Returns:
            JSON string (single object for one package, array for multiple),
            or empty array "[]" if no packages
        """
        if not package_info:
            return "[]"

        packages_data = []
        for pkg in package_info:
            packages_data.append(self._format_single_package_json(pkg))

        # Return single object if only one package, array if multiple
        if len(packages_data) == 1:
            return json.dumps(packages_data[0], indent=2)
        return json.dumps(packages_data, indent=2)

    def format_packages_table(self, packages: List[PackageInfo]) -> str:
        """
        Format multiple packages as JSON array (implements Formatter.format_packages_table).

        Args:
            packages: List of package information objects

        Returns:
            JSON array string, or empty array "[]" if no packages
        """
        if not packages:
            return "[]"
        packages_data = []
        for pkg in packages:
            packages_data.append(self._format_single_package_json(pkg))
        return json.dumps(packages_data, indent=2)
