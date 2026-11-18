# Copyright: (c) 2026, Kangwarn Chinthammit
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""SDK module arguments without third-party runtime imports."""


def common_argspec() -> dict:
    """Argument spec fragments shared by every SDK module."""
    return dict(
        vco_host=dict(type="str", required=True),
        api_token=dict(type="str", required=False, no_log=True),
        username=dict(type="str", required=False),
        password=dict(type="str", required=False, no_log=True),
        enterprise_id=dict(type="int", required=False),
        verify_ssl=dict(type="bool", required=False, default=True),
    )


def common_argspec_constraints() -> dict:
    """`mutually_exclusive` / `required_one_of` / `required_together` constraints."""
    return dict(
        mutually_exclusive=[
            ("api_token", "username"),
            ("api_token", "password"),
        ],
        required_together=[("username", "password")],
        required_one_of=[("api_token", "username")],
    )
