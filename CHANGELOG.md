# Changelog

## 0.1.0

- Initial public release of the `velocloud.api` collection. Install with
  `ansible-galaxy collection install git+<repo-url>`.
- Gateway and enterprise modules with operator authentication, check mode,
  and idempotent deletion. Existing gateways are skipped; their record and
  activation key are returned. `deleteGateway` sends `id`.
- Enterprise updates on existing enterprises send only fields accepted by
  `updateEnterprise`. Initial Quick Start Profile creation is retry-safe.
- Gateway creation reads the activation key from the network gateway list,
  falling back to `getGateway` when the list entry omits it.
- Segment, profile, edge, and `edge_*` configuration modules.
- Edge LAN routed/switched patches clear the interface's other representation
  so an interface can change type.
- `edge` returns the edge's own activation key when creation returns none.
- Add `profile_vpn` to configure CloudVPN on a profile segment, including hub
  designation (`enableEdgeForEdgeHub` / `BackHaul` / `EdgeToEdgeBridge`) and
  `deviceSettings:vpn:edgeHub` refs. Hub edges are resolved by name; hub
  clusters are not supported yet. `edge_to_data_center` is Branch-to-Site and
  is not used to enable hub backhaul.
- Apply profile firewall SSH access (`enabled` and `allow_selected_ip`) via
  pyvelo `FirewallServicesGroup`. Firewall services are also patched on
  existing profiles when name and description already match, so SSH and
  console access do not require deleting and recreating the profile.
- Keep `orchestrator_service_reachable` and
  `orchestrator_service_reachable_backup` on `wan_link_settings` (PRIVATE
  links). Unknown `WanLink` keys are forwarded instead of being dropped.
- Attach profile segments with factory defaults across device settings, QoS,
  and firewall, preserving existing segment settings and avoiding duplicates.
- Single `requirements.txt` runtime (requests, Pydantic 2, loguru, pyvelo,
  pyvelo-intent). pyvelo is pinned at a fork commit that contains
  `pyvelo-intent`.
- TLS verification defaults to true on all modules.
- Added `COPYING` (GPL-3.0-or-later), Code of Conduct, and contributing docs.
- ansible-test sanity is clean for MUST-NOT-ignore validate-modules checks.
  SDK modules load argument specs from `sdk_args` so introspection does not
  require pyvelo. Third-party `module_utils` imports are listed in
  `tests/sanity/ignore-*.txt`.
- Pin ansible-test sanity in CI to Python 3.14, the only controller
  interpreter this collection supports, and require ansible-core 2.20 or later.
- GitHub Actions runs ansible-test sanity (ansible-core 2.20–2.22 and devel)
  and `uv run pytest` on Python 3.14, including a weekly schedule.
- Pin the pytest job to `astral-sh/setup-uv@v10.3.3` (there is no floating `v10`
  tag) and drop unreachable `return` after `fail_json` so devel pylint passes.
  `execute_module` uses `else` so mocked `fail_json` still does not fall through
  to `exit_json`.
- Add a standalone gateway and enterprise example that creates or downloads
  an operator API token, saves it privately, and reuses it on later runs.
- Exclude saved token directories from Git and collection artifacts, and
  cover token bootstrap, reuse, and profile segment defaults in tests.
- Behaviour tests cover SDK CRUD modules, `edge_*` patch check mode, and drift helpers.
