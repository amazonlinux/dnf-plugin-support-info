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

"""Tests for models module."""

from supportinfo.handler import OriginInfo, PhaseInfo, SupportLevelInfo, SupportStatement

from dnf_support_info_plugin.models import PackageInfo, PackageState


class TestPackageInfoGetField:
    """Test PackageInfo.get_field() method."""

    def test_get_field_returns_value_from_statement(self):
        """Test get_field returns value from support_statement when field exists."""
        statement = SupportStatement(
            current_phase="full_support",
            phases={
                "full_support": PhaseInfo(
                    name="full_support",
                    start_date="2023-01-01",
                    support_level_info=SupportLevelInfo(
                        name="standard",
                        severities="Low,Medium,Important,Critical",
                        description="Full support",
                    ),
                )
            },
            summary="Test summary",
            text="Test text",
            link="https://example.com",
        )

        pkg_info = PackageInfo(
            name="test",
            version="1.0",
            arch="x86_64",
            state=PackageState.INSTALLED,
            support_statement=statement,
            statement_id="test",
            note=None,
        )

        assert pkg_info.get_field("summary") == "Test summary"
        assert pkg_info.get_field("text") == "Test text"
        assert pkg_info.get_field("link") == "https://example.com"

    def test_get_field_returns_value_from_current_phase(self):
        """Test get_field returns value from current phase when field exists there."""
        level_info = SupportLevelInfo(
            name="standard",
            severities="Low,Medium,Important,Critical",
            description="Full support",
        )
        statement = SupportStatement(
            current_phase="full_support",
            phases={
                "full_support": PhaseInfo(
                    name="full_support",
                    start_date="2023-01-01",
                    support_level_info=level_info,
                )
            },
            summary="",
            text="",
            link="",
        )

        pkg_info = PackageInfo(
            name="test",
            version="1.0",
            arch="x86_64",
            state=PackageState.INSTALLED,
            support_statement=statement,
            statement_id="test",
            note=None,
        )

        assert pkg_info.get_field("support_level") == level_info.name
        assert pkg_info.get_field("severities") == "Low,Medium,Important,Critical"

        # Fields without properties return None
        assert pkg_info.get_field("start_date") is None

    def test_get_field_returns_none_when_not_exists(self):
        """Test get_field returns None when field doesn't exist."""
        statement = SupportStatement(
            current_phase="full_support",
            phases={
                "full_support": PhaseInfo(
                    name="full_support",
                    start_date="2023-01-01",
                )
            },
            summary="",
            text="",
            link="",
        )

        pkg_info = PackageInfo(
            name="test",
            version="1.0",
            arch="x86_64",
            state=PackageState.INSTALLED,
            support_statement=statement,
            statement_id="test",
            note=None,
        )

        assert pkg_info.get_field("nonexistent_field") is None

    def test_get_field_with_empty_string_value(self):
        """Test get_field returns empty string when field is empty string."""
        statement = SupportStatement(
            current_phase="full_support",
            phases={
                "full_support": PhaseInfo(
                    name="full_support",
                    start_date="2023-01-01",
                )
            },
            summary="",
            text="",
            link="",
        )

        pkg_info = PackageInfo(
            name="test",
            version="1.0",
            arch="x86_64",
            state=PackageState.INSTALLED,
            support_statement=statement,
            statement_id="test",
            note=None,
        )

        # summary is an empty string; get_field delegates to the summary property
        # which returns the raw value from support_statement
        assert pkg_info.get_field("summary") == ""

    def test_get_field_returns_current_phase(self):
        """Test get_field returns current_phase field from statement."""
        phase = PhaseInfo(
            name="maintenance_support",
            start_date="2023-01-01",
        )
        statement = SupportStatement(
            current_phase="maintenance_support",
            phases={"maintenance_support": phase},
            summary="Test",
            text="",
            link="",
        )

        pkg_info = PackageInfo(
            name="test",
            version="1.0",
            arch="x86_64",
            state=PackageState.INSTALLED,
            support_statement=statement,
            statement_id="test",
            note=None,
        )

        assert pkg_info.get_field("current_phase") == phase.name


class TestPackageInfoProperties:
    """Test PackageInfo property accessors."""

    def test_origin_property_returns_display_name_or_name(self):
        """Test origin property returns display_name if set, falling back to name."""
        origin_info = OriginInfo(
            name="amazon",
            repo_id="amazonlinux-2023",
            dist="amzn2023",
            vendor="Amazon Linux",
            signing_key="key123",
        )

        statement = SupportStatement(
            current_phase="full_support",
            phases={},
            origin=origin_info,
        )

        pkg_info = PackageInfo(
            name="test",
            version="1.0",
            arch="x86_64",
            state=PackageState.INSTALLED,
            support_statement=statement,
            statement_id="test",
            note=None,
        )

        assert pkg_info.origin == origin_info.name
        assert pkg_info.get_field("origin") == origin_info.name

    def test_origin_property_returns_none_when_no_origin(self):
        """Test origin property returns None when no origin is set."""
        statement = SupportStatement(
            current_phase="full_support",
            phases={},
            origin=None,
        )

        pkg_info = PackageInfo(
            name="test",
            version="1.0",
            arch="x86_64",
            state=PackageState.INSTALLED,
            support_statement=statement,
            statement_id="test",
            note=None,
        )

        assert pkg_info.origin is None
        assert pkg_info.get_field("origin") is None

    def test_support_level_property_from_current_phase(self):
        """Test support_level property returns display_name if set, falling back to name."""
        level_info = SupportLevelInfo(
            name="core",
            severities="Low,Medium,Important,Critical",
            description="Core support",
        )
        statement = SupportStatement(
            current_phase="full_support",
            phases={
                "full_support": PhaseInfo(
                    name="full_support",
                    start_date="2023-01-01",
                    support_level_info=level_info,
                )
            },
        )

        pkg_info = PackageInfo(
            name="test",
            version="1.0",
            arch="x86_64",
            state=PackageState.INSTALLED,
            support_statement=statement,
            statement_id="test",
            note=None,
        )

        assert pkg_info.support_level == level_info.name
        assert pkg_info.get_field("support_level") == level_info.name

    def test_severities_property_from_current_phase(self):
        """Test severities property extracts from current phase."""
        statement = SupportStatement(
            current_phase="maintenance_support",
            phases={
                "maintenance_support": PhaseInfo(
                    name="maintenance_support",
                    start_date="2025-01-01",
                    support_level_info=SupportLevelInfo(
                        name="security",
                        severities="Important,Critical",
                        description="Security updates only",
                    ),
                )
            },
        )

        pkg_info = PackageInfo(
            name="test",
            version="1.0",
            arch="x86_64",
            state=PackageState.INSTALLED,
            support_statement=statement,
            statement_id="test",
            note=None,
        )

        assert pkg_info.severities == "Important,Critical"
        assert pkg_info.get_field("severities") == "Important,Critical"

    def test_support_level_description_property_from_current_phase(self):
        """Test support_level_description property extracts from current phase."""
        statement = SupportStatement(
            current_phase="full_support",
            phases={
                "full_support": PhaseInfo(
                    name="full_support",
                    start_date="2023-01-01",
                    support_level_info=SupportLevelInfo(
                        name="default",
                        severities="Low,Medium,Important,Critical",
                        description="Full security and bug fix support for all severities",
                    ),
                )
            },
        )

        pkg_info = PackageInfo(
            name="test",
            version="1.0",
            arch="x86_64",
            state=PackageState.INSTALLED,
            support_statement=statement,
            statement_id="test",
            note=None,
        )

        assert (
            pkg_info.support_level_description
            == "Full security and bug fix support for all severities"
        )
        assert (
            pkg_info.get_field("support_level_description")
            == "Full security and bug fix support for all severities"
        )

    def test_properties_return_none_when_no_current_phase(self):
        """Test properties return None when current_phase is not set."""
        statement = SupportStatement(
            current_phase=None,
            phases={
                "full_support": PhaseInfo(
                    name="full_support",
                    support_level_info=SupportLevelInfo(
                        name="core",
                        severities="Low,Medium,Important,Critical",
                        description="Core support",
                    ),
                )
            },
        )

        pkg_info = PackageInfo(
            name="test",
            version="1.0",
            arch="x86_64",
            state=PackageState.INSTALLED,
            support_statement=statement,
            statement_id="test",
            note=None,
        )

        assert pkg_info.support_level is None
        assert pkg_info.severities is None

    def test_current_phase_property(self):
        """Test current_phase property returns display_name if set, falling back to phase name."""
        phase = PhaseInfo(name="full_support")
        statement = SupportStatement(
            current_phase="full_support",
            phases={"full_support": phase},
        )

        pkg_info = PackageInfo(
            name="test",
            version="1.0",
            arch="x86_64",
            state=PackageState.INSTALLED,
            support_statement=statement,
            statement_id="test",
            note=None,
        )

        assert pkg_info.current_phase == phase.name
        assert pkg_info.get_field("current_phase") == phase.name

    def test_current_phase_property_uses_display_name_when_set(self):
        """Test current_phase property returns display_name when it is set."""
        phase = PhaseInfo(name="full_support", display_name="Full Support")
        statement = SupportStatement(
            current_phase="full_support",
            phases={"full_support": phase},
        )

        pkg_info = PackageInfo(
            name="test",
            version="1.0",
            arch="x86_64",
            state=PackageState.INSTALLED,
            support_statement=statement,
            statement_id="test",
            note=None,
        )

        assert pkg_info.current_phase == "Full Support"
        assert pkg_info.get_field("current_phase") == "Full Support"

    def test_support_level_property_uses_display_name_when_set(self):
        """Test support_level property returns display_name when it is set."""
        level_info = SupportLevelInfo(
            name="core",
            display_name="Core Support",
            severities="Low,Medium,Important,Critical",
            description="Core support",
        )
        statement = SupportStatement(
            current_phase="full_support",
            phases={
                "full_support": PhaseInfo(
                    name="full_support",
                    start_date="2023-01-01",
                    support_level_info=level_info,
                )
            },
        )

        pkg_info = PackageInfo(
            name="test",
            version="1.0",
            arch="x86_64",
            state=PackageState.INSTALLED,
            support_statement=statement,
            statement_id="test",
            note=None,
        )

        assert pkg_info.support_level == "Core Support"
        assert pkg_info.get_field("support_level") == "Core Support"

    def test_origin_property_uses_display_name_when_set(self):
        """Test origin property returns display_name when it is set."""
        origin_info = OriginInfo(
            name="amazon",
            display_name="Amazon Linux 2023",
            repo_id="amazonlinux-2023",
            dist="amzn2023",
            vendor="Amazon Linux",
            signing_key="key123",
        )
        statement = SupportStatement(
            current_phase="full_support",
            phases={},
            origin=origin_info,
        )

        pkg_info = PackageInfo(
            name="test",
            version="1.0",
            arch="x86_64",
            state=PackageState.INSTALLED,
            support_statement=statement,
            statement_id="test",
            note=None,
        )

        assert pkg_info.origin == "Amazon Linux 2023"
        assert pkg_info.get_field("origin") == "Amazon Linux 2023"

    def test_statement_fields_properties(self):
        """Test properties for SupportStatement fields."""
        statement = SupportStatement(
            current_phase="full_support",
            phases={},
            summary="Test summary",
            text="Test description",
            link="https://example.com/support",
            lifecycle_note="Important note",
            package_class="core",
        )

        pkg_info = PackageInfo(
            name="test",
            version="1.0",
            arch="x86_64",
            state=PackageState.INSTALLED,
            support_statement=statement,
            statement_id="test",
            note=None,
        )

        assert pkg_info.summary == "Test summary"
        assert pkg_info.text == "Test description"
        assert pkg_info.link == "https://example.com/support"
        assert pkg_info.lifecycle_note == "Important note"
        assert pkg_info.package_class == "core"
