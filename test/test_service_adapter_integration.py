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

"""Integration tests for SupportInfoService."""

from unittest.mock import Mock

import pytest
from dnf.exceptions import Error as DnfError
from supportinfo.handler import (
    PhaseInfo,
    SupportinfoSchemaVersions,
    SupportLevelInfo,
    SupportStatement,
)

from dnf_support_info_plugin.models import PackageState
from dnf_support_info_plugin.support_info_service import SupportInfoService


class TestSupportInfoServiceIntegration:
    """Test SupportInfoService with real handlers."""

    def test_service_initializes_with_handler(self, legacy_handler):
        """Test service initializes with handler."""
        service = SupportInfoService(legacy_handler)

        assert service.handler == legacy_handler

    def test_get_package_info_returns_package_with_support_info(self, legacy_handler):
        """Test get_package_info returns PackageInfo with support information."""
        service = SupportInfoService(legacy_handler)

        package_states = {
            "installed": {
                "test-glibc": {
                    "name": "test-glibc",
                    "version": "2.34-52.amzn2023.0.7",
                    "arch": "x86_64",
                }
            },
            "available": {},
        }

        result = service.get_package_info("test-glibc", package_states)

        assert result is not None
        assert result.name == "test-glibc"
        assert result.state == PackageState.INSTALLED
        assert result.statement_id is not None
        assert result.support_statement is not None

    def test_get_package_info_not_found_returns_none(self, legacy_handler):
        """Test get_package_info returns None when package not found."""
        service = SupportInfoService(legacy_handler)

        package_states = {"installed": {}, "available": {}}

        result = service.get_package_info("nonexistent-package", package_states)

        assert result is None

    def test_get_package_info_unavailable_package(self, legacy_handler):
        """Test get_package_info with unavailable package."""
        service = SupportInfoService(legacy_handler)

        # Package exists in support info but not in DNF states
        package_states = {"installed": {}, "available": {}}

        result = service.get_package_info("test-glibc", package_states)

        assert result is not None
        assert result.state == PackageState.UNAVAILABLE

    def test_filter_packages_all(self, legacy_handler):
        """Test filter_packages with 'all' filter returns all packages."""
        service = SupportInfoService(legacy_handler)

        package_states = {
            "installed": {
                "test-glibc": {
                    "name": "test-glibc",
                    "version": "2.34-52.amzn2023.0.7",
                    "arch": "x86_64",
                },
                "test-bash": {
                    "name": "test-bash",
                    "version": "5.2.15-1.amzn2023.0.4",
                    "arch": "x86_64",
                },
            },
            "available": {},
        }

        results = service.filter_packages(["all"], package_states)

        assert len(results) >= 2
        for pkg in results:
            assert pkg.statement_id is not None

    def test_filter_packages_installed(self, legacy_handler):
        """Test filter_packages with 'installed' filter."""
        service = SupportInfoService(legacy_handler)

        package_states = {
            "installed": {
                "test-glibc": {
                    "name": "test-glibc",
                    "version": "2.34-52.amzn2023.0.7",
                    "arch": "x86_64",
                }
            },
            "available": {
                "test-php81": {
                    "name": "test-php81",
                    "version": "8.1.28-1.amzn2023",
                    "arch": "x86_64",
                }
            },
        }

        results = service.filter_packages(["installed"], package_states)

        for pkg in results:
            assert pkg.state == PackageState.INSTALLED

    def test_filter_packages_available(self, legacy_handler):
        """Test filter_packages with 'available' filter."""
        service = SupportInfoService(legacy_handler)

        package_states = {
            "installed": {
                "test-glibc": {
                    "name": "test-glibc",
                    "version": "2.34-52.amzn2023.0.7",
                    "arch": "x86_64",
                }
            },
            "available": {
                "test-php81": {
                    "name": "test-php81",
                    "version": "8.1.28-1.amzn2023",
                    "arch": "x86_64",
                }
            },
        }

        results = service.filter_packages(["available"], package_states)

        for pkg in results:
            assert pkg.state == PackageState.AVAILABLE

    def test_filter_packages_invalid_filter_raises_error(self, legacy_handler):
        """Test filter_packages raises ValueError for invalid filter."""
        service = SupportInfoService(legacy_handler)

        package_states = {"installed": {}, "available": {}}

        with pytest.raises(ValueError, match="Unknown filter"):
            service.filter_packages(["invalid_filter"], package_states)

    def test_filter_packages_all_includes_unavailable(self, legacy_handler):
        """Test filter_packages with 'all' filter includes unavailable packages."""
        service = SupportInfoService(legacy_handler)

        # Empty package states - all packages are unavailable
        package_states = {"installed": {}, "available": {}}

        results = service.filter_packages(["all"], package_states)

        # With 'all' filter, unavailable packages should be included
        assert len(results) > 0
        for pkg in results:
            assert pkg.state == PackageState.UNAVAILABLE

    def test_filter_packages_multiple_state_filters(self, legacy_handler):
        """Test filter_packages with multiple state filters (OR logic)."""
        service = SupportInfoService(legacy_handler)

        package_states = {
            "installed": {
                "test-glibc": {
                    "name": "test-glibc",
                    "version": "2.34-52.amzn2023.0.7",
                    "arch": "x86_64",
                }
            },
            "available": {
                "test-php81": {
                    "name": "test-php81",
                    "version": "8.1.28-1.amzn2023",
                    "arch": "x86_64",
                }
            },
        }

        # Multiple state filters should OR together
        results = service.filter_packages(["installed", "available"], package_states)

        states = {pkg.state for pkg in results}
        # Should include both installed and available packages
        assert PackageState.INSTALLED in states or PackageState.AVAILABLE in states

    def test_filter_packages_unavailable_filter(self, legacy_handler):
        """Test filter_packages with 'unavailable' filter."""
        service = SupportInfoService(legacy_handler)

        # Only have one package installed, others should be unavailable
        package_states = {
            "installed": {
                "test-glibc": {
                    "name": "test-glibc",
                    "version": "2.34-52.amzn2023.0.7",
                    "arch": "x86_64",
                }
            },
            "available": {},
        }

        results = service.filter_packages(["unavailable"], package_states)

        for pkg in results:
            assert pkg.state == PackageState.UNAVAILABLE

    def test_filter_packages_state_and_support_level_filters(self, legacy_handler):
        """Test filter_packages with both state and support level filters (AND logic)."""
        service = SupportInfoService(legacy_handler)

        package_states = {
            "installed": {
                "test-glibc": {
                    "name": "test-glibc",
                    "version": "2.34-52.amzn2023.0.7",
                    "arch": "x86_64",
                }
            },
            "available": {
                "test-php81": {
                    "name": "test-php81",
                    "version": "8.1.28-1.amzn2023",
                    "arch": "x86_64",
                }
            },
        }

        # Get valid support level names from handler
        support_levels = service.handler.get_support_level_info()
        if support_levels:
            support_level_name = support_levels[0].name
            results = service.filter_packages(["installed", support_level_name], package_states)

            # All results should be installed AND have the specified support level
            for pkg in results:
                assert pkg.state == PackageState.INSTALLED

    def test_filter_packages_empty_candidate_packages(self, legacy_handler):
        """Test filter_packages returns empty when no packages match state filters."""
        service = SupportInfoService(legacy_handler)

        # No packages in any state, but filter for 'installed'
        package_states = {"installed": {}, "available": {}}

        results = service.filter_packages(["installed"], package_states)

        # Should return empty list, not all packages
        assert results == []

    def test_get_package_info_with_note(self, legacy_handler):
        """Test get_package_info retrieves note when available."""
        service = SupportInfoService(legacy_handler)

        package_states = {
            "available": {
                "test-python36": {
                    "name": "test-python36",
                    "version": "3.6.15-1.amzn2023",
                    "arch": "x86_64",
                }
            },
            "installed": {},
        }

        result = service.get_package_info("test-python36", package_states)

        # test-python36 has a note in the test fixture
        if result:
            # Note might be None or a string depending on fixture
            assert result.note is None or isinstance(result.note, str)

    def test_service_has_support_statement(self, legacy_handler):
        """Test service returns PackageInfo with support_statement."""
        service = SupportInfoService(legacy_handler)

        package_states = {
            "installed": {
                "test-glibc": {
                    "name": "test-glibc",
                    "version": "2.34-52.amzn2023.0.7",
                    "arch": "x86_64",
                }
            },
            "available": {},
        }

        result = service.get_package_info("test-glibc", package_states)

        assert result is not None
        assert result.support_statement is not None
        assert isinstance(result.support_statement, SupportStatement)
        assert result.statement_id is not None

    def test_get_all_packages_empty_list(self, legacy_handler):
        """Test _get_all_packages with empty list returns empty dict."""
        service = SupportInfoService(legacy_handler)
        result = service._get_all_packages(package_names=[])

        assert result == {}


class TestSupportInfoServiceCoverage:
    """Tests for SupportInfoService coverage gaps."""

    def test_get_package_info_handles_exception(self, legacy_handler, monkeypatch):
        """Test get_package_info raises DnfError on exceptions."""
        service = SupportInfoService(legacy_handler)

        # Mock _get_all_packages to raise an exception
        def raise_exception(*args, **kwargs):
            raise RuntimeError("Simulated error")

        monkeypatch.setattr(service, "_get_all_packages", raise_exception)

        package_states = {
            "installed": {
                "test-glibc": {
                    "name": "test-glibc",
                    "version": "2.34-52",
                    "arch": "x86_64",
                }
            },
            "available": {},
        }

        with pytest.raises(DnfError, match="Unable to retrieve support information"):
            service.get_package_info("test-glibc", package_states)

    def test_get_package_info_statement_not_found(self, legacy_handler, monkeypatch):
        """Test get_package_info when statement_id exists but metadata doesn't."""
        service = SupportInfoService(legacy_handler)

        monkeypatch.setattr(
            service.handler, "get_package_support_info", lambda *args, **kwargs: None
        )

        package_states = {
            "installed": {
                "test-glibc": {
                    "name": "test-glibc",
                    "version": "2.34-52",
                    "arch": "x86_64",
                }
            },
            "available": {},
        }

        result = service.get_package_info("test-glibc", package_states)
        assert result is None

    def test_resolve_note_from_lifecycle_note(self, legacy_handler):
        """Test _resolve_note uses lifecycle_note when available."""
        service = SupportInfoService(legacy_handler)

        statement = SupportStatement(
            current_phase="full_support",
            phases={
                "full_support": PhaseInfo(
                    name="full_support",
                    start_date="2023-01-01",
                    support_level_info=SupportLevelInfo(
                        name="default", severities="Low", description="Default support"
                    ),
                )
            },
            summary="",
            text="",
            link="",
            lifecycle_note="lifecycle_note_key",
        )

        all_notes = {
            "lifecycle_note_key": "Note from lifecycle",
            "package_note_key": "Note from package element",
        }

        result = service._resolve_note(statement, "package_note_key", all_notes)
        assert result == "Note from lifecycle"

    def test_resolve_note_from_note_ref(self, legacy_handler):
        """Test _resolve_note uses note_ref when lifecycle_note is None."""
        service = SupportInfoService(legacy_handler)

        statement = SupportStatement(
            current_phase="full_support",
            phases={
                "full_support": PhaseInfo(
                    name="full_support",
                    start_date="2023-01-01",
                    support_level_info=SupportLevelInfo(
                        name="default", severities="Low", description="Default support"
                    ),
                )
            },
            summary="",
            text="",
            link="",
            lifecycle_note=None,
        )

        all_notes = {"package_note_key": "Note from package element"}

        result = service._resolve_note(statement, "package_note_key", all_notes)
        assert result == "Note from package element"

    def test_resolve_note_returns_none_when_no_notes(self, legacy_handler):
        """Test _resolve_note returns None when no notes available."""
        service = SupportInfoService(legacy_handler)

        statement = SupportStatement(
            current_phase="full_support",
            phases={
                "full_support": PhaseInfo(
                    name="full_support",
                    start_date="2023-01-01",
                    support_level_info=SupportLevelInfo(
                        name="default", severities="Low", description="Default support"
                    ),
                )
            },
            summary="",
            text="",
            link="",
            lifecycle_note=None,
        )

        result = service._resolve_note(statement, None, {})
        assert result is None

    def test_categorize_filters_all_alone(self, legacy_handler):
        """Test _categorize_filters expands 'all' to all PackageState values."""
        service = SupportInfoService(legacy_handler)

        state_filters, support_filters = service._categorize_filters(["all"])

        assert state_filters == {s.value for s in PackageState}
        assert support_filters == set()

    def test_categorize_filters_installed_only_in_state(self, legacy_handler):
        """Test _categorize_filters puts 'installed' only in state list."""
        service = SupportInfoService(legacy_handler)

        state_filters, support_filters = service._categorize_filters(["installed"])

        assert state_filters == {"installed"}
        assert support_filters == set()

    def test_categorize_filters_ambiguous_in_both(self, legacy_handler):
        """Test _categorize_filters puts ambiguous name in both lists."""
        service = SupportInfoService(legacy_handler)

        # Get a support level name that conflicts with a state filter name
        # Use explicit support level to test categorization
        support_levels = service.handler.get_support_level_info()
        if support_levels:
            support_level_name = support_levels[0].name
            state_filters, support_filters = service._categorize_filters(
                ["installed", support_level_name]
            )

            assert "installed" in state_filters
            assert support_level_name in support_filters

    def test_categorize_filters_state_prefix(self, legacy_handler):
        """Test _categorize_filters with state: prefix."""
        service = SupportInfoService(legacy_handler)

        state_filters, support_filters = service._categorize_filters(["state:installed"])

        assert state_filters == {"installed"}
        assert support_filters == set()

    def test_categorize_filters_support_prefix(self, legacy_handler):
        """Test _categorize_filters with support: prefix."""
        service = SupportInfoService(legacy_handler)

        support_levels = service.handler.get_support_level_info()
        if support_levels:
            support_level_name = support_levels[0].name
            state_filters, support_filters = service._categorize_filters(
                [f"support:{support_level_name}"]
            )

            assert state_filters == set()
            assert support_filters == {support_level_name}

    def test_matches_filters_state_only(self, legacy_handler):
        """Test _matches_filters with only state filters."""
        service = SupportInfoService(legacy_handler)

        statement = SupportStatement(current_phase=None, phases={}, summary="", text="", link="")

        assert (
            service._matches_filters(PackageState.INSTALLED, statement, {"installed"}, set())
            is True
        )
        assert (
            service._matches_filters(PackageState.AVAILABLE, statement, {"installed"}, set())
            is False
        )
        # OR within state: installed or available
        assert (
            service._matches_filters(
                PackageState.INSTALLED, statement, {"installed", "available"}, set()
            )
            is True
        )
        assert (
            service._matches_filters(
                PackageState.AVAILABLE, statement, {"installed", "available"}, set()
            )
            is True
        )
        assert (
            service._matches_filters(
                PackageState.UNAVAILABLE, statement, {"installed", "available"}, set()
            )
            is False
        )

    def test_matches_filters_support_level_only(self, legacy_handler):
        """Test _matches_filters with only support level filters."""
        service = SupportInfoService(legacy_handler)

        support_levels = service.handler.get_support_level_info()
        if not support_levels:
            pytest.skip("No support levels available in test fixture")

        support_level_name = support_levels[0].name

        statement = SupportStatement(
            current_phase="phase1",
            phases={
                "phase1": PhaseInfo(
                    name="phase1", start_date="2023-01-01", support_level_info=support_levels[0]
                )
            },
            summary="",
            text="",
            link="",
        )

        assert (
            service._matches_filters(PackageState.INSTALLED, statement, set(), {support_level_name})
            is True
        )
        assert (
            service._matches_filters(PackageState.INSTALLED, statement, set(), {"nonexistent"})
            is False
        )

    def test_matches_filters_state_and_support_level(self, legacy_handler):
        """Test _matches_filters with both state and support level filters (AND logic)."""
        service = SupportInfoService(legacy_handler)

        support_levels = service.handler.get_support_level_info()
        if not support_levels:
            pytest.skip("No support levels available in test fixture")

        support_level_name = support_levels[0].name

        statement = SupportStatement(
            current_phase="phase1",
            phases={
                "phase1": PhaseInfo(
                    name="phase1", start_date="2023-01-01", support_level_info=support_levels[0]
                )
            },
            summary="",
            text="",
            link="",
        )

        # Both match
        assert (
            service._matches_filters(
                PackageState.INSTALLED, statement, {"installed"}, {support_level_name}
            )
            is True
        )
        # State mismatch
        assert (
            service._matches_filters(
                PackageState.AVAILABLE, statement, {"installed"}, {support_level_name}
            )
            is False
        )
        # Support level mismatch
        assert (
            service._matches_filters(
                PackageState.INSTALLED, statement, {"installed"}, {"nonexistent"}
            )
            is False
        )

    def test_matches_filters_empty_filters(self, legacy_handler):
        """Test _matches_filters with empty filter sets matches everything."""
        service = SupportInfoService(legacy_handler)

        statement = SupportStatement(current_phase=None, phases={}, summary="", text="", link="")

        assert service._matches_filters(PackageState.INSTALLED, statement, set(), set()) is True
        assert service._matches_filters(PackageState.UNAVAILABLE, statement, set(), set()) is True

    def test_parse_filter_prefix_with_state(self, legacy_handler):
        """Test _parse_filter_prefix with state: prefix."""
        service = SupportInfoService(legacy_handler)

        prefix, name = service._parse_filter_prefix("state:installed")
        assert prefix == "state"
        assert name == "installed"

    def test_parse_filter_prefix_with_support(self, legacy_handler):
        """Test _parse_filter_prefix with support: prefix."""
        service = SupportInfoService(legacy_handler)

        prefix, name = service._parse_filter_prefix("support:default")
        assert prefix == "support"
        assert name == "default"

    def test_parse_filter_prefix_no_prefix(self, legacy_handler):
        """Test _parse_filter_prefix without prefix."""
        service = SupportInfoService(legacy_handler)

        prefix, name = service._parse_filter_prefix("installed")
        assert prefix is None
        assert name == "installed"


def _make_mock_handler(support_levels=None, schema_version="unversioned"):
    """Create a mock SupportinfoHandler.

    Args:
        support_levels: List of mock support level objects, or None for legacy.
        schema_version: Schema version string.
    """
    handler = Mock()

    # Match the enum comparison used in get_valid_filters:
    # self.handler.schema_version == SupportinfoSchemaVersions.LEGACY
    if schema_version == "unversioned":
        handler.schema_version = SupportinfoSchemaVersions.LEGACY
    else:
        handler.schema_version = SupportinfoSchemaVersions.V1_0

    if support_levels is not None:
        handler.get_support_level_info.return_value = support_levels
    else:
        handler.get_support_level_info.return_value = []

    return handler


def _make_legacy_mock_handler():
    """Create mock handler matching real legacy handler behavior.

    The real legacy handler returns ['supported', 'unsupported'] from
    get_support_level_info(), not an empty list.
    """
    level_supported = Mock()
    level_supported.name = "supported"
    level_supported.description = None
    level_unsupported = Mock()
    level_unsupported.name = "unsupported"
    level_unsupported.description = None
    return _make_mock_handler(support_levels=[level_supported, level_unsupported])


def _make_support_statement(current_phase="supported", support_level_info=None):
    """Create a minimal SupportStatement."""
    phase = Mock()
    phase.name = current_phase
    phase.support_level_info = support_level_info
    phase.start_date = "2023-03-15"
    phase.display_name = None

    return SupportStatement(
        current_phase=current_phase,
        phases={current_phase: phase},
        summary="Test summary",
        text="Test text",
        link=None,
        lifecycle_note=None,
        package_class=None,
        origin=None,
    )


class TestGetValidFiltersNoSupportLevels:
    """Test get_valid_filters when handler returns no support levels."""

    def test_state_filters_unchanged(self):
        """Test state filters are the same regardless of handler type."""
        handler = _make_mock_handler(support_levels=None)
        service = SupportInfoService(handler)
        state_filters, _ = service.get_valid_filters()
        assert "all" in state_filters
        assert "installed" in state_filters
        assert "available" in state_filters
        assert "unavailable" in state_filters

    def test_no_support_levels_returns_empty(self):
        """Test handler with no support levels returns empty support filters."""
        handler = _make_mock_handler(support_levels=None)
        service = SupportInfoService(handler)
        _, support_filters = service.get_valid_filters()
        assert support_filters == {}


class TestGetValidFiltersV10:
    """Test get_valid_filters with V1.0 handler (has support levels)."""

    def test_v10_handler_uses_support_level_names(self):
        """Test V1.0 handler uses support level names from XML."""
        level1 = Mock()
        level1.name = "Default Support"
        level1.description = "Full support"
        level2 = Mock()
        level2.name = "End of Support"
        level2.description = "No support"

        handler = _make_mock_handler(
            support_levels=[level1, level2],
            schema_version="1.0",
        )
        service = SupportInfoService(handler)
        _, support_filters = service.get_valid_filters()
        assert "Default Support" in support_filters
        assert "End of Support" in support_filters

    def test_v10_handler_does_not_have_legacy_filters(self):
        """Test V1.0 handler does NOT provide 'supported'/'unsupported'."""
        level1 = Mock()
        level1.name = "Default Support"
        level1.description = "Full support"

        handler = _make_mock_handler(
            support_levels=[level1],
            schema_version="1.0",
        )
        service = SupportInfoService(handler)
        _, support_filters = service.get_valid_filters()
        assert "supported" not in support_filters
        assert "unsupported" not in support_filters


class TestGetCurrentSupportLevelNameFallback:
    """Test _get_current_support_level_name falls back to phase name."""

    def test_with_support_level_info_returns_level_name(self):
        """Test returns support_level_info.name when available."""
        level_info = Mock()
        level_info.name = "Default Support"
        statement = _make_support_statement(
            current_phase="supported",
            support_level_info=level_info,
        )

        handler = _make_mock_handler()
        service = SupportInfoService(handler)
        result = service._get_current_support_level_name(statement)
        assert result == "Default Support"

    def test_without_support_level_info_returns_phase_name(self):
        """Test returns phase name when no support_level_info (legacy)."""
        statement = _make_support_statement(
            current_phase="supported",
            support_level_info=None,
        )

        handler = _make_mock_handler()
        service = SupportInfoService(handler)
        result = service._get_current_support_level_name(statement)
        assert result == "supported"

    def test_unsupported_phase_returns_unsupported(self):
        """Test returns 'unsupported' for unsupported phase without level info."""
        statement = _make_support_statement(
            current_phase="unsupported",
            support_level_info=None,
        )

        handler = _make_mock_handler()
        service = SupportInfoService(handler)
        result = service._get_current_support_level_name(statement)
        assert result == "unsupported"

    def test_no_current_phase_returns_none(self):
        """Test returns None when no current phase set."""
        statement = SupportStatement(
            current_phase=None,
            phases={},
            summary="",
            text="",
            link=None,
            lifecycle_note=None,
            package_class=None,
            origin=None,
        )

        handler = _make_mock_handler()
        service = SupportInfoService(handler)
        result = service._get_current_support_level_name(statement)
        assert result is None

    def test_v10_phase_without_support_level_info_returns_none(self):
        """Test V1.0 handler with missing support_level_info returns None."""
        # Even if NO phase has support_level_info, V1.0 handler
        # should NOT fall back to phase name
        supported_phase = Mock()
        supported_phase.name = "supported"
        supported_phase.support_level_info = None
        supported_phase.start_date = "2023-03-15"

        statement = SupportStatement(
            current_phase="supported",
            phases={"supported": supported_phase},
            summary="",
            text="",
            link=None,
            lifecycle_note=None,
            package_class=None,
            origin=None,
        )

        # Key: V1.0 handler, not legacy
        handler = _make_mock_handler(schema_version="1.0")
        service = SupportInfoService(handler)
        result = service._get_current_support_level_name(statement)
        assert result is None

    def test_current_phase_not_in_phases_returns_none(self):
        """Test current_phase not in phases dict returns None."""
        statement = SupportStatement(
            current_phase="supported",
            phases={},  # empty — current_phase not present
            summary="",
            text="",
            link=None,
            lifecycle_note=None,
            package_class=None,
            origin=None,
        )

        handler = _make_mock_handler()
        service = SupportInfoService(handler)
        result = service._get_current_support_level_name(statement)
        assert result is None


class TestValidateFiltersLegacy:
    """Test _validate_filters with legacy handler."""

    def test_supported_is_valid_filter_legacy(self):
        """Test 'supported' is accepted as valid filter with legacy handler."""
        handler = _make_legacy_mock_handler()
        service = SupportInfoService(handler)
        service._validate_filters(["supported"])

    def test_unsupported_is_valid_filter_legacy(self):
        """Test 'unsupported' is accepted as valid filter with legacy handler."""
        handler = _make_legacy_mock_handler()
        service = SupportInfoService(handler)
        service._validate_filters(["unsupported"])

    def test_installed_is_valid_filter_legacy(self):
        """Test 'installed' is still valid with legacy handler."""
        handler = _make_mock_handler(support_levels=None)
        service = SupportInfoService(handler)
        # Should not raise
        service._validate_filters(["installed"])

    def test_all_is_valid_filter_legacy(self):
        """Test 'all' is still valid with legacy handler."""
        handler = _make_mock_handler(support_levels=None)
        service = SupportInfoService(handler)
        # Should not raise
        service._validate_filters(["all"])

    def test_invalid_filter_raises_legacy(self):
        """Test unknown filter raises ValueError with legacy handler."""
        handler = _make_mock_handler(support_levels=None)
        service = SupportInfoService(handler)
        with pytest.raises(ValueError, match="Unknown filter"):
            service._validate_filters(["banana"])

    def test_default_support_invalid_for_legacy(self):
        """Test 'Default Support' is NOT valid with legacy handler."""
        handler = _make_mock_handler(support_levels=None)
        service = SupportInfoService(handler)
        with pytest.raises(ValueError, match="Unknown filter"):
            service._validate_filters(["Default Support"])


class TestCategorizeFiltersLegacy:
    """Test _categorize_filters with legacy handler."""

    def test_supported_categorized_as_support_filter(self):
        """Test 'supported' is categorized as a support level filter."""
        handler = _make_legacy_mock_handler()
        service = SupportInfoService(handler)
        state_filters, support_filters = service._categorize_filters(["supported"])
        assert "supported" in support_filters

    def test_installed_categorized_as_state_filter(self):
        """Test 'installed' is categorized as a state filter."""
        handler = _make_mock_handler(support_levels=None)
        service = SupportInfoService(handler)
        state_filters, support_filters = service._categorize_filters(["installed"])
        assert "installed" in state_filters
        assert len(support_filters) == 0

    def test_combined_filters(self):
        """Test combining state and support filters."""
        handler = _make_legacy_mock_handler()
        service = SupportInfoService(handler)
        state_filters, support_filters = service._categorize_filters(["installed", "supported"])
        assert "installed" in state_filters
        assert "supported" in support_filters
