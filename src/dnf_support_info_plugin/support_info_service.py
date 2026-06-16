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

"""Thin service layer to integrate handler with DNF package data."""

import logging
from typing import Any, Dict, List, Optional, Tuple

from dnf.exceptions import Error as DnfError
from supportinfo.handler import SupportinfoHandler, SupportinfoSchemaVersions, SupportStatement

from .const import STATE_FILTER_ALL, UNKNOWN_ARCH
from .models import PackageInfo, PackageState

logger = logging.getLogger("dnf.plugin")


class SupportInfoService:
    """Thin wrapper that combines handler support data with DNF package states.

    This service's only job is to:
    1. Call handler methods to get support info
    2. Merge with DNF package states (installed/available/version/arch)
    3. Return PackageInfo objects for display
    """

    def __init__(self, handler: SupportinfoHandler):
        """
        Initialize the service with a support info handler.

        Args:
            handler: SupportinfoHandler instance (auto-detects legacy or v1.0 format)
        """
        self.handler = handler
        logger.debug(
            f"Initialized service with handler schema version: {handler.schema_version.value}"
        )

    def _get_all_packages(
        self, package_names: Optional[List[str]] = None
    ) -> Dict[str, Tuple[str, Optional[str]]]:
        """Get packages - handles both single/multiple package queries and bulk queries.

        Args:
            package_names: Optional list of package names to query.
                          If None, returns all packages (bulk query).
                          If empty list, returns empty dict.
                          If list with names, queries each package individually.

        Returns:
            Dict mapping package_name -> (statement_id, note_ref)
        """
        package_mapping: Dict[str, Tuple[str, Optional[str]]] = {}

        if package_names is None:
            # Bulk query: get all packages at once
            entries = self.handler.get_package_entries()
        elif not package_names:
            # Empty list - return empty result
            return package_mapping
        else:
            # Targeted query: get specific packages
            entries = []
            for pkg_name in package_names:
                pkg_entries = self.handler.get_package_entries(package_name=pkg_name)
                entries.extend(pkg_entries)

        # Unified processing - get_package_entries returns PackageEntry for both formats
        for entry in entries:
            package_mapping[entry.name] = (entry.statement_id, entry.note_ref)

        return package_mapping

    def _get_dnf_package_info(
        self, package_name: str, package_states: Dict[str, Dict[str, Any]]
    ) -> Tuple[PackageState, str, str]:
        """
        Get DNF package information (state, version, arch).

        Args:
            package_name: Name of the package to check
            package_states: Dict with 'installed' and 'available' package info

        Returns:
            Tuple of (PackageState, version_string, arch_string)
        """
        installed_key = PackageState.INSTALLED.value
        available_key = PackageState.AVAILABLE.value

        # Use .get() for defensive access to package_states keys
        installed_packages = package_states.get(installed_key, {})
        available_packages = package_states.get(available_key, {})

        if package_name in installed_packages:
            pkg_info = installed_packages[package_name]
            return (
                PackageState.INSTALLED,
                pkg_info.get("version", ""),
                pkg_info.get("arch", UNKNOWN_ARCH),
            )
        elif package_name in available_packages:
            pkg_info = available_packages[package_name]
            return (
                PackageState.AVAILABLE,
                pkg_info.get("version", ""),
                pkg_info.get("arch", UNKNOWN_ARCH),
            )
        else:
            return PackageState.UNAVAILABLE, "", UNKNOWN_ARCH

    def _resolve_note(
        self,
        support_statement: SupportStatement,
        note_ref: Optional[str],
        all_notes: Dict[str, str],
    ) -> Optional[str]:
        """
        Resolve note from support statement or note reference.

        Args:
            support_statement: SupportStatement object from handler
            note_ref: Optional note reference from package element
            all_notes: Dict of all notes from handler

        Returns:
            Note string if found, None otherwise
        """
        if support_statement.lifecycle_note:
            return all_notes.get(support_statement.lifecycle_note)
        elif note_ref:
            return all_notes.get(note_ref)
        return None

    def _build_package_info(
        self,
        pkg_name: str,
        version: str,
        arch: str,
        state: PackageState,
        support_statement: SupportStatement,
        statement_id: str,
        note: Optional[str],
    ) -> PackageInfo:
        """
        Build a PackageInfo object.

        Args:
            pkg_name: Package name
            version: Package version string
            arch: Package architecture
            state: Package installation state
            support_statement: SupportStatement object from handler
            statement_id: ID of the statement/lifecycle
            note: Optional note string

        Returns:
            PackageInfo object
        """
        return PackageInfo(
            name=pkg_name,
            version=version,
            arch=arch,
            state=state,
            support_statement=support_statement,
            statement_id=statement_id,
            note=note,
        )

    def get_package_info(
        self, package_name: str, package_states: Dict[str, Dict[str, Any]]
    ) -> Optional[PackageInfo]:
        """
        Get support information for a specific package.

        Args:
            package_name: Name of the package to look up
            package_states: Dict with package installation states

        Returns:
            PackageInfo object or None if package not found
        """
        try:
            packages = self._get_all_packages(package_names=[package_name])

            package_data = packages.get(package_name)
            if package_data is None:
                return None

            statement_id, note_ref = package_data

            support_statement = self.handler.get_package_support_info(package_name)

            if support_statement is None:
                return None

            state, version, arch = self._get_dnf_package_info(package_name, package_states)

            all_notes = self.handler.get_support_notes()
            note = self._resolve_note(support_statement, note_ref, all_notes)

            return self._build_package_info(
                pkg_name=package_name,
                version=version,
                arch=arch,
                state=state,
                support_statement=support_statement,
                statement_id=statement_id,
                note=note,
            )

        except (AttributeError, TypeError, ValueError, RuntimeError) as e:
            raise DnfError(
                f"Unable to retrieve support information for '{package_name}'. "
                "The support info file may be corrupted or missing required data. "
                "Try: dnf supportinfo --clean-cache"
            ) from e

    def get_valid_filters(self) -> tuple[dict, dict]:
        """Get all valid filter values with descriptions.

        Returns:
            Tuple of (state_filters, support_level_filters) dicts.
            State filters map filter name to description.
            Support level filters map support level name to description.
        """
        # State filters with descriptions
        state_filters = {
            STATE_FILTER_ALL: "All packages (installed, available, and unavailable)",
            PackageState.INSTALLED.value: "Packages currently installed on the system",
            PackageState.AVAILABLE.value: "Packages available in repositories but not installed",
            PackageState.UNAVAILABLE.value: "Packages in support info but not in any repository",
        }

        # Get support level filters with descriptions
        support_levels = self.handler.get_support_level_info()
        if support_levels:
            support_level_filters = {level.name: level.description for level in support_levels}
        else:
            support_level_filters = {}

        return state_filters, support_level_filters

    def _parse_filter_prefix(self, filter_str: str) -> tuple[Optional[str], str]:
        """Parse optional prefix from filter string.

        Args:
            filter_str: Filter string, possibly with prefix (e.g., "state:installed")

        Returns:
            Tuple of (prefix, filter_name). Prefix is None if no prefix found.
        """
        if ":" in filter_str:
            prefix, name = filter_str.split(":", 1)
            return (prefix, name)
        return (None, filter_str)

    def _categorize_filters(self, filters: List[str]) -> tuple[set, set]:
        """Categorize filter strings into state and support level sets.

        Each filter is matched against the valid state and support level lists:
        - Explicit state:NAME  → added only to state set
        - Explicit support:NAME → added only to support level set
        - Unambiguous NAME (only in one list) → added to that list
        - Ambiguous NAME (in both lists) → added to BOTH lists

        'all' in the state list is expanded to all PackageState values.

        Args:
            filters: List of filter strings (may include prefixes)

        Returns:
            Tuple of (state_filters, support_level_filters) as sets of names.
        """
        valid_state_filters, valid_support_level_filters = self.get_valid_filters()

        state_group: set = set()
        support_group: set = set()

        for f in filters:
            prefix, name = self._parse_filter_prefix(f)

            if prefix == "state":
                if name == STATE_FILTER_ALL:
                    state_group.update(s.value for s in PackageState)
                else:
                    state_group.add(name)
            elif prefix == "support":
                support_group.add(name)
            else:
                in_state = name in valid_state_filters
                in_support = name in valid_support_level_filters

                if in_state:
                    if name == STATE_FILTER_ALL:
                        state_group.update(s.value for s in PackageState)
                    else:
                        state_group.add(name)
                if in_support:
                    support_group.add(name)

        return state_group, support_group

    def _matches_filters(
        self,
        state: PackageState,
        support_statement: SupportStatement,
        state_filters: set,
        support_filters: set,
    ) -> bool:
        """Check if a package matches the given filter sets.

        State filters are OR'ed: package state must be in the state set.
        Support level filters are OR'ed: support level must be in the support set.
        When both sets are non-empty, both conditions must hold (AND between groups).

        Args:
            state: Package installation state
            support_statement: SupportStatement for the package
            state_filters: Set of state values to match (OR logic within)
            support_filters: Set of support level names to match (OR logic within)

        Returns:
            True if the package matches all filter criteria
        """
        if state_filters and state.value not in state_filters:
            return False

        if support_filters:
            support_level_name = self._get_current_support_level_name(support_statement)
            if support_level_name not in support_filters:
                return False

        return True

    def _validate_filters(self, filters: List[str]) -> None:
        """Validate that all filter strings are recognised.

        Args:
            filters: List of filter strings (may include prefixes)

        Raises:
            ValueError: If any filter is unknown or uses an unrecognised prefix
        """
        state_valid, support_level_valid = self.get_valid_filters()
        invalid_filters = []

        for f in filters:
            prefix, name = self._parse_filter_prefix(f)

            if prefix == "state":
                if name not in state_valid:
                    invalid_filters.append(f)
            elif prefix == "support":
                if name not in support_level_valid:
                    invalid_filters.append(f)
            elif prefix is None:
                if name not in state_valid and name not in support_level_valid:
                    invalid_filters.append(f)
            else:
                invalid_filters.append(f)

        if invalid_filters:
            raise ValueError(f"Unknown filter(s): {', '.join(repr(f) for f in invalid_filters)}")

    def _collect_matching_packages(
        self,
        state_filters: set,
        support_filters: set,
        package_states: Dict[str, Dict[str, Any]],
    ) -> List[PackageInfo]:
        """Iterate all support-info packages and return those matching the filter sets.

        Args:
            state_filters: Set of PackageState values to include (empty = any state)
            support_filters: Set of support-level names to include (empty = any level)
            package_states: DNF package state map from DnfPackageService

        Returns:
            List of PackageInfo objects that pass the filter criteria
        """
        all_packages = self._get_all_packages(package_names=None)
        all_metadata = self.handler.get_support_metadata()
        all_notes = self.handler.get_support_notes()

        logger.debug(f"Filtering from {len(all_packages)} packages in support info")

        filtered_packages: List[PackageInfo] = []

        for pkg_name in all_packages:
            statement_id, note_ref = all_packages[pkg_name]

            state, version, arch = self._get_dnf_package_info(pkg_name, package_states)

            support_statement = all_metadata.get(statement_id)
            if not support_statement:
                continue

            if self._matches_filters(state, support_statement, state_filters, support_filters):
                note = self._resolve_note(support_statement, note_ref, all_notes)
                package_info = self._build_package_info(
                    pkg_name=pkg_name,
                    version=version,
                    arch=arch,
                    state=state,
                    support_statement=support_statement,
                    statement_id=statement_id,
                    note=note,
                )
                filtered_packages.append(package_info)

        logger.debug(f"Filtered to {len(filtered_packages)} packages")
        return filtered_packages

    def filter_packages(
        self, filters: List[str], package_states: Dict[str, Dict[str, Any]]
    ) -> List[PackageInfo]:
        """
        Filter packages based on specified criteria.

        Supports optional prefixes for disambiguation:
        - state:name - Explicitly a state filter
        - support:name - Explicitly a support level filter
        - name (no prefix) - Added to state list if it matches, support list if it matches, or both

        Multiple filters with AND/OR logic:
        - State filters are OR'ed together
        - Support level filters are OR'ed together
        - State and support level groups are AND'ed (when both present)

        Delegates to three single-responsibility helpers:
        1. _validate_filters    - raises ValueError for unknown filters
        2. _categorize_filters  - maps filter strings to typed sets
        3. _collect_matching_packages - iterates packages and applies filter sets

        Args:
            filters: List of filter strings (may include prefixes)
            package_states: Dict with package installation states

        Returns:
            List of PackageInfo objects matching the filter

        Raises:
            ValueError: If any filter is invalid
        """
        self._validate_filters(filters)

        state_filters, support_filters = self._categorize_filters(filters)
        logger.debug(f"State filters: {state_filters}, Support level filters: {support_filters}")

        return self._collect_matching_packages(state_filters, support_filters, package_states)

    def _get_current_support_level_name(self, support_statement: SupportStatement) -> Optional[str]:
        """Get the support level name of the current phase.

        For V1.0 format: returns the support_level_info name
        (e.g. "Default Support").
        For legacy format: returns the phase name directly
        (e.g. "supported", "unsupported").
        This allows --show supported to work with legacy data.

        Args:
            support_statement: SupportStatement object

        Returns:
            Support level name string, phase name as fallback, or None
        """
        current_phase = support_statement.current_phase
        if not current_phase:
            return None

        if current_phase not in support_statement.phases:
            return None

        phase_info = support_statement.phases[current_phase]
        if phase_info is None:
            return None
        if phase_info.support_level_info:
            return phase_info.support_level_info.name

        # Legacy format: use phase name directly as the support level name
        if self.handler.schema_version == SupportinfoSchemaVersions.LEGACY:
            return current_phase

        return None
