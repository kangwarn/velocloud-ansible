#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Kangwarn Chinthammit
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: edge_common

short_description: Configure common device settings (HA, …) on a VeloCloud edge

version_added: "0.1.0"

description:
    - Patches common sections of C(device_settings) that do not have their own
      dedicated module — starting with C(device_settings.ha).
    - Drift detection is native via pyvelo C(ConfigPipeline.save).
    - Each top-level config section (C(ha), future C(ntp)/C(snmp)) is optional;
      only provided sections are patched.
    - Fails if the edge does not exist.

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
    ha:
        description: >
            High-availability settings mapped to C(device_settings.ha).
            Omit the key to leave HA config untouched.
        required: false
        type: dict
        suboptions:
            enabled:
                description: Enable HA on this edge.
                type: bool
                default: false
            interface:
                description: HA heartbeat interface name.
                type: str
                default: GE1
            unique_lan_macs:
                description: Override LAN MAC addresses (vmacoverride).
                type: bool
                default: false
            unique_wan_macs:
                description: Override WAN MAC addresses (wanmacoverride).
                type: bool
                default: false
            nodes:
                description: >
                    HA node list (active/standby serial numbers).
                    Omit to leave existing nodes untouched; pass C([]) to clear.
                type: list
                elements: dict
                suboptions:
                    serial_number:
                        description: Serial number of the edge node.
                        type: str
                    instance_id:
                        description: Node instance index (1 or 2).
                        type: int
                        choices: [1, 2]
            ha_graceful_switchover:
                description: Enable graceful HA switchover.
                type: bool
                default: false
            ha_failover_count:
                description: Number of missed heartbeats before failover.
                type: float
                default: 7
            preempt_switchover:
                description: Allow preemptive switchover (preEmptSwitchover).
                type: bool
                default: false
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
- name: Enable HA on vce1 with GE1 heartbeat interface
  velocloud.api.edge_common:
    vco_host: vco.example.com
    api_token: "{{ vco_api_token }}"
    edge: vce1
    ha:
      enabled: true
      interface: GE1
      unique_lan_macs: false
      unique_wan_macs: false

- name: Enable HA with node serial numbers
  velocloud.api.edge_common:
    vco_host: vco.example.com
    api_token: "{{ vco_api_token }}"
    edge: vce1
    ha:
      enabled: true
      interface: GE1
      nodes:
        - instance_id: 1
          serial_number: VC-AABBCCDD
        - instance_id: 2
          serial_number: VC-EEFF0011

- name: Disable HA
  velocloud.api.edge_common:
    vco_host: vco.example.com
    api_token: "{{ vco_api_token }}"
    edge: vce1
    ha:
      enabled: false
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
        HaInput,
        HaNodeInput,
        apply_ha,
    )

    HAS_PYVELO = True
    PYVELO_IMPORT_ERROR = None
except ImportError as e:
    HAS_PYVELO = False
    PYVELO_IMPORT_ERROR = str(e)


async def _resolve_edge(client, enterprise_id, edge_name, edge_id):
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


def _build_ha_spec(ha_params: dict) -> HaInput:
    nodes_raw = ha_params.pop("nodes", None)
    spec = HaInput(**ha_params)
    if nodes_raw is not None:
        spec.nodes = [HaNodeInput(**n) for n in nodes_raw]
    return spec


async def _async_main(module: AnsibleModule, params: dict) -> dict:
    enterprise_id = resolve_enterprise_id(params)

    client = build_client(params)
    async with client:
        edge_id = await _resolve_edge(
            client, enterprise_id, params.get("edge"), params.get("edge_id")
        )

        pipeline = ConfigPipeline(client)
        cfg_state = await pipeline.load(edge_id, enterprise_id=enterprise_id)

        if params.get("ha") is not None:
            ha_spec = _build_ha_spec(dict(params["ha"]))
            cfg_state = await apply_ha(pipeline, cfg_state, ha_spec)

        result = await pipeline.save(
            cfg_state, dry_run=module.check_mode, validate=params["validate"]
        )

        validation_errors = getattr(result, "validation_errors", None) or []
        if validation_errors:
            raise RuntimeError(f"Validation failed: {validation_errors}")

        modules_updated = [str(m) for m in (result.modules_updated or [])]
        modules_inserted = [str(m) for m in (result.modules_inserted or [])]
        return {
            "changed": bool(modules_updated) or bool(modules_inserted),
            "modules_updated": modules_updated,
            "modules_inserted": modules_inserted,
        }


def main() -> None:
    argspec = common_argspec()
    argspec.update(
        edge=dict(type="str"),
        edge_id=dict(type="int"),
        ha=dict(type="dict"),
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
            msg=f"velocloud.api.edge_common failed: {type(e).__name__}: {e}",
            exception=traceback.format_exc(),
        )

    module.exit_json(**result)


if __name__ == "__main__":
    main()
