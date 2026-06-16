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

"""Data models for package support information."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

# Import handler's data structures directly instead of duplicating
from supportinfo.handler import SupportStatement


class PackageState(Enum):
    """Package installation state."""

    INSTALLED = "installed"
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


@dataclass
class PackageInfo:
    """Package info data model for display purposes.

    Combines package metadata (name, version, arch, state) with support
    information from SupportStatement.

    All displayable fields are exposed as properties for clarity and type safety.
    """

    name: str
    version: str
    arch: str
    state: PackageState
    support_statement: SupportStatement
    statement_id: str
    note: Optional[str] = None

    @staticmethod
    def _display_name_or_name(obj) -> Optional[str]:
        """Return display_name if set, otherwise name, from an object with both attributes.

        Args:
            obj: Object with display_name and name attributes, or None

        Returns:
            display_name if truthy, else name, or None if obj is None
        """
        if obj is None:
            return None
        return obj.display_name or obj.name

    def _get_current_phase_info(self):
        """Look up and return the current phase's support_level_info, or None.

        Encapsulates the repeated pattern of:
          1. Checking whether current_phase is set on the support statement
          2. Looking up the phase object in the phases dict
          3. Returning support_level_info (or None if the phase is missing/has no info)

        Returns:
            The support_level_info object for the current phase, or None
        """
        current = self.support_statement.current_phase
        if not current:
            return None
        phase = self.support_statement.phases.get(current)
        if phase and phase.support_level_info:
            return phase.support_level_info
        return None

    @property
    def current_phase(self) -> Optional[str]:
        """Get current phase display name from support statement.

        Returns display_name if set, falling back to the raw phase name.

        Returns:
            Current phase display name (or name if no display_name), or None if not set
        """
        current = self.support_statement.current_phase
        if not current:
            return None
        phase = self.support_statement.phases.get(current)
        if phase:
            return self._display_name_or_name(phase)
        return current

    @property
    def support_level(self) -> Optional[str]:
        """Get support level display name from current phase.

        Returns display_name if set, falling back to the raw support level name.

        Returns:
            Support level display name (or name if no display_name) from current phase,
            or None if no current phase
        """
        return self._display_name_or_name(self._get_current_phase_info())

    @property
    def severities(self) -> Optional[str]:
        """Get severities from current phase.

        Returns:
            Comma-separated severities string from current phase, or None if no current phase
        """
        info = self._get_current_phase_info()
        return info.severities if info else None

    @property
    def support_level_description(self) -> Optional[str]:
        """Get support level description from current phase.

        Returns:
            Support level description string from current phase, or None if no current phase
        """
        info = self._get_current_phase_info()
        return info.description if info else None

    @property
    def origin(self) -> Optional[str]:
        """Get display name from origin OriginInfo object.

        Returns display_name if set, falling back to the origin name.

        Returns:
            Origin display name (or name if no display_name), or None if no origin
        """
        return self._display_name_or_name(self.support_statement.origin)

    @property
    def link(self) -> Optional[str]:
        """Get link from support statement.

        Returns:
            Support information link URL, or None if not set
        """
        return self.support_statement.link

    @property
    def text(self) -> Optional[str]:
        """Get text from support statement.

        Returns:
            Support statement description text, or None if not set
        """
        return self.support_statement.text

    @property
    def summary(self) -> Optional[str]:
        """Get summary from support statement.

        Returns:
            Support statement summary text, or None if not set
        """
        return self.support_statement.summary

    @property
    def lifecycle_note(self) -> Optional[str]:
        """Get lifecycle note from support statement.

        Returns:
            Lifecycle note text, or None if not set
        """
        return self.support_statement.lifecycle_note

    @property
    def package_class(self) -> Optional[str]:
        """Get package class from support statement.

        Returns:
            Package class name, or None if not set
        """
        return self.support_statement.package_class

    def get_field(self, field_key: str) -> Optional[str]:
        """Get field value by name.

        Uses properties to access all displayable fields, providing a consistent
        interface for formatters.

        Args:
            field_key: Name of the field to retrieve

        Returns:
            Field value or None if not found
        """
        return getattr(self, field_key, None)
