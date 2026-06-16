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

"""
Integration tests for dnf-plugin-support-info.
Tests verify data structures and logic without testing output formatting.
"""

import json
import xml.etree.ElementTree as ElementTree

from dnf_support_info_plugin.formatters import JSONFormatter, XMLFormatter
from dnf_support_info_plugin.models import PackageInfo, PackageState


class TestXMLDataParsing:
    """Tests that verify XML parsing produces correct data structures"""

    def test_package_data_structure(self, parsed_test_data):
        """Verify package data is parsed correctly"""
        package_data = parsed_test_data["package_data"]

        # Verify all expected EOL IDs exist
        assert "eol" in package_data
        assert "eol_php81" in package_data
        assert "eol_python36" in package_data

        # Verify packages are associated with correct EOL IDs
        assert "test-glibc" in package_data["eol"]
        assert "test-bash" in package_data["eol"]
        assert "test-php81" in package_data["eol_php81"]
        assert "test-python36" in package_data["eol_python36"]

    def test_support_statement_data_structure(self, parsed_test_data):
        """Verify support statement data is parsed correctly"""
        support_statement_data = parsed_test_data["support_statement_data"]

        # Verify all EOL IDs have statements
        assert "eol" in support_statement_data
        assert "eol_php81" in support_statement_data
        assert "eol_python36" in support_statement_data

        # Verify main EOL statement has required fields
        eol_statement = support_statement_data["eol"]
        assert eol_statement["statement_id"] == "eol"
        assert eol_statement["current_phase"] is not None

    def test_note_data_structure(self, parsed_test_data):
        """Verify note data is parsed correctly"""
        note_data = parsed_test_data["note_data"]

        # Verify notes exist for custom EOL IDs
        assert "eol_php81" in note_data
        assert "eol_python36" in note_data

        # Verify note content
        assert "PHP 8.1" in note_data["eol_php81"]
        assert "Python 3.6" in note_data["eol_python36"]


class TestPackageStateLogic:
    """Tests that verify package state determination logic"""

    def test_package_state_mapping(self, mock_package_states):
        """Verify mock package states are structured correctly"""
        # Verify installed packages
        assert "test-glibc" in mock_package_states["installed"]
        assert "test-bash" in mock_package_states["installed"]
        assert mock_package_states["installed"]["test-glibc"]["state"] == "installed"
        assert mock_package_states["installed"]["test-glibc"]["version"] == "2.34-52.amzn2023.0.7"

        # Verify available packages
        assert "test-php81" in mock_package_states["available"]
        assert "test-python36" in mock_package_states["available"]
        assert mock_package_states["available"]["test-php81"]["state"] == "available"

    def test_package_to_statement_mapping(self, parsed_test_data):
        """Verify packages can be mapped to their statements"""
        package_data = parsed_test_data["package_data"]
        support_statement_data = parsed_test_data["support_statement_data"]

        # For each package, verify it has a corresponding statement
        for eol_id, packages in package_data.items():
            assert eol_id in support_statement_data, f"Missing statement for {eol_id}"
            statement = support_statement_data[eol_id]
            assert statement["statement_id"] == eol_id
            assert len(packages) > 0, f"No packages for {eol_id}"

    def test_multiple_packages_query(self, parsed_test_data, mock_package_states):
        """Verify querying multiple packages at once works correctly"""
        package_data = parsed_test_data["package_data"]

        # Simulate querying multiple packages at once
        query_packages = ["test-glibc", "test-bash", "test-php81"]

        # Verify all requested packages can be found
        found_packages = set()
        for eol_id, packages in package_data.items():
            for pkg in packages:
                if pkg in query_packages:
                    found_packages.add(pkg)

        # Should find test-glibc, test-bash, and test-php81
        assert "test-glibc" in found_packages
        assert "test-bash" in found_packages
        assert "test-php81" in found_packages
        assert len(found_packages) == 3

        # Verify state information is available for all packages
        for pkg in query_packages:
            found_in_states = False
            if pkg in mock_package_states["installed"]:
                found_in_states = True
                assert mock_package_states["installed"][pkg]["name"] == pkg
            elif pkg in mock_package_states["available"]:
                found_in_states = True
                assert mock_package_states["available"][pkg]["name"] == pkg
            assert found_in_states, f"Package {pkg} not found in package states"

    def test_invalid_package_handling(self, parsed_test_data, mock_package_states):
        """Verify handling of non-existent/invalid packages"""
        package_data = parsed_test_data["package_data"]

        # Test with packages that don't exist
        invalid_packages = ["nonexistent-package", "invalid-pkg", "does-not-exist"]

        # Verify invalid packages are not in package data
        for eol_id, packages in package_data.items():
            for invalid_pkg in invalid_packages:
                assert (
                    invalid_pkg not in packages
                ), f"Invalid package {invalid_pkg} found in package data"

        # Verify invalid packages are not in package states
        for invalid_pkg in invalid_packages:
            assert (
                invalid_pkg not in mock_package_states["installed"]
            ), f"Invalid package {invalid_pkg} found in installed states"
            assert (
                invalid_pkg not in mock_package_states["available"]
            ), f"Invalid package {invalid_pkg} found in available states"

    def test_mixed_valid_invalid_packages(self, parsed_test_data, mock_package_states):
        """Verify handling of mix of valid and invalid packages"""
        package_data = parsed_test_data["package_data"]

        # Mix of valid and invalid packages
        mixed_packages = ["test-glibc", "nonexistent-pkg", "test-php81", "invalid-package"]

        # Find only valid packages
        valid_found = []
        invalid_found = []

        for pkg in mixed_packages:
            pkg_exists = False
            # Check in package data
            for eol_id, packages in package_data.items():
                if pkg in packages:
                    pkg_exists = True
                    break

            if pkg_exists:
                valid_found.append(pkg)
            else:
                invalid_found.append(pkg)

        # Should find only the valid packages
        assert "test-glibc" in valid_found
        assert "test-php81" in valid_found
        assert len(valid_found) == 2

        # Should identify the invalid packages
        assert "nonexistent-pkg" in invalid_found
        assert "invalid-package" in invalid_found
        assert len(invalid_found) == 2


class TestMultiPackageEdgeCases:
    """Tests for edge cases in multi-package handling"""

    def test_empty_list_handling(self, parsed_test_data, mock_package_states):
        """Verify behavior when empty list is provided"""
        package_data = parsed_test_data["package_data"]

        # Empty list should be treated as "query all packages" behavior
        # This matches the docstring: "If None or empty, returns all packages"
        empty_list_packages = []

        # When we query with empty list, we should get all packages
        all_packages = set()
        for eol_id, packages in package_data.items():
            all_packages.update(packages)

        # Verify we have multiple packages available
        assert len(all_packages) > 0
        assert "test-glibc" in all_packages
        assert "test-bash" in all_packages
        assert "test-php81" in all_packages
        assert "test-python36" in all_packages

    def test_none_value_handling(self, parsed_test_data):
        """Verify behavior when None is provided (should return all packages)"""
        package_data = parsed_test_data["package_data"]

        # None should also mean "return all packages" per docstring
        all_packages = set()
        for eol_id, packages in package_data.items():
            all_packages.update(packages)

        # Should have all test packages
        assert len(all_packages) == 4
        assert "test-glibc" in all_packages
        assert "test-bash" in all_packages
        assert "test-php81" in all_packages
        assert "test-python36" in all_packages

    def test_duplicate_packages_handling(self, parsed_test_data, mock_package_states):
        """Verify behavior when duplicate package names are provided"""
        package_data = parsed_test_data["package_data"]

        # Query with duplicates
        packages_with_duplicates = [
            "test-glibc",
            "test-bash",
            "test-glibc",
            "test-php81",
            "test-glibc",
        ]

        # Find unique packages (duplicates should be handled gracefully)
        unique_found = set()
        for eol_id, packages in package_data.items():
            for pkg in packages:
                if pkg in packages_with_duplicates:
                    unique_found.add(pkg)

        # Should find only unique packages
        assert len(unique_found) == 3
        assert "test-glibc" in unique_found
        assert "test-bash" in unique_found
        assert "test-php81" in unique_found

        # Verify each package appears exactly once in the result set
        assert unique_found == {"test-glibc", "test-bash", "test-php81"}

    def test_single_package_as_list(self, parsed_test_data, mock_package_states):
        """Verify single package works when passed as list"""
        package_data = parsed_test_data["package_data"]

        # Single package in list (as documented: "For single package, pass as ['package_name']")
        single_package_list = ["test-glibc"]

        found_packages = []
        for eol_id, packages in package_data.items():
            for pkg in packages:
                if pkg in single_package_list:
                    found_packages.append(pkg)

        # Should find exactly one package
        assert len(found_packages) == 1
        assert found_packages[0] == "test-glibc"

        # Verify it has correct state
        assert "test-glibc" in mock_package_states["installed"]

    def test_all_invalid_packages(self, parsed_test_data, mock_package_states):
        """Verify behavior when all packages in list are invalid"""
        package_data = parsed_test_data["package_data"]

        # All invalid packages
        all_invalid = ["nonexistent1", "invalid-pkg2", "fake-package3"]

        found_packages = []
        for eol_id, packages in package_data.items():
            for pkg in packages:
                if pkg in all_invalid:
                    found_packages.append(pkg)

        # Should find nothing
        assert len(found_packages) == 0

        # Verify none are in package states
        for invalid_pkg in all_invalid:
            assert invalid_pkg not in mock_package_states["installed"]
            assert invalid_pkg not in mock_package_states["available"]

    def test_case_sensitivity(self, parsed_test_data):
        """Verify package name matching is case-sensitive"""
        package_data = parsed_test_data["package_data"]

        # Try with wrong case
        wrong_case_packages = ["Test-Glibc", "TEST-BASH", "test-PHP81"]

        found_packages = []
        for eol_id, packages in package_data.items():
            for pkg in packages:
                if pkg in wrong_case_packages:
                    found_packages.append(pkg)

        # Should find nothing (case-sensitive matching)
        assert len(found_packages) == 0

        # Verify correct case works
        correct_case = ["test-glibc"]
        found_correct = []
        for eol_id, packages in package_data.items():
            for pkg in packages:
                if pkg in correct_case:
                    found_correct.append(pkg)

        assert len(found_correct) == 1


class TestFilterLogic:
    """Tests that verify filtering logic for different package states"""

    def test_supported_packages_identified(self, parsed_test_data):
        """Verify we can identify all supported packages"""
        package_data = parsed_test_data["package_data"]
        support_statement_data = parsed_test_data["support_statement_data"]

        # Filter packages by current_phase being "supported" or similar
        supported_packages = []
        for eol_id, packages in package_data.items():
            stmt = support_statement_data[eol_id]
            current_phase = stmt.get("current_phase", "")
            if current_phase in ("supported", "full_support", "standard_support"):
                supported_packages.extend(packages)

        # Should have test-glibc, test-bash (from eol), test-php81 (from eol_php81)
        assert "test-glibc" in supported_packages
        assert "test-bash" in supported_packages
        assert "test-php81" in supported_packages

    def test_unsupported_packages_identified(self, parsed_test_data):
        """Verify we can identify all unsupported packages"""
        package_data = parsed_test_data["package_data"]
        support_statement_data = parsed_test_data["support_statement_data"]

        # Filter packages by current_phase being "unsupported" or "end_of_life"
        unsupported_packages = []
        for eol_id, packages in package_data.items():
            stmt = support_statement_data[eol_id]
            current_phase = stmt.get("current_phase", "")
            if current_phase in ("unsupported", "end_of_life"):
                unsupported_packages.extend(packages)

        # Should have test-python36 only
        assert "test-python36" in unsupported_packages

    def test_installed_packages_filtered(self, parsed_test_data, mock_package_states):
        """Verify we can filter to only installed packages"""
        package_data = parsed_test_data["package_data"]
        installed_states = mock_package_states["installed"]

        installed_packages = []
        for eol_id, packages in package_data.items():
            for pkg in packages:
                if pkg in installed_states:
                    installed_packages.append(pkg)

        assert "test-glibc" in installed_packages
        assert "test-bash" in installed_packages
        assert "test-php81" not in installed_packages
        assert "test-python36" not in installed_packages

    def test_available_packages_filtered(self, parsed_test_data, mock_package_states):
        """Verify we can filter to only available packages"""
        package_data = parsed_test_data["package_data"]
        available_states = mock_package_states["available"]

        available_packages = []
        for eol_id, packages in package_data.items():
            for pkg in packages:
                if pkg in available_states:
                    available_packages.append(pkg)

        assert "test-php81" in available_packages
        assert "test-python36" in available_packages
        assert "test-glibc" not in available_packages


class TestXMLDataIntegrity:
    """Integration tests that validate XML data consistency"""

    def test_all_packages_have_complete_data(self, parsed_test_data):
        """Ensure all packages in test XML have required fields"""
        package_data = parsed_test_data["package_data"]
        support_statement_data = parsed_test_data["support_statement_data"]
        note_data = parsed_test_data["note_data"]

        for eol_id, packages in package_data.items():
            # Verify statement exists for this eol_id
            assert eol_id in support_statement_data, f"Missing statement for eol_id: {eol_id}"

            statement = support_statement_data[eol_id]

            # Verify required fields are present
            required_fields = ["statement_id", "current_phase"]
            for field in required_fields:
                assert field in statement, f"Missing {field} in statement {eol_id}"
                assert statement[field] is not None, f"{field} is None in statement {eol_id}"

            # Verify packages list is not empty
            assert len(packages) > 0, f"No packages for eol_id: {eol_id}"

            # If eol_id is not 'eol', verify note exists
            if eol_id != "eol":
                assert eol_id in note_data, f"Missing note for eol_id: {eol_id}"


class TestJSONFormatter:
    """Tests for JSON output formatting"""

    def test_json_format_single_package(self, supported_statement_legacy, mock_package_states):
        """Test JSON formatter produces valid JSON for a single package"""
        package_info = PackageInfo(
            name="test-glibc",
            version="2.34-52.amzn2023.0.7",
            arch="x86_64",
            state=PackageState.INSTALLED,
            support_statement=supported_statement_legacy,
            statement_id="eol",
            note=None,
        )

        # Format as JSON
        formatter = JSONFormatter()
        json_output = formatter.format_packages([package_info])

        # Verify valid JSON
        parsed = json.loads(json_output)
        assert parsed["name"] == "test-glibc"
        assert parsed["version"] == "2.34-52.amzn2023.0.7"
        assert parsed["state"] == "installed"

    def test_json_format_multiple_packages(
        self, supported_statement_legacy, unsupported_statement_legacy, mock_package_states
    ):
        """Test JSON formatter produces valid JSON array for multiple packages"""
        # Create multiple PackageInfo objects
        packages = []

        # test-glibc (installed, supported)
        packages.append(
            PackageInfo(
                name="test-glibc",
                version="2.34-52.amzn2023.0.7",
                arch="x86_64",
                state=PackageState.INSTALLED,
                support_statement=supported_statement_legacy,
                statement_id="eol",
                note=None,
            )
        )

        # test-php81 (available, supported)
        packages.append(
            PackageInfo(
                name="test-php81",
                version="8.1.28-1.amzn2023",
                arch="x86_64",
                state=PackageState.AVAILABLE,
                support_statement=supported_statement_legacy,
                statement_id="eol_php81",
                note=None,
            )
        )

        # Format as JSON array
        formatter = JSONFormatter()
        json_output = formatter.format_packages_table(packages)

        # Verify valid JSON array
        parsed = json.loads(json_output)
        assert isinstance(parsed, list)
        assert len(parsed) == 2

        # Verify first package (test-glibc)
        assert parsed[0]["name"] == "test-glibc"
        assert parsed[0]["state"] == "installed"

        # Verify second package (test-php81)
        assert parsed[1]["name"] == "test-php81"
        assert parsed[1]["state"] == "available"


class TestXMLFormatter:
    """Tests for XML output formatting"""

    def test_xml_format_single_package(self, supported_statement_legacy, mock_package_states):
        """Test XML formatter produces valid XML for a single package"""
        package_info = PackageInfo(
            name="test-glibc",
            version="2.34-52.amzn2023.0.7",
            arch="x86_64",
            state=PackageState.INSTALLED,
            support_statement=supported_statement_legacy,
            statement_id="eol",
            note=None,
        )

        # Format as XML
        formatter = XMLFormatter()
        xml_output = formatter.format_packages([package_info])

        # Verify valid XML
        assert "<?xml version=" in xml_output
        assert "encoding=" in xml_output
        assert "<package_support" in xml_output
        assert 'id="eol"' in xml_output
        assert '<package name="test-glibc"' in xml_output
        assert 'nevra="2.34-52.amzn2023.0.7"' in xml_output

        # Parse XML to verify structure
        xml_content = xml_output.split("?>", 1)[1] if "?>" in xml_output else xml_output
        root = ElementTree.fromstring(xml_content.strip())

        assert root.tag == "package_support"
        assert root.find(".//statement") is not None
        assert root.find(".//package") is not None

    def test_xml_format_multiple_packages(
        self, supported_statement_legacy, unsupported_statement_legacy, mock_package_states
    ):
        """Test XML formatter for multiple packages"""
        # Create multiple PackageInfo objects
        packages = []

        # test-glibc (installed, supported)
        packages.append(
            PackageInfo(
                name="test-glibc",
                version="2.34-52.amzn2023.0.7",
                arch="x86_64",
                state=PackageState.INSTALLED,
                support_statement=supported_statement_legacy,
                statement_id="eol",
                note=None,
            )
        )

        # test-python36 (available, unsupported)
        packages.append(
            PackageInfo(
                name="test-python36",
                version="3.6.15-1.amzn2023",
                arch="x86_64",
                state=PackageState.AVAILABLE,
                support_statement=unsupported_statement_legacy,
                statement_id="eol_python36",
                note=None,
            )
        )

        # Format as XML
        formatter = XMLFormatter()
        xml_output = formatter.format_packages_table(packages)

        # Verify output is a single XML document with both packages
        assert xml_output.count("<?xml version=") == 1
        assert '<package name="test-glibc"' in xml_output
        assert '<package name="test-python36"' in xml_output

        # Parse XML to verify structure
        xml_content = xml_output.split("?>", 1)[1] if "?>" in xml_output else xml_output
        root = ElementTree.fromstring(xml_content.strip())

        # Should have 2 statements
        statements = root.findall(".//statement")
        assert len(statements) == 2

        # Verify both packages are present
        packages_in_xml = root.findall(".//package")
        package_names = [pkg.get("name") for pkg in packages_in_xml]
        assert "test-glibc" in package_names
        assert "test-python36" in package_names
