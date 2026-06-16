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

"""Utility functions for DNF Support Info plugin."""

from .const import MAX_ABSOLUTE_CACHE_DURATION_SECONDS


def validate_metadata_expire(metadata_expire: int) -> None:
    """Validate metadata_expire value.

    Args:
        metadata_expire: Cache validity duration in seconds

    Raises:
        ValueError: If metadata_expire value is invalid
            - Must be -1 (infinite cache) or non-negative
            - Cannot exceed MAX_ABSOLUTE_CACHE_DURATION_SECONDS
    """
    if metadata_expire < -1:
        raise ValueError(
            "metadata_expire must be -1 (infinite) or non-negative, " f"got {metadata_expire}"
        )
    elif metadata_expire > MAX_ABSOLUTE_CACHE_DURATION_SECONDS:
        raise ValueError(
            f"metadata_expire ({metadata_expire} seconds = "
            f"{metadata_expire / 86400:.1f} days) exceeds maximum "
            f"({MAX_ABSOLUTE_CACHE_DURATION_SECONDS} seconds = "
            f"{MAX_ABSOLUTE_CACHE_DURATION_SECONDS / 86400:.0f} days). "
            "For infinite cache, use -1"
        )
