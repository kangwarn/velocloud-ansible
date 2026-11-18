#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Kangwarn Chinthammit
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: edge_lan

short_description: Configure LAN-side interfaces, sub-interfaces, and VLANs on a VeloCloud edge

version_added: "0.1.0"

description:
    - Patches C(device_settings.routed_interfaces) (LAN-side ports + sub-interfaces),
      C(device_settings.lan.interfaces) (switched ports), and C(device_settings.lan.networks)
      (VLAN definitions) on an existing edge.
    - Drift detection is native — pyvelo's C(ConfigPipeline.save) diffs against
      the loaded config and only writes modules that actually changed. C(changed)
      reflects whether the save touched any config module.
    - Fails if the edge does not exist (does NOT silently no-op).
    - Listed entries are reconciled; entries already on the edge that are
      NOT listed in the playbook are left alone (no purge mode).
    - Individual VLANs can be removed by setting C(state=absent) on the
      VLAN entry; only C(vlan_id) is required for deletion.

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
    edge:
        description: Edge name. Mutually exclusive with edge_id.
        required: false
        type: str
    edge_id:
        description: Edge numeric ID. Mutually exclusive with edge.
        required: false
        type: int
    routed_interfaces:
        description: List of LAN routed interface specs.
        required: false
        type: list
        elements: dict
        default: []
    switched_interfaces:
        description: List of switched (LAN) port specs.
        required: false
        type: list
        elements: dict
        default: []
    vlans:
        description: List of VLAN/LAN network definitions.
        required: false
        type: list
        elements: dict
        default: []
    validate:
        description: Run pyvelo validators before save.
        required: false
        type: bool
        default: true

requirements:
    - pyvelo
    - requests

author:
    - Kangwarn Chinthammit (@kangwarn-arista)
"""

EXAMPLES = r"""
- name: Configure LAN on BRANCH-01
  velocloud.api.edge_lan:
    vco_host: vco.example.com
    api_token: "{{ vco_api_token }}"
    edge: BRANCH-01
    routed_interfaces:
      - name: GE2
        segment_id: Global Segment
        addressing: { type: STATIC, cidr: 172.24.10.1/24 }
        advertise: true
        override: true
        subinterfaces:
          - subinterface_id: 10
            vlan_id: 10
            segment_id: Demo-Segment
            addressing: { type: STATIC, cidr: 172.24.9.1/24 }
            advertise: true
    switched_interfaces:
      - name: GE1
        port_mode: access
        untagged_vlan: 1
        vlan_ids: [1]
    vlans:
      - name: Corporate
        vlan_id: 1
        cidr: 10.10.0.1/24
        segment_id: Global Segment

- name: Remove a VLAN from BRANCH-01
  velocloud.api.edge_lan:
    vco_host: vco.example.com
    api_token: "{{ vco_api_token }}"
    edge: BRANCH-01
    vlans:
      - vlan_id: 999
        state: absent
"""

RETURN = r"""
changed:
    description: True if any pyvelo configuration module was updated or inserted.
    type: bool
    returned: always
modules_updated:
    description: pyvelo configuration module names that were updated.
    type: list
    returned: always
modules_inserted:
    description: pyvelo configuration module names that were inserted.
    type: list
    returned: always
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
    from pyvelo.client.schemas.enterprise import GetEnterpriseEdges
    from pyvelo_intent.config.pipeline import ConfigPipeline
    from ansible_collections.velocloud.api.plugins.module_utils.topology import (
        RoutedInterfaceInput,
        SwitchedInterfaceInput,
        VlanInput,
        apply_routed_interfaces,
        apply_switched_interfaces,
        apply_vlans,
    )

    HAS_PYVELO = True
    PYVELO_IMPORT_ERROR = None
except ImportError as e:
    HAS_PYVELO = False
    PYVELO_IMPORT_ERROR = str(e)


async def _resolve_edge(client, enterprise_id: int, edge_name, edge_id):
    if edge_id is not None:
        return int(edge_id)
    edges = await client.get_enterprise_edges(
        GetEnterpriseEdges(enterprise_id=enterprise_id)
    )
    match = next((e for e in edges if e.name == edge_name), None)
    if match is None:
        available = ", ".join(e.name for e in edges if e.name)
        raise ValueError(
            f"Edge '{edge_name}' not found in enterprise {enterprise_id}. "
            f"Run velocloud.api.edge first. Available: {available}"
        )
    return match.id_


async def _async_main(module: AnsibleModule, params: dict) -> dict:
    enterprise_id = resolve_enterprise_id(params)

    routed = [
        RoutedInterfaceInput(**ri) for ri in (params.get("routed_interfaces") or [])
    ]
    switched = [
        SwitchedInterfaceInput(**si) for si in (params.get("switched_interfaces") or [])
    ]
    vlans = [VlanInput(**v) for v in (params.get("vlans") or [])]

    client = build_client(params)
    async with client:
        edge_id = await _resolve_edge(
            client, enterprise_id, params.get("edge"), params.get("edge_id")
        )

        pipeline = ConfigPipeline(client)
        cfg_state = await pipeline.load(edge_id, enterprise_id=enterprise_id)
        cfg_state = await apply_routed_interfaces(pipeline, cfg_state, routed)
        cfg_state = await apply_switched_interfaces(pipeline, cfg_state, switched)
        cfg_state = await apply_vlans(pipeline, cfg_state, vlans)

        result = await pipeline.save(
            cfg_state, dry_run=module.check_mode, validate=params["validate"]
        )

        validation_errors = getattr(result, "validation_errors", None) or []
        if validation_errors:
            raise RuntimeError(f"Validation failed: {validation_errors}")

        modules_updated = [str(m) for m in (result.modules_updated or [])]
        modules_inserted = [str(m) for m in (result.modules_inserted or [])]
        changed = bool(modules_updated) or bool(modules_inserted)

        return {
            "changed": changed,
            "modules_updated": modules_updated,
            "modules_inserted": modules_inserted,
        }


def main() -> None:
    argspec = common_argspec()
    argspec.update(
        edge=dict(type="str"),
        edge_id=dict(type="int"),
        routed_interfaces=dict(type="list", elements="dict", default=[]),
        switched_interfaces=dict(type="list", elements="dict", default=[]),
        vlans=dict(type="list", elements="dict", default=[]),
        validate=dict(type="bool", default=True),
    )

    constraints = common_argspec_constraints()
    constraints["mutually_exclusive"] = list(constraints["mutually_exclusive"]) + [
        ("edge", "edge_id"),
    ]
    constraints["required_one_of"] = list(constraints["required_one_of"]) + [
        ("edge", "edge_id"),
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
            msg=f"velocloud.api.edge_lan failed: {type(e).__name__}: {e}",
            exception=traceback.format_exc(),
        )

    module.exit_json(**result)


if __name__ == "__main__":
    main()
