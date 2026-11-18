# velocloud.api

Reusable Ansible modules for VeloCloud Orchestrator (VCO). Gateway and enterprise management use the VCO REST API directly; the existing edge, profile and segment modules use the pyvelo SDK.

## Install

Install straight from this git repository (pin a tag or commit for reproducible installs):

```sh
ansible-galaxy collection install git+https://github.com/kangwarn-arista/velocloud-ansible.git,<tag>
```

Or record it in a `requirements.yml` and run `ansible-galaxy collection install -r requirements.yml`:

```yaml
collections:
  - name: https://github.com/kangwarn-arista/velocloud-ansible.git
    type: git
    version: <tag>
```

Galaxy installs collection files only. It does not install Python packages. This collection runs on the controller and requires **Python 3.14** in that interpreter (pyvelo requires 3.14 and does not support other versions). Install the dependencies from `requirements.txt`:

```sh
# From a git checkout
pip install -r requirements.txt

# After ansible-galaxy collection install (adjust the collections path if needed)
pip install -r ~/.ansible/collections/ansible_collections/velocloud/api/requirements.txt
```

Use `hosts: localhost`, `connection: local` to run on the controller. `meta/execution-environment.yml` declares the same Python dependencies for Ansible Builder.

## Modules

| FQCN | Purpose |
|---|---|
| `velocloud.api.gateway` | Create/update/delete gateway records without device activation. |
| `velocloud.api.enterprise` | Create/update/delete enterprises and ensure their initial Quick Start Profile. |
| `velocloud.api.segment` | Create/delete network segments. |
| `velocloud.api.profile` | Create/delete configuration profiles, attach segments with device settings, QoS, and firewall factory defaults, and apply firewall console and SSH access. |
| `velocloud.api.profile_vpn` | Patch CloudVPN on a profile segment, including hub designation and vpn edgeHub refs. |
| `velocloud.api.edge` | Create/delete edges (no config patches). |
| `velocloud.api.edge_lan` | Patch LAN routed interfaces, sub-interfaces, switched ports, VLAN networks. |
| `velocloud.api.edge_wan` | Patch WAN-facing interfaces and `wan.links` settings. |
| `velocloud.api.edge_bgp` | Patch per-segment BGP configuration. |
| `velocloud.api.edge_common` | Patch common edge settings. |
| `velocloud.api.edge_loopback` | Patch loopback interfaces. |
| `velocloud.api.edge_segment` | Patch per-segment settings. |

The three `edge_*` patch modules use pyvelo's `ConfigPipeline` which natively diffs and saves only the modules that changed. The top-level CRUD modules (`segment`, `profile`, `edge`) skip-if-exists by default; pass `force: true` to delete and recreate on drift. `profile` still patches firewall console and SSH services on an existing profile when name and description already match.

## Authentication

All modules accept either `api_token` or `username` + `password`.

Gateway and enterprise modules require operator permissions. Tokens use `Authorization: Token`; username/password uses an operator login session cookie. `timeout` bounds each HTTP request (30 seconds by default). `network_id` defaults to 1 and scopes name lookup.

SDK modules pass tokens to `pyvelo.client.VcoClient` as Bearer tokens. Username/password uses an operator login session cookie.

TLS verification defaults to true on all modules. Use `verify_ssl: false` explicitly for a lab with a self-signed certificate.

SDK modules can infer `enterprise_id` from a token. Supply it explicitly when needed; gateway and enterprise management identify resources by name.

## Configuration and activation

`gateway` creates a gateway record when none exists with that name; new gateways require `ip_address`. An existing gateway is left unchanged (reported as not changed) and its current record and activation key are returned. Changing IP, service state or pool on an existing gateway is not supported. It returns `gateway`, a compatibility alias `result`, and `activation_key`. It never logs into the gateway or runs an activation command. Protect the registered record with `no_log: true` because it may contain an activation key. `state: absent` needs only a name.

`enterprise` applies supplied API fields such as delegation flags, `licenses`, `assignedOperatorProfileConfigurationIds`, contacts and alerts when it creates the enterprise. On existing enterprises it updates only fields that `updateEnterprise` accepts (name, description, `gatewayPoolId`, account number, alert flags, contact and address fields, domain, prefix, locale, timezone, lat, lon); other supplied fields are ignored. By default it ensures a `Quick Start Profile` exists, retrying profile creation if an earlier run created only the enterprise. Set `auto_create_profile: false` to manage profiles separately. Results are available as `enterprise` and the compatibility alias `result`; the profile is in `auto_created_config`.

Repeated runs report unchanged once supplied, updatable fields match. Unspecified fields are retained; removing a field from a playbook does not reset it. Nested dictionaries retain unspecified fields, and lists are compared as supplied. `state: absent` removes only the named record and leaves dependency checks to VCO. Duplicate names fail before any changes. Check mode authenticates and reads current state, returning predicted changes without write requests; newly predicted resources have no numeric ID or activation key.

## Usage

Call modules by FQCN:

```yaml
- velocloud.api.segment:
    vco_host: "{{ vco_host }}"
    api_token: "{{ vco_api_token }}"
    name: Demo-Segment
    segment_id: 99
```

Inspect complete options with `ansible-doc velocloud.api.gateway` or `ansible-doc velocloud.api.enterprise`.

### Standalone example

The included [examples/configure.yml](examples/configure.yml) configures gateway and enterprise records. Run it from a checkout, or use the copy in the installed collection. On the first run, supply `vco_host`, `vco_username`, and `vco_password` through an Ansible Vault variables file:

```sh
uv run ansible-playbook examples/configure.yml -e @vco-vault.yml --ask-vault-pass
# Later runs reuse the saved token and need only the hostname:
uv run ansible-playbook examples/configure.yml -e vco_host=vco.example.com
# Preview changes using authenticated reads:
uv run ansible-playbook examples/configure.yml -e vco_host=vco.example.com --check
```

The example uses an explicit `vco_token` first, then a saved token, and otherwise logs in with the operator credentials to create or download a named token. It saves the token beside the playbook in `examples/.tokens/<SHA-256 of vco_host>.token`, with file mode `0600` and a newly created directory mode `0700`. Override `vco_token_file` to save it in another private directory. Token directories are excluded from Git and collection builds, and bootstrap tasks suppress secret output.

`vco_token_name` defaults to `ansible-collection-example`; `vco_token_lifetime_ms` defaults to one year. An expired or revoked saved token causes authentication to fail. To issue a replacement, remove the saved file and supply credentials with a new token name. Check mode requires an explicit or saved token and never creates one. Set `vco_verify_ssl: false` explicitly for a self-signed lab VCO.

When creating a profile with attached segments, the profile module adds factory defaults to device settings, QoS (22 stock business-policy rules and four defaults), and firewall (`AllowAny` outbound, logging disabled). It preserves existing segment configuration rather than copying the Global Segment's customized settings.

## Limitations

- **`force: true` on `velocloud.api.edge` is destructive** — invalidates the activation key and telemetry history.
- **No purge mode** — removing a routed interface or BGP neighbor from the playbook does not delete it from the edge. Listed entries are reconciled, others are left alone.
- **No optimistic locking** — do not run `velocloud.api.edge_*` tasks against the same edge in parallel; use `serial: 1` or `throttle: 1`.
- **No concurrent reconciliation** of the same resource; VCO does not provide optimistic locking here.
- **VCO API variation** can affect accepted fields; `parameters` uses the orchestrator's native field names. Validate against a test VCO before production rollout.
- **Python 3.14** is required on the controller. pyvelo and pyvelo-intent do not support other interpreter versions, including newer ones that ansible-core may allow.

## Communication

- [GitHub Issues](https://github.com/kangwarn-arista/velocloud-ansible/issues) for bugs and feature requests. Anyone can file and view issues.
- [Ansible Forum Get Help](https://forum.ansible.com/c/help/6) for usage questions. Tag topics with the technology name (for example `velocloud`) when a matching tag exists.

## Versioning

This collection follows [semantic versioning](https://semver.org/). Until 1.0.0, a `0.y.z` minor bump may include breaking changes. After 1.0.0, patch releases fix bugs, minor releases add features, and major releases may break compatibility. See [CHANGELOG.md](CHANGELOG.md).

## Code of Conduct

This project follows the [Ansible Community Code of Conduct](https://docs.ansible.com/projects/ansible/latest/community/code_of_conduct.html). See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Development

```sh
uv sync
uv run pytest -q
uv run ansible-galaxy collection build . --output-path dist
```

The dev environment uses Python 3.14 and installs pyvelo so every module can be imported. Unit tests check that every module imports and that its documentation matches its argument spec. They also cover operator and SDK convergence, check mode, authentication and partial-failure recovery. Integration tests build and install the artifact into a temporary consumer directory and execute Ansible against a local mock VCO. GitHub Actions runs `ansible-test sanity` and `uv run pytest` on every pull request and weekly. Tests and development files are excluded from the released artifact. See [CONTRIBUTING.md](CONTRIBUTING.md) for pull-request expectations.

## Licensing

GNU General Public License v3.0 or later. See [COPYING](COPYING) for the full text.
