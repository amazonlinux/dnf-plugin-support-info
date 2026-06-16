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
#

# Special filter keyword for showing all packages regardless of state
STATE_FILTER_ALL = "all"

# Default cache duration: 30 minutes
# This default is used when metadata_expire is not set in the config file
DEFAULT_CACHE_DURATION_SECONDS = 30 * 60  # 1800 seconds

# metadata_expire validation limits
# Maximum: 90 days (one quarter)
# Rationale:
#   - Prevents dangerously stale security support information
#   - Still provides flexibility for slower environments
#   - For infinite cache (never check for updates), use -1
MAX_ABSOLUTE_CACHE_DURATION_SECONDS = 90 * 24 * 60 * 60  # 7776000 seconds

# Sentinel value used when a package architecture cannot be determined
UNKNOWN_ARCH = "Unknown"

# Configuration file path
SUPPORT_INFO_CONFIG_PATH = "/etc/dnf/plugins/supportinfo.conf"

# ---------------------------------------------------------------------------
# Legacy mode constants
# ---------------------------------------------------------------------------
# When legacy=1 is set in the config, the plugin converts the downloaded
# 1.0 format XML to the legacy (unversioned) format used by the previous
# dnf-plugin-support-info package. These constants define file names and
# paths for that conversion.

# Filename of the XML file as bundled by the old dnf-plugin-support-info RPM
LEGACY_SUPPORT_INFO_FILENAME = "support_info.xml"

# Directory name where old plugin stored its files
LEGACY_DNF_PLUGINS_DIR = "dnf-plugins"

# Filename for the symlink created in the new plugin's cache directory
# This symlink points to the real V1 file at the old plugin's location
LEGACY_CONVERTED_FILENAME = "supportinfo-legacy.xml"

# Suffix for the sidecar that records the SHA-256 of the source XML used for
# the last successful legacy conversion. Written next to the legacy file as
# an atomic identity marker so we can detect stale conversions independently
# of mtime or any in-XML attribute (e.g. current_as).
LEGACY_SOURCE_HASH_SUFFIX = ".source-sha256"

# Phase name values from XML
PHASE_SUPPORTED = "supported"
PHASE_UNSUPPORTED = "unsupported"
