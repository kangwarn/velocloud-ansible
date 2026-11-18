#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Kangwarn Chinthammit
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Configure an enterprise and its initial configuration profile."""

DOCUMENTATION = r"""
module: enterprise
short_description: Configure VeloCloud enterprises and their initial profile
description:
  - Create, update or remove enterprises by name.
  - Feature, delegation and license settings in O(parameters) apply at creation.
  - Existing enterprises are updated only for fields accepted by updateEnterprise
    (name, description, gatewayPoolId, contact, address, alert, domain, prefix,
    locale, timezone, lat and lon); other supplied fields are ignored.
  - Ensure a Quick Start Profile exists, including recovery after partial creation.
version_added: "0.1.0"
author:
  - Kangwarn Chinthammit (@kangwarn-arista)
extends_documentation_fragment: [velocloud.api.operator]
options:
  configuration_id:
    description:
      - Initial operator configuration ID, used only during enterprise creation.
      - Existing enterprise profile assignments can be supplied through parameters using assignedOperatorProfileConfigurationIds.
    type: int
  auto_create_profile:
    description: Ensure the enterprise has a Quick Start Profile cloned from its segmented template.
    type: bool
    default: true
"""

EXAMPLES = r"""
- name: Configure an enterprise
  velocloud.api.enterprise:
    vco_host: vco.example.com
    api_token: "{{ vco_token }}"
    name: Example Enterprise
    gateway_pool_id: 1
    configuration_id: 6
    parameters:
      description: Managed by Ansible
      enableEnterpriseDelegationToOperator: true
      assignedOperatorProfileConfigurationIds: [6]
      licenses:
        ids: [1, 2]
  register: enterprise_result
"""

RETURN = r"""
enterprise:
  description: Enterprise API record, including auto_created_config when profile management is enabled.
  type: dict
  returned: always
result:
  description: Alias of enterprise for legacy playbook compatibility.
  type: dict
  returned: always
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
        configuration_id=dict(type="int"),
        auto_create_profile=dict(type="bool", default=True),
    )
    module = AnsibleModule(
        argument_spec=argspec, supports_check_mode=True, **auth_constraints()
    )
    if IMPORT_ERROR:
        module.fail_json(msg=f"Install collection Python requirements: {IMPORT_ERROR}")
    execute_module(module, "enterprise")


if __name__ == "__main__":
    main()
