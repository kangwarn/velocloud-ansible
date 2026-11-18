#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Kangwarn Chinthammit
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: edge_loopback

short_description: Configure loopback interfaces on a VeloCloud edge

version_added: "0.1.0"

description:
    - Patches C(device_settings.loopback_interfaces) on an edge via the pyvelo
      C(ConfigPipeline).
    - Each loopback is identified by a name (the dict key in the VCO data model).
      The IP address is always a /32.
    - Idempotent — pyvelo drift detection prevents unnecessary saves.
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
    loopback_interfaces:
        description: List of loopback interfaces to configure.
        required: true
        type: list
        elements: dict
        suboptions:
            name:
                description: Loopback interface name (e.g. C(loop0), C(lo1)).
                required: true
                type: str
            cidr_ip:
                description: IPv4 address for this loopback (/32 prefix is implied).
                required: true
                type: str
            segment_id:
                description: Segment name this loopback belongs to (e.g. C(Global Segment)).
                type: str
                default: "Global Segment"
            advertise:
                description: Advertise this loopback into the SD-WAN overlay.
                type: bool
                default: true
            ping_response:
                description: Respond to ICMP pings on this loopback.
                type: bool
                default: true
            disable_ipv4:
                description: Disable IPv4 on this loopback (disableV4).
                type: bool
                default: false
            disable_ipv6:
                description: Disable IPv6 on this loopback (disableV6).
                type: bool
                default: true
            description:
                description: Optional human-readable description.
                type: str
                required: false
            ospf:
                description: OSPF settings for this loopback.
                type: dict
                suboptions:
                    enabled:
                        description: Enable OSPF on this loopback.
                        type: bool
                        default: false
                    area:
                        description: OSPF area list.
                        type: list
                        elements: raw
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
- name: Configure loopback interfaces on vce1
  velocloud.api.edge_loopback:
    vco_host: vco.example.com
    api_token: "{{ vco_api_token }}"
    edge: vce1
    loopback_interfaces:
      - name: loop0
        cidr_ip: 10.255.0.1
        segment_id: 0
        advertise: true

- name: Configure loopback with OSPF
  velocloud.api.edge_loopback:
    vco_host: vco.example.com
    api_token: "{{ vco_api_token }}"
    edge: vce1
    loopback_interfaces:
      - name: loop0
        cidr_ip: 192.168.100.1
        description: Router ID loopback
        advertise: true
        ospf:
          enabled: true
          area:
            - 0

- name: Configure multiple loopbacks across segments
  velocloud.api.edge_loopback:
    vco_host: vco.example.com
    api_token: "{{ vco_api_token }}"
    edge: vce1
    loopback_interfaces:
      - name: loop0
        cidr_ip: 10.0.0.1
        segment_id: 0
        advertise: true
      - name: loop1
        cidr_ip: 10.1.0.1
        segment_id: 1
        advertise: true
        ping_response: false
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
        LoopbackInterfaceInput,
        LoopbackOspfInput,
        apply_loopback_interfaces,
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


def _build_loopback_spec(raw: dict) -> LoopbackInterfaceInput:
    ospf_raw = raw.pop("ospf", None) or {}
    spec = LoopbackInterfaceInput(**raw)
    if ospf_raw:
        spec.ospf = LoopbackOspfInput(**ospf_raw)
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

        loopback_specs = [
            _build_loopback_spec(dict(lo)) for lo in params["loopback_interfaces"]
        ]
        cfg_state = await apply_loopback_interfaces(pipeline, cfg_state, loopback_specs)

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
        loopback_interfaces=dict(type="list", elements="dict", required=True),
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
            msg=f"velocloud.api.edge_loopback failed: {type(e).__name__}: {e}",
            exception=traceback.format_exc(),
        )

    module.exit_json(**result)


if __name__ == "__main__":
    main()
