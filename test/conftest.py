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
Pytest fixtures for dnf-plugin-support-info integration tests.
"""
import os
import sys
import types
from unittest.mock import MagicMock, Mock

import pytest


# Create proper exception classes for dnf.exceptions
class MockDnfError(Exception):
    """Mock DNF Error exception"""

    pass


mock_dnf_module = MagicMock()
mock_dnf_module.Plugin = object
mock_dnf_module.cli.Command = object
mock_dnf_module.cli.output.Output = Mock
mock_dnf_module.Base = Mock
mock_dnf_module.subject.Subject = Mock
mock_dnf_module.i18n.fill_exact_width = lambda text, width: text.ljust(width)
sys.modules["dnf"] = mock_dnf_module

# Create a proper module object for dnf.exceptions
mock_dnf_exceptions = types.ModuleType("dnf.exceptions")
mock_dnf_exceptions.Error = MockDnfError
sys.modules["dnf.exceptions"] = mock_dnf_exceptions

sys.modules["dnf.cli"] = mock_dnf_module
sys.modules["dnf.cli.output"] = mock_dnf_module
sys.modules["dnf.subject"] = mock_dnf_module
sys.modules["dnf.i18n"] = mock_dnf_module
sys.modules["dnf.plugin"] = mock_dnf_module

mock_hawkey_module = MagicMock()
mock_hawkey_module.FORM_NEVRA = 1
sys.modules["hawkey"] = mock_hawkey_module

sys.modules["libdnf"] = MagicMock()
sys.modules["libdnf.conf"] = MagicMock()
sys.modules["dnf.conf"] = MagicMock()
sys.modules["dnf.conf.substitutions"] = MagicMock()

# Mock dnf.crypto and dnf.yum.misc so GpgVerifier can be imported without
# the real DNF crypto stack installed in the test environment.
mock_dnf_crypto = MagicMock()
mock_dnf_crypto.keyids_from_pubring.return_value = []
mock_dnf_crypto.retrieve.return_value = []
mock_dnf_crypto.log_key_import = MagicMock()
mock_dnf_crypto.pubring_dir = MagicMock()
mock_dnf_crypto.pubring_dir.return_value.__enter__ = lambda s: None
mock_dnf_crypto.pubring_dir.return_value.__exit__ = MagicMock(return_value=False)
sys.modules["dnf.crypto"] = mock_dnf_crypto

mock_dnf_yum = MagicMock()
mock_dnf_yum_misc = MagicMock()
sys.modules["dnf.yum"] = mock_dnf_yum
sys.modules["dnf.yum.misc"] = mock_dnf_yum_misc

# Mock the 'gpg' module (provided by system python3-gpg / GPGME package).
# In the Brazil test environment this RPM is not installed, so we stub it out
# here.  Tests that exercise GpgVerifier directly patch gpg.Context as needed.
_mock_gpg_errors = types.ModuleType("gpg.errors")


class _MockBadSignatures(Exception):
    """Stub for gpg.errors.BadSignatures."""

    pass


_mock_gpg_errors.BadSignatures = _MockBadSignatures  # type: ignore[attr-defined]

mock_gpg_module = MagicMock()
mock_gpg_module.errors = _mock_gpg_errors
mock_gpg_module.Context = MagicMock()

sys.modules["gpg"] = mock_gpg_module
sys.modules["gpg.errors"] = _mock_gpg_errors


from test.helpers import build_package_data, build_statement_data

from supportinfo.handler import PhaseInfo, SupportinfoHandler, SupportLevelInfo, SupportStatement


@pytest.fixture
def mock_package_states():
    """Mock package states data matching DNF query results"""
    return {
        "installed": {
            "test-glibc": {
                "name": "test-glibc",
                "state": "installed",
                "version": "2.34-52.amzn2023.0.7",
                "arch": "x86_64",
            },
            "test-bash": {
                "name": "test-bash",
                "state": "installed",
                "version": "5.2.15-1.amzn2023.0.4",
                "arch": "x86_64",
            },
        },
        "available": {
            "test-php81": {
                "name": "test-php81",
                "state": "available",
                "version": "8.1.28-1.amzn2023",
                "arch": "x86_64",
            },
            "test-python36": {
                "name": "test-python36",
                "state": "available",
                "version": "3.6.15-1.amzn2023",
                "arch": "x86_64",
            },
        },
    }


@pytest.fixture
def parsed_test_data(legacy_handler):
    """Parse test support_info.xml using actual handler and return data structures.

    Uses legacy_handler fixture to load real handler, then extracts data using
    helper functions. This ensures we test against the actual handler implementation.

    Returns:
        Dict with package_data, support_statement_data, and note_data
    """
    return {
        "package_data": build_package_data(legacy_handler),
        "support_statement_data": build_statement_data(legacy_handler),
        "note_data": dict(legacy_handler.get_support_notes()),
    }


@pytest.fixture
def legacy_handler():
    """Create real handler from legacy test fixture."""
    test_dir = os.path.dirname(__file__)
    test_xml = os.path.join(test_dir, "fixtures", "test_support_info_legacy.xml")
    return SupportinfoHandler.create(test_xml)


@pytest.fixture
def v1_handler():
    """Create real handler from V1.0 test fixture."""
    test_dir = os.path.dirname(__file__)
    test_xml = os.path.join(test_dir, "fixtures", "test_support_info_v1.xml")
    v1_xsd = os.path.join(test_dir, "fixtures", "supportinfo-1.0.xsd")
    return SupportinfoHandler.create(test_xml, v1_xsd)


@pytest.fixture
def supported_statement_legacy(legacy_handler):
    """Get real supported SupportStatement from Legacy fixture."""
    metadata = legacy_handler.get_support_metadata()
    return metadata["eol"]  # "eol" statement is supported


@pytest.fixture
def unsupported_statement_legacy(legacy_handler):
    """Get real unsupported SupportStatement from Legacy fixture."""
    metadata = legacy_handler.get_support_metadata()
    return metadata["eol_python36"]  # "eol_python36" statement is unsupported


@pytest.fixture
def mock_dnf_output():
    """Create mock DNF output object for ConsoleFormatter tests."""
    mock_output = Mock()
    mock_output.fmtKeyValFill = lambda k, v: f"{k}{v}"
    return mock_output


@pytest.fixture
def v1_eos_statement():
    """Create V1.0 end-of-support (unsupported) statement for testing."""
    return SupportStatement(
        current_phase="end_of_life",
        phases={
            "end_of_life": PhaseInfo(
                name="end_of_life",
                start_date="2025-01-01",
                support_level_info=SupportLevelInfo(
                    name="eos", severities="", description="End of support - no further updates"
                ),
                milestone=None,
            )
        },
        summary="End of support",
        text="",
        link="",
    )


@pytest.fixture
def v1_supported_statement():
    """Create V1.0 supported statement for testing."""
    return SupportStatement(
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
                milestone=None,
            )
        },
        summary="Full support",
        text="",
        link="",
    )
