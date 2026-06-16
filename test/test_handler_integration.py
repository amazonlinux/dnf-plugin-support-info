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

"""Tests for AmazonLinuxSupportInfo handler integration."""

import os
import unittest

from supportinfo.handler import PackageEntry, SupportinfoHandler, SupportStatement

from dnf_support_info_plugin.models import PackageState
from dnf_support_info_plugin.support_info_service import SupportInfoService


class TestSupportInfoHandlerIntegration(unittest.TestCase):
    """Test proper integration with AmazonLinuxSupportInfo handler."""

    def setUp(self):
        """Set up test fixtures."""
        test_dir = os.path.dirname(__file__)
        self.legacy_xml = os.path.join(test_dir, "fixtures", "test_support_info_legacy.xml")
        self.v1_xml = os.path.join(test_dir, "fixtures", "test_support_info_v1.xml")
        self.v1_xsd_path = os.path.join(test_dir, "fixtures", "supportinfo-1.0.xsd")

    def test_handler_creation_legacy(self):
        """Test that handler detects legacy/unversioned format correctly."""
        handler = SupportinfoHandler.create(self.legacy_xml)
        self.assertIsNotNone(handler)

        # Legacy format should be detected as unversioned
        self.assertEqual(handler.schema_version.value, "unversioned")
        self.assertEqual(handler.__class__.__name__, "SupportinfoHandlerLegacy")

    def test_handler_creation_v1(self):
        """Test that handler detects v1.0 format correctly."""
        handler = SupportinfoHandler.create(self.v1_xml, self.v1_xsd_path)
        self.assertIsNotNone(handler)

        # v1.0 format should be detected
        self.assertEqual(handler.schema_version.value, "1.0")
        self.assertNotEqual(handler.__class__.__name__, "SupportinfoHandlerLegacy")

    def test_handler_creation_with_xsd_v1(self):
        """Test handler creation with XSD for v1.0 format."""
        handler = SupportinfoHandler.create(self.v1_xml, self.v1_xsd_path)
        self.assertIsNotNone(handler)
        self.assertEqual(handler.schema_version.value, "1.0")

    def test_service_initialization_legacy(self):
        """Test that service works with legacy handler."""
        handler = SupportinfoHandler.create(self.legacy_xml)
        service = SupportInfoService(handler)

        # Verify service initialized correctly
        self.assertIsNotNone(service.handler)

    def test_service_initialization_v1(self):
        """Test that service works with v1.0 handler."""
        handler = SupportinfoHandler.create(self.v1_xml, self.v1_xsd_path)
        service = SupportInfoService(handler)

        # Verify service initialized correctly
        self.assertIsNotNone(service.handler)

    def test_handler_data_structures_legacy(self):
        """Test that legacy handler returns expected data structures."""
        handler = SupportinfoHandler.create(self.legacy_xml)

        # Get metadata
        metadata = handler.get_support_metadata()
        self.assertIsInstance(metadata, dict)

        # Check that values are SupportStatement instances
        for statement_id, statement in metadata.items():
            self.assertIsInstance(statement, SupportStatement)
            # Legacy handler sets current_phase based on support status
            self.assertIsNotNone(statement.current_phase)

        # Get notes
        notes = handler.get_support_notes()
        self.assertIsInstance(notes, dict)

        # Get package entries - returns unified PackageEntry list
        package_entries = handler.get_package_entries()
        self.assertIsInstance(package_entries, list)

        # All entries should be PackageEntry dataclasses
        package_names = set()
        for entry in package_entries:
            self.assertIsInstance(entry, PackageEntry)
            package_names.add(entry.name)

        # Verify test packages are in the mapping
        self.assertIn("test-glibc", package_names)
        self.assertIn("test-bash", package_names)
        self.assertIn("test-php81", package_names)
        self.assertIn("test-python36", package_names)

    def test_handler_data_structures_v1(self):
        """Test that v1.0 handler returns expected data structures."""
        handler = SupportinfoHandler.create(self.v1_xml, self.v1_xsd_path)

        # Get metadata - returns lifecycle data for v1.0
        metadata = handler.get_support_metadata()
        self.assertIsInstance(metadata, dict)

        # Check that values are SupportStatement instances
        # V1.0 sets current_phase to the current phase name
        for lifecycle_name, statement in metadata.items():
            self.assertIsInstance(statement, SupportStatement)
            # V1.0 populates current_phase with phase name
            self.assertIsNotNone(statement.current_phase)
            # V1.0 has phases dict with support level info
            self.assertIsInstance(statement.phases, dict)

        # Get notes
        notes = handler.get_support_notes()
        self.assertIsInstance(notes, dict)

        # Get package entries - returns unified PackageEntry list
        package_entries = handler.get_package_entries()
        self.assertIsInstance(package_entries, list)

        # All entries should be PackageEntry dataclasses
        package_names = [entry.name for entry in package_entries]
        for entry in package_entries:
            self.assertIsInstance(entry, PackageEntry)

        self.assertIn("test-glibc", package_names)
        self.assertIn("test-bash", package_names)
        self.assertIn("test-php81", package_names)
        self.assertIn("test-python36", package_names)

    def test_handler_compatibility_across_schemas(self):
        """Test that both handlers return compatible data structures."""
        legacy_handler = SupportinfoHandler.create(self.legacy_xml)
        v1_handler = SupportinfoHandler.create(self.v1_xml, self.v1_xsd_path)

        # Extract package names from both handlers - now unified PackageEntry format
        legacy_pkg_names = {entry.name for entry in legacy_handler.get_package_entries()}
        v1_pkg_names = {entry.name for entry in v1_handler.get_package_entries()}

        # Both should have same package names
        self.assertEqual(legacy_pkg_names, v1_pkg_names)

        # Both should have same statement/lifecycle IDs
        legacy_statements = set(legacy_handler.get_support_metadata().keys())
        v1_statements = set(v1_handler.get_support_metadata().keys())
        self.assertEqual(legacy_statements, v1_statements)

        # Both should have same notes
        legacy_notes = set(legacy_handler.get_support_notes().keys())
        v1_notes = set(v1_handler.get_support_notes().keys())
        self.assertEqual(legacy_notes, v1_notes)

    def test_service_package_lookup_legacy(self):
        """Test package lookup through service with legacy handler."""
        handler = SupportinfoHandler.create(self.legacy_xml)
        service = SupportInfoService(handler)

        # Create mock package states
        package_states = {
            PackageState.INSTALLED.value: {
                "test-glibc": {"version": "2.34-52.amzn2023.0.7", "arch": "x86_64"}
            },
            PackageState.AVAILABLE.value: {},
        }

        # Get package info
        result = service.get_package_info("test-glibc", package_states)

        self.assertIsNotNone(result)
        self.assertEqual(result.name, "test-glibc")
        self.assertIsInstance(result.support_statement, SupportStatement)
        self.assertEqual(result.statement_id, "eol")

    def test_service_package_lookup_v1(self):
        """Test package lookup through service with v1.0 handler."""
        handler = SupportinfoHandler.create(self.v1_xml, self.v1_xsd_path)
        service = SupportInfoService(handler)

        # Create mock package states
        package_states = {
            PackageState.INSTALLED.value: {
                "test-glibc": {"version": "2.34-52.amzn2023.0.7", "arch": "x86_64"}
            },
            PackageState.AVAILABLE.value: {},
        }

        # Get package info
        result = service.get_package_info("test-glibc", package_states)

        self.assertIsNotNone(result)
        self.assertEqual(result.name, "test-glibc")
        self.assertIsInstance(result.support_statement, SupportStatement)
        self.assertEqual(result.statement_id, "eol")

    def test_service_filter_packages_legacy(self):
        """Test package filtering with legacy handler."""
        handler = SupportinfoHandler.create(self.legacy_xml)
        service = SupportInfoService(handler)

        package_states = {
            PackageState.INSTALLED.value: {
                "test-glibc": {"version": "2.34-52.amzn2023.0.7", "arch": "x86_64"}
            },
            PackageState.AVAILABLE.value: {
                "test-php81": {"version": "8.1.28-1.amzn2023", "arch": "x86_64"}
            },
        }

        # Test filtering with list of filters
        all_packages = service.filter_packages(["all"], package_states)
        self.assertIsInstance(all_packages, list)
        self.assertGreater(len(all_packages), 0)

        supported_packages = service.filter_packages(["supported"], package_states)
        self.assertIsInstance(supported_packages, list)

    def test_service_filter_packages_v1(self):
        """Test package filtering with v1.0 handler."""
        handler = SupportinfoHandler.create(self.v1_xml, self.v1_xsd_path)
        service = SupportInfoService(handler)

        package_states = {
            PackageState.INSTALLED.value: {
                "test-glibc": {"version": "2.34-52.amzn2023.0.7", "arch": "x86_64"}
            },
            PackageState.AVAILABLE.value: {
                "test-php81": {"version": "8.1.28-1.amzn2023", "arch": "x86_64"}
            },
        }

        # Test filtering with list of filters
        all_packages = service.filter_packages(["all"], package_states)
        self.assertIsInstance(all_packages, list)
        self.assertGreater(len(all_packages), 0)

        # Get valid filters from service - includes state and support level filters
        state_filters, support_level_filters = service.get_valid_filters()
        self.assertIn("all", state_filters)
        self.assertIn("installed", state_filters)
        self.assertIn("available", state_filters)
        self.assertIn("unavailable", state_filters)
        self.assertIsInstance(support_level_filters, dict)

    def test_current_phase_is_set_for_both_handlers(self):
        """Test that current_phase is set for both handlers."""
        test_cases = [
            (self.legacy_xml, None),
            (self.v1_xml, self.v1_xsd_path),
        ]
        for xml_path, xsd_path in test_cases:
            handler = SupportinfoHandler.create(xml_path, xsd_path)
            metadata = handler.get_support_metadata()

            # Check that current_phase values are set
            for statement in metadata.values():
                # current_phase should be set for both formats
                self.assertIsNotNone(statement.current_phase)
                # Should be string
                self.assertIsInstance(statement.current_phase, str)
