# Copyright: (c) 2026, Kangwarn Chinthammit
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)


class ModuleDocFragment:
    DOCUMENTATION = r"""
options:
  vco_host:
    description: Orchestrator hostname or hostname:port, optionally prefixed with https://.
    type: str
    required: true
  api_token:
    description: Operator API token, sent using the VCO Token authentication scheme.
    type: str
  username:
    description: Operator username for cookie authentication.
    type: str
  password:
    description: Operator password. Required with username.
    type: str
  verify_ssl:
    description: Validate the orchestrator TLS certificate.
    type: bool
    default: true
  timeout:
    description: Timeout for each HTTP request in seconds.
    type: int
    default: 30
  name:
    description: Unique resource name within the operator network.
    type: str
    required: true
  network_id:
    description: Operator network to search for the resource.
    type: int
    default: 1
  state:
    description: Whether the resource should exist. Deletion does not delete dependent resources first.
    type: str
    choices: [present, absent]
    default: present
  gateway_pool_id:
    description: Gateway pool ID. Only managed when supplied; new gateways default to pool 1.
    type: int
  parameters:
    description:
      - Additional VCO API configuration fields in camelCase.
      - Only supplied fields are reconciled. Unspecified nested fields are retained.
      - Identity, activation and control fields cannot be supplied here.
      - Explicit module options take precedence over matching API fields.
    type: dict
    default: {}
requirements:
  - requests >= 2.32.5
  - pydantic >= 2.0
notes:
  - Use either api_token or username and password, with operator permissions.
  - Check mode reads the orchestrator but never writes configuration.
"""
