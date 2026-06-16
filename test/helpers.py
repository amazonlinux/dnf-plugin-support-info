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

"""Test helper functions for creating test data."""

from supportinfo.handler import PhaseInfo, SupportLevelInfo, SupportStatement


def create_support_statement(
    current_phase, start_date=None, end_date=None, summary="", text="", link=""
):
    """Helper to create SupportStatement with proper types.

    Args:
        current_phase: Current phase name string (e.g., "supported", "unsupported", "full_support")
        start_date: Start date string or None
        end_date: End date string or None (used to create second phase if unsupported transition)
        summary: Summary text or None
        text: Full text or None
        link: URL link or None

    Returns:
        SupportStatement with proper structure
    """
    phases = {}

    # Create phase for current_phase
    if current_phase:
        is_supported_phase = current_phase in ("supported", "full_support")
        phases[current_phase] = PhaseInfo(
            name=current_phase,
            start_date=str(start_date) if start_date else None,
            support_level_info=SupportLevelInfo(
                name="default" if is_supported_phase else "eos",
                severities="Low,Medium,Important,Critical" if is_supported_phase else None,
                description=None,
            ),
        )

    # If there's an end_date, create an unsupported phase
    if end_date and current_phase in ("supported", "full_support"):
        phases["unsupported"] = PhaseInfo(
            name="unsupported",
            start_date=str(end_date),
            support_level_info=SupportLevelInfo(
                name="eos",
                severities=None,
                description=None,
            ),
        )

    return SupportStatement(
        current_phase=current_phase,
        phases=phases,
        summary=str(summary) if summary else "",
        text=str(text) if text else "",
        link=str(link) if link else "",
    )


def build_package_data(handler):
    """Build package_data dict from handler (statement_id -> list of package names).

    Args:
        handler: SupportinfoHandler instance

    Returns:
        Dict mapping statement_id to list of package names
    """
    entries = handler.get_package_entries()
    package_data = {}

    for entry in entries:
        statement_id = entry.statement_id
        pkg_name = entry.name

        if statement_id not in package_data:
            package_data[statement_id] = []
        package_data[statement_id].append(pkg_name)

    return package_data


def build_statement_data(handler):
    """Build support_statement_data dict from handler.

    Args:
        handler: SupportinfoHandler instance

    Returns:
        Dict mapping statement_id to statement dict with current_phase, summary, text, etc.
    """
    metadata = handler.get_support_metadata()
    support_statement_data = {}

    for statement_id, statement in metadata.items():
        stmt_dict = {
            "statement_id": statement_id,
            "current_phase": statement.current_phase,
            "summary": statement.summary,
            "text": statement.text,
        }

        # Get start_date from current phase if available
        if statement.current_phase and statement.phases:
            current_phase_info = statement.phases.get(statement.current_phase)
            if current_phase_info and current_phase_info.start_date:
                stmt_dict["start_date"] = current_phase_info.start_date

        # Only include optional fields if they're not None
        if statement.link is not None:
            stmt_dict["link"] = statement.link

        support_statement_data[statement_id] = stmt_dict

    return support_statement_data
