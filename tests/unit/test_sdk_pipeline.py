import asyncio
from types import SimpleNamespace

import pytest

from ansible_collections.velocloud.api.plugins.module_utils.topology import (
    prefix_to_netmask,
    split_cidr,
)
from ansible_collections.velocloud.api.plugins.modules import edge_bgp
from ansible_collections.velocloud.api.plugins.modules import edge_common
from ansible_collections.velocloud.api.plugins.modules import edge_lan
from ansible_collections.velocloud.api.plugins.modules import edge_loopback
from ansible_collections.velocloud.api.plugins.modules import edge_segment
from ansible_collections.velocloud.api.plugins.modules import edge_wan


class FakeModule:
    def __init__(self, check_mode=False):
        self.check_mode = check_mode
        self.warnings = []

    def warn(self, msg):
        self.warnings.append(msg)


class FakeEdge:
    def __init__(self, name="BRANCH", id_=7):
        self.name = name
        self.id_ = id_


class FakeClient:
    def __init__(self, edges=None):
        self.edges = list(edges) if edges is not None else [FakeEdge()]

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get_enterprise_edges(self, req):
        return list(self.edges)


class FakePipeline:
    def __init__(self, updated=None, errors=None):
        self.loads = []
        self.saves = []
        self.updated = updated if updated is not None else ["deviceSettings"]
        self.errors = errors or []

    async def load(self, edge_id, enterprise_id=None):
        self.loads.append((edge_id, enterprise_id))
        return {"edge_id": edge_id}

    async def save(self, state, dry_run=False, validate=True):
        self.saves.append({"dry_run": dry_run, "validate": validate, "state": state})
        return SimpleNamespace(
            validation_errors=self.errors,
            modules_updated=[] if dry_run else self.updated,
            modules_inserted=[],
        )


async def _passthrough(pipeline, state, *args, **kwargs):
    return state


def _sdk_params(**kwargs):
    data = dict(
        vco_host="vco.example.com",
        api_token="token",
        enterprise_id=1,
        verify_ssl=True,
        edge="BRANCH",
        validate=True,
    )
    data.update(kwargs)
    return data


def _install(monkeypatch, module, pipeline, *apply_names):
    monkeypatch.setattr(module, "build_client", lambda params: FakeClient())
    monkeypatch.setattr(module, "ConfigPipeline", lambda client: pipeline)
    for name in apply_names:
        monkeypatch.setattr(module, name, _passthrough)


def test_cidr_helpers():
    assert split_cidr("192.0.2.0/24") == ("192.0.2.0", 24)
    assert prefix_to_netmask(24) == "255.255.255.0"


@pytest.mark.parametrize(
    "module,apply_names,params",
    [
        (
            edge_bgp,
            ("apply_bgp",),
            _sdk_params(
                segment_id="Global Segment",
                enabled=True,
                asn="65000",
                connected_routes=True,
                overlay_prefix=False,
                propagate_uplink=False,
                keepalive="60",
                holdtime="180",
                enable_graceful_restart=False,
                neighbors=[],
            ),
        ),
        (
            edge_lan,
            ("apply_routed_interfaces", "apply_switched_interfaces", "apply_vlans"),
            _sdk_params(routed_interfaces=[], switched_interfaces=[], vlans=[]),
        ),
        (
            edge_wan,
            ("apply_wan_links", "apply_wan_link_settings"),
            _sdk_params(wan_links=[], wan_link_settings=[]),
        ),
        (
            edge_common,
            ("apply_ha",),
            _sdk_params(ha={"enabled": True, "interface": "GE1"}),
        ),
        (
            edge_loopback,
            ("apply_loopback_interfaces",),
            _sdk_params(loopback_interfaces=[{"name": "LO1", "cidr_ip": "192.0.2.1"}]),
        ),
        (
            edge_segment,
            ("apply_bgp", "apply_routes", "apply_bizpolicy"),
            _sdk_params(
                segment_id="Global Segment",
                bgp={"asn": "65000", "enabled": True},
                routes=None,
                bizpolicy=None,
            ),
        ),
    ],
)
def test_edge_patch_modules_save_and_check_mode(
    monkeypatch, module, apply_names, params
):
    pipeline = FakePipeline()
    _install(monkeypatch, module, pipeline, *apply_names)
    result = asyncio.run(module._async_main(FakeModule(), params))
    assert result["changed"]
    assert result["modules_updated"] == ["deviceSettings"]
    assert pipeline.loads == [(7, 1)]
    assert pipeline.saves[0]["dry_run"] is False

    check_pipeline = FakePipeline()
    _install(monkeypatch, module, check_pipeline, *apply_names)
    check = asyncio.run(module._async_main(FakeModule(check_mode=True), params))
    assert not check["changed"]
    assert check_pipeline.saves[0]["dry_run"] is True


def test_edge_bgp_missing_edge_and_validation_errors(monkeypatch):
    pipeline = FakePipeline()
    monkeypatch.setattr(edge_bgp, "ConfigPipeline", lambda client: pipeline)
    monkeypatch.setattr(edge_bgp, "apply_bgp", _passthrough)
    monkeypatch.setattr(edge_bgp, "build_client", lambda params: FakeClient(edges=[]))
    params = _sdk_params(
        segment_id="Global Segment",
        enabled=True,
        asn="65000",
        connected_routes=True,
        overlay_prefix=False,
        propagate_uplink=False,
        keepalive="60",
        holdtime="180",
        enable_graceful_restart=False,
        neighbors=[],
    )
    with pytest.raises(ValueError, match="not found"):
        asyncio.run(edge_bgp._async_main(FakeModule(), params))

    failing = FakePipeline(errors=["invalid bgp"])
    monkeypatch.setattr(edge_bgp, "build_client", lambda params: FakeClient())
    monkeypatch.setattr(edge_bgp, "ConfigPipeline", lambda client: failing)
    with pytest.raises(RuntimeError, match="Validation failed"):
        asyncio.run(edge_bgp._async_main(FakeModule(), params))
