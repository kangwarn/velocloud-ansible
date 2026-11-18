"""Exercise the released artifact through real Ansible module subprocesses."""

import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import sys
import tarfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest
import yaml

COLLECTION = Path(__file__).resolve().parents[2]
GALAXY = yaml.safe_load((COLLECTION / "galaxy.yml").read_text())


def run_cli(workdir, env, module, *args):
    result = subprocess.run(
        [sys.executable, "-m", module, *map(str, args)],
        cwd=workdir,
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


@pytest.fixture(scope="module")
def consumer(tmp_path_factory):
    root = tmp_path_factory.mktemp("collection-consumer")
    install = root / "collections"
    config = root / "ansible.cfg"
    config.write_text(
        f"[defaults]\ncollections_path = {install}\nretry_files_enabled = false\n"
    )
    env = {
        **os.environ,
        "ANSIBLE_CONFIG": str(config),
        "ANSIBLE_COLLECTIONS_PATH": str(install),
        "ANSIBLE_LOCAL_TEMP": str(root / "local-tmp"),
        "ANSIBLE_REMOTE_TEMP": str(root / "remote-tmp"),
        "ANSIBLE_NOCOLOR": "1",
    }
    env.pop("PYTHONPATH", None)
    source = root / "collection-source"
    shutil.copytree(
        COLLECTION,
        source,
        ignore=shutil.ignore_patterns(
            ".tokens",
            "__pycache__",
            "*.tar.gz",
            ".git",
            ".venv",
            ".pytest_cache",
            ".sanity-tree",
            "dist",
            "output",
        ),
    )
    saved_tokens = source / "examples/.tokens"
    saved_tokens.mkdir()
    (saved_tokens / "dummy.token").write_text("must-not-be-packaged")
    run_cli(
        root,
        env,
        "ansible.cli.galaxy",
        "collection",
        "build",
        source,
        "--output-path",
        root,
    )
    artifact = (
        root / f"{GALAXY['namespace']}-{GALAXY['name']}-{GALAXY['version']}.tar.gz"
    )
    with tarfile.open(artifact) as archive:
        names = archive.getnames()
        assert "plugins/modules/gateway.py" in names
        assert "plugins/modules/enterprise.py" in names
        assert "requirements.txt" in names
        assert "COPYING" in names
        assert "requirements-sdk.txt" not in names
        assert "examples/configure.yml" in names
        assert not any(
            name.startswith("tests/") or "__pycache__" in name or ".tokens" in name
            for name in names
        )
    run_cli(
        root,
        env,
        "ansible.cli.galaxy",
        "collection",
        "install",
        artifact,
        "-p",
        install,
        "--no-deps",
    )
    return root, env


@pytest.fixture
def vco(tmp_path):
    """Small HTTPS VCO stand-in with sparse list and complete detail responses."""
    resources = {"gateway": {}, "enterprise": {}, "auth_calls": [], "tokens": []}
    profiles = []
    writes = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            assert self.path == "/portal/vco/getSessionContext"
            assert "velocloud.session=test-cookie" in self.headers.get("Cookie", "")
            resources["auth_calls"].append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"userId": 42}')

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            endpoint = self.path.removeprefix("/portal/rest")
            if endpoint == "/login/operatorLogin":
                assert payload == {"username": "operator", "password": "password"}
                resources["auth_calls"].append(endpoint)
                self.send_response(200)
                self.send_header("Set-Cookie", "velocloud.session=test-cookie; Path=/")
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b"{}")
                return
            assert self.headers.get(
                "Authorization"
            ) == "Token token" or "velocloud.session=test-cookie" in self.headers.get(
                "Cookie", ""
            )
            result = None
            for kind in ("gateway", "enterprise"):
                collection = resources[kind]
                if endpoint == f"/network/getNetwork{kind.title()}s":
                    assert payload["networkId"] == 1
                    result = [
                        {"id": item["id"], "name": item["name"]}
                        for item in collection.values()
                    ]
                elif endpoint == f"/{kind}/get{kind.title()}":
                    result = collection[payload["id"]]
                elif endpoint == f"/{kind}/" + (
                    "gatewayProvision" if kind == "gateway" else "insertEnterprise"
                ):
                    record = {**payload, "id": len(collection) + 1}
                    if kind == "gateway":
                        record["activationKey"] = "activation-secret"
                    collection[record["id"]] = record
                    writes.append(endpoint)
                    result = {"id": record["id"]}  # Older VCOs can return only an ID.
                elif endpoint == f"/{kind}/update{kind.title()}":
                    fields = payload.get(
                        "_update",
                        {k: v for k, v in payload.items() if k != "gatewayId"},
                    )
                    collection[payload[f"{kind}Id"]].update(fields)
                    writes.append(endpoint)
                    result = {"rows": 1}
            if endpoint == "/enterprise/getEnterpriseConfigurations":
                result = profiles
            elif endpoint == "/configuration/cloneEnterpriseTemplate":
                result = {**payload, "id": 10}
                profiles.append(result)
                writes.append(endpoint)
            elif endpoint == "/operatorUser/getApiTokens":
                assert payload["id"] == 42
                resources["auth_calls"].append(endpoint)
                result = resources["tokens"]
            elif endpoint == "/network/createApiToken":
                assert payload["operatorUserId"] == 42
                assert isinstance(payload["lifetimeMs"], int)
                resources["auth_calls"].append(endpoint)
                resources["tokens"].append({"id": 51, "name": payload["name"]})
                writes.append(endpoint)
                result = {"id": 51}
            elif endpoint == "/network/downloadApiToken":
                assert payload["id"] == 51
                resources["auth_calls"].append(endpoint)
                result = {"token": "token"}
            if result is None:
                self.send_error(500, "Unexpected endpoint")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())

    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
        ],
        check=True,
        capture_output=True,
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"127.0.0.1:{server.server_port}", resources, writes
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_installed_documentation(consumer):
    root, env = consumer
    output = run_cli(
        root,
        env,
        "ansible.cli.doc",
        "--json",
        "velocloud.api.gateway",
        "velocloud.api.enterprise",
    )
    docs = json.loads(output)
    assert set(docs) == {"velocloud.api.gateway", "velocloud.api.enterprise"}
    assert all(str(root) in item["doc"]["filename"] for item in docs.values())


def run_example(consumer, host, token_file, *, check=False, **variables):
    root, env = consumer
    example = (
        root / "collections/ansible_collections/velocloud/api/examples/configure.yml"
    )
    extra_vars = {
        "vco_host": host,
        "vco_verify_ssl": False,
        "vco_token_file": str(token_file),
        "ansible_python_interpreter": sys.executable,
        **variables,
    }
    return run_cli(
        root,
        env,
        "ansible.cli.playbook",
        example,
        "-i",
        "localhost,",
        "-e",
        json.dumps(extra_vars),
        *(["--check"] if check else []),
    )


def test_example_bootstraps_saves_and_reuses_token(consumer, vco, tmp_path):
    host, resources, writes = vco
    token_file = tmp_path / "private" / "vco.token"
    run_example(
        consumer, host, token_file, vco_username="operator", vco_password="password"
    )
    assert token_file.read_text().strip() == "token"
    assert token_file.stat().st_mode & 0o777 == 0o600
    assert token_file.parent.stat().st_mode & 0o777 == 0o700
    assert resources["auth_calls"].count("/login/operatorLogin") == 1
    assert resources["auth_calls"].count("/network/createApiToken") == 1
    assert resources["auth_calls"].count("/network/downloadApiToken") == 1
    auth_calls, api_writes = list(resources["auth_calls"]), list(writes)

    # No credentials are supplied on the second run, including in check mode.
    run_example(consumer, host, token_file)
    run_example(consumer, host, token_file, check=True)
    assert resources["auth_calls"] == auth_calls
    assert writes == api_writes


def test_example_downloads_existing_named_remote_token(consumer, vco, tmp_path):
    host, resources, writes = vco
    resources["tokens"].append({"id": 51, "name": "ansible-collection-example"})
    token_file = tmp_path / "private" / "vco.token"
    run_example(
        consumer, host, token_file, vco_username="operator", vco_password="password"
    )
    assert token_file.read_text().strip() == "token"
    assert "/network/createApiToken" not in writes
    assert resources["auth_calls"].count("/network/downloadApiToken") == 1


def test_example_explicit_token_takes_precedence(consumer, vco, tmp_path):
    host, resources, _writes = vco
    token_file = tmp_path / "wrong.token"
    token_file.write_text("invalid-saved-token")
    run_example(consumer, host, token_file, vco_token="token")
    assert not resources["auth_calls"]
    assert token_file.read_text() == "invalid-saved-token"


def test_installed_modules_and_check_mode(consumer, vco):
    root, env = consumer
    host, resources, writes = vco
    gateway = {
        "vco_host": host,
        "api_token": "token",
        "verify_ssl": False,
        "name": "gateway",
        "ip_address": "192.0.2.10",
    }
    enterprise = {
        "vco_host": host,
        "username": "operator",
        "password": "password",
        "verify_ssl": False,
        "name": "enterprise",
        "parameters": {"description": "managed"},
    }
    tasks = [
        {
            "velocloud.api.gateway": gateway,
            "register": "gateway_created",
            "no_log": True,
        },
        {
            "velocloud.api.gateway": gateway,
            "register": "gateway_repeat",
            "no_log": True,
        },
        {"velocloud.api.enterprise": enterprise, "register": "enterprise_created"},
        {"velocloud.api.enterprise": enterprise, "register": "enterprise_repeat"},
        {
            "velocloud.api.gateway": {**gateway, "ip_address": "192.0.2.20"},
            "check_mode": True,
            "register": "preview",
            "no_log": True,
        },
        {
            "velocloud.api.enterprise": {**enterprise, "name": "preview-enterprise"},
            "check_mode": True,
            "register": "enterprise_preview",
        },
        {
            "ansible.builtin.assert": {
                "that": [
                    "gateway_created.changed",
                    "not gateway_repeat.changed",
                    "gateway_created.activation_key == 'activation-secret'",
                    "enterprise_created.changed",
                    "not enterprise_repeat.changed",
                    "enterprise_created.result.id == 1",
                    "enterprise_created.result.auto_created_config.id == 10",
                    "not preview.changed",
                    "enterprise_preview.changed",
                ]
            },
            "no_log": True,
        },
    ]
    playbook = root / "consumer.yml"
    playbook.write_text(
        yaml.safe_dump(
            [
                {
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": False,
                    "tasks": tasks,
                }
            ]
        )
    )
    run_cli(
        root,
        env,
        "ansible.cli.playbook",
        playbook,
        "-i",
        "localhost,",
        "-e",
        f"ansible_python_interpreter={sys.executable}",
    )
    assert len(writes) == 3
    assert resources["gateway"][1]["ipAddress"] == "192.0.2.10"
    assert len(resources["enterprise"]) == 1
