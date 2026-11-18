import asyncio
from types import SimpleNamespace

from ansible_collections.velocloud.api.plugins.modules import edge as edge_mod
from ansible_collections.velocloud.api.plugins.modules import profile as profile_mod
from ansible_collections.velocloud.api.plugins.modules import segment as segment_mod


class FakeModule:
    def __init__(self, check_mode=False):
        self.check_mode = check_mode
        self.warnings = []

    def warn(self, msg):
        self.warnings.append(msg)


class FakeSegment:
    def __init__(
        self,
        name,
        id_=11,
        logical_id="seg-log",
        type_="REGULAR",
        description="",
        segment_id=1,
        delegate_to_enterprise=True,
        delegate_to_enterprise_proxy=True,
    ):
        self.id_ = id_
        self.logical_id = logical_id
        self.name = name
        self.type_ = type_
        self.description = description
        self.data = SimpleNamespace(
            segment_id=segment_id,
            delegate_to_enterprise=delegate_to_enterprise,
            delegate_to_enterprise_proxy=delegate_to_enterprise_proxy,
        )


class FakeProfile:
    def __init__(self, name, id_=21, description=""):
        self.id_ = id_
        self.name = name
        self.description = description


class FakeEdge:
    def __init__(
        self,
        name,
        id_=31,
        configuration_id=21,
        model_number="virtual",
        edge_license_id=520,
        activation_key="act-key",
    ):
        self.id_ = id_
        self.name = name
        self.configuration_id = configuration_id
        self.model_number = model_number
        self.edge_license_id = edge_license_id
        self.activation_key = activation_key


class FakeClient:
    def __init__(self, segments=None, profiles=None, edges=None):
        self.segments = list(segments or [])
        self.profiles = list(profiles or [])
        self.edges = list(edges or [])
        self.writes = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get_enterprise_network_segments(self, req):
        return list(self.segments)

    async def delete_enterprise_network_segment(self, req):
        self.writes.append(("delete_segment", req.id_))
        self.segments = [item for item in self.segments if item.id_ != req.id_]

    async def insert_enterprise_network_segment(self, req):
        self.writes.append(("insert_segment", req.name))
        created = FakeSegment(
            name=req.name,
            id_=12,
            type_=req.type_,
            description=req.description,
            segment_id=req.data.segment_id,
            delegate_to_enterprise=req.data.delegate_to_enterprise,
            delegate_to_enterprise_proxy=req.data.delegate_to_enterprise_proxy,
        )
        self.segments.append(created)
        return created

    async def get_enterprise_configurations(self, req):
        return list(self.profiles)

    async def delete_enterprise_profile(self, req):
        self.writes.append(("delete_profile", req.id_))
        self.profiles = [item for item in self.profiles if item.id_ != req.id_]

    async def create_enterprise_profile(self, req):
        self.writes.append(("create_profile", req.name))
        created = FakeProfile(name=req.name, id_=22, description=req.description)
        self.profiles.append(created)
        return created

    async def get_enterprise_edges(self, req):
        return list(self.edges)

    async def delete_edge(self, req):
        self.writes.append(("delete_edge", req.id_))
        self.edges = [item for item in self.edges if item.id_ != req.id_]

    async def create_edge(self, req):
        self.writes.append(("create_edge", req.name))
        created = FakeEdge(
            name=req.name,
            id_=32,
            configuration_id=req.configuration_id,
            model_number=req.model_number,
            edge_license_id=req.edge_license_id,
        )
        self.edges.append(created)
        return created


def _params(**kwargs):
    data = dict(
        vco_host="vco.example.com",
        api_token="token",
        enterprise_id=1,
        verify_ssl=True,
        state="present",
        force=False,
        description="",
    )
    data.update(kwargs)
    return data


def _run(module_mod, client, params, check_mode=False, monkeypatch=None):
    monkeypatch.setattr(module_mod, "build_client", lambda _params: client)
    return asyncio.run(module_mod._async_main(FakeModule(check_mode), params))


def test_segment_create_skip_force_delete_and_check_mode(monkeypatch):
    client = FakeClient()
    present = _params(
        name="seg",
        type="REGULAR",
        segment_id=1,
        delegate_to_enterprise=True,
        delegate_to_enterprise_proxy=True,
    )
    created = _run(segment_mod, client, present, monkeypatch=monkeypatch)
    assert created["changed"]
    assert created["segment"]["name"] == "seg"
    skipped = _run(segment_mod, client, present, monkeypatch=monkeypatch)
    assert not skipped["changed"]
    drifted = _run(
        segment_mod,
        client,
        {**present, "segment_id": 99},
        monkeypatch=monkeypatch,
    )
    assert not drifted["changed"]
    assert "segment_id" in drifted["drift"]
    forced = _run(
        segment_mod,
        client,
        {**present, "segment_id": 99, "force": True},
        monkeypatch=monkeypatch,
    )
    assert forced["changed"]
    assert ("delete_segment", 12) in client.writes
    check = _run(
        segment_mod,
        FakeClient(),
        present,
        check_mode=True,
        monkeypatch=monkeypatch,
    )
    assert check["changed"]
    assert check["segment"]["id"] is None
    existing = FakeClient(segments=[FakeSegment("seg")])
    deleted = _run(
        segment_mod,
        existing,
        {**present, "state": "absent"},
        monkeypatch=monkeypatch,
    )
    assert deleted["changed"]
    assert existing.writes[0][0] == "delete_segment"


def test_profile_create_skip_and_absent(monkeypatch):
    client = FakeClient()
    present = _params(name="prof", segments=[], firewall={})
    created = _run(profile_mod, client, present, monkeypatch=monkeypatch)
    assert created["changed"]
    assert created["profile"]["name"] == "prof"
    skipped = _run(profile_mod, client, present, monkeypatch=monkeypatch)
    assert not skipped["changed"]
    absent = _run(
        profile_mod,
        client,
        {**present, "state": "absent"},
        monkeypatch=monkeypatch,
    )
    assert absent["changed"]
    missing = _run(
        profile_mod,
        client,
        {**present, "state": "absent"},
        monkeypatch=monkeypatch,
    )
    assert not missing["changed"]


def test_edge_create_skip_force_and_check_mode(monkeypatch):
    client = FakeClient(profiles=[FakeProfile("Demo-Profile", id_=21)])
    present = _params(
        name="BRANCH",
        profile="Demo-Profile",
        model_number="virtual",
        edge_license_id=520,
        site=None,
    )
    created = _run(edge_mod, client, present, monkeypatch=monkeypatch)
    assert created["changed"]
    assert created["edge"]["activation_key"] == "act-key"
    skipped = _run(edge_mod, client, present, monkeypatch=monkeypatch)
    assert not skipped["changed"]
    drifted = _run(
        edge_mod,
        client,
        {**present, "model_number": "edge510"},
        monkeypatch=monkeypatch,
    )
    assert not drifted["changed"]
    assert drifted["drift"]
    forced = _run(
        edge_mod,
        client,
        {**present, "model_number": "edge510", "force": True},
        monkeypatch=monkeypatch,
    )
    assert forced["changed"]
    check = _run(
        edge_mod,
        FakeClient(profiles=[FakeProfile("Demo-Profile", id_=21)]),
        present,
        check_mode=True,
        monkeypatch=monkeypatch,
    )
    assert check["changed"]
    assert check["edge"]["id"] is None
