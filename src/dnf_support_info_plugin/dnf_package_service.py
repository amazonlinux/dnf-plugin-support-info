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

"""Service for querying DNF package information."""

from typing import Dict, List, Optional, Tuple, TypedDict

import dnf
import hawkey

from .models import PackageState


class PackageNevra(TypedDict):
    """Parsed NEVRA (Name-Epoch-Version-Release-Arch) structure.

    Represents the individual components of a package identifier.
    """

    name: str
    epoch: str
    version: str
    release: str
    arch: str


class PackageStateDict(TypedDict):
    """Raw dictionary structure for package state information from DNF queries.

    This is the intermediate format between DNF package queries and PackageInfo creation.
    All values are strings as returned from DNF. Use this to create PackageInfo objects
    in the domain layer.
    """

    name: str
    state: str
    version: str
    arch: str


class PackageStatesMap(TypedDict):
    """Map of package states organized by installation status.

    Structure:
        {
            'installed': {'package_name': PackageStateDict, ...},
            'available': {'package_name': PackageStateDict, ...}
        }
    """

    installed: Dict[str, PackageStateDict]
    available: Dict[str, PackageStateDict]


class DnfPackageService:
    """Service class for DNF package query operations."""

    @staticmethod
    def parse_nevra(nevra_str: str) -> Optional[PackageNevra]:
        """
        Parse a full NEVRA string and return a nevra dictionary.

        Args:
            nevra_str: Package NEVRA string to parse

        Returns:
            PackageNevra with name, epoch, version, release, arch keys,
            or None if the string cannot be parsed.
        """
        subject = dnf.subject.Subject(nevra_str)
        possible_nevra = list(subject.get_nevra_possibilities(forms=[hawkey.FORM_NEVRA]))

        if possible_nevra:
            nevra = possible_nevra[0]
            return {
                "name": nevra.name,
                "epoch": nevra.epoch,
                "version": nevra.version,
                "release": nevra.release,
                "arch": nevra.arch,
            }

        return None

    @staticmethod
    def _get_available_installed(package_names: Optional[List[str]] = None) -> Tuple:
        """
        Collect available and installed packages from DNF.

        Args:
            package_names: Optional list of package names to filter by.
                          If None or empty, returns all packages.

        Returns:
            Tuple of (available_packages_query, installed_packages_query)
        """
        with dnf.Base() as base:
            # Read the configuration file
            conf = base.conf
            conf.read()
            # Set installroot
            installroot = "/"
            conf.installroot = installroot
            # Don't prompt for user confirmations
            conf.assumeyes = True
            # Load substitutions (awsregion, awsdomain) from the filesystem
            conf.substitutions.update_from_etc(installroot)
            # Check amazonlinux.repo (and others) to find packages available to install
            base.read_all_repos()
            base.fill_sack(load_system_repo=True)
            # Query matches all packages in sack
            q = base.sack.query()

            # Apply package name filter if specified
            if package_names:
                q = q.filterm(name=package_names)

            # Derived query matches only latest available packages
            q_available = q.available().latest().run()
            # Derived query matches only installed packages
            q_installed = q.installed().run()
            return q_available, q_installed

    def _build_package_state_dict_from_nevra(
        self, pkg_nevra: PackageNevra, state: str
    ) -> PackageStateDict:
        """
        Build a dictionary with package installation state and metadata from parsed NEVRA.

        Args:
            pkg_nevra: Already parsed NEVRA dictionary
            state: Installation state string ('installed' or 'available')

        Returns:
            PackageStateDict with name, state, version, and arch
        """
        vr = pkg_nevra["version"] + "-" + pkg_nevra["release"]
        arch = pkg_nevra["arch"]

        return {"name": pkg_nevra["name"], "state": state, "version": vr, "arch": arch}

    def get_package_states(self, package_names: Optional[List[str]] = None) -> PackageStatesMap:
        """
        Get the state of installed and available packages.

        Args:
            package_names: Optional list of package names to filter by.
                          If None or empty, returns all packages.

        Returns:
            PackageStatesMap with 'installed' and 'available' package states
        """
        available_pkgs, installed_pkgs = self._get_available_installed(package_names)

        map_states: PackageStatesMap = {
            PackageState.INSTALLED.value: {},
            PackageState.AVAILABLE.value: {},
        }

        self._collect_package_states(installed_pkgs, PackageState.INSTALLED.value, map_states)
        self._collect_package_states(available_pkgs, PackageState.AVAILABLE.value, map_states)

        return map_states

    def _collect_package_states(self, pkgs: List, state: str, map_states: PackageStatesMap) -> None:
        """
        Parse each package's NEVRA and add it to map_states under the given state key.

        Packages whose NEVRA string cannot be parsed are silently skipped.

        Args:
            pkgs: Iterable of DNF package objects to process.
            state: Installation state string ('installed' or 'available').
            map_states: Mapping to update in place.
        """
        for pkg in pkgs:
            pkg_nevra = self.parse_nevra(str(pkg))
            if pkg_nevra is None:
                continue
            pkg_name = pkg_nevra["name"]
            map_states[state][pkg_name] = self._build_package_state_dict_from_nevra(
                pkg_nevra, state
            )
