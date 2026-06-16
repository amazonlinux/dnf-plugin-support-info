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

"""Convert schema_version='1.0' supportinfo XML to legacy (unversioned) format.

The legacy format uses <statements>/<statement> with an inline marker attribute,
while the 1.0 format uses <lifecycles>/<lifecycle>/<phase>. This module bridges
the two so that customers who depend on the legacy format can continue to use it
after the data source switches to 1.0.

Conversion rules:
    - Each lifecycle becomes a <statement> element
    - Phases are used to calculate marker, start_date, end_date attributes
    - Packages are regrouped from a flat list into per-statement blocks
    - Notes use 'id' attribute instead of 'name'
    - <summary>, <text>, <link> are generated from available metadata
    - The schema_version attribute is removed from the root element

This module uses the SupportinfoHandler API to read the 1.0 format,
avoiding direct XML parsing and ensuring consistency with the handler's
milestone resolution and phase calculation logic.
"""

import logging
import os
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from lxml import etree
from supportinfo.handler import LifecycleInfo, PackageEntry, SupportinfoHandler, SupportStatement

from .const import PHASE_SUPPORTED, PHASE_UNSUPPORTED

logger = logging.getLogger("dnf.plugin")

# Default link for packages in the legacy format.
# The 1.0 schema does not carry link URLs — that data existed only
# in the legacy pipeline (namespaced_pkgs.json).
_DEFAULT_LINK = "https://aws.amazon.com/amazon-linux-ami/faqs/"

# Suffix on lifecycle display_name values, e.g. "Clamav1.4 Lifecycle"
_LIFECYCLE_DISPLAY_NAME_SUFFIX = " Lifecycle"

# Placeholder for <text> element when description is empty
_TEXT_PLACEHOLDER = "See note for details."

# The default lifecycle "eol_lc" has generic metadata in the 1.0 format
# (display_name="Lc Lifecycle", no note attribute). This override provides
# the original legacy values for this specific lifecycle.
# The 1.0 XML schema does not include <summary> text, <link> URLs,
# or per-package note references. These fields are generated from
# available 1.0 metadata (display_name, description, lifecycle note).
# This is by design — the legacy format is a lossy conversion.
_DEFAULT_LIFECYCLE_OVERRIDES = {
    "eol_lc": {
        "statement_id": "eol_al2023",
        "summary_name": "Amazon Linux 2023",
        "description": (
            "This is the support statement for AL2023. The end-of-life "
            "of Amazon Linux 2023 is June 2029. From this point, the "
            "Amazon Linux 2023 packages will no longer receive any "
            "updates from AWS."
        ),
    },
}


class LegacyConverter:
    """Converts schema_version='1.0' supportinfo XML to legacy (unversioned) format.

    Uses the SupportinfoHandler API to read and interpret the 1.0 format,
    then builds legacy XML from the parsed data.

    Usage::

        converter = LegacyConverter(source_path)
        converter.convert("/path/to/output.xml")
    """

    def __init__(self, source_path: str):
        """Initialize with path to schema_version='1.0' format XML.

        Args:
            source_path: Path to the 1.0 format XML file.

        Raises:
            FileNotFoundError: If the source file does not exist.
            ValueError: If the XML is invalid or cannot be parsed.
        """
        self._source_path = source_path

        if not Path(source_path).exists():
            raise FileNotFoundError(f"Source XML not found: {source_path}")

        # Create handler — this validates, parses, and resolves milestones
        self._handler = SupportinfoHandler.create(source_path)

        # Preserve the original current_as timestamp
        self._current_as = self._handler._root.get("current_as", "")

        # Load data via handler API
        self._lifecycles: List[LifecycleInfo] = self._handler.get_lifecycle_info() or []
        self._metadata: Dict[str, SupportStatement] = self._handler.get_support_metadata()
        self._notes: Dict[str, str] = self._handler.get_support_notes()
        self._package_entries: List[PackageEntry] = self._handler.get_package_entries()

        # Build package groups: lifecycle_name → sorted list of PackageEntry
        self._package_groups: Dict[str, List[PackageEntry]] = self._build_package_groups()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def convert(self, output_path: str) -> str:
        """Convert 1.0 XML to legacy format and write to output_path.

        The output file is written atomically (write to temp file, then rename)
        to avoid leaving a corrupt file on disk if the process is interrupted.

        Args:
            output_path: Where to write the legacy XML file.

        Returns:
            The output_path string on success.

        Raises:
            OSError: If the output file cannot be written.
        """
        current_as = self._current_as

        # Create legacy root (no schema_version)
        legacy_root = etree.Element("package_support", current_as=current_as)
        legacy_root.append(etree.Comment("Auto-Generated by the Amazon Linux team."))

        # Convert lifecycles to statements
        statements_elem = etree.SubElement(legacy_root, "statements")
        self._convert_all_lifecycles(statements_elem)

        # Convert notes (name → id)
        self._convert_notes(legacy_root)

        # Write to disk atomically
        self._write_xml(legacy_root, output_path)

        logger.info(f"Converted 1.0 XML to legacy format: {output_path}")
        return output_path

    # ------------------------------------------------------------------
    # Initialization helpers
    # ------------------------------------------------------------------

    def _build_package_groups(self) -> Dict[str, List[PackageEntry]]:
        """Group package entries by lifecycle name.

        Returns:
            Dict mapping lifecycle_name to sorted list of PackageEntry.
        """
        groups: Dict[str, List[PackageEntry]] = defaultdict(list)

        for entry in self._package_entries:
            groups[entry.statement_id].append(entry)

        # Sort each group alphabetically by package name
        for lifecycle_name in groups:
            groups[lifecycle_name].sort(key=lambda e: e.name)

        logger.debug(
            f"Grouped {len(self._package_entries)} packages " f"across {len(groups)} lifecycles"
        )
        return dict(groups)

    # ------------------------------------------------------------------
    # Marker and date calculation
    # ------------------------------------------------------------------

    def _calculate_statement_attrs(
        self,
        statement: SupportStatement,
    ) -> Tuple[str, Optional[str], Optional[str]]:
        """Calculate the marker, start_date, and end_date for a statement.

        The legacy format encodes support status differently depending on
        the marker value:

        - ``marker="supported"``: ``start_date`` is when support began,
          ``end_date`` is when it will end (transition to unsupported).
        - ``marker="unsupported"``: ``start_date`` is when the unsupported
          period began. No ``end_date``.

        Args:
            statement: SupportStatement from the handler.

        Returns:
            Tuple of (marker, start_date, end_date). Dates may be None.
        """
        phases = statement.phases
        marker = statement.current_phase or "unknown"

        # Extract dates for known phases
        supported_date: Optional[str] = None
        unsupported_date: Optional[str] = None

        for phase_name, phase_info in phases.items():
            if phase_name == PHASE_SUPPORTED:
                supported_date = phase_info.start_date
            elif phase_name == PHASE_UNSUPPORTED:
                unsupported_date = phase_info.start_date

        # Single unsupported phase (no supported phase)
        if unsupported_date and not supported_date:
            return PHASE_UNSUPPORTED, unsupported_date, None

        if marker == PHASE_SUPPORTED:
            return marker, supported_date, unsupported_date
        elif marker == PHASE_UNSUPPORTED:
            return marker, unsupported_date, None
        else:
            return marker, supported_date or unsupported_date, None

    # ------------------------------------------------------------------
    # Content generation
    # ------------------------------------------------------------------

    def _generate_summary(
        self,
        display_name: str,
        marker: str,
        start_date: Optional[str],
        end_date: Optional[str],
    ) -> str:
        """Generate a <summary> string from lifecycle metadata.

        Attempts to match the legacy format pattern::

            "Clamav1.4 has security support until August 2027"

        Args:
            display_name: Lifecycle display_name attribute.
            marker: Current marker value.
            start_date: Statement start_date string.
            end_date: Statement end_date string.

        Returns:
            Human-readable summary string.
        """
        clean_name = display_name
        if clean_name.endswith(_LIFECYCLE_DISPLAY_NAME_SUFFIX):
            clean_name = clean_name[: -len(_LIFECYCLE_DISPLAY_NAME_SUFFIX)]
        clean_name = clean_name.strip()

        if not clean_name:
            return "Support information"

        if marker == PHASE_SUPPORTED and end_date:
            date_words = self._format_date_as_words(end_date)
            return f"{clean_name} has security support until {date_words}"
        elif marker == PHASE_UNSUPPORTED and start_date:
            date_words = self._format_date_as_words(start_date)
            return f"{clean_name} reached end of support in {date_words}"
        else:
            return f"{clean_name} support information"

    @staticmethod
    def _format_date_as_words(date_str: str) -> str:
        """Convert ISO date string to "Month Year" format.

        Args:
            date_str: ISO format date string, e.g. "2027-08-15".

        Returns:
            Formatted string, e.g. "August 2027".
        """
        try:
            dt = datetime.fromisoformat(date_str)
            return dt.strftime("%B %Y")
        except (ValueError, TypeError):
            return date_str

    # ------------------------------------------------------------------
    # Lifecycle → Statement conversion
    # ------------------------------------------------------------------

    def _convert_all_lifecycles(self, statements_elem) -> None:
        """Convert all lifecycles to legacy <statement> elements.

        Args:
            statements_elem: The <statements> parent element to append to.
        """
        if not self._lifecycles:
            logger.warning("No lifecycles found in 1.0 XML")
            return

        for lifecycle_info in self._lifecycles:
            self._convert_one_lifecycle(lifecycle_info, statements_elem)

    def _convert_one_lifecycle(
        self,
        lifecycle_info: LifecycleInfo,
        statements_elem,
    ) -> None:
        """Convert a single lifecycle to a legacy <statement>.

        Args:
            lifecycle_info: LifecycleInfo from the handler.
            statements_elem: Parent <statements> element to append to.
        """
        lifecycle_name = lifecycle_info.name
        note_ref = lifecycle_info.note
        display_name = lifecycle_info.display_name or ""
        description = lifecycle_info.description or ""

        # Get the SupportStatement (phases, current_phase) from metadata
        statement = self._metadata.get(lifecycle_name)
        if not statement or not statement.phases:
            logger.warning(f"Lifecycle '{lifecycle_name}' has no phases in metadata, skipping.")
            return

        # Check for known lifecycle overrides (e.g., default "eol_lc")
        override = _DEFAULT_LIFECYCLE_OVERRIDES.get(lifecycle_name)

        # Statement id: override > note > lifecycle name
        if override:
            statement_id = override["statement_id"]
        else:
            statement_id = note_ref if note_ref else lifecycle_name

        # Calculate marker, start_date, end_date
        marker, start_date, end_date = self._calculate_statement_attrs(statement)

        # Build statement attributes in alphabetical order
        attrs: Dict[str, str] = {}
        if end_date:
            attrs["end_date"] = end_date
        attrs["id"] = statement_id
        attrs["marker"] = marker
        if start_date:
            attrs["start_date"] = start_date

        # Create <statement> element
        statement_elem = etree.SubElement(statements_elem, "statement", **attrs)

        # Add <summary>
        summary_elem = etree.SubElement(statement_elem, "summary")
        if override and "summary_name" in override:
            summary_elem.text = self._generate_summary(
                override["summary_name"] + _LIFECYCLE_DISPLAY_NAME_SUFFIX,
                marker,
                start_date,
                end_date,
            )
        else:
            summary_elem.text = self._generate_summary(display_name, marker, start_date, end_date)

        # Add <text>
        text_elem = etree.SubElement(statement_elem, "text")
        if override and "description" in override:
            text_elem.text = override["description"]
        else:
            text_elem.text = description if description else _TEXT_PLACEHOLDER

        # Add <link>
        link_elem = etree.SubElement(statement_elem, "link")
        link_elem.text = _DEFAULT_LINK

        # Add <packages>
        self._add_packages_to_statement(statement_elem, lifecycle_name, statement_id)

    # ------------------------------------------------------------------
    # Package regrouping
    # ------------------------------------------------------------------

    def _add_packages_to_statement(
        self,
        statement_elem,
        lifecycle_name: str,
        note_value: str,
    ) -> None:
        """Add packages belonging to a lifecycle into a <statement>.

        Args:
            statement_elem: The <statement> element to add packages to.
            lifecycle_name: Lifecycle name to look up in package groups.
            note_value: Value for the ``note`` attribute on each package.
        """
        packages_elem = etree.SubElement(statement_elem, "packages")

        entries = self._package_groups.get(lifecycle_name, [])
        if not entries:
            logger.debug(f"No packages found for lifecycle '{lifecycle_name}'")

        for entry in entries:
            etree.SubElement(
                packages_elem,
                "package",
                name=entry.name,
                note=note_value,
            )

    # ------------------------------------------------------------------
    # Notes conversion
    # ------------------------------------------------------------------

    def _convert_notes(self, legacy_root) -> None:
        """Convert notes from 1.0 format to legacy format.

        The handler returns notes with 'name' keys.
        Legacy format uses 'id' attribute instead.

        Args:
            legacy_root: The legacy root element to append <notes> to.
        """
        if not self._notes:
            return

        notes_elem = etree.SubElement(legacy_root, "notes")

        for note_name, note_text in self._notes.items():
            legacy_note = etree.SubElement(notes_elem, "note", id=note_name)
            legacy_note.text = note_text

    # ------------------------------------------------------------------
    # File writing
    # ------------------------------------------------------------------

    def _write_xml(self, root, output_path: str) -> None:
        """Write XML tree to disk atomically.

        Uses a temporary file + rename pattern to avoid leaving a
        corrupt file on disk if the process is interrupted.

        Args:
            root: lxml Element to write.
            output_path: Destination file path.

        Raises:
            OSError: If the file cannot be written.
        """
        output_dir = Path(output_path).parent
        output_dir.mkdir(parents=True, exist_ok=True)

        tmp_path: Optional[str] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=str(output_dir),
                delete=False,
                suffix=".tmp",
            ) as tmp_file:
                tree = etree.ElementTree(root)
                tree.write(
                    tmp_file,
                    xml_declaration=True,
                    encoding="utf-8",
                    pretty_print=True,
                )
                tmp_file.flush()
                os.fsync(tmp_file.fileno())
                tmp_path = tmp_file.name

            os.chmod(tmp_path, 0o644)
            os.replace(tmp_path, output_path)

        except Exception as e:
            if tmp_path is not None:
                try:
                    Path(tmp_path).unlink(missing_ok=True)
                except OSError as cleanup_error:
                    logger.debug(f"Failed to clean up temp file: {cleanup_error}")
            raise OSError(f"Failed to write legacy XML to {output_path}: {e}") from e
