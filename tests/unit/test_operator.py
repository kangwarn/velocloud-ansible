from copy import deepcopy
from unittest.mock import Mock

import pytest
import requests
from pydantic import ValidationError

from ansible_collections.velocloud.api.plugins.module_utils import operator
from ansible_collections.velocloud.api.plugins.module_utils.operator import (
    EnterpriseSpec,
    GatewaySpec,
    OperatorClient,
    reconcile_enterprise,
    reconcile_gateway,
)


class FakeAPI:
    """Persist state across runs so tests exercise convergence, not just payloads."""

    def __init__(self):
        self.gateways = []
        self.enterprises = []
        self.profiles = []
        self.writes = []

    def read(self, endpoint, payload):
        if endpoint == "/network/getNetworkGateways":
            return deepcopy(self.gateways)
        if endpoint == "/network/getNetworkEnterprises":
            return deepcopy(self.enterprises)
        if endpoint == "/enterprise/getEnterpriseConfigurations":
            return deepcopy(self.profiles)
        items = self.gateways if endpoint == "/gateway/getGateway" else self.enterprises
        return deepcopy(next(item for item in items if item["id"] == payload["id"]))

    def write(self, endpoint, payload):
        self.writes.append((endpoint, deepcopy(payload)))
        if endpoint == "/gateway/gatewayProvision":
            result = {**payload, "id": 12, "activationKey": "secret-key"}
            self.gateways.append(result)
            return deepcopy(result)
        if endpoint == "/enterprise/insertEnterprise":
            result = {**payload, "id": 23}
            self.enterprises.append(result)
            return deepcopy(result)
        if endpoint == "/configuration/cloneEnterpriseTemplate":
            result = {**payload, "id": 34}
            self.profiles.append(result)
            return deepcopy(result)
        if endpoint.endswith("updateGateway"):
            self.gateways[0].update(
                {k: v for k, v in payload.items() if k != "gatewayId"}
            )
        elif endpoint.endswith("updateEnterprise"):
            self.enterprises[0].update(payload["_update"])
        elif endpoint.endswith("deleteGateway"):
            self.gateways.clear()
        elif endpoint.endswith("deleteEnterprise"):
            self.enterprises.clear()
        else:
            raise AssertionError(endpoint)
        return {"rows": 1}


def test_gateway_create_then_skip_existing_preserves_activation():
    api = FakeAPI()
    spec = GatewaySpec(
        name="gw", ip_address="192.0.2.1", parameters={"site": {"contactName": "Admin"}}
    )
    first = reconcile_gateway(api, spec, False)
    assert first["changed"]
    assert first["activation_key"] == "secret-key"
    assert not reconcile_gateway(api, spec, False)["changed"]
    # Existing gateways are never modified, even when supplied fields differ.
    skipped = reconcile_gateway(
        api, GatewaySpec(name="gw", service_state="OUT_OF_SERVICE"), False
    )
    assert not skipped["changed"]
    assert "already exists" in skipped["msg"]
    assert skipped["activation_key"] == "secret-key"
    assert len(api.gateways) == 1
    assert [call[0] for call in api.writes] == ["/gateway/gatewayProvision"]


def test_gateway_delete_sends_id():
    api = FakeAPI()
    api.gateways = [{"id": 7, "name": "gw"}]
    assert reconcile_gateway(api, GatewaySpec(name="gw", state="absent"), False)[
        "changed"
    ]
    assert api.writes == [("/gateway/deleteGateway", {"id": 7})]


@pytest.mark.parametrize(
    "kind,spec_type,reconcile",
    [
        ("gateways", GatewaySpec, reconcile_gateway),
        ("enterprises", EnterpriseSpec, reconcile_enterprise),
    ],
)
def test_absent_and_check_mode(kind, spec_type, reconcile):
    api = FakeAPI()
    spec = spec_type(name="example", state="absent")
    assert not reconcile(api, spec, False)["changed"]
    getattr(api, kind).append({"id": 7, "name": "example"})
    assert reconcile(api, spec, True)["changed"]
    assert not api.writes
    assert reconcile(api, spec, False)["changed"]
    assert not reconcile(api, spec, False)["changed"]


def test_gateway_check_mode_never_creates_or_updates():
    api = FakeAPI()
    spec = GatewaySpec(name="gw", ip_address="192.0.2.1")
    assert reconcile_gateway(api, spec, True)["changed"]
    assert not api.writes
    api.gateways = [{"name": "gw", "id": 1, "ipAddress": "192.0.2.2"}]
    assert not reconcile_gateway(api, spec, True)["changed"]
    assert not api.writes


def test_gateway_creation_requires_ip_but_delete_does_not():
    with pytest.raises(ValueError, match="ip_address is required"):
        reconcile_gateway(FakeAPI(), GatewaySpec(name="gw"), False)
    with pytest.raises(ValidationError):
        GatewaySpec(name="gw", ip_address="not-an-ip")


def test_duplicate_names_fail_before_writing():
    api = FakeAPI()
    api.gateways = [{"id": 1, "name": "gw"}, {"id": 2, "name": "gw"}]
    with pytest.raises(ValueError, match="Multiple resources"):
        reconcile_gateway(api, GatewaySpec(name="gw", state="absent"), False)
    assert not api.writes


def test_enterprise_create_profile_and_converge_with_features():
    api = FakeAPI()
    spec = EnterpriseSpec(
        name="Enterprise",
        configuration_id=6,
        gateway_pool_id=2,
        parameters={
            "enableEnterpriseDelegationToOperator": True,
            "licenses": {"ids": [1, 2]},
        },
    )
    first = reconcile_enterprise(api, spec, False)
    assert first["result"]["id"] == 23
    assert first["result"]["auto_created_config"]["id"] == 34
    assert api.enterprises[0]["configurationId"] == 6
    assert api.enterprises[0]["licenses"] == {"ids": [1, 2]}
    assert not reconcile_enterprise(api, spec, False)["changed"]
    assert len(api.writes) == 2


def test_enterprise_profile_recovery_after_partial_failure():
    api = FakeAPI()
    api.enterprises = [{"name": "Enterprise", "id": 23}]
    result = reconcile_enterprise(api, EnterpriseSpec(name="Enterprise"), False)
    assert result["changed"]
    assert [call[0] for call in api.writes] == [
        "/configuration/cloneEnterpriseTemplate"
    ]
    assert not reconcile_enterprise(api, EnterpriseSpec(name="Enterprise"), False)[
        "changed"
    ]


def test_enterprise_update_only_sends_updatable_fields():
    api = FakeAPI()
    api.enterprises = [
        {
            "name": "Enterprise",
            "id": 23,
            "licenses": {"ids": [1], "other": True},
            "description": "old",
            "contactName": "keep",
        }
    ]
    # licenses and delegation flags are creation-only; updateEnterprise ignores them.
    spec = EnterpriseSpec(
        name="Enterprise",
        auto_create_profile=False,
        parameters={
            "licenses": {"ids": [2]},
            "enableEnterpriseDelegationToOperator": True,
            "description": "new",
        },
    )
    assert reconcile_enterprise(api, spec, False)["changed"]
    assert [call[0] for call in api.writes] == ["/enterprise/updateEnterprise"]
    assert api.writes[0][1]["_update"] == {"description": "new"}
    assert api.enterprises[0]["licenses"] == {"ids": [1], "other": True}
    assert api.enterprises[0]["contactName"] == "keep"
    assert not reconcile_enterprise(api, spec, False)["changed"]


def test_enterprise_check_mode_existing_and_new_profiles():
    api = FakeAPI()
    spec = EnterpriseSpec(name="Enterprise")
    assert reconcile_enterprise(api, spec, True)["changed"]
    api.enterprises = [{"name": "Enterprise", "id": 23}]
    assert reconcile_enterprise(api, spec, True)["changed"]
    assert not api.writes


@pytest.mark.parametrize(
    "key",
    [
        "name",
        "id",
        "enterpriseId",
        "gatewayId",
        "networkId",
        "activationKey",
        "_update",
        "autoCreateConfig",
    ],
)
def test_raw_parameters_cannot_override_identity_or_activation(key):
    with pytest.raises(ValidationError, match="identity, activation, or control"):
        GatewaySpec(name="gw", parameters={key: "override"})


@pytest.fixture
def session(monkeypatch):
    session = Mock()
    session.headers = {}
    session.cookies = {}
    session.post.return_value.status_code = 200
    session.post.return_value.json.return_value = []
    monkeypatch.setattr(operator.requests, "Session", lambda: session)
    return session


def params(**extra):
    return {
        "vco_host": "vco.example.com",
        "api_token": "private-token",
        "verify_ssl": True,
        "timeout": 30,
        **extra,
    }


def test_token_transport_uses_timeouts_and_does_not_login(session):
    with OperatorClient(params()) as api:
        assert api.read("/network/getNetworkGateways", {"networkId": 1}) == []
    assert session.headers["Authorization"] == "Token private-token"
    session.post.assert_called_once_with(
        "https://vco.example.com/portal/rest/network/getNetworkGateways",
        json={"networkId": 1},
        timeout=30,
        allow_redirects=False,
    )
    assert session.verify is True
    session.close.assert_called_once()


def test_cookie_auth_success_and_failure_close_sessions(session):
    session.cookies = {"velocloud.session": "cookie"}
    with OperatorClient(params(api_token=None, username="operator", password="secret")):
        pass
    assert "Authorization" not in session.headers
    session.post.assert_called_once()
    session.cookies = {}
    with pytest.raises(RuntimeError, match="session cookie"):
        with OperatorClient(
            params(api_token=None, username="operator", password="secret")
        ):
            pass
    assert session.close.call_count == 2


@pytest.mark.parametrize("failure", ["http", "json", "api", "network"])
def test_transport_errors_are_safe_and_do_not_claim_success(session, failure):
    if failure == "http":
        session.post.return_value.status_code = 403
    elif failure == "json":
        session.post.return_value.json.side_effect = ValueError("private-token")
    elif failure == "api":
        session.post.return_value.json.return_value = {"error": "private-token"}
    else:
        session.post.side_effect = requests.ConnectionError("private-token")
    with OperatorClient(params()) as api:
        with pytest.raises(RuntimeError) as error:
            api.write("/enterprise/insertEnterprise", {})
        assert "private-token" not in str(error.value)
        assert not api.changed


def test_module_reports_successful_write_before_profile_failure(monkeypatch):
    api = Mock()
    api.changed = True
    api.__enter__ = Mock(return_value=api)
    api.__exit__ = Mock(return_value=None)
    monkeypatch.setattr(operator, "OperatorClient", lambda _: api)
    monkeypatch.setattr(
        operator,
        "reconcile_enterprise",
        Mock(side_effect=RuntimeError("profile failed")),
    )
    module = Mock(params={"name": "Enterprise"}, check_mode=False)
    operator.execute_module(module, "enterprise")
    module.fail_json.assert_called_once_with(msg="profile failed", changed=True)
    module.exit_json.assert_not_called()
