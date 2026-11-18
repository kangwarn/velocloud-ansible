import base64
import json
from unittest.mock import Mock

import pytest
import requests

from ansible_collections.velocloud.api.plugins.module_utils.auth import (
    _sync_login,
    resolve_enterprise_id,
)
from ansible_collections.velocloud.api.plugins.module_utils.sdk_args import (
    common_argspec,
    common_argspec_constraints,
)


def _jwt(payload):
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"header.{body}.sig"


def test_resolve_enterprise_id_prefers_explicit_then_jwt():
    assert (
        resolve_enterprise_id(
            {"enterprise_id": 7, "api_token": _jwt({"enterpriseId": 9})}
        )
        == 7
    )
    assert resolve_enterprise_id({"api_token": _jwt({"enterpriseId": 9})}) == 9
    assert resolve_enterprise_id({"api_token": _jwt({"networkId": 3})}) == 3
    with pytest.raises(ValueError, match="enterprise_id required"):
        resolve_enterprise_id({"username": "op"})


def test_sync_login_does_not_echo_response_body(monkeypatch):
    response = Mock(status_code=401, text="password=secret")
    session = Mock()
    session.post.return_value = response
    session.cookies.get.return_value = None
    monkeypatch.setattr(requests, "Session", lambda: session)
    with pytest.raises(RuntimeError, match="HTTP 401") as caught:
        _sync_login("vco.example.com", "user", "secret", True)
    assert "secret" not in str(caught.value)


def test_sdk_args_mark_secrets_and_default_tls_on():
    spec = common_argspec()
    assert spec["api_token"]["no_log"] is True
    assert spec["password"]["no_log"] is True
    assert spec["verify_ssl"]["default"] is True
    constraints = common_argspec_constraints()
    assert ("api_token", "username") in constraints["mutually_exclusive"]
    assert ("username", "password") in constraints["required_together"]
