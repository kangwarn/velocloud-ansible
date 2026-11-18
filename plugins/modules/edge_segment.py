#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Kangwarn Chinthammit
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: edge_segment

short_description: Configure per-segment settings (BGP, routes, business policy) on a VeloCloud edge

version_added: "0.1.0"

description:
    - Patches per-segment configuration for a named segment on a single edge.
    - C(bgp) and C(routes) patch C(device_settings.segments.<segment>);
      C(bizpolicy) patches C(qos.segments.<segment>.rules).
    - Supports C(bgp), C(routes), and C(bizpolicy) as optional sub-options;
      at least one must be provided.
    - Loop the task to configure multiple segments on the same edge.
    - Drift detection is native via pyvelo C(ConfigPipeline.save).
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
        description: Segment name (string, not numeric id).
        required: false
        type: str
        default: Global Segment
    bgp:
        description: BGP configuration for this segment.
        required: false
        type: dict
        suboptions:
            enabled:
                description: Whether BGP is enabled.
                type: bool
                default: true
            asn:
                description: BGP autonomous system number (string).
                type: str
                required: true
            connected_routes:
                description: Advertise connected routes.
                type: bool
                default: true
            overlay_prefix:
                description: Advertise overlay prefix.
                type: bool
                default: false
            propagate_uplink:
                description: Propagate uplink.
                type: bool
                default: false
            router_id:
                description: BGP router ID.
                type: str
            keepalive:
                description: BGP keepalive timer (seconds, string).
                type: str
                default: "60"
            holdtime:
                description: BGP holdtime (seconds, string).
                type: str
                default: "180"
            enable_graceful_restart:
                description: Enable BGP graceful restart.
                type: bool
                default: false
            neighbors:
                description: List of BGP neighbor specs.
                type: list
                elements: dict
                default: []
    routes:
        description: Routes configuration for this segment.
        required: false
        type: dict
        suboptions:
            static:
                description: >
                    List of static routes. Each entry accepts either a C(cidr) shorthand
                    (e.g. "10.0.0.0/24") or explicit C(destination), C(netmask), C(cidr_prefix).
                    C(gateway) is always required.
                type: list
                elements: dict
                default: []
            static_v6:
                description: List of static IPv6 routes (same structure as C(static)).
                type: list
                elements: dict
                default: []
    bizpolicy:
        description: >
            Business-policy (QoS) rules for this segment. Each rule has its
            own C(state) (C(present) or C(absent)) so individual rules can be
            added, updated, or deleted without disturbing siblings. Patches
            C(qos.segments.<segment>.rules).
        required: false
        type: list
        elements: dict
        suboptions:
            name:
                description: Rule name (also the dict key in the VCO data model).
                required: true
                type: str
            state:
                description: C(present) creates/updates the rule; C(absent) deletes it.
                type: str
                choices: [present, absent]
                default: present
            match:
                description: Match criteria. Field names use VCO short aliases.
                type: dict
                suboptions:
                    dip:
                        description: Destination IP. Use C(any) for wildcard.
                        type: str
                        default: "any"
                    dsm:
                        description: Destination subnet mask.
                        type: str
                        default: "255.255.255.255"
                    sip:
                        description: Source IP. Use C(any) for wildcard.
                        type: str
                        default: "any"
                    ssm:
                        description: Source subnet mask.
                        type: str
                        default: "255.255.255.255"
                    proto:
                        description: IP protocol number (-1 for any).
                        type: int
                        default: -1
                    sport_low:
                        description: Source port range low (-1 for any).
                        type: int
                        default: -1
                    sport_high:
                        description: Source port range high (-1 for any).
                        type: int
                        default: -1
                    dport_low:
                        description: Destination port range low (-1 for any).
                        type: int
                        default: -1
                    dport_high:
                        description: Destination port range high (-1 for any).
                        type: int
                        default: -1
                    appid:
                        description: VCO application id (-1 for any).
                        type: int
                        default: -1
                    classid:
                        description: VCO application class id (-1 for any).
                        type: int
                        default: -1
                    dscp:
                        description: DSCP value (-1 for any).
                        type: int
                        default: -1
                    svlan:
                        description: Source VLAN id (-1 for any).
                        type: int
                        default: -1
                    dvlan:
                        description: Destination VLAN id (-1 for any).
                        type: int
                        default: -1
            action:
                description: Action portion of the rule.
                type: dict
                suboptions:
                    route_type:
                        description:
                            - One of C(edge2Edge), C(edge2DataCenter), C(edge2Cloud), C(edge2Any).
                            - C(edge2Any) fans the route action across all three route-action
                              blocks; the cloud leg overrides C(route_policy) to C(gateway) when
                              C(route_policy=auto).
                        type: str
                        default: "edge2Any"
                    route_policy:
                        description:
                            - C(auto) lets VCO pick; C(gateway) forces traffic through the
                              gateway (required for the cloud route action under C(edge2Any)).
                        type: str
                        choices: [auto, gateway]
                        default: "auto"
                    link_policy:
                        description: One of C(auto), C(fixed), C(preferred), C(available), C(required).
                        type: str
                        default: "auto"
                    service_group:
                        description: One of C(ALL), C(PUBLIC_WIRED), C(PRIVATE_WIRED), etc.
                        type: str
                        default: "ALL"
                    service_class:
                        description: QoS service class (mapped to C(QoS.type)). E.g. C(transactional), C(realtime), C(bulk).
                        type: str
                        default: "transactional"
                    wan_link:
                        description: Specific WAN link name, or C(auto).
                        type: str
                        default: "auto"
                    interface:
                        description: Specific interface name, or C(auto).
                        type: str
                        default: "auto"
                    qos:
                        description: QoS scheduler priority (applied to both rx and tx schedulers).
                        type: dict
                        suboptions:
                            priority:
                                description: Scheduler priority.
                                type: str
                                choices: [high, normal, low]
                                default: "normal"
                    sla:
                        description: SLA thresholds (latency/jitter/loss).
                        type: dict
                        suboptions:
                            latency_ms:
                                description: Maximum latency in milliseconds (string).
                                type: str
                                default: "0"
                            jitter_ms:
                                description: Maximum jitter in milliseconds (string).
                                type: str
                                default: "0"
                            loss_pct:
                                description: Maximum packet loss percentage (string).
                                type: str
                                default: "0.0"
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
# Configure BGP on the Global Segment
- name: BGP on Global Segment
  velocloud.api.edge_segment:
    vco_host: vco.example.com
    api_token: "{{ vco_api_token }}"
    edge: BRANCH-01
    segment_id: Global Segment
    bgp:
      asn: "64010"
      connected_routes: true
      neighbors:
        - neighbor_ip: 172.24.10.2
          neighbor_as: "64011"

# Configure static routes on the Global Segment using cidr shorthand
- name: Static routes on Global Segment
  velocloud.api.edge_segment:
    vco_host: vco.example.com
    api_token: "{{ vco_api_token }}"
    edge: BRANCH-01
    segment_id: Global Segment
    routes:
      static:
        - cidr: 10.99.0.0/24
          gateway: 172.24.10.2
          advertise: true

# Configure both BGP and routes on the same segment in one task
- name: BGP + routes on Demo-Segment
  velocloud.api.edge_segment:
    vco_host: vco.example.com
    api_token: "{{ vco_api_token }}"
    edge: BRANCH-01
    segment_id: Demo-Segment
    bgp:
      asn: "64010"
      neighbors:
        - neighbor_ip: 172.24.9.2
          neighbor_as: "64011"
    routes:
      static:
        - cidr: 192.168.100.0/24
          gateway: 172.24.9.2
          advertise: true

# Loop over segment_config list from host_vars
- name: Configure per-segment settings (BGP + routes)
  velocloud.api.edge_segment:
    vco_host: "{{ vco_host }}"
    api_token: "{{ vco_api_token }}"
    enterprise_id: "{{ enterprise_id }}"
    verify_ssl: false
    edge: "{{ inventory_hostname }}"
    segment_id: "{{ item.segment_id }}"
    bgp: "{{ item.bgp | default(omit) }}"
    routes: "{{ item.routes | default(omit) }}"
  loop: "{{ velocloud_edge_config.segment_config | default([]) }}"
  loop_control:
    label: "{{ item.segment_id }}"

- name: Pin SAP traffic to MPLS with an SLA
  velocloud.api.edge_segment:
    vco_host: vco.example.com
    api_token: "{{ vco_api_token }}"
    edge: BRANCH-01
    segment_id: Global Segment
    bizpolicy:
      - name: SAP-MPLS-Preferred
        match:
          dip: "10.200.0.0"
          dsm: "255.255.0.0"
        action:
          route_type: edge2DataCenter
          service_class: transactional
          route_policy: auto
          link_policy: preferred
          service_group: PRIVATE_WIRED
          qos:
            priority: high
          sla:
            latency_ms: "50"
            jitter_ms: "20"
            loss_pct: "0.5"

# Match by application id and remove a stale rule in the same task
- name: Office365-direct + remove old rule
  velocloud.api.edge_segment:
    vco_host: vco.example.com
    api_token: "{{ vco_api_token }}"
    edge: BRANCH-01
    segment_id: Global Segment
    bizpolicy:
      - name: Office365-Direct
        match:
          appid: 1411
        action:
          route_type: edge2Cloud
          service_class: realtime
          link_policy: fixed
          service_group: PUBLIC_WIRED
      - name: Old-Test-Rule
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
        BgpInput,
        BgpNeighborInput,
        BizPolicyActionInput,
        BizPolicyMatchInput,
        BizPolicyQosInput,
        BizPolicyRuleInput,
        BizPolicySlaInput,
        RoutesInput,
        StaticRouteInput,
        apply_bgp,
        apply_bizpolicy,
        apply_routes,
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


def _build_bgp_spec(bgp_params: dict, segment_id: str) -> BgpInput:
    neighbors = [BgpNeighborInput(**n) for n in (bgp_params.get("neighbors") or [])]
    kwargs = {k: v for k, v in bgp_params.items() if k != "neighbors"}
    kwargs["segment_id"] = segment_id
    kwargs["neighbors"] = neighbors
    return BgpInput(**kwargs)


def _build_routes_spec(routes_params: dict, segment_id: str) -> RoutesInput:
    static = [StaticRouteInput(**r) for r in (routes_params.get("static") or [])]
    static_v6 = [StaticRouteInput(**r) for r in (routes_params.get("static_v6") or [])]
    return RoutesInput(segment_id=segment_id, static=static, static_v6=static_v6)


def _build_bizpolicy_spec(raw: dict) -> BizPolicyRuleInput:
    rule_data = dict(raw)
    match_raw = rule_data.pop("match", None) or {}
    action_raw = dict(rule_data.pop("action", None) or {})
    sla_raw = action_raw.pop("sla", None)
    qos_raw = action_raw.pop("qos", None)

    # Drop None-valued keys so Pydantic uses class defaults rather than
    # rejecting Ansible's explicit nulls for unset suboptions.
    match_kwargs = {k: v for k, v in match_raw.items() if v is not None}
    action_kwargs = {k: v for k, v in action_raw.items() if v is not None}

    rule_data["match"] = BizPolicyMatchInput(**match_kwargs)
    action = BizPolicyActionInput(**action_kwargs)
    if qos_raw:
        qos_kwargs = {k: v for k, v in qos_raw.items() if v is not None}
        if qos_kwargs:
            action.qos = BizPolicyQosInput(**qos_kwargs)
    if sla_raw:
        sla_kwargs = {k: v for k, v in sla_raw.items() if v is not None}
        action.sla = BizPolicySlaInput(**sla_kwargs)
    rule_data["action"] = action
    return BizPolicyRuleInput(**rule_data)


async def _async_main(module: AnsibleModule, params: dict) -> dict:
    enterprise_id = resolve_enterprise_id(params)
    segment_id = params["segment_id"]

    client = build_client(params)
    async with client:
        edge_id = await _resolve_edge(
            client, enterprise_id, params.get("edge"), params.get("edge_id")
        )

        pipeline = ConfigPipeline(client)
        cfg_state = await pipeline.load(edge_id, enterprise_id=enterprise_id)

        if params.get("bgp"):
            bgp_spec = _build_bgp_spec(params["bgp"], segment_id)
            cfg_state = await apply_bgp(pipeline, cfg_state, bgp_spec)

        if params.get("routes"):
            routes_spec = _build_routes_spec(params["routes"], segment_id)
            cfg_state = await apply_routes(pipeline, cfg_state, routes_spec)

        if params.get("bizpolicy"):
            rule_specs = [_build_bizpolicy_spec(r) for r in params["bizpolicy"]]
            cfg_state = await apply_bizpolicy(
                pipeline, cfg_state, segment_id, rule_specs
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
        segment_id=dict(type="str", default="Global Segment"),
        bgp=dict(
            type="dict",
            options=dict(
                enabled=dict(type="bool", default=True),
                asn=dict(type="str", required=True),
                connected_routes=dict(type="bool", default=True),
                overlay_prefix=dict(type="bool", default=False),
                propagate_uplink=dict(type="bool", default=False),
                router_id=dict(type="str"),
                keepalive=dict(type="str", default="60"),
                holdtime=dict(type="str", default="180"),
                enable_graceful_restart=dict(type="bool", default=False),
                neighbors=dict(type="list", elements="dict", default=[]),
            ),
        ),
        routes=dict(
            type="dict",
            options=dict(
                static=dict(type="list", elements="dict", default=[]),
                static_v6=dict(type="list", elements="dict", default=[]),
            ),
        ),
        bizpolicy=dict(
            type="list",
            elements="dict",
            options=dict(
                name=dict(type="str", required=True),
                state=dict(
                    type="str", choices=["present", "absent"], default="present"
                ),
                match=dict(
                    type="dict",
                    options=dict(
                        dip=dict(type="str", default="any"),
                        dsm=dict(type="str", default="255.255.255.255"),
                        sip=dict(type="str", default="any"),
                        ssm=dict(type="str", default="255.255.255.255"),
                        proto=dict(type="int", default=-1),
                        sport_low=dict(type="int", default=-1),
                        sport_high=dict(type="int", default=-1),
                        dport_low=dict(type="int", default=-1),
                        dport_high=dict(type="int", default=-1),
                        appid=dict(type="int", default=-1),
                        classid=dict(type="int", default=-1),
                        dscp=dict(type="int", default=-1),
                        svlan=dict(type="int", default=-1),
                        dvlan=dict(type="int", default=-1),
                    ),
                ),
                action=dict(
                    type="dict",
                    options=dict(
                        route_type=dict(type="str", default="edge2Any"),
                        route_policy=dict(
                            type="str",
                            choices=["auto", "gateway"],
                            default="auto",
                        ),
                        link_policy=dict(type="str", default="auto"),
                        service_group=dict(type="str", default="ALL"),
                        service_class=dict(type="str", default="transactional"),
                        wan_link=dict(type="str", default="auto"),
                        interface=dict(type="str", default="auto"),
                        qos=dict(
                            type="dict",
                            options=dict(
                                priority=dict(
                                    type="str",
                                    choices=["high", "normal", "low"],
                                    default="normal",
                                ),
                            ),
                        ),
                        sla=dict(
                            type="dict",
                            options=dict(
                                latency_ms=dict(type="str", default="0"),
                                jitter_ms=dict(type="str", default="0"),
                                loss_pct=dict(type="str", default="0.0"),
                            ),
                        ),
                    ),
                ),
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
        ("bgp", "routes", "bizpolicy"),
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
        module.exit_json(**result)
    except Exception as exc:
        module.fail_json(msg=str(exc))


if __name__ == "__main__":
    main()
