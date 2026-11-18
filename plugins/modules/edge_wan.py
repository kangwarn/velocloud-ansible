#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Kangwarn Chinthammit
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: edge_wan

short_description: Configure WAN-facing interfaces and link settings on a VeloCloud edge

version_added: "0.1.0"

description:
    - Patches C(device_settings.routed_interfaces) for WAN-facing (overlay-bearing)
      ports and C(wan.links) for bandwidth, mode, discovery, and reachability.
    - Drift detection is native via pyvelo C(ConfigPipeline.save).
    - Fails if the edge does not exist.
    - No purge — WAN links/settings already on the edge that are NOT listed are
      left alone.

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
        description: Edge name.
        required: false
        type: str
    edge_id:
        description: Edge numeric ID.
        required: false
        type: int
    wan_links:
        description: List of WAN-facing routed interface specs (see WanLinkInput).
        required: false
        type: list
        elements: dict
        default: []
    wan_link_settings:
        description: >
            List of wan.links specs (see WanLinkSettingsInput). Includes bandwidth,
            mode, discovery, and PRIVATE-link orchestrator reachability flags.
            Extra keys that match pyvelo WanLink fields are forwarded to the VCO.
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
- name: Configure WAN on BRANCH-01
  velocloud.api.edge_wan:
    vco_host: vco.example.com
    api_token: "{{ vco_api_token }}"
    edge: BRANCH-01
    wan_links:
      - name: GE3
        addressing: { type: STATIC, cidr: 172.25.0.2/24, gateway: 172.25.0.1 }
        wan_overlay: USER_DEFINED
        nat_direct: true
      - name: GE4
        addressing: { type: STATIC, cidr: 100.64.66.2/24, gateway: 100.64.66.1 }
        wan_overlay: AUTO_DISCOVERED
        nat_direct: true
    wan_link_settings:
      - name: MPLS
        type: WIRED
        interfaces: [GE3]
        mode: PRIVATE
        discovery: USER_DEFINED
        orchestrator_service_reachable: true
        orchestrator_service_reachable_backup: true
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
        WanLinkInput,
        WanLinkSettingsInput,
        apply_wan_link_settings,
        apply_wan_links,
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


async def _async_main(module: AnsibleModule, params: dict) -> dict:
    enterprise_id = resolve_enterprise_id(params)
    wan_links = [WanLinkInput(**w) for w in (params.get("wan_links") or [])]
    wan_link_settings = [
        WanLinkSettingsInput(**w) for w in (params.get("wan_link_settings") or [])
    ]

    client = build_client(params)
    async with client:
        edge_id = await _resolve_edge(
            client, enterprise_id, params.get("edge"), params.get("edge_id")
        )

        pipeline = ConfigPipeline(client)
        cfg_state = await pipeline.load(edge_id, enterprise_id=enterprise_id)
        cfg_state = await apply_wan_links(pipeline, cfg_state, wan_links)
        cfg_state = await apply_wan_link_settings(
            pipeline, cfg_state, wan_link_settings
        )

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
        wan_links=dict(type="list", elements="dict", default=[]),
        wan_link_settings=dict(type="list", elements="dict", default=[]),
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
            msg=f"velocloud.api.edge_wan failed: {type(e).__name__}: {e}",
            exception=traceback.format_exc(),
        )

    module.exit_json(**result)


if __name__ == "__main__":
    main()
