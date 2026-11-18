# Copyright: (c) 2026, Kangwarn Chinthammit
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Drift-detection helpers for top-level VeloCloud resources.

For network segments, profiles, and edges the pyvelo SDK exposes only
create/delete (no in-place update). These helpers compare a desired Pydantic
spec against the existing VCO record and return the field-level diff so a
module can decide whether to skip, warn, or (when `force: true`) delete and
recreate.
"""

from __future__ import annotations

from typing import Any


def diff_dicts(
    desired: dict[str, Any], actual: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """Return {field: {'desired': X, 'actual': Y}} for every field that differs.

    Only fields present in `desired` are checked — fields the user did not
    specify are left alone. Nested dicts are compared recursively.
    """
    diff: dict[str, dict[str, Any]] = {}
    for key, want in desired.items():
        have = actual.get(key)
        if isinstance(want, dict) and isinstance(have, dict):
            nested = diff_dicts(want, have)
            if nested:
                diff[key] = {"desired": want, "actual": have, "_nested": nested}
        elif want != have:
            diff[key] = {"desired": want, "actual": have}
    return diff


def segment_drift(
    spec_dict: dict[str, Any], existing: Any
) -> dict[str, dict[str, Any]]:
    """Compute drift for a NetworkSegment. `existing` is a pyvelo NetworkSegment."""
    actual = {
        "name": existing.name,
        "type": existing.type_,
        "description": existing.description or "",
        "segment_id": existing.data.segment_id if existing.data else None,
        "delegate_to_enterprise": (
            existing.data.delegate_to_enterprise if existing.data else None
        ),
        "delegate_to_enterprise_proxy": (
            existing.data.delegate_to_enterprise_proxy if existing.data else None
        ),
    }
    return diff_dicts(spec_dict, actual)


def profile_drift(
    spec_dict: dict[str, Any], existing: Any
) -> dict[str, dict[str, Any]]:
    """Compute drift for an EnterpriseConfigurationProfile.

    Only top-level fields visible from the list endpoint are compared (name,
    description). Segment attachments and firewall settings are not compared
    here — they would require a full profile load and are deliberately out of
    scope for the lightweight drift check.
    """
    actual = {
        "name": existing.name,
        "description": getattr(existing, "description", "") or "",
    }
    minimal = {k: v for k, v in spec_dict.items() if k in actual}
    return diff_dicts(minimal, actual)


def edge_drift(spec_dict: dict[str, Any], existing: Any) -> dict[str, dict[str, Any]]:
    """Compute drift for an Edge (top-level fields only)."""
    actual = {
        "name": existing.name,
        "model_number": getattr(existing, "model_number", None),
        "edge_license_id": getattr(existing, "edge_license_id", None),
        "configuration_id": getattr(existing, "configuration_id", None),
    }
    minimal = {k: v for k, v in spec_dict.items() if k in actual}
    return diff_dicts(minimal, actual)
