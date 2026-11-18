# Copyright: (c) 2026, Kangwarn Chinthammit
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Operator-scoped REST transport and reconciliation shared by management modules.

These endpoints are not currently exposed by pyvelo's typed client, so the
collection implements them directly.
"""

from __future__ import annotations

from copy import deepcopy
from ipaddress import IPv4Address
from typing import Any, Literal

import requests
from pydantic import BaseModel, Field, field_validator


class ResourceSpec(BaseModel):
    name: str = Field(min_length=1)
    state: Literal["present", "absent"] = "present"
    network_id: int = Field(default=1, gt=0)
    parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("parameters")
    @classmethod
    def protect_identity(cls, value: dict[str, Any]) -> dict[str, Any]:
        reserved = {
            "id",
            "name",
            "networkId",
            "enterpriseId",
            "gatewayId",
            "_update",
            "activationKey",
            "activationState",
            "gatewayState",
            "autoCreateConfig",
        }
        if reserved.intersection(value):
            raise ValueError(
                "parameters cannot contain identity, activation, or control fields: "
                + ", ".join(sorted(reserved.intersection(value)))
            )
        return value


class GatewaySpec(ResourceSpec):
    ip_address: IPv4Address | None = None
    gateway_pool_id: int | None = Field(default=None, gt=0)
    service_state: Literal["IN_SERVICE", "OUT_OF_SERVICE"] | None = None

    def desired(self) -> dict[str, Any]:
        fields = deepcopy(self.parameters)
        for source, target in (
            ("ip_address", "ipAddress"),
            ("gateway_pool_id", "gatewayPoolId"),
            ("service_state", "serviceState"),
        ):
            value = getattr(self, source)
            if value is not None:
                fields[target] = str(value) if source == "ip_address" else value
        return fields


class EnterpriseSpec(ResourceSpec):
    gateway_pool_id: int | None = Field(default=None, gt=0)
    configuration_id: int | None = Field(default=None, gt=0)
    auto_create_profile: bool = True

    def desired(self) -> dict[str, Any]:
        fields = deepcopy(self.parameters)
        for source, target in (
            ("gateway_pool_id", "gatewayPoolId"),
            ("configuration_id", "configurationId"),
        ):
            value = getattr(self, source)
            if value is not None:
                fields[target] = value
        return fields


class OperatorClient:
    """Cookie or Token authentication with bounded requests and safe errors."""

    def __init__(self, params: dict[str, Any]) -> None:
        host = params["vco_host"].removeprefix("https://").rstrip("/")
        if not host or "/" in host or "@" in host or "?" in host or "#" in host:
            raise ValueError("vco_host must be a hostname or hostname:port")
        self.base_url = f"https://{host}/portal/rest"
        self.timeout = params["timeout"]
        if self.timeout <= 0:
            raise ValueError("timeout must be positive")
        self.params = params
        self.session = requests.Session()
        self.session.verify = params["verify_ssl"]
        self.session.headers.update({"Content-Type": "application/json"})
        self.changed = False

    def __enter__(self) -> OperatorClient:
        try:
            if self.params.get("api_token"):
                self.session.headers["Authorization"] = (
                    f"Token {self.params['api_token']}"
                )
            else:
                self._request(
                    "/login/operatorLogin",
                    {
                        "username": self.params["username"],
                        "password": self.params["password"],
                    },
                    login=True,
                )
                if not self.session.cookies.get("velocloud.session"):
                    raise RuntimeError("VCO login did not return a session cookie")
            return self
        except Exception:
            self.session.close()
            raise

    def __exit__(self, *exc: Any) -> None:
        self.session.close()

    def _request(self, endpoint: str, payload: dict, *, login: bool = False) -> Any:
        try:
            response = self.session.post(
                self.base_url + endpoint,
                json=payload,
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException:
            raise RuntimeError(f"VCO request to {endpoint} failed") from None
        allowed = (200, 302) if login else (200,)
        if response.status_code not in allowed:
            raise RuntimeError(f"VCO {endpoint} returned HTTP {response.status_code}")
        if login:
            return None
        try:
            result = response.json()
        except ValueError:
            raise RuntimeError(f"VCO {endpoint} returned invalid JSON") from None
        if isinstance(result, dict) and (
            result.get("error") or result.get("errorCode")
        ):
            # Do not echo error bodies: they can contain credentials or activation keys.
            raise RuntimeError(f"VCO {endpoint} reported an API error")
        return result

    def read(self, endpoint: str, payload: dict) -> Any:
        return self._request(endpoint, payload)

    def write(self, endpoint: str, payload: dict) -> Any:
        result = self._request(endpoint, payload)
        self.changed = True
        return result


def find_resource(items: Any, name: str) -> dict | None:
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise ValueError("VCO resource list response must be a list of objects")
    matches = [item for item in items if item.get("name") == name]
    if len(matches) > 1:
        raise ValueError(
            f"Multiple resources named {name!r}; refusing ambiguous changes"
        )
    if matches and not matches[0].get("id"):
        raise ValueError("VCO resource response is missing its id")
    return matches[0] if matches else None


def managed_changes(desired: dict, existing: dict) -> dict:
    """Compare only supplied fields, retaining unspecified nested settings."""
    changes = {}
    for key, value in desired.items():
        current = existing.get(key)
        if isinstance(value, dict) and isinstance(current, dict):
            nested = managed_changes(value, current)
            if nested:
                changes[key] = {**current, **nested}
        elif current != value:
            changes[key] = value
    return changes


UPDATABLE_ENTERPRISE_FIELDS = {
    "name",
    "description",
    "gatewayPoolId",
    "accountNumber",
    "alertsEnabled",
    "operatorAlertsEnabled",
    "contactMobile",
    "contactEmail",
    "streetAddress",
    "streetAddress2",
    "contactName",
    "contactPhone",
    "country",
    "postalCode",
    "city",
    "state",
    "domain",
    "prefix",
    "locale",
    "timezone",
    "lat",
    "lon",
}


def resource_details(api: OperatorClient, kind: str, existing: dict) -> dict:
    details = api.read(f"/{kind}/get{kind.title()}", {"id": existing["id"]})
    if not isinstance(details, dict) or details.get("id") != existing["id"]:
        raise ValueError(f"VCO returned invalid {kind} details")
    return {**existing, **details}


def reconcile_gateway(api: OperatorClient, spec: GatewaySpec, check: bool) -> dict:
    existing = find_resource(
        api.read("/network/getNetworkGateways", {"networkId": spec.network_id}),
        spec.name,
    )
    if spec.state == "absent":
        if existing and not check:
            api.write("/gateway/deleteGateway", {"id": existing["id"]})
        return {
            "changed": existing is not None,
            "gateway": existing or {},
            "result": existing or {},
        }

    if existing:
        return {
            "changed": False,
            "msg": f"Gateway {spec.name} already exists, skipping.",
            "gateway": existing,
            "result": existing,
            "activation_key": existing.get("activationKey", ""),
        }

    desired = spec.desired()
    if not desired.get("ipAddress"):
        raise ValueError("ip_address is required when creating a gateway")
    payload = {
        "serviceState": "IN_SERVICE",
        "gatewayPoolId": 1,
        **desired,
        "name": spec.name,
        "networkId": spec.network_id,
    }
    created = payload if check else api.write("/gateway/gatewayProvision", payload)
    if not isinstance(created, dict) or (not check and not created.get("id")):
        raise ValueError("VCO gatewayProvision response is missing its id")
    result = {**payload, **created}
    if not check and not result.get("activationKey"):
        found = find_resource(
            api.read("/network/getNetworkGateways", {"networkId": spec.network_id}),
            spec.name,
        )
        if found:
            result = {**result, **found}
        if not result.get("activationKey"):
            # Some VCOs return sparse list entries; the detail call has the key.
            result = {**result, **resource_details(api, "gateway", result)}
    return {
        "changed": True,
        "gateway": result,
        "result": result,
        "activation_key": result.get("activationKey", ""),
    }


def ensure_profile(
    api: OperatorClient, enterprise_id: int, check: bool
) -> tuple[bool, dict]:
    profiles = api.read(
        "/enterprise/getEnterpriseConfigurations", {"enterpriseId": enterprise_id}
    )
    profile = find_resource(profiles, "Quick Start Profile")
    if profile:
        return False, profile
    payload = {
        "enterpriseId": enterprise_id,
        "configurationType": "SEGMENT_BASED",
        "name": "Quick Start Profile",
        "description": "Enterprise configuration profile created automatically",
    }
    profile = (
        payload
        if check
        else api.write("/configuration/cloneEnterpriseTemplate", payload)
    )
    if not isinstance(profile, dict) or (not check and not profile.get("id")):
        raise ValueError("VCO cloneEnterpriseTemplate response is missing its id")
    return True, profile


def reconcile_enterprise(
    api: OperatorClient, spec: EnterpriseSpec, check: bool
) -> dict:
    existing = find_resource(
        api.read("/network/getNetworkEnterprises", {"networkId": spec.network_id}),
        spec.name,
    )
    if spec.state == "absent":
        if existing and not check:
            api.write("/enterprise/deleteEnterprise", {"enterpriseId": existing["id"]})
        return {
            "changed": existing is not None,
            "enterprise": existing or {},
            "result": existing or {},
        }

    desired = spec.desired()
    if existing:
        existing = resource_details(api, "enterprise", existing)
        # configurationId and delegation/profile assignment fields are creation-only
        # in insertEnterprise; updateEnterprise only accepts UPDATABLE_ENTERPRISE_FIELDS.
        update_fields = {
            key: value
            for key, value in desired.items()
            if key in UPDATABLE_ENTERPRISE_FIELDS
        }
        changes = managed_changes(update_fields, existing)
        if changes and not check:
            api.write(
                "/enterprise/updateEnterprise",
                {"enterpriseId": existing["id"], "_update": changes},
            )
        result = {**existing, **changes}
        changed = bool(changes)
    else:
        payload = {
            "domain": spec.name.lower().replace(" ", ""),
            "description": f"Enterprise created by Ansible: {spec.name}",
            "contactFirstName": "Ansible",
            "contactLastName": "User",
            "contactEmail": "ansible@example.com",
            "contactPhone": "555-1234",
            "alertsEnabled": True,
            "operatorAlertsEnabled": True,
            "endpointPkiMode": "CERTIFICATE_OPTIONAL",
            "locale": "en-US",
            "timezone": "America/Los_Angeles",
            "operatorConfigurationType": "SEGMENT_BASED",
            "enableEnterpriseDelegationToOperator": False,
            "enableEnterpriseUserManagementDelegationToOperator": False,
            "enableEnterpriseDelegationToProxy": False,
            "delegateEdgeImageManagementToEnterprise": False,
            **desired,
            "name": spec.name,
        }
        created = (
            payload if check else api.write("/enterprise/insertEnterprise", payload)
        )
        if not isinstance(created, dict) or (not check and not created.get("id")):
            raise ValueError("VCO insertEnterprise response is missing its id")
        result = {**payload, **created}
        changed = True

    if spec.auto_create_profile:
        if result.get("id"):
            profile_changed, profile = ensure_profile(api, result["id"], check)
            result = {**result, "auto_created_config": profile}
            changed |= profile_changed
        elif check:
            result = {**result, "auto_created_config": {"name": "Quick Start Profile"}}
    return {"changed": changed, "enterprise": result, "result": result}


def execute_module(module: Any, kind: str) -> None:
    """Validate once and consistently report partial successful API writes."""
    api = None
    try:
        spec_type = GatewaySpec if kind == "gateway" else EnterpriseSpec
        fields = {
            key: value
            for key, value in module.params.items()
            if key in spec_type.model_fields
        }
        spec = spec_type(**fields)
        api = OperatorClient(module.params)
        reconcile = reconcile_gateway if kind == "gateway" else reconcile_enterprise
        with api:
            result = reconcile(api, spec, module.check_mode)
    except Exception as exc:
        module.fail_json(msg=str(exc), changed=bool(api and api.changed))
    else:
        module.exit_json(**result)
