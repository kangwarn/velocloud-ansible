#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Kangwarn Chinthammit
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: edge

short_description: Create or delete a VeloCloud edge

version_added: "0.1.0"

description:
    - Create an edge bound to a configuration profile, or delete an existing edge.
    - This module only handles the edge record itself. Configure interfaces,
      VLANs, and BGP using C(velocloud.api.edge_lan), C(velocloud.api.edge_wan),
      and C(velocloud.api.edge_bgp).
    - The pyvelo SDK does not expose an in-place update for edges. When an edge
      exists with drift, the module warns and skips by default. Pass C(force=true)
      to delete and recreate. WARNING — deleting an edge invalidates its
      activation key and removes telemetry history.

options:
    vco_host:
        description: VCO hostname or IP.
        required: true
        type: str
    api_token:
        description: API token.
        required: false
        type: str
    username:
        description: VCO username.
        required: false
        type: str
    password:
        description: VCO password.
        required: false
        type: str
    enterprise_id:
        description: Enterprise ID.
        required: false
        type: int
    verify_ssl:
        description: Verify the VCO TLS certificate.
        required: false
        type: bool
        default: true
    state:
        description: present ensures the edge exists; absent deletes it.
        required: false
        type: str
        choices: [present, absent]
        default: present
    name:
        description: Edge name.
        required: true
        type: str
    profile:
        description: Configuration profile name (must already exist).
        required: false
        type: str
    profile_id:
        description: Configuration profile ID. Mutually exclusive with profile.
        required: false
        type: int
    model_number:
        description: Edge model identifier (e.g. virtual, edge520).
        required: false
        type: str
    edge_license_id:
        description: Edge license ID.
        required: false
        type: int
    site:
        description: Site location dict with optional name, city, state, country.
        required: false
        type: dict
    force:
        description: Delete and recreate if edge exists with drift. DESTRUCTIVE.
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
- name: Create an edge
  velocloud.api.edge:
    vco_host: vco.example.com
    api_token: "{{ vco_api_token }}"
    name: BRANCH-01
    profile: Demo-Profile
    model_number: virtual
    edge_license_id: 520
    site:
      city: New York
      state: NY
      country: US
  register: branch01
  no_log: true   # activation_key is sensitive

- name: Delete an edge
  velocloud.api.edge:
    vco_host: vco.example.com
    api_token: "{{ vco_api_token }}"
    name: BRANCH-01
    state: absent
"""

RETURN = r"""
changed:
    description: Whether the edge was created, deleted, or recreated.
    type: bool
    returned: always
edge:
    description: Edge record (id, name, activation_key, configuration_id).
    type: dict
    returned: when state=present and edge exists or was created
"""

from typing import Optional

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
    from ansible_collections.velocloud.api.plugins.module_utils.diff import edge_drift
    from pyvelo.client.enums.edge import ModelNumber
    from pyvelo.client.schemas.edge import DeleteEdge
    from pyvelo.client.schemas.enterprise import GetEnterpriseEdges
    from pyvelo.client.schemas.profiles import GetEnterpriseConfigurations
    from ansible_collections.velocloud.api.plugins.module_utils.topology import (
        EdgeSite,
        EdgeSpec,
        create_edge_only,
    )

    HAS_PYVELO = True
    PYVELO_IMPORT_ERROR = None
except ImportError as e:
    HAS_PYVELO = False
    PYVELO_IMPORT_ERROR = str(e)


def _edge_to_dict(edge, activation_key=None) -> dict:
    out = {
        "id": edge.id_,
        "name": getattr(edge, "name", None),
        "configuration_id": getattr(edge, "configuration_id", None),
    }
    if activation_key is None:
        raw_key = getattr(edge, "activation_key", None)
        if isinstance(raw_key, str) and raw_key:
            activation_key = raw_key
    if activation_key is not None:
        out["activation_key"] = activation_key
    return out


async def _resolve_profile_id(
    client, enterprise_id: int, profile_name: Optional[str], profile_id: Optional[int]
) -> int:
    if profile_id is not None:
        return int(profile_id)
    if profile_name is None:
        raise ValueError(
            "Either 'profile' or 'profile_id' is required to create an edge"
        )
    profiles = await client.get_enterprise_configurations(
        GetEnterpriseConfigurations(enterprise_id=enterprise_id)
    )
    match = next((p for p in profiles if p.name == profile_name), None)
    if match is None or match.id_ is None:
        available = ", ".join(p.name for p in profiles if p.name)
        raise ValueError(
            f"Profile '{profile_name}' not found in enterprise {enterprise_id}. "
            f"Available: {available}"
        )
    return match.id_


async def _async_main(module: AnsibleModule, params: dict) -> dict:
    enterprise_id = resolve_enterprise_id(params)
    state = params["state"]
    force = params["force"]
    check_mode = module.check_mode
    name = params["name"]

    client = build_client(params)
    async with client:
        existing_list = await client.get_enterprise_edges(
            GetEnterpriseEdges(enterprise_id=enterprise_id)
        )
        existing = next((e for e in existing_list if e.name == name), None)

        if state == "absent":
            if existing is None:
                return {"changed": False}
            if not check_mode:
                await client.delete_edge(
                    DeleteEdge(id_=existing.id_, enterprise_id=enterprise_id)
                )
            return {"changed": True, "edge": _edge_to_dict(existing)}

        # state == "present"
        if existing is not None:
            spec_dict = {"name": name}
            if params.get("model_number"):
                spec_dict["model_number"] = params["model_number"]
            if params.get("edge_license_id") is not None:
                spec_dict["edge_license_id"] = params["edge_license_id"]
            drift = edge_drift(spec_dict, existing)
            if not drift:
                return {"changed": False, "edge": _edge_to_dict(existing)}
            if not force:
                module.warn(
                    f"Edge '{name}' exists but drifts from spec; pass force=true "
                    "to delete and recreate. DESTRUCTIVE — invalidates activation key."
                )
                return {
                    "changed": False,
                    "edge": _edge_to_dict(existing),
                    "drift": drift,
                }
            if not check_mode:
                await client.delete_edge(
                    DeleteEdge(id_=existing.id_, enterprise_id=enterprise_id)
                )

        # Need to create
        if not params.get("model_number") or params.get("edge_license_id") is None:
            raise ValueError(
                "model_number and edge_license_id are required to create an edge"
            )

        profile_id = await _resolve_profile_id(
            client, enterprise_id, params.get("profile"), params.get("profile_id")
        )

        site_obj = None
        if params.get("site"):
            site_obj = EdgeSite(**params["site"])

        spec = EdgeSpec(
            name=name,
            profile=params.get("profile") or "",
            model_number=ModelNumber(params["model_number"]),
            edge_license_id=int(params["edge_license_id"]),
            site=site_obj,
        )

        if check_mode:
            return {
                "changed": True,
                "edge": {"name": name, "configuration_id": profile_id, "id": None},
            }

        result = await create_edge_only(client, enterprise_id, spec, profile_id)
        return {
            "changed": True,
            "edge": {
                "id": result.id_,
                "name": name,
                "configuration_id": profile_id,
                "activation_key": result.activation_key,
            },
        }


def main() -> None:
    argspec = common_argspec()
    argspec.update(
        state=dict(type="str", choices=["present", "absent"], default="present"),
        name=dict(type="str", required=True),
        profile=dict(type="str"),
        profile_id=dict(type="int"),
        model_number=dict(type="str"),
        edge_license_id=dict(type="int"),
        site=dict(type="dict"),
        force=dict(type="bool", default=False),
    )

    constraints = common_argspec_constraints()
    constraints["mutually_exclusive"] = list(constraints["mutually_exclusive"]) + [
        ("profile", "profile_id"),
    ]

    module = AnsibleModule(
        argument_spec=argspec,
        supports_check_mode=True,
        **constraints,
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
            msg=f"velocloud.api.edge failed: {type(e).__name__}: {e}",
            exception=traceback.format_exc(),
        )

    module.exit_json(**result)


if __name__ == "__main__":
    main()
