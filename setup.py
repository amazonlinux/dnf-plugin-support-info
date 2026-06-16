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

# PEP 621 [project] metadata in pyproject.toml is only read by setuptools
# >= 61. Some downstream RPM builds use older setuptools, which silently
# drops [project] metadata. Mirror the customer-visible fields here so the
# wheel produced by every setuptools version carries the right metadata.
# pyproject.toml [project] is the source of truth; bump both together.
from pathlib import Path

from setuptools import find_packages, setup

HERE = Path(__file__).parent
LONG_DESCRIPTION = (HERE / "README.md").read_text(encoding="utf-8")

setup(
    name="dnf-plugin-support-info",
    version="2.0.0",
    description=(
        "DNF plugin for querying and displaying Amazon Linux package support "
        "information"
    ),
    long_description=LONG_DESCRIPTION,
    long_description_content_type="text/markdown",
    author="Amazon.com, Inc. or its affiliates",
    license="GPL-2.0-only",
    url="https://github.com/amazonlinux/dnf-plugin-support-info",
    project_urls={
        "Homepage": "https://github.com/amazonlinux/dnf-plugin-support-info",
        "Issues": "https://github.com/amazonlinux/dnf-plugin-support-info/issues",
    },
    classifiers=[
        "License :: OSI Approved :: GNU General Public License v2 (GPLv2)",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3 :: Only",
        "Operating System :: POSIX :: Linux",
        "Topic :: System :: Software Distribution",
        "Topic :: System :: Systems Administration",
    ],
    python_requires=">=3.9",
    packages=find_packages(where="src", exclude=("test",)),
    package_dir={"": "src"},
    package_data={"dnf_support_info_plugin": ["py.typed"]},
    install_requires=["supportinfo"],
    extras_require={
        "test": ["pytest", "pytest-cov"],
        "dev": ["black", "isort", "mypy", "flake8", "pep8-naming"],
    },
)
