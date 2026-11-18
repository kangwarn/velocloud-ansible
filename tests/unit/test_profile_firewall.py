import asyncio
from types import SimpleNamespace

from pyvelo.client.models.configuration.firewall.services import FirewallServicesGroup

from ansible_collections.velocloud.api.plugins.module_utils.topology import (
    ProfileFirewallSpec,
    ProfileSpec,
    apply_profile_firewall,
    firewall_requested,
)
from ansible_collections.velocloud.api.plugins.modules import profile as profile_mod


class RecordingPipeline:
    def __init__(self, updated=None, errors=None):
        self.patches = []
        self.loads = []
        self.saves = []
        self.updated = updated if updated is not None else ["firewall"]
        self.errors = errors or []

    async def load_profile(self, profile_id, enterprise_id=None):
        self.loads.append((profile_id, enterprise_id))
        return {"profile_id": profile_id}

    async def apply(self, state, *, module, patch):
        self.patches.append({"module": module, "patch": patch})
        return state

    async def save(self, state, dry_run=False, validate=True):
        self.saves.append({"dry_run": dry_run, "validate": validate, "state": state})
        return SimpleNamespace(
            validation_errors=self.errors,
            modules_updated=self.updated,
            modules_inserted=[],
        )


class FakeModule:
    def __init__(self, check_mode=False):
        self.check_mode = check_mode
        self.warnings = []

    def warn(self, msg):
        self.warnings.append(msg)


class FakeProfile:
    def __init__(self, name, id_=21, description=""):
        self.id_ = id_
        self.name = name
        self.description = description


class FakeClient:
    def __init__(self, profiles=None):
        self.profiles = list(profiles or [])
        self.writes = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get_enterprise_configurations(self, req):
        return list(self.profiles)

    async def create_enterprise_profile(self, req):
        self.writes.append(("create_profile", req.name))
        created = FakeProfile(name=req.name, id_=22, description=req.description)
        self.profiles.append(created)
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
        segments=[],
        firewall={},
        name="Demo-Profile",
    )
    data.update(kwargs)
    return data


def _run(client, params, check_mode=False, monkeypatch=None, pipeline=None):
    monkeypatch.setattr(profile_mod, "build_client", lambda _params: client)
    if pipeline is not None:
        monkeypatch.setattr(profile_mod, "ConfigPipeline", lambda _client: pipeline)
    return asyncio.run(profile_mod._async_main(FakeModule(check_mode), params))


def test_profile_firewall_spec_parses_ssh_from_host_vars():
    spec = ProfileFirewallSpec(
        **{
            "console_enabled": True,
            "ssh": {"enabled": True, "allow_selected_ip": ["192.168.2.2"]},
        }
    )
    assert spec.console_enabled is True
    assert spec.ssh is not None
    assert spec.ssh.enabled is True
    assert spec.ssh.allow_selected_ip == ["192.168.2.2"]
    assert firewall_requested(spec)
    assert not firewall_requested(ProfileFirewallSpec())


def test_apply_profile_firewall_builds_console_and_ssh_services():
    pipeline = RecordingPipeline()
    spec = ProfileFirewallSpec(
        console_enabled=True,
        ssh={"enabled": True, "allow_selected_ip": ["192.168.2.2"]},
    )

    asyncio.run(apply_profile_firewall(pipeline, {}, spec))

    assert len(pipeline.patches) == 1
    patch = pipeline.patches[0]
    assert patch["module"] == "firewall"
    services = patch["patch"]["services"]
    assert services["console"]["enabled"] is True
    assert services["ssh"]["enabled"] is True
    assert services["ssh"]["allow_selected_ip"] == ["192.168.2.2"]
    assert "allow_selected_ip_v6" not in services["ssh"]
    dumped = FirewallServicesGroup(**services["ssh"])
    assert dumped.enabled is True


def test_apply_profile_firewall_skips_when_nothing_requested():
    pipeline = RecordingPipeline()
    asyncio.run(apply_profile_firewall(pipeline, {}, ProfileFirewallSpec()))
    assert pipeline.patches == []


def test_profile_applies_ssh_on_existing_profile(monkeypatch):
    client = FakeClient(profiles=[FakeProfile("Demo-Profile", id_=21)])
    pipeline = RecordingPipeline(updated=["firewall"])
    result = _run(
        client,
        _params(
            firewall={
                "console_enabled": True,
                "ssh": {"enabled": True, "allow_selected_ip": ["192.168.2.2"]},
            }
        ),
        monkeypatch=monkeypatch,
        pipeline=pipeline,
    )
    assert result["changed"]
    assert result["modules_updated"] == ["firewall"]
    assert pipeline.loads == [(21, 1)]
    assert pipeline.patches[0]["patch"]["services"]["ssh"]["allow_selected_ip"] == [
        "192.168.2.2"
    ]
    assert pipeline.saves[0]["dry_run"] is False


def test_profile_existing_firewall_check_mode(monkeypatch):
    client = FakeClient(profiles=[FakeProfile("Demo-Profile", id_=21)])
    pipeline = RecordingPipeline(updated=["firewall"])
    result = _run(
        client,
        _params(firewall={"ssh": {"enabled": True}}),
        check_mode=True,
        monkeypatch=monkeypatch,
        pipeline=pipeline,
    )
    assert result["changed"]
    assert result["modules_updated"] == ["firewall"]
    assert pipeline.saves[0]["dry_run"] is True


def test_profile_create_applies_ssh(monkeypatch):
    client = FakeClient()
    pipeline = RecordingPipeline(updated=["firewall"])
    result = _run(
        client,
        _params(
            name="New-Profile",
            firewall={"ssh": {"enabled": True, "allow_selected_ip": ["10.0.0.1"]}},
        ),
        monkeypatch=monkeypatch,
        pipeline=pipeline,
    )
    assert result["changed"]
    assert result["profile"]["name"] == "New-Profile"
    assert ("create_profile", "New-Profile") in client.writes
    assert pipeline.patches[0]["patch"]["services"]["ssh"]["allow_selected_ip"] == [
        "10.0.0.1"
    ]


def test_profile_spec_accepts_nested_firewall():
    spec = ProfileSpec(
        name="Demo-Profile",
        firewall={
            "console_enabled": True,
            "ssh": {"enabled": True, "allow_selected_ip": ["192.168.2.2"]},
        },
    )
    assert spec.firewall.ssh.enabled is True
