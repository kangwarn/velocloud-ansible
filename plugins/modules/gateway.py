#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Kangwarn Chinthammit
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Configure a gateway record without activating its device."""

DOCUMENTATION = r"""
module: gateway
short_description: Configure VeloCloud gateway records without device activation
description:
  - Create or remove operator gateway records by name.
  - Device activation is a separate SSH or cloud-init workflow.
  - Existing records are left unchanged; their activation key is returned.
version_added: "0.1.0"
author:
  - Kangwarn Chinthammit (@kangwarn-arista)
extends_documentation_fragment: [velocloud.api.operator]
options:
  ip_address:
    description: Gateway IPv4 address. Required when creating a gateway.
    type: str
  service_state:
    description: Gateway service state. New gateways default to IN_SERVICE.
    type: str
    choices: [IN_SERVICE, OUT_OF_SERVICE]
"""

EXAMPLES = r"""
- name: Configure a gateway; activation is performed separately
  velocloud.api.gateway:
    vco_host: vco.example.com
    api_token: "{{ vco_token }}"
    name: gateway-1
    ip_address: 192.0.2.10
    gateway_pool_id: 1
  register: gateway_result
  no_log: true
"""

RETURN = r"""
gateway:
  description: Gateway API record. May contain an activationKey; protect registered output.
  type: dict
  returned: always
result:
  description: Alias of gateway for legacy playbook compatibility.
  type: dict
  returned: always
activation_key:
  description: Activation key for a separate activation workflow; empty if unavailable.
  type: str
  returned: when state is present
"""

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.velocloud.api.plugins.module_utils.operator_args import (
    auth_constraints,
    connection_argspec,
)

try:
    from ansible_collections.velocloud.api.plugins.module_utils.operator import (
        execute_module,
    )

    IMPORT_ERROR = None
except ImportError as exc:
    IMPORT_ERROR = str(exc)


def main() -> None:
    argspec = connection_argspec()
    argspec.update(
        ip_address=dict(type="str"),
        service_state=dict(type="str", choices=["IN_SERVICE", "OUT_OF_SERVICE"]),
    )
    module = AnsibleModule(
        argument_spec=argspec, supports_check_mode=True, **auth_constraints()
    )
    if IMPORT_ERROR:
        module.fail_json(msg=f"Install collection Python requirements: {IMPORT_ERROR}")
    execute_module(module, "gateway")


if __name__ == "__main__":
    main()
