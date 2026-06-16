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

"""Tests for legacy_converter module."""

import os
import tempfile

import pytest
from lxml import etree
from supportinfo.handler import SupportinfoHandler

from dnf_support_info_plugin.legacy_converter import LegacyConverter


@pytest.fixture
def v1_conversion_xml():
    """Path to the V1.0 XML fixture designed for conversion testing."""
    test_dir = os.path.dirname(__file__)
    return os.path.join(test_dir, "fixtures", "test_support_info_v1_for_conversion.xml")


@pytest.fixture
def converted_legacy_path(v1_conversion_xml):
    """Convert V1.0 XML to legacy format and return the output path.

    This fixture runs the converter once and provides the output path
    for all tests that need to inspect the converted XML.
    """
    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as tmp:
        output_path = tmp.name

    try:
        converter = LegacyConverter(v1_conversion_xml)
        converter.convert(output_path)
        yield output_path
    finally:
        if os.path.exists(output_path):
            os.unlink(output_path)


@pytest.fixture
def converted_root(converted_legacy_path):
    """Parse the converted legacy XML and return the root element."""
    tree = etree.parse(converted_legacy_path)
    return tree.getroot()


class TestLegacyConverterInit:
    """Test LegacyConverter initialization."""

    def test_init_with_valid_file(self, v1_conversion_xml):
        """Test converter initializes with valid V1.0 XML."""
        converter = LegacyConverter(v1_conversion_xml)
        assert converter is not None

    def test_init_with_nonexistent_file(self):
        """Test converter raises FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError, match="Source XML not found"):
            LegacyConverter("/nonexistent/path.xml")


class TestRootElement:
    """Test root element conversion."""

    def test_root_has_current_as(self, converted_root):
        """Test converted root preserves current_as attribute."""
        assert converted_root.get("current_as") == "2024-01-17T00:00:00"

    def test_root_has_no_schema_version(self, converted_root):
        """Test converted root does not have schema_version attribute."""
        assert converted_root.get("schema_version") is None

    def test_root_tag_is_package_support(self, converted_root):
        """Test converted root tag is package_support."""
        assert converted_root.tag == "package_support"


class TestMilestoneResolution:
    """Test that milestone references are resolved to concrete dates."""

    def test_milestone_resolved_in_supported_statement(self, converted_root):
        """Test AL2023_GA milestone resolved to date in start_date."""
        # The eol_lc lifecycle uses start_milestone="al2023_ga"
        # which should resolve to "2023-03-15"
        stmt = converted_root.xpath(".//statement[@id='eol_default_lc']")
        assert len(stmt) == 1
        assert stmt[0].get("start_date") == "2023-03-15"

    def test_milestone_resolved_in_end_date(self, converted_root):
        """Test AL2023_EOL milestone resolved to date in end_date."""
        # The eol_lc lifecycle has unsupported phase with
        # start_milestone="al2023_eol" → "2028-03-15"
        stmt = converted_root.xpath(".//statement[@id='eol_default_lc']")
        assert len(stmt) == 1
        assert stmt[0].get("end_date") == "2028-03-15"


class TestLifecycleToStatementConversion:
    """Test lifecycle to statement conversion for all patterns."""

    def test_statements_element_exists(self, converted_root):
        """Test converted XML has <statements> element."""
        statements = converted_root.xpath("statements")
        assert len(statements) == 1

    def test_no_lifecycles_element(self, converted_root):
        """Test converted XML does not have <lifecycles> element."""
        lifecycles = converted_root.xpath("lifecycles")
        assert len(lifecycles) == 0

    def test_correct_number_of_statements(self, converted_root):
        """Test correct number of statements generated."""
        statements = converted_root.xpath(".//statement")
        assert len(statements) == 3

    def test_supported_statement_with_milestones(self, converted_root):
        """Test Pattern A: supported lifecycle with milestone dates."""
        stmt = converted_root.xpath(".//statement[@id='eol_default_lc']")
        assert len(stmt) == 1
        stmt = stmt[0]
        assert stmt.get("marker") == "supported"
        assert stmt.get("start_date") == "2023-03-15"
        assert stmt.get("end_date") == "2028-03-15"

    def test_supported_statement_with_concrete_dates(self, converted_root):
        """Test Pattern B: supported lifecycle with concrete dates and note."""
        stmt = converted_root.xpath(".//statement[@id='eol_php81']")
        assert len(stmt) == 1
        stmt = stmt[0]
        assert stmt.get("marker") == "supported"
        assert stmt.get("start_date") == "2023-03-15"
        assert stmt.get("end_date") == "2026-11-25"

    def test_unsupported_statement(self, converted_root):
        """Test Pattern C: single unsupported phase (past EOL)."""
        stmt = converted_root.xpath(".//statement[@id='eol_python36']")
        assert len(stmt) == 1
        stmt = stmt[0]
        assert stmt.get("marker") == "unsupported"
        assert stmt.get("start_date") == "2023-03-15"
        assert stmt.get("end_date") is None

    def test_statement_id_from_lifecycle_note(self, converted_root):
        """Test statement id comes from lifecycle note attribute."""
        # eol_php81_lc has note="eol_php81" → id="eol_php81"
        stmt = converted_root.xpath(".//statement[@id='eol_php81']")
        assert len(stmt) == 1

    def test_statement_id_fallback_to_lifecycle_name(self, converted_root):
        """Test statement id falls back to lifecycle name when no note."""
        # eol_lc has no note attribute → id="eol_lc"
        stmt = converted_root.xpath(".//statement[@id='eol_default_lc']")
        assert len(stmt) == 1


class TestStatementContent:
    """Test generated <summary>, <text>, <link> elements."""

    def test_supported_summary_contains_name_and_date(self, converted_root):
        """Test supported statement summary includes display name and end date."""
        stmt = converted_root.xpath(".//statement[@id='eol_php81']")
        summary = stmt[0].xpath("summary")[0].text
        # display_name="Php8.1 Lifecycle" → stripped to "Php8.1"
        # end_date="2026-11-25" → "November 2026"
        assert "Php8.1" in summary
        assert "November 2026" in summary

    def test_unsupported_summary_contains_name(self, converted_root):
        """Test unsupported statement summary includes display name."""
        stmt = converted_root.xpath(".//statement[@id='eol_python36']")
        summary = stmt[0].xpath("summary")[0].text
        assert "Python3.6" in summary

    def test_text_from_description(self, converted_root):
        """Test <text> contains lifecycle description."""
        stmt = converted_root.xpath(".//statement[@id='eol_php81']")
        text = stmt[0].xpath("text")[0].text
        assert text == "Support timeline for php8.1 packages"

    def test_link_has_placeholder(self, converted_root):
        """Test <link> contains placeholder text."""
        stmt = converted_root.xpath(".//statement[@id='eol_php81']")
        link = stmt[0].xpath("link")[0].text
        assert link is not None
        assert len(link) > 0


class TestPackageRegrouping:
    """Test that packages are correctly nested inside statements."""

    def test_packages_nested_in_correct_statement(self, converted_root):
        """Test packages are grouped under their lifecycle's statement."""
        # eol_lc should have test-bash and test-glibc
        stmt = converted_root.xpath(".//statement[@id='eol_default_lc']")
        packages = stmt[0].xpath("packages/package")
        pkg_names = [p.get("name") for p in packages]
        assert "test-bash" in pkg_names
        assert "test-glibc" in pkg_names
        assert len(pkg_names) == 2

    def test_packages_sorted_alphabetically(self, converted_root):
        """Test packages within a statement are sorted by name."""
        stmt = converted_root.xpath(".//statement[@id='eol_default_lc']")
        packages = stmt[0].xpath("packages/package")
        pkg_names = [p.get("name") for p in packages]
        assert pkg_names == sorted(pkg_names)

    def test_package_has_note_attribute(self, converted_root):
        """Test packages have note attribute from lifecycle note."""
        stmt = converted_root.xpath(".//statement[@id='eol_php81']")
        packages = stmt[0].xpath("packages/package")
        assert len(packages) == 1
        assert packages[0].get("note") == "eol_php81"

    def test_package_note_fallback_to_lifecycle_name(self, converted_root):
        """Test package note falls back to lifecycle name when no note."""
        stmt = converted_root.xpath(".//statement[@id='eol_default_lc']")
        packages = stmt[0].xpath("packages/package")
        for pkg in packages:
            assert pkg.get("note") == "eol_default_lc"

    def test_package_has_no_lifecycle_attr(self, converted_root):
        """Test packages do not have lifecycle attribute (V2-only)."""
        all_packages = converted_root.xpath(".//packages/package")
        for pkg in all_packages:
            assert pkg.get("lifecycle") is None

    def test_package_has_no_origin_attr(self, converted_root):
        """Test packages do not have origin attribute (V2-only)."""
        all_packages = converted_root.xpath(".//packages/package")
        for pkg in all_packages:
            assert pkg.get("origin") is None


class TestNotesConversion:
    """Test notes attribute rename from name to id."""

    def test_notes_element_exists(self, converted_root):
        """Test converted XML has <notes> element."""
        notes = converted_root.xpath("notes")
        assert len(notes) == 1

    def test_notes_use_id_attribute(self, converted_root):
        """Test notes use 'id' attribute instead of 'name'."""
        notes = converted_root.xpath("notes/note")
        for note in notes:
            assert note.get("id") is not None
            assert note.get("name") is None

    def test_note_text_preserved(self, converted_root):
        """Test note text content is preserved."""
        note = converted_root.xpath("notes/note[@id='eol_php81']")
        assert len(note) == 1
        assert "PHP 8.1" in note[0].text

    def test_correct_number_of_notes(self, converted_root):
        """Test correct number of notes in output."""
        notes = converted_root.xpath("notes/note")
        assert len(notes) == 2


class TestV2OnlySectionsDropped:
    """Test that V1.0-only sections are removed from output."""

    def test_no_support_milestones(self, converted_root):
        """Test <support_milestones> is not in output."""
        assert len(converted_root.xpath("support_milestones")) == 0

    def test_no_support_levels(self, converted_root):
        """Test <support_levels> is not in output."""
        assert len(converted_root.xpath("support_levels")) == 0

    def test_no_package_classes(self, converted_root):
        """Test <package_classes> is not in output."""
        assert len(converted_root.xpath("package_classes")) == 0

    def test_no_package_origins(self, converted_root):
        """Test <package_origins> is not in output."""
        assert len(converted_root.xpath("package_origins")) == 0


class TestHandlerCompatibility:
    """Test that converted XML can be parsed by SupportinfoHandlerLegacy."""

    def test_handler_parses_converted_xml(self, converted_legacy_path):
        """Test SupportinfoHandler.create() loads converted XML as legacy."""
        handler = SupportinfoHandler.create(converted_legacy_path)
        assert handler.schema_version.value == "unversioned"

    def test_handler_get_support_metadata(self, converted_legacy_path):
        """Test handler can retrieve support metadata from converted XML."""
        handler = SupportinfoHandler.create(converted_legacy_path)
        metadata = handler.get_support_metadata()
        assert len(metadata) == 3

    def test_handler_get_package_entries(self, converted_legacy_path):
        """Test handler can retrieve package entries from converted XML."""
        handler = SupportinfoHandler.create(converted_legacy_path)
        entries = handler.get_package_entries()
        pkg_names = [e.name for e in entries]
        assert "test-bash" in pkg_names
        assert "test-glibc" in pkg_names
        assert "test-php81" in pkg_names
        assert "test-python36" in pkg_names

    def test_handler_get_support_notes(self, converted_legacy_path):
        """Test handler can retrieve notes from converted XML."""
        handler = SupportinfoHandler.create(converted_legacy_path)
        notes = handler.get_support_notes()
        assert "eol_php81" in notes
        assert "eol_python36" in notes

    def test_handler_package_support_info(self, converted_legacy_path):
        """Test handler can get support info for specific package."""
        handler = SupportinfoHandler.create(converted_legacy_path)
        info = handler.get_package_support_info("test-php81")
        assert info is not None
        assert info.current_phase == "supported"

    def test_handler_unsupported_package(self, converted_legacy_path):
        """Test handler correctly identifies unsupported package."""
        handler = SupportinfoHandler.create(converted_legacy_path)
        info = handler.get_package_support_info("test-python36")
        assert info is not None
        assert info.current_phase == "unsupported"


class TestAtomicWrite:
    """Test atomic file writing behavior."""

    def test_output_file_created(self, v1_conversion_xml):
        """Test converter creates output file."""
        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as tmp:
            output_path = tmp.name

        try:
            converter = LegacyConverter(v1_conversion_xml)
            result = converter.convert(output_path)
            assert os.path.exists(result)
            assert result == output_path
        finally:
            os.unlink(output_path)

    def test_output_file_is_valid_xml(self, converted_legacy_path):
        """Test output file is well-formed XML."""
        # This will raise if XML is malformed
        tree = etree.parse(converted_legacy_path)
        assert tree.getroot() is not None

    def test_output_to_nonexistent_directory(self, v1_conversion_xml):
        """Test converter creates parent directories as needed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "subdir", "nested", "output.xml")
            converter = LegacyConverter(v1_conversion_xml)
            result = converter.convert(output_path)
            assert os.path.exists(result)


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_single_unsupported_phase_future_date(self):
        """Test lifecycle with only unsupported phase and future date."""
        xml_content = """<?xml version="1.0" ?>
<package_support schema_version="1.0" current_as="2022-01-01T00:00:00">
  <lifecycles>
    <lifecycle name="eol_future_lc" note="eol_future"
               display_name="Future Lifecycle"
               description="Not yet unsupported">
      <phase name="unsupported" support_level="eos" start_date="2025-01-01"/>
    </lifecycle>
  </lifecycles>
  <support_milestones/>
  <support_levels>
    <support_level name="eos" severities="" description="End of support - no further updates"/>
  </support_levels>
  <packages>
    <package name="future-pkg" lifecycle="eol_future_lc" origin="test"/>
  </packages>
  <package_classes>
    <package_class name="core"><summary>Core</summary><text>Core packages</text></package_class>
  </package_classes>
  <package_origins>
    <package_origin name="test" repo_id="test" dist="test" vendor="test"/>
  </package_origins>
  <notes>
    <note name="eol_future">Will be unsupported in 2025</note>
  </notes>
</package_support>"""

        with tempfile.NamedTemporaryFile(suffix=".xml", mode="w", delete=False) as src:
            src.write(xml_content)
            src_path = src.name

        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as out:
            out_path = out.name

        try:
            converter = LegacyConverter(src_path)
            converter.convert(out_path)
            tree = etree.parse(out_path)
            root = tree.getroot()
            stmt = root.xpath(".//statement[@id='eol_future']")
            assert len(stmt) == 1
            # Should be "unsupported" marker even though date is in future
            # because legacy handler recalculates status from marker + date
            assert stmt[0].get("marker") == "unsupported"
            assert stmt[0].get("start_date") == "2025-01-01"
        finally:
            os.unlink(src_path)
            os.unlink(out_path)

    def test_default_lifecycle_override_eol_lc(self):
        """Test that eol_lc lifecycle uses hardcoded override values."""
        xml_content = """<?xml version="1.0" ?>
<package_support schema_version="1.0" current_as="2024-01-17T00:00:00">
  <lifecycles>
    <lifecycle name="eol_lc" display_name="Lc Lifecycle"
               description="Support timeline for lc packages">
      <phase name="supported" support_level="standard" start_date="2023-03-15"/>
      <phase name="unsupported" support_level="eos" start_date="2029-06-30"/>
    </lifecycle>
  </lifecycles>
  <support_milestones/>
  <support_levels>
    <support_level name="standard" severities="Low,Medium,Important,Critical" description="Full security and bug fix support"/>
    <support_level name="eos" severities="" description="End of support - no further updates"/>
  </support_levels>
  <packages>
    <package name="test-pkg" lifecycle="eol_lc" origin="test"/>
  </packages>
  <package_classes>
    <package_class name="core"><summary>Core</summary><text>Core packages</text></package_class>
  </package_classes>
  <package_origins>
    <package_origin name="test" repo_id="test" dist="test" vendor="test"/>
  </package_origins>
  <notes>
    <note name="eol_lc">Default lifecycle note</note>
  </notes>
</package_support>"""

        with tempfile.NamedTemporaryFile(suffix=".xml", mode="w", delete=False) as src:
            src.write(xml_content)
            src_path = src.name

        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as out:
            out_path = out.name

        try:
            converter = LegacyConverter(src_path)
            converter.convert(out_path)
            tree = etree.parse(out_path)
            root = tree.getroot()

            # Statement ID should be overridden to eol_al2023
            stmt = root.xpath(".//statement[@id='eol_al2023']")
            assert len(stmt) == 1

            # Summary should use "Amazon Linux 2023" not "Lc"
            summary = stmt[0].xpath("summary")[0].text
            assert "Amazon Linux 2023" in summary

            # Text should use override description not "Support timeline for lc packages"
            text = stmt[0].xpath("text")[0].text
            assert "end-of-life" in text.lower()

            # Package note should use overridden statement_id
            pkg = stmt[0].xpath("packages/package[@name='test-pkg']")
            assert len(pkg) == 1
            assert pkg[0].get("note") == "eol_al2023"

            # No statement with original id should exist
            original = root.xpath(".//statement[@id='eol_lc']")
            assert len(original) == 0
        finally:
            os.unlink(src_path)
            os.unlink(out_path)
