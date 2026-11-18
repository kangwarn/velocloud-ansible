#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Kangwarn Chinthammit
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: segment

short_description: Manage VeloCloud network segments

version_added: "0.1.0"

description:
    - Create or delete a network segment in a VeloCloud enterprise.
    - When the segment exists by name and fields differ from the spec, the module
      logs a warning and skips by default. Pass C(force=true) to delete and
      recreate the segment instead.
    - The pyvelo SDK does not expose an in-place update for segments.

options:
    vco_host:
        description: VCO hostname or IP.
        required: true
        type: str
    api_token:
        description: API token (mutually exclusive with username/password).
        required: false
        type: str
    username:
        description: VCO username (used with C(password)).
        required: false
        type: str
    password:
        description: VCO password (used with C(username)).
        required: false
        type: str
    enterprise_id:
        description:
            - Enterprise ID. Auto-resolved from the JWT payload when C(api_token) is used.
            - Required for username/password auth.
        required: false
        type: int
    verify_ssl:
        description: Verify the VCO TLS certificate.
        required: false
        type: bool
        default: true
    state:
        description: C(present) ensures the segment exists; C(absent) deletes it.
        required: false
        type: str
        choices: [present, absent]
        default: present
    name:
        description: Segment name.
        required: true
        type: str
    type:
        description: Segment type.
        required: false
        type: str
        choices: [REGULAR, CDE, PRIVATE_WIRE]
        default: REGULAR
    description:
        description: Free-form description.
        required: false
        type: str
        default: ""
    segment_id:
        description: Numeric segment identifier (must be unique within the enterprise).
        required: false
        type: int
        default: 1
    delegate_to_enterprise:
        description: Delegate management of this segment to the enterprise admin.
        required: false
        type: bool
        default: true
    delegate_to_enterprise_proxy:
        description: Delegate management of this segment to enterprise proxies.
        required: false
        type: bool
        default: true
    force:
        description:
            - When C(true) and an existing segment differs from the spec, delete
              and recreate it. Destructive — any references to the existing
              logical_id will break.
        required: false
        type: bool
        default: false

requirements:
    - pyvelo
    - requests

author:
    - Kangwarn Chinthammit (@kangwarn-arista)
"""

EXAMPLES = r"""
- name: Create a regular segment
  velocloud.api.segment:
    vco_host: vco.example.com
    api_token: "{{ vco_api_token }}"
    name: Demo-Segment
    segment_id: 99
    description: Created by Ansible

- name: Delete a segment
  velocloud.api.segment:
    vco_host: vco.example.com
    api_token: "{{ vco_api_token }}"
    name: Demo-Segment
    state: absent

- name: Username/password auth (enterprise_id required)
  velocloud.api.segment:
    vco_host: vco.example.com
    username: super@velocloud.net
    password: "{{ vco_password }}"
    enterprise_id: 2
    name: Demo-Segment
    segment_id: 99
"""

RETURN = r"""
changed:
    description: Whether the segment was created, deleted, or recreated.
    type: bool
    returned: always
segment:
    description: Segment record (id, logical_id, name, segment_id, type).
    type: dict
    returned: when state=present and segment exists or was created
drift:
    description: Field-level diff between the spec and the existing segment.
    type: dict
    returned: when an existing segment differs from the spec
"""

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.velocloud.api.plugins.module_utils.sdk_args import (
    common_argspec,
    common_argspec_constraints,
)

try:
    from ansible_collections.velocloud.api.plugins.module_utils.auth import (
        build_client,
        resolve_enterprise_id,
        run_async,
    )
    from ansible_collections.velocloud.api.plugins.module_utils.diff import (
        segment_drift,
    )
    from pyvelo.client.enums.enterprise import NetworkSegmentType
    from pyvelo.client.models.enterprise import NetworkSegmentData
    from pyvelo.client.schemas.enterprise import (
        DeleteEnterpriseNetworkSegment,
        GetEnterpriseNetworkSegments,
        InsertEnterpriseNetworkSegment,
    )
    from ansible_collections.velocloud.api.plugins.module_utils.topology import (
        SegmentSpec,
    )

    HAS_PYVELO = True
    PYVELO_IMPORT_ERROR = None
except ImportError as e:
    HAS_PYVELO = False
    PYVELO_IMPORT_ERROR = str(e)


def _segment_to_dict(seg) -> dict:
    return {
        "id": seg.id_,
        "logical_id": str(seg.logical_id),
        "name": seg.name,
        "segment_id": seg.data.segment_id if seg.data else None,
        "type": seg.type_.value if hasattr(seg.type_, "value") else seg.type_,
    }


async def _async_main(module: AnsibleModule, params: dict) -> dict:
    spec = SegmentSpec(
        name=params["name"],
        type=NetworkSegmentType(params["type"]),
        description=params["description"],
        segment_id=params["segment_id"],
        delegate_to_enterprise=params["delegate_to_enterprise"],
        delegate_to_enterprise_proxy=params["delegate_to_enterprise_proxy"],
    )
    enterprise_id = resolve_enterprise_id(params)
    state = params["state"]
    force = params["force"]
    check_mode = module.check_mode

    client = build_client(params)
    async with client:
        existing_list = await client.get_enterprise_network_segments(
            GetEnterpriseNetworkSegments(enterprise_id=enterprise_id)
        )
        existing = next((s for s in existing_list if s.name == spec.name), None)

        if state == "absent":
            if existing is None:
                return {"changed": False}
            if not check_mode:
                await client.delete_enterprise_network_segment(
                    DeleteEnterpriseNetworkSegment(
                        id_=existing.id_, enterprise_id=enterprise_id
                    )
                )
            return {"changed": True, "segment": _segment_to_dict(existing)}

        # state == "present"
        spec_dict = spec.model_dump(mode="json")
        spec_dict["type"] = (
            spec.type.value if hasattr(spec.type, "value") else spec.type
        )

        if existing is not None:
            drift = segment_drift(spec_dict, existing)
            if not drift:
                return {"changed": False, "segment": _segment_to_dict(existing)}

            if not force:
                module.warn(
                    f"Segment '{spec.name}' exists but drifts from spec; "
                    "pass force=true to delete and recreate."
                )
                return {
                    "changed": False,
                    "segment": _segment_to_dict(existing),
                    "drift": drift,
                }

            if not check_mode:
                await client.delete_enterprise_network_segment(
                    DeleteEnterpriseNetworkSegment(
                        id_=existing.id_, enterprise_id=enterprise_id
                    )
                )

        if check_mode:
            return {
                "changed": True,
                "segment": {
                    "name": spec.name,
                    "segment_id": spec.segment_id,
                    "type": spec_dict["type"],
                    "id": None,
                    "logical_id": None,
                },
            }

        created = await client.insert_enterprise_network_segment(
            InsertEnterpriseNetworkSegment(
                name=spec.name,
                type_=spec.type,
                description=spec.description,
                data=NetworkSegmentData(
                    segment_id=spec.segment_id,
                    delegate_to_enterprise=spec.delegate_to_enterprise,
                    delegate_to_enterprise_proxy=spec.delegate_to_enterprise_proxy,
                ),
                enterprise_id=enterprise_id,
            )
        )
        return {"changed": True, "segment": _segment_to_dict(created)}


def main() -> None:
    argspec = common_argspec()
    argspec.update(
        state=dict(
            type="str", required=False, choices=["present", "absent"], default="present"
        ),
        name=dict(type="str", required=True),
        type=dict(
            type="str",
            required=False,
            choices=["REGULAR", "CDE", "PRIVATE_WIRE"],
            default="REGULAR",
        ),
        description=dict(type="str", required=False, default=""),
        segment_id=dict(type="int", required=False, default=1),
        delegate_to_enterprise=dict(type="bool", required=False, default=True),
        delegate_to_enterprise_proxy=dict(type="bool", required=False, default=True),
        force=dict(type="bool", required=False, default=False),
    )

    module = AnsibleModule(
        argument_spec=argspec,
        supports_check_mode=True,
        **common_argspec_constraints(),
    )

    if not HAS_PYVELO:
        module.fail_json(msg=f"pyvelo SDK not available: {PYVELO_IMPORT_ERROR}")

    try:
        result = run_async(_async_main(module, module.params))
    except ValueError as e:
        module.fail_json(msg=str(e))
    except Exception as e:
        import traceback

        module.fail_json(
            msg=f"velocloud.api.segment failed: {type(e).__name__}: {e}",
            exception=traceback.format_exc(),
        )

    module.exit_json(**result)


if __name__ == "__main__":
    main()
