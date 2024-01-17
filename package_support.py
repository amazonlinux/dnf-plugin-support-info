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

import os
import xml.sax
from datetime import datetime
from xml.dom import minidom
from xml.etree import ElementTree
from xml.etree.ElementTree import Element, SubElement

import dnf
import hawkey


class PackageHandler(xml.sax.handler.ContentHandler):
    """Parses <packages> element in metadata file and fetches package name and eol id"""

    def __init__(self):
        self.pkg_data = {}

    def startElement(self, tag, attrs):
        if tag == "package":
            eol_id = attrs.get("note", "eol")
            data = self.pkg_data.setdefault(eol_id, [])
            data.append(attrs["name"])


class StatementHandler(xml.sax.handler.ContentHandler):
    """Parses <statement> element in metadata file and fetches all support statements"""

    def __init__(self):
        self._current = None
        self._tags_stack = None
        self.support_data = {}

    def startElement(self, tag, attrs):
        if tag == "statement":
            self._current = {
                "eol_id": attrs["id"],
                "start_date": attrs["start_date"],
                "end_date": attrs["end_date"],
                "status": attrs["marker"],
                "summary": "",
                "link": "",
                "text": "",
            }
            self._tags_stack = []
        if tag == "package" and self._current is not None:
            note_id = attrs.get("note", self._current["eol_id"])
            data = self.support_data.setdefault(note_id, {})
            data.update(
                {
                    "start_date": self._current["start_date"],
                    "end_date": self._current["end_date"],
                    "status": self._current["status"],
                    "summary": self._current["summary"],
                    "link": self._current["link"],
                    "text": self._current["text"],
                }
            )

        if self._current is not None:
            self._tags_stack.append(tag)

    def characters(self, content):
        if self._current is not None:
            if self._tags_stack[-1] == "summary":
                self._current["summary"] += content
            elif self._tags_stack[-1] == "link":
                self._current["link"] += content
            elif self._tags_stack[-1] == "text":
                self._current["text"] += content

    def endElement(self, tag):
        if self._current is not None:
            if self._tags_stack[-1] == "statement":
                self.support_data[self._current["eol_id"]] = {
                    "start_date": self._current["start_date"],
                    "end_date": self._current["end_date"],
                    "status": self._current["status"],
                    "summary": self._current["summary"],
                    "link": self._current["link"],
                    "text": self._current["text"],
                }
                self._current = None
                self._tags_stack = None
            else:
                del self._tags_stack[-1]


class NoteHandler(xml.sax.handler.ContentHandler):
    """Parses <note> element in metadata file and fetches notes for namespaced packages"""

    def __init__(self):
        self._current = None
        self._tags_stack = None
        self.note_data = {}

    def startElement(self, tag, attrs):
        if tag == "note":
            self._current = {"eol_id": attrs["id"], "pkg_info": ""}
            self._tags_stack = []
        if self._current is not None:
            self._tags_stack.append(tag)

    def characters(self, content):
        if self._current is not None:
            if self._tags_stack[-1] == "note":
                self._current["pkg_info"] += content

    def endElement(self, tag):
        if self._current is not None:
            if self._tags_stack[-1] == "note":
                self.note_data[self._current["eol_id"]] = self._current["pkg_info"]
                self._current = None
                self._tags_stack = None
            else:
                del self._tags_stack[-1]


# available filters for packages
STATE_AVAILABLE = "available"
STATE_UNAVAILABLE = "unavailable"
STATE_INSTALLED = "installed"
SUPPORT_STATUS_SUPPORTED = "supported"
SUPPORT_STATUS_UNSUPPORTED = "unsupported"


@dnf.plugin.register_command
class SupportInfoCommand(dnf.cli.Command):
    """Provides a manual command to check support statements for any package"""

    aliases = ("supportinfo",)
    summary = "Get support statements for DL packages"

    def prettify(self, elem):
        """Return a pretty-printed XML string for package support statements"""
        rough_string = ElementTree.tostring(elem, "utf-8")
        reparsed = minidom.parseString(rough_string)
        return reparsed.toprettyxml(indent="  ")

    def _nevra_parser(self, nevra_str):
        """Parse a full nevra string and return a nevra dict"""
        subject = dnf.subject.Subject(nevra_str)
        possible_nevra = list(subject.get_nevra_possibilities(forms=[hawkey.FORM_NEVRA]))
        if possible_nevra:
            nevra = possible_nevra[0]
        else:
            keys = ["name", "epoch", "version", "release", "arch"]
            res = {key: "Unknown" for key in keys}
            return res
        nevra_dict = {
            "name": nevra.name,
            "epoch": nevra.epoch,
            "version": nevra.version,
            "release": nevra.release,
            "arch": nevra.arch,
        }
        return nevra_dict

    def get_available_installed(self):
        """Collect all available and installed packages"""
        with dnf.Base() as base:
            # read the configuration file
            conf = base.conf
            conf.read()
            # set installroot
            installroot = "/"
            conf.installroot = installroot
            # don't prompt for user confirmations
            conf.assumeyes = True
            # load substitutions (awsregion, awsdomain) from the filesystem
            conf.substitutions.update_from_etc(installroot)
            # check amazonlinux.repo (and others) to find packages available to install
            base.read_all_repos()
            base.fill_sack(load_system_repo=True)
            # query matches all packages in sack
            q = base.sack.query()
            # derived query matches only latest available packages
            q_available = q.available().latest().run()
            # derived query matches only installed packages
            q_installed = q.installed().run()
            return q_available, q_installed

    def _pkg_state_helper(self, pkg, state):
        """Returns installation states and other metadata per package in a dictionary"""
        pkg_nevra = self._nevra_parser(str(pkg))
        vr = pkg_nevra["version"] + "-" + pkg_nevra["release"]
        arch = pkg_nevra["arch"]
        pkg_state = {"name": pkg_nevra["name"], "state": state, "version": vr, "arch": arch}
        return pkg_state

    def get_packages_state(self):
        available_pkgs, installed_pkgs = self.get_available_installed()
        map_states = {STATE_INSTALLED: {}, STATE_AVAILABLE: {}}
        for pkg in installed_pkgs:
            pkg_name = self._nevra_parser(str(pkg))["name"]
            map_states[STATE_INSTALLED][pkg_name] = self._pkg_state_helper(pkg, STATE_INSTALLED)
        for pkg in available_pkgs:
            pkg_name = self._nevra_parser(str(pkg))["name"]
            map_states[STATE_AVAILABLE][pkg_name] = self._pkg_state_helper(pkg, STATE_AVAILABLE)
        return map_states

    def show_xml(
        self, pkg, eol_id, nevra, support_status, summary, start_date, end_date, pkg_info, link
    ):
        """Create a basic XML template similar to support_info.xml"""
        package_support = Element(
            "package_support", {"current_as": datetime.now().strftime("%Y-%m-%d")}
        )

        statements = SubElement(package_support, "statements")

        statement = SubElement(
            statements,
            "statement",
            {
                "id": eol_id,
                "marker": support_status,
                "start_date": start_date,
                "end_date": end_date,
            },
        )

        pkg_summary = SubElement(statement, "summary")
        pkg_summary.text = summary

        pkg_support_info = SubElement(statement, "text")
        pkg_support_info.text = pkg_info

        pkg_support_link = SubElement(statement, "link")
        pkg_support_link.text = link

        packages = SubElement(statement, "packages")
        SubElement(packages, "package", {"name": pkg, "nevra": nevra})

        print(self.prettify(package_support))

    def package_info_field(self, dnf_output, key, val, fill=20):
        """Format command line output"""
        return dnf_output.fmtKeyValFill(dnf.i18n.fill_exact_width(key, fill) + " : ", val or "")

    def show_support_periods(self, dnf_output, support_statement):
        """Format support periods output to display different support states"""
        pkg_supported_period = self.package_info_field(
            dnf_output, f"from {support_statement['start_date']}", SUPPORT_STATUS_SUPPORTED
        )
        pkg_unsupported_period = self.package_info_field(
            dnf_output, f"from {support_statement['end_date']}", SUPPORT_STATUS_UNSUPPORTED
        )
        print(self.package_info_field(dnf_output, "Support Periods", pkg_supported_period))
        print(self.package_info_field(dnf_output, "", pkg_unsupported_period))

    def print_package_info(
        self, dnf_output, pkg, eol_id, nevra, state, support_statement, note_data
    ):
        """Print information about the given package"""
        # print package name, nevra, OS state
        print(self.package_info_field(dnf_output, "Name", pkg))
        print(self.package_info_field(dnf_output, "Version", nevra))
        print(self.package_info_field(dnf_output, "State", state))

        # print support status and support periods
        print(self.package_info_field(dnf_output, "Support Status", support_statement["status"]))
        pkg_support_period = self.show_support_periods(dnf_output, support_statement)

        # print support statements
        print(
            self.package_info_field(dnf_output, "Support Statement", support_statement["summary"])
        )
        print(self.package_info_field(dnf_output, "Link", support_statement["link"]))
        print(self.package_info_field(dnf_output, "Other Info", support_statement["text"]))

        if eol_id != "eol":
            print(self.package_info_field(dnf_output, "Package Note", note_data[eol_id]))

        print()

    def get_pkg_os_state(self, package, package_states):
        """Return NEVRA and state of a package if it is installed or available to be installed"""
        if package in package_states[STATE_INSTALLED]:
            nevra = package_states[STATE_INSTALLED][package]["version"]
            return STATE_INSTALLED, nevra
        elif package in package_states[STATE_AVAILABLE]:
            nevra = package_states[STATE_AVAILABLE][package]["version"]
            return STATE_AVAILABLE, nevra
        else:
            return STATE_UNAVAILABLE, ""

    def get_pkg_eol(self, pkg, package_data, support_statement_data, note_data, package_states):
        """Get package data from support_info.xml"""
        with dnf.Base() as base:
            base = dnf.Base()
            dnf_output = dnf.cli.output.Output(base, base.conf)
        for eol_id in package_data:
            if pkg in package_data[eol_id]:
                state, nevra = self.get_pkg_os_state(pkg, package_states)
                support_statement = support_statement_data[eol_id]
                # dnf supportinfo --pkg <pkg> --showxml
                if self.opts.show_xml:
                    return self.show_xml(
                        pkg,
                        eol_id,
                        nevra,
                        support_statement["status"],
                        support_statement["summary"],
                        support_statement["start_date"],
                        support_statement["end_date"],
                        support_statement["text"],
                        support_statement["link"],
                    )
                # dnf supportinfo --pkg <pkg>
                self.print_package_info(
                    dnf_output, pkg, eol_id, nevra, state, support_statement, note_data
                )

    def _record_table(self, package, version, state, status, end_date, statement):
        """Sets formatting for pretty table"""
        return (
            f"{package:<42} {version:<36} {state:<18} {status:<18} {end_date:<18} {statement:<18}"
        )

    def print_support_statements_table(self, pkg, nevra, state, support_info):
        """
        Print table based on supported, unsupported, installed
        and uninstalled filters
        """
        # generate table
        pkg_statement = self._record_table(
            pkg,
            nevra,
            state,
            support_info["status"],
            support_info["end_date"],
            support_info["summary"],
        )
        if state != STATE_UNAVAILABLE:
            print(pkg_statement)

    def display_support_statements(self, _filter, packages, statement, package_states):
        """Print support statements for supported, unsupported or all packages"""
        for eol_id, data in packages.items():
            for pkg in sorted(data):
                state, nevra = self.get_pkg_os_state(pkg, package_states)
                support_info = statement[eol_id]

                # gather packages information per user input filter
                if _filter == STATE_INSTALLED:
                    if state == _filter:
                        self.print_support_statements_table(pkg, nevra, state, support_info)

                elif _filter == STATE_AVAILABLE:
                    if state == _filter:
                        self.print_support_statements_table(pkg, nevra, state, support_info)

                elif _filter == SUPPORT_STATUS_SUPPORTED:
                    if support_info["status"] == _filter:
                        self.print_support_statements_table(pkg, nevra, state, support_info)

                elif _filter == SUPPORT_STATUS_UNSUPPORTED:
                    if support_info["status"] == _filter:
                        self.print_support_statements_table(pkg, nevra, state, support_info)

                elif _filter == "all":
                    self.print_support_statements_table(pkg, nevra, state, support_info)

                else:
                    raise ValueError(f"unknown statement filter: {_filter}")

    @staticmethod
    def set_argparser(parser):
        """Parse package name as command line argument"""
        parser.add_argument(
            "--pkg", help="Display support statements for a package", dest="package"
        )
        parser.add_argument(
            "--showxml",
            help="Generate support info XML for a package",
            action="store_true",
            dest="show_xml",
        )
        parser.add_argument(
            "--show",
            help="Display support statements for packages",
            dest="filter",
            choices=["all", "supported", "unsupported", "installed", "available"],
        )

    def run(self):
        """Runs 'dnf supportinfo --pkg|--show <>' command"""
        # support_info.xml will be stored at this same location of this file
        plugin_dir = os.path.dirname(__file__)
        support_info = os.path.join(plugin_dir, "support_info.xml")

        # get data from <package> element
        package_handler = PackageHandler()
        xml.sax.parse(support_info, package_handler)
        package_data = package_handler.pkg_data

        # get data from <statement> element
        statement_handler = StatementHandler()
        xml.sax.parse(support_info, statement_handler)
        support_statement_data = statement_handler.support_data

        # get data from <note> element
        note_handler = NoteHandler()
        xml.sax.parse(support_info, note_handler)
        note_data = note_handler.note_data

        # get all installed and available packages info
        package_states = self.get_packages_state()

        # support statements for all/supported/unsupported/installed/available packages
        if self.opts.filter:
            self.display_support_statements(
                self.opts.filter, package_data, support_statement_data, package_states
            )

        # show xml or get support info per package
        if self.opts.package:
            self.get_pkg_eol(
                self.opts.package, package_data, support_statement_data, note_data, package_states
            )
