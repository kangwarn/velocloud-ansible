# Copyright: (c) 2026, Kangwarn Chinthammit
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Management module arguments without third-party runtime imports."""


def connection_argspec() -> dict:
    return dict(
        vco_host=dict(type="str", required=True),
        api_token=dict(type="str", no_log=True),
        username=dict(type="str"),
        password=dict(type="str", no_log=True),
        verify_ssl=dict(type="bool", default=True),
        timeout=dict(type="int", default=30),
        name=dict(type="str", required=True),
        state=dict(type="str", choices=["present", "absent"], default="present"),
        network_id=dict(type="int", default=1),
        gateway_pool_id=dict(type="int"),
        parameters=dict(type="dict", default={}),
    )


def auth_constraints() -> dict:
    return dict(
        mutually_exclusive=[("api_token", "username"), ("api_token", "password")],
        required_together=[("username", "password")],
        required_one_of=[("api_token", "username")],
    )
