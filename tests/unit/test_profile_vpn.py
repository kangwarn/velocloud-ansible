import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

from pyvelo.client.enums.configuration import ConfigurationModuleType
from pyvelo.client.enums.enterprise import NetworkSegmentType
from pyvelo.client.models.configuration.common import SegmentMetadata
from pyvelo.client.models.configuration.device_settings.lan import LanSettings
from pyvelo.client.models.configuration.device_settings.refs import (
    DeviceSettingsRefs,
    DeviceSettingsSegmentRef,
    DeviceSettingsVpnEdgeHubRef,
)
from pyvelo.client.models.configuration.device_settings.root import DeviceSettingsData
from pyvelo.client.models.configuration.device_settings.segment import DeviceSegment
from pyvelo.client.schemas.configuration import (
    DeviceSettingsConfigurationModule,
    EnterpriseConfigurationProfile,
)
from pyvelo.client.schemas.edge import EnableEdgeHub
from pyvelo.config.resolver import ResolverContext
from pyvelo_intent.config.state import ConfigState

from ansible_collections.velocloud.api.plugins.module_utils.topology import (
    DynamicVpnInput,
    EdgeToEdgeDetailInput,
    EdgeToEdgeHubInput,
    VpnHubInput,
    VpnInput,
    apply_vpn,
    current_hub_roles,
    desired_hub_roles,
    diff_hub_roles,
    reject_hub_clusters,
    resolve_vpn_hubs,
    sync_profile_vpn_hubs,
)
from ansible_collections.velocloud.api.plugins.modules import profile_vpn

_TS = datetime(2024, 1, 1, tzinfo=UTC)
_SEG_LID = UUID("02a8e4f9-5e6f-4d1e-8476-76cf83e16d43")
_HUB1_LID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1")
_HUB2_LID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa2")
_SVC1_LID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb1")
_SVC2_LID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb2")


class FakeEdge:
    def __init__(self, name, id_, logical_id):
        self.name = name
        self.id_ = id_
        self.logical_id = logical_id


class FakeService:
    def __init__(self, id_, logical_id, name, edge_id):
        self.id_ = id_
        self.logical_id = logical_id
        self.name = name
        self.edge_id = edge_id


class FakeClient:
    def __init__(self, edges=None, profiles=None):
        self.edges = list(edges or [])
        self.profiles = list(
            profiles or [SimpleNamespace(name="Branch-Profile", id_=10)]
        )
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get_enterprise_configurations(self, req):
        return list(self.profiles)

    async def get_enterprise_edges(self, req):
        return list(self.edges)

    async def enable_edge_hub(self, request):
        self.calls.append(("enable_hub", request.id_))
        lid = {4: _SVC1_LID, 5: _SVC2_LID}[request.id_]
        return FakeService(request.id_ + 100, lid, f"svc-{request.id_}", request.id_)

    async def enable_edge_backhaul(self, request):
        self.calls.append(("enable_backhaul", request.id_))
        return FakeService(
            request.id_ + 100, _SVC1_LID, f"svc-{request.id_}", request.id_
        )

    async def enable_edge_to_edge_bridge(self, request):
        self.calls.append(("enable_e2e", request.id_))
        return FakeService(
            request.id_ + 100, _SVC1_LID, f"svc-{request.id_}", request.id_
        )

    async def disable_edge_hub(self, request):
        self.calls.append(("disable_hub", request.id_))

    async def disable_edge_backhaul(self, request):
        self.calls.append(("disable_backhaul", request.id_))

    async def disable_edge_to_edge_bridge(self, request):
        self.calls.append(("disable_e2e", request.id_))


class RecordingPipeline:
    def __init__(self, state, updated=None, errors=None):
        self.state = state
        self.patches = []
        self.saves = []
        self.updated = updated if updated is not None else ["deviceSettings"]
        self.errors = errors or []

    async def load_profile(self, profile_id, enterprise_id=None):
        return self.state

    async def apply(self, state, module, patch):
        self.patches.append({"module": module, "patch": patch})
        return state

    async def save(self, state, dry_run=False, validate=True):
        self.saves.append({"dry_run": dry_run, "validate": validate})
        return SimpleNamespace(
            validation_errors=self.errors,
            modules_updated=[] if dry_run else self.updated,
            modules_inserted=[],
        )


class FakeModule:
    def __init__(self, check_mode=False):
        self.check_mode = check_mode


def _edges():
    return [
        FakeEdge("hub1", 4, _HUB1_LID),
        FakeEdge("hub2", 5, _HUB2_LID),
        FakeEdge("vce1a", 1, UUID("cccccccc-cccc-cccc-cccc-ccccccccccc1")),
    ]


def _branch_spec(**kwargs):
    data = dict(
        segment_id="Global Segment",
        enabled=True,
        edge_to_edge=True,
        edge_to_data_center=False,
        hub_edges=EdgeToEdgeHubInput(
            enabled=True,
            vpn_hubs=[
                VpnHubInput(
                    name="hub1", type="edgeHub", logical_id=str(_HUB1_LID), edge_id=4
                ),
                VpnHubInput(
                    name="hub2", type="edgeHub", logical_id=str(_HUB2_LID), edge_id=5
                ),
            ],
        ),
        edge_to_edge_detail=EdgeToEdgeDetailInput(
            encryption_protocol="AES_256_GCM",
            use_cloud_gateway=False,
            auto_select_vpn_hubs=False,
            dynamic=DynamicVpnInput(enabled=True, type="DIRECT", timeout=180),
            vpn_hubs=[
                VpnHubInput(
                    name="hub1", type="edgeHub", logical_id=str(_HUB1_LID), edge_id=4
                ),
                VpnHubInput(
                    name="hub2", type="edgeHub", logical_id=str(_HUB2_LID), edge_id=5
                ),
            ],
        ),
    )
    data.update(kwargs)
    return VpnInput(**data)


def _profile_state(vpn_hub_refs=None):
    global_meta = SegmentMetadata(
        name="Global Segment",
        segment_id=0,
        type_=NetworkSegmentType.REGULAR,
        segment_logical_id=_SEG_LID,
    )
    ds = DeviceSettingsConfigurationModule(
        name="deviceSettings",
        data=DeviceSettingsData(
            lan=LanSettings(),
            segments=[DeviceSegment(segment=global_meta)],
        ),
        created=_TS,
        modified=_TS,
        id_=67,
        type_=ConfigurationModuleType.ENTERPRISE,
        description=None,
        configuration_id=10,
        enterprise_logical_id=None,
        schema_version=None,
        version=None,
        metadata=None,
        refs=DeviceSettingsRefs(
            segment=DeviceSettingsSegmentRef(
                ref="deviceSettings:segment",
                object_="NETWORK_SEGMENT",
                type_=NetworkSegmentType.REGULAR,
                configuration_id=10,
                module_id=67,
                logical_id=_SEG_LID,
                enterprise_object_id=15,
                name="Global Segment",
            ),
            **({"vpn_edge_hub": vpn_hub_refs} if vpn_hub_refs is not None else {}),
        ),
    )
    profile = EnterpriseConfigurationProfile(
        name="Branch-Profile",
        id_=10,
        modules=[ds],
    )
    state = ConfigState(
        edge_config=None,
        profile_config=profile,
        target_type="profile",
        resolver_context=ResolverContext(),
    )
    state.take_snapshot()
    return state


def _hub_ref(edge_id, edge_lid, service_lid, roles):
    return DeviceSettingsVpnEdgeHubRef(
        ref="deviceSettings:vpn:edgeHub",
        object_="NETWORK_SERVICE",
        type_="edgeHub",
        configuration_id=10,
        module_id=67,
        logical_id=service_lid,
        enterprise_object_id=100 + edge_id,
        name=f"hub{edge_id}",
        segment_logical_id=_SEG_LID,
        segment_object_id=15,
        data={
            "logicalId": str(edge_lid),
            "roles": {
                "edgeHub": True,
                "backHaulEdge": "backhaul" in roles,
                "edgeToEdgeBridge": "e2e" in roles,
            },
        },
    )


def test_enable_edge_hub_request_uses_id():
    dumped = EnableEdgeHub(
        id_=4,
        configuration_id=10,
        module_id=67,
        segment_object_id=15,
        enterprise_id=1,
    ).model_dump(by_alias=True, exclude_unset=True)
    assert dumped["id"] == 4
    assert "edgeId" not in dumped


def test_reject_hub_clusters():
    spec = VpnInput(
        hub_edges=EdgeToEdgeHubInput(
            enabled=True,
            vpn_hubs=[VpnHubInput(name="cluster1", type="edgeHubCluster")],
        )
    )
    with pytest.raises(ValueError, match="not supported"):
        reject_hub_clusters(spec)


def test_resolve_vpn_hubs_by_name():
    resolved = resolve_vpn_hubs(_edges(), [VpnHubInput(name="hub1", type="edgeHub")])
    assert resolved[0].edge_id == 4
    assert resolved[0].logical_id == str(_HUB1_LID)


def test_resolve_vpn_hubs_missing_name():
    with pytest.raises(ValueError, match="not found"):
        resolve_vpn_hubs(_edges(), [VpnHubInput(name="missing", type="edgeHub")])


def test_desired_roles_branch_profile():
    roles = desired_hub_roles(_branch_spec())
    assert roles[4] == {"hub", "backhaul", "e2e"}
    assert roles[5] == {"hub", "backhaul", "e2e"}


def test_desired_roles_hub_profile_flags_only():
    spec = VpnInput(
        enabled=True,
        edge_to_edge=False,
        edge_to_data_center=False,
        segment_id="Global Segment",
    )
    assert desired_hub_roles(spec) == {}


def test_diff_hub_roles_first_enable():
    spec = _branch_spec()
    hubs = {4: spec.hub_edges.vpn_hubs[0], 5: spec.hub_edges.vpn_hubs[1]}
    diff = diff_hub_roles(desired_hub_roles(spec), {}, hubs)
    assert [h.edge_id for h in diff.enable_hub] == [4, 5]
    assert [h.edge_id for h in diff.enable_backhaul] == [4, 5]
    assert [h.edge_id for h in diff.enable_e2e] == [4, 5]
    assert diff.disable_hub == []


def test_diff_hub_roles_remove_one_hub():
    spec = _branch_spec(
        hub_edges=EdgeToEdgeHubInput(
            enabled=True,
            vpn_hubs=[
                VpnHubInput(
                    name="hub1", type="edgeHub", logical_id=str(_HUB1_LID), edge_id=4
                )
            ],
        ),
        edge_to_edge_detail=EdgeToEdgeDetailInput(
            use_cloud_gateway=False,
            vpn_hubs=[
                VpnHubInput(
                    name="hub1", type="edgeHub", logical_id=str(_HUB1_LID), edge_id=4
                )
            ],
        ),
    )
    current = {
        4: {"hub", "backhaul", "e2e"},
        5: {"hub", "backhaul", "e2e"},
    }
    hubs = {
        4: VpnHubInput(
            name="hub1", type="edgeHub", logical_id=str(_HUB1_LID), edge_id=4
        ),
        5: VpnHubInput(
            name="hub2", type="edgeHub", logical_id=str(_HUB2_LID), edge_id=5
        ),
    }
    diff = diff_hub_roles(desired_hub_roles(spec), current, hubs)
    assert [h.edge_id for h in diff.disable_hub] == [5]
    assert [h.edge_id for h in diff.disable_backhaul] == [5]
    assert [h.edge_id for h in diff.disable_e2e] == [5]


def test_apply_vpn_includes_backhaul_edges():
    pipeline = RecordingPipeline(_profile_state())
    asyncio.run(apply_vpn(pipeline, pipeline.state, _branch_spec()))
    vpn = pipeline.patches[0]["patch"]["segments"]["Global Segment"]["vpn"]
    assert vpn["enabled"] is True
    assert vpn["edgeToDataCenter"] is False
    assert {h["name"] for h in vpn["backHaulEdges"]} == {"hub1", "hub2"}
    assert {h["name"] for h in vpn["edgeToEdgeHub"]["vpnHubs"]} == {"hub1", "hub2"}
    assert {h["name"] for h in vpn["edgeToEdgeDetail"]["vpnHubs"]} == {"hub1", "hub2"}


def test_sync_enables_hubs_in_ui_order():
    state = _profile_state()
    client = FakeClient(edges=_edges())
    changed = asyncio.run(
        sync_profile_vpn_hubs(
            client,
            state,
            _branch_spec(),
            enterprise_id=1,
            edges=_edges(),
            check_mode=False,
        )
    )
    assert changed
    assert client.calls == [
        ("enable_hub", 4),
        ("enable_hub", 5),
        ("enable_backhaul", 4),
        ("enable_backhaul", 5),
        ("enable_e2e", 4),
        ("enable_e2e", 5),
    ]
    refs = state.profile_config.device_settings.refs.vpn_edge_hub
    assert len(refs) == 2
    assert {ref.enterprise_object_id for ref in refs} == {104, 105}
    assert refs[0].data["roles"]["backHaulEdge"] is True
    assert refs[0].data["roles"]["edgeToEdgeBridge"] is True


def test_sync_idempotent_when_refs_match():
    refs = [
        _hub_ref(4, _HUB1_LID, _SVC1_LID, {"hub", "backhaul", "e2e"}),
        _hub_ref(5, _HUB2_LID, _SVC2_LID, {"hub", "backhaul", "e2e"}),
    ]
    state = _profile_state(vpn_hub_refs=refs)
    current, _hubs = current_hub_roles(state, 15, _edges())
    assert current[4] == {"hub", "backhaul", "e2e"}
    client = FakeClient(edges=_edges())
    changed = asyncio.run(
        sync_profile_vpn_hubs(
            client,
            state,
            _branch_spec(),
            enterprise_id=1,
            edges=_edges(),
            check_mode=False,
        )
    )
    assert client.calls == []
    assert changed is False


def test_sync_check_mode_does_not_call_enable():
    client = FakeClient(edges=_edges())
    changed = asyncio.run(
        sync_profile_vpn_hubs(
            client,
            _profile_state(),
            _branch_spec(),
            enterprise_id=1,
            edges=_edges(),
            check_mode=True,
        )
    )
    assert changed
    assert client.calls == []


def test_sync_disables_removed_hub():
    refs = [
        _hub_ref(4, _HUB1_LID, _SVC1_LID, {"hub", "backhaul", "e2e"}),
        _hub_ref(5, _HUB2_LID, _SVC2_LID, {"hub", "backhaul", "e2e"}),
    ]
    state = _profile_state(vpn_hub_refs=refs)
    spec = _branch_spec(
        hub_edges=EdgeToEdgeHubInput(
            enabled=True,
            vpn_hubs=[
                VpnHubInput(
                    name="hub1", type="edgeHub", logical_id=str(_HUB1_LID), edge_id=4
                )
            ],
        ),
        edge_to_edge_detail=EdgeToEdgeDetailInput(
            use_cloud_gateway=False,
            vpn_hubs=[
                VpnHubInput(
                    name="hub1", type="edgeHub", logical_id=str(_HUB1_LID), edge_id=4
                )
            ],
        ),
    )
    client = FakeClient(edges=_edges())
    asyncio.run(
        sync_profile_vpn_hubs(
            client,
            state,
            spec,
            enterprise_id=1,
            edges=_edges(),
            check_mode=False,
        )
    )
    assert client.calls == [
        ("disable_backhaul", 5),
        ("disable_e2e", 5),
        ("disable_hub", 5),
    ]
    refs_after = state.profile_config.device_settings.refs.vpn_edge_hub
    assert len(refs_after) == 1
    assert refs_after[0].enterprise_object_id == 104


def test_sync_hub_profile_without_hubs_is_noop():
    client = FakeClient(edges=_edges())
    changed = asyncio.run(
        sync_profile_vpn_hubs(
            client,
            _profile_state(),
            VpnInput(enabled=True, segment_id="Global Segment"),
            enterprise_id=1,
            edges=_edges(),
            check_mode=False,
        )
    )
    assert changed is False
    assert client.calls == []


def _sdk_params(**kwargs):
    data = dict(
        vco_host="vco.example.com",
        api_token="token",
        enterprise_id=1,
        verify_ssl=True,
        profile="Branch-Profile",
        segment_id="Global Segment",
        enabled=True,
        edge_to_edge=True,
        edge_to_data_center=False,
        conditional_backhaul=False,
        validate=True,
        edge_to_edge_detail={
            "encryption_protocol": "AES_256_GCM",
            "use_cloud_gateway": False,
            "auto_select_vpn_hubs": False,
            "dynamic": {"enabled": True, "type": "DIRECT", "timeout": 180},
            "vpn_hubs": [{"name": "hub1", "type": "edgeHub"}],
        },
        hub_edges={
            "enabled": True,
            "vpn_hubs": [{"name": "hub1", "type": "edgeHub"}],
        },
    )
    data.update(kwargs)
    return data


def test_module_resolves_profile_and_saves(monkeypatch):
    state = _profile_state()
    pipeline = RecordingPipeline(state)
    client = FakeClient(edges=_edges())
    monkeypatch.setattr(profile_vpn, "build_client", lambda params: client)
    monkeypatch.setattr(profile_vpn, "ConfigPipeline", lambda c: pipeline)
    result = asyncio.run(profile_vpn._async_main(FakeModule(), _sdk_params()))
    assert result["changed"]
    assert result["hubs_changed"]
    assert ("enable_hub", 4) in client.calls
    assert pipeline.saves[0]["dry_run"] is False
    vpn = pipeline.patches[0]["patch"]["segments"]["Global Segment"]["vpn"]
    assert vpn["backHaulEdges"][0]["name"] == "hub1"


def test_module_missing_hub_name(monkeypatch):
    pipeline = RecordingPipeline(_profile_state())
    client = FakeClient(edges=_edges())
    monkeypatch.setattr(profile_vpn, "build_client", lambda params: client)
    monkeypatch.setattr(profile_vpn, "ConfigPipeline", lambda c: pipeline)
    params = _sdk_params(
        hub_edges={"enabled": True, "vpn_hubs": [{"name": "nope", "type": "edgeHub"}]},
        edge_to_edge_detail={"vpn_hubs": []},
    )
    with pytest.raises(ValueError, match="not found"):
        asyncio.run(profile_vpn._async_main(FakeModule(), params))


def test_module_check_mode_skips_enable(monkeypatch):
    pipeline = RecordingPipeline(_profile_state())
    client = FakeClient(edges=_edges())
    monkeypatch.setattr(profile_vpn, "build_client", lambda params: client)
    monkeypatch.setattr(profile_vpn, "ConfigPipeline", lambda c: pipeline)
    result = asyncio.run(
        profile_vpn._async_main(FakeModule(check_mode=True), _sdk_params())
    )
    assert result["changed"]
    assert client.calls == []
    assert pipeline.saves[0]["dry_run"] is True
