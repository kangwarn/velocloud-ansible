# Copyright: (c) 2026, Kangwarn Chinthammit
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Auth shim and async runner for velocloud.api SDK modules.

`build_client(params)` returns an `async with`-able pyvelo `VcoClient` for either
auth mode:

  * `api_token` provided -> standard `VcoClient(host, token)` (Bearer-style header).
  * `username` + `password` provided -> sync login via `/portal/rest/login/operatorLogin`,
    captures the `velocloud.session` cookie, returns a `VcoCookieClient` subclass
    that authenticates with that cookie instead of a Bearer token.

`run_async(coro)` runs a coroutine to completion in a fresh event loop. Each
Ansible task runs in its own subprocess, so `asyncio.run` per invocation is safe.

Shared argument specs live in `sdk_args.py` so ansible-test can introspect modules
without importing pyvelo.

`resolve_enterprise_id(params)` returns the enterprise_id, falling back to JWT
payload decode for token auth. Fails fast for username/password without an
explicit enterprise_id.
"""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Coroutine, Generator
from typing import Any, TypeVar

import httpx
import requests

from pyvelo.client import VcoClient


# ---------------------------------------------------------------------------
# Cookie-based VcoClient subclass for username/password auth
# ---------------------------------------------------------------------------


class _CookieAuth(httpx.Auth):
    """httpx auth that sends a `velocloud.session` cookie instead of a Bearer token."""

    def __init__(self, session_cookie: str) -> None:
        self._cookie = session_cookie

    def auth_flow(
        self, request: httpx.Request
    ) -> Generator[httpx.Request, httpx.Response]:
        existing = request.headers.get("Cookie", "")
        sep = "; " if existing else ""
        request.headers["Cookie"] = f"{existing}{sep}velocloud.session={self._cookie}"
        yield request


class VcoCookieClient(VcoClient):
    """VcoClient that authenticates via session cookie instead of API token.

    Used when the operator passes `username`/`password` instead of `api_token`.
    Stores the cookie value in the inherited `_token` SecretStr field; the
    field name is misleading but avoids duplicating all of VcoClient's state.
    """

    async def _connect(self) -> None:
        headers = {"Content-Type": "application/json"}
        self._http = await httpx.AsyncClient(
            auth=_CookieAuth(self._token.get_secret_value()),
            base_url=f"https://{self._vco_fqdn}",
            headers=headers,
            verify=self._verify_ssl,
            timeout=self._timeout,
        ).__aenter__()


# ---------------------------------------------------------------------------
# Sync login (username/password -> session cookie)
# ---------------------------------------------------------------------------


def _sync_login(host: str, username: str, password: str, verify_ssl: bool) -> str:
    """Operator-login via /portal/rest/login/operatorLogin. Returns the session cookie."""
    url = f"https://{host}/portal/rest/login/operatorLogin"
    session = requests.Session()
    session.verify = verify_ssl
    response = session.post(
        url,
        json={"username": username, "password": password},
        allow_redirects=False,
        timeout=30,
    )
    if response.status_code not in (200, 302):
        # Do not echo response bodies: they can contain credentials.
        raise RuntimeError(f"VCO login failed: HTTP {response.status_code}")
    cookie = session.cookies.get("velocloud.session")
    if not cookie:
        raise RuntimeError(
            "VCO login succeeded but no 'velocloud.session' cookie was returned"
        )
    return cookie


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def build_client(params: dict[str, Any]) -> VcoClient:
    """Construct a VcoClient appropriate for the chosen auth mode.

    The returned client is NOT yet connected. The caller must wrap it in
    `async with`.
    """
    host = params["vco_host"]
    verify_ssl = params.get("verify_ssl", True)
    api_token = params.get("api_token")

    if api_token:
        return VcoClient(host, api_token, verify_ssl=verify_ssl)

    username = params.get("username")
    password = params.get("password")
    if not (username and password):
        raise ValueError(
            "auth required: provide either api_token or both username and password"
        )

    cookie = _sync_login(host, username, password, verify_ssl)
    return VcoCookieClient(host, cookie, verify_ssl=verify_ssl)


def _decode_jwt_payload(token: str) -> dict[str, Any] | None:
    """Decode a JWT payload to a dict; return None on any failure."""
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return None
        payload = parts[1]
        payload += "=" * (-len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload).decode("utf-8")
        return json.loads(decoded)
    except Exception:
        return None


def resolve_enterprise_id(params: dict[str, Any]) -> int:
    """Return the effective enterprise_id, decoding the JWT payload if necessary.

    Order of precedence:
      1. params['enterprise_id'] if explicitly provided.
      2. JWT payload's 'enterpriseId' (token auth only).
      3. JWT payload's 'networkId' (token auth only) — covers operator-scoped tokens.

    Raises ValueError if no enterprise_id can be determined.
    """
    explicit = params.get("enterprise_id")
    if explicit is not None:
        return int(explicit)

    api_token = params.get("api_token")
    if api_token:
        payload = _decode_jwt_payload(api_token)
        if payload:
            for key in ("enterpriseId", "networkId"):
                value = payload.get(key)
                if value is not None:
                    return int(value)

    raise ValueError(
        "enterprise_id required: not provided in module args and could not be "
        "resolved from the API token payload"
    )


T = TypeVar("T")


def run_async(coro: Coroutine[Any, Any, T]) -> T:
    """Run an async coroutine to completion in a fresh event loop."""
    return asyncio.run(coro)
