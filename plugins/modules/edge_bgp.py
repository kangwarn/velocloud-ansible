#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Kangwarn Chinthammit
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: edge_bgp

short_description: Configure BGP on a VeloCloud edge for a single segment

version_added: "0.1.0"

description:
    - Patches C(device_settings.segments.<segment>.bgp) for the named segment on
      a single edge.
    - Drift detection is native via pyvelo C(ConfigPipeline.save).
    - Loop the task to configure multiple segments on the same edge.
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
        description: Edge name.
        required: false
        type: str
    edge_id:
        description: Edge numeric ID.
        required: false
        type: int
    segment_id:
        description: Segment name (note - this is a string, not a numeric id).
        required: false
        type: str
        default: Global Segment
    enabled:
        description: Whether BGP is enabled on this segment.
        required: false
        type: bool
        default: true
    asn:
        description: BGP autonomous system number (string per pyvelo schema).
        required: true
        type: str
    connected_routes:
        description: Advertise connected routes.
        required: false
        type: bool
        default: true
    overlay_prefix:
        description: Advertise overlay prefix.
        required: false
        type: bool
        default: false
    propagate_uplink:
        description: Propagate uplink.
        required: false
        type: bool
        default: false
    router_id:
        description: BGP router ID.
        required: false
        type: str
    keepalive:
        description: BGP keepalive timer (seconds, string).
        required: false
        type: str
        default: "60"
    holdtime:
        description: BGP holdtime (seconds, string).
        required: false
        type: str
        default: "180"
    enable_graceful_restart:
        description: Enable BGP graceful restart.
        required: false
        type: bool
        default: false
    neighbors:
        description: List of BGP neighbor specs.
        required: false
        type: list
        elements: dict
        default: []
        suboptions:
            neighbor_ip:
                description: Neighbor IPv4 address.
                type: str
                required: true
            neighbor_as:
                description: Neighbor autonomous system number.
                type: str
                required: true
            description:
                description: Neighbor description.
                type: str
                default: ""
            enable_bfd:
                description: Enable BFD for this neighbor.
                type: bool
                default: false
            enable_md5:
                description: Enable MD5 authentication for this neighbor.
                type: bool
                default: false
            md5_password:
                description: MD5 password for the neighbor session.
                type: str
                default: ""
            uplink:
                description: Treat the neighbor as an uplink.
                type: bool
                default: false
            allow_as:
                description: Allow AS.
                type: bool
                default: false
            max_hop:
                description: Maximum hop count.
                type: str
                default: "1"
            keepalive:
                description: Neighbor keepalive timer in seconds.
                type: str
                default: "60"
            holdtime:
                description: Neighbor holdtime in seconds.
                type: str
                default: "180"
            connect:
                description: Connect retry timer in seconds.
                type: str
                default: "120"
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
- name: BGP on Global Segment
  velocloud.api.edge_bgp:
    vco_host: vco.example.com
    api_token: "{{ vco_api_token }}"
    edge: BRANCH-01
    segment_id: Global Segment
    asn: "64010"
    connected_routes: true
    neighbors:
      - neighbor_ip: 172.24.10.2
        neighbor_as: "64011"

- name: BGP on each segment via loop
  velocloud.api.edge_bgp:
    vco_host: vco.example.com
    api_token: "{{ vco_api_token }}"
    edge: BRANCH-01
    segment_id: "{{ item.segment_id }}"
    asn: "{{ item.asn }}"
    neighbors: "{{ item.neighbors }}"
  loop:
    - segment_id: Global Segment
      asn: "64010"
      neighbors: [{ neighbor_ip: 172.24.10.2, neighbor_as: "64011" }]
    - segment_id: Demo-Segment
      asn: "64010"
      neighbors: [{ neighbor_ip: 172.24.9.2, neighbor_as: "64011" }]
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
        BgpInput,
        BgpNeighborInput,
        apply_bgp,
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


def _build_bgp_spec(params: dict) -> BgpInput:
    neighbors = [BgpNeighborInput(**n) for n in (params.get("neighbors") or [])]
    kwargs = dict(
        enabled=params["enabled"],
        asn=params["asn"],
        segment_id=params["segment_id"],
        connected_routes=params["connected_routes"],
        overlay_prefix=params["overlay_prefix"],
        propagate_uplink=params["propagate_uplink"],
        keepalive=params["keepalive"],
        holdtime=params["holdtime"],
        enable_graceful_restart=params["enable_graceful_restart"],
        neighbors=neighbors,
    )
    if params.get("router_id"):
        kwargs["router_id"] = params["router_id"]
    return BgpInput(**kwargs)


async def _async_main(module: AnsibleModule, params: dict) -> dict:
    enterprise_id = resolve_enterprise_id(params)
    bgp_spec = _build_bgp_spec(params)

    client = build_client(params)
    async with client:
        edge_id = await _resolve_edge(
            client, enterprise_id, params.get("edge"), params.get("edge_id")
        )

        pipeline = ConfigPipeline(client)
        cfg_state = await pipeline.load(edge_id, enterprise_id=enterprise_id)
        cfg_state = await apply_bgp(pipeline, cfg_state, bgp_spec)

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
        segment_id=dict(type="str", default="Global Segment"),
        enabled=dict(type="bool", default=True),
        asn=dict(type="str", required=True),
        connected_routes=dict(type="bool", default=True),
        overlay_prefix=dict(type="bool", default=False),
        propagate_uplink=dict(type="bool", default=False),
        router_id=dict(type="str"),
        keepalive=dict(type="str", default="60"),
        holdtime=dict(type="str", default="180"),
        enable_graceful_restart=dict(type="bool", default=False),
        neighbors=dict(
            type="list",
            elements="dict",
            default=[],
            options=dict(
                neighbor_ip=dict(type="str", required=True),
                neighbor_as=dict(type="str", required=True),
                description=dict(type="str", default=""),
                enable_bfd=dict(type="bool", default=False),
                enable_md5=dict(type="bool", default=False),
                md5_password=dict(type="str", default="", no_log=True),
                uplink=dict(type="bool", default=False),
                allow_as=dict(type="bool", default=False),
                max_hop=dict(type="str", default="1"),
                keepalive=dict(type="str", default="60"),
                holdtime=dict(type="str", default="180"),
                connect=dict(type="str", default="120"),
            ),
        ),
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
            msg=f"velocloud.api.edge_bgp failed: {type(e).__name__}: {e}",
            exception=traceback.format_exc(),
        )

    module.exit_json(**result)


if __name__ == "__main__":
    main()
