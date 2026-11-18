#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Kangwarn Chinthammit
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: profile_vpn

short_description: Configure CloudVPN settings on a VeloCloud profile for a single segment

version_added: "0.1.0"

description:
    - Patches C(device_settings.segments.<segment>.vpn) on a configuration profile.
    - VPN topology is C(ProfileOnly) in pyvelo — this module always operates on a profile,
      never on an edge.
    - Hub edges are resolved by name to numeric id and logical id from the enterprise
      edge list. The module then designates those edges as hubs on the profile
      (edge hub, backhaul, and edge-to-edge bridge roles) and writes
      C(deviceSettings:vpn:edgeHub) refs before saving VPN data.
    - When C(hub_edges) are enabled, those hubs are also designated as backhaul
      hubs. C(edge_to_data_center) is Branch-to-Site (Non-SD-WAN destinations)
      and requires selected sites; leave it false unless sites are configured.
    - Hub clusters (C(type=edgeHubCluster)) are not supported yet.
    - Drift detection is native via pyvelo C(ConfigPipeline.save).
    - Loop the task to configure multiple segments on the same profile.

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
        description: VCO username (used with password).
        required: false
        type: str
    password:
        description: VCO password (used with username).
        required: false
        type: str
    enterprise_id:
        description: Enterprise ID. Auto-resolved from JWT for token auth.
        required: false
        type: int
    verify_ssl:
        description: Verify the VCO TLS certificate.
        required: false
        type: bool
        default: true
    profile:
        description: Configuration profile name.
        required: true
        type: str
    segment_id:
        description: Segment name (string, not a numeric ID).
        required: false
        type: str
        default: Global Segment
    enabled:
        description: Whether CloudVPN is enabled on this segment.
        required: false
        type: bool
        default: true
    edge_to_edge:
        description: Enable edge-to-edge VPN.
        required: false
        type: bool
        default: false
    edge_to_data_center:
        description: >
            Enable Branch-to-Site VPN (Non-SD-WAN destinations). VCO rejects
            this unless site refs are selected. Hub backhaul is controlled by
            C(hub_edges), not this flag.
        required: false
        type: bool
        default: false
    conditional_backhaul:
        description: Enable conditional backhaul.
        required: false
        type: bool
        default: false
    edge_to_edge_detail:
        description: >
            Edge-to-edge VPN detail configuration. Supported sub-keys:
            C(encryption_protocol) (GROUP_IPSEC | AES_128_GCM | AES_256_GCM, default GROUP_IPSEC),
            C(use_cloud_gateway) (bool, default true),
            C(auto_select_vpn_hubs) (bool, default false),
            C(dynamic) (dict with C(enabled) bool, C(type) DIRECT|RELAY, C(timeout) int),
            C(vpn_hubs) (list of dicts with C(name) str and C(type) edgeHub;
            logical_id and edge id are resolved automatically by edge name).
        required: false
        type: dict
        default: {}
    hub_edges:
        description: >
            Hub-edges (edgeToEdgeHub) configuration. Supported sub-keys:
            C(enabled) (bool, default false),
            C(vpn_hubs) (list of dicts with C(name) str and C(type) edgeHub;
            logical_id and edge id are resolved automatically by edge name).
        required: false
        type: dict
        default: {}
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
- name: Enable edge-to-edge VPN with AES-256 encryption
  velocloud.api.profile_vpn:
    vco_host: vco.example.com
    api_token: "{{ vco_api_token }}"
    profile: Branch-Profile
    segment_id: Global Segment
    enabled: true
    edge_to_edge: true
    edge_to_edge_detail:
      encryption_protocol: AES_256_GCM
      use_cloud_gateway: true
      dynamic:
        enabled: true
        type: DIRECT

- name: Enable VPN with static hub list (ids resolved by name)
  velocloud.api.profile_vpn:
    vco_host: vco.example.com
    api_token: "{{ vco_api_token }}"
    profile: Branch-Profile
    segment_id: Global Segment
    enabled: true
    edge_to_edge: true
    edge_to_data_center: false
    edge_to_edge_detail:
      encryption_protocol: AES_256_GCM
      use_cloud_gateway: false
      auto_select_vpn_hubs: false
      vpn_hubs:
        - name: hub1
          type: edgeHub
        - name: hub2
          type: edgeHub
    hub_edges:
      enabled: true
      vpn_hubs:
        - name: hub1
          type: edgeHub
        - name: hub2
          type: edgeHub

- name: Disable CloudVPN on a segment
  velocloud.api.profile_vpn:
    vco_host: vco.example.com
    api_token: "{{ vco_api_token }}"
    profile: Branch-Profile
    segment_id: Global Segment
    enabled: false
"""

RETURN = r"""
changed:
    description: True if VPN data or hub designations changed.
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
hubs_changed:
    description: True if hub enable/disable APIs or vpn edgeHub refs changed.
    type: bool
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
    from ansible_collections.velocloud.api.plugins.module_utils.topology import (
        DynamicVpnInput,
        EdgeToEdgeDetailInput,
        EdgeToEdgeHubInput,
        VpnHubInput,
        VpnInput,
        apply_vpn,
        resolve_spec_hubs,
        sync_profile_vpn_hubs,
        vpn_hubs_need_resolution,
    )
    from pyvelo.client.schemas.enterprise import GetEnterpriseEdges
    from pyvelo.client.schemas.profiles import GetEnterpriseConfigurations
    from pyvelo_intent.config.pipeline import ConfigPipeline

    HAS_PYVELO = True
    PYVELO_IMPORT_ERROR = None
except ImportError as e:
    HAS_PYVELO = False
    PYVELO_IMPORT_ERROR = str(e)


async def _resolve_profile(client, enterprise_id, profile_name):
    profiles = await client.get_enterprise_configurations(
        GetEnterpriseConfigurations(enterprise_id=enterprise_id)
    )
    match = next((p for p in profiles if p.name == profile_name), None)
    if match is None:
        available = ", ".join(p.name for p in profiles if p.name)
        raise ValueError(
            f"Profile '{profile_name}' not found in enterprise {enterprise_id}. "
            f"Available: {available}"
        )
    return match.id_


def _build_vpn_spec(params):
    detail_raw = params.get("edge_to_edge_detail") or {}
    hub_edges_raw = params.get("hub_edges") or {}

    detail = None
    if detail_raw:
        dynamic_raw = detail_raw.get("dynamic")
        dynamic = DynamicVpnInput(**dynamic_raw) if dynamic_raw else None
        raw_hubs = detail_raw.get("vpn_hubs") or []
        detail = EdgeToEdgeDetailInput(
            encryption_protocol=detail_raw.get("encryption_protocol", "GROUP_IPSEC"),
            use_cloud_gateway=detail_raw.get("use_cloud_gateway", True),
            auto_select_vpn_hubs=detail_raw.get("auto_select_vpn_hubs", False),
            dynamic=dynamic,
            vpn_hubs=[VpnHubInput(**h) for h in raw_hubs],
        )

    hub_edges = None
    if hub_edges_raw:
        raw_hubs = hub_edges_raw.get("vpn_hubs") or []
        hub_edges = EdgeToEdgeHubInput(
            enabled=hub_edges_raw.get("enabled", False),
            vpn_hubs=[VpnHubInput(**h) for h in raw_hubs],
        )

    return VpnInput(
        segment_id=params["segment_id"],
        enabled=params["enabled"],
        edge_to_edge=params["edge_to_edge"],
        edge_to_data_center=params["edge_to_data_center"],
        conditional_backhaul=params["conditional_backhaul"],
        edge_to_edge_detail=detail,
        hub_edges=hub_edges,
    )


async def _async_main(module, params):
    enterprise_id = resolve_enterprise_id(params)
    vpn_spec = _build_vpn_spec(params)

    client = build_client(params)
    async with client:
        profile_id = await _resolve_profile(client, enterprise_id, params["profile"])
        edges = await client.get_enterprise_edges(
            GetEnterpriseEdges(enterprise_id=enterprise_id)
        )
        if vpn_hubs_need_resolution(vpn_spec):
            vpn_spec = resolve_spec_hubs(vpn_spec, edges)

        pipeline = ConfigPipeline(client)
        cfg_state = await pipeline.load_profile(profile_id, enterprise_id=enterprise_id)
        hubs_changed = await sync_profile_vpn_hubs(
            client,
            cfg_state,
            vpn_spec,
            enterprise_id=enterprise_id,
            edges=edges,
            check_mode=module.check_mode,
        )
        cfg_state = await apply_vpn(pipeline, cfg_state, vpn_spec)

        result = await pipeline.save(
            cfg_state, dry_run=module.check_mode, validate=params["validate"]
        )

        validation_errors = getattr(result, "validation_errors", None) or []
        if validation_errors:
            raise RuntimeError(f"Validation failed: {validation_errors}")

        modules_updated = [str(m) for m in (result.modules_updated or [])]
        modules_inserted = [str(m) for m in (result.modules_inserted or [])]
        return {
            "changed": bool(modules_updated)
            or bool(modules_inserted)
            or bool(hubs_changed),
            "modules_updated": modules_updated,
            "modules_inserted": modules_inserted,
            "hubs_changed": bool(hubs_changed),
        }


def main():
    argspec = common_argspec()
    argspec.update(
        profile=dict(type="str", required=True),
        segment_id=dict(type="str", default="Global Segment"),
        enabled=dict(type="bool", default=True),
        edge_to_edge=dict(type="bool", default=False),
        edge_to_data_center=dict(type="bool", default=False),
        conditional_backhaul=dict(type="bool", default=False),
        edge_to_edge_detail=dict(type="dict", default={}),
        hub_edges=dict(type="dict", default={}),
        validate=dict(type="bool", default=True),
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
            msg=f"velocloud.api.profile_vpn failed: {type(e).__name__}: {e}",
            exception=traceback.format_exc(),
        )

    module.exit_json(**result)


if __name__ == "__main__":
    main()
