import asyncio

from ansible_collections.velocloud.api.plugins.module_utils.topology import (
    WanLinkSettingsInput,
    apply_wan_link_settings,
)


class RecordingPipeline:
    def __init__(self):
        self.patches = []

    async def apply(self, state, module, patch):
        self.patches.append({"module": module, "patch": patch})
        return state


def _apply(spec):
    pipeline = RecordingPipeline()
    asyncio.run(apply_wan_link_settings(pipeline, object(), [spec]))
    assert pipeline.patches
    assert pipeline.patches[0]["module"] == "wan"
    return pipeline.patches[0]["patch"]["links"]


def test_orchestrator_reachability_survives_into_wan_patch():
    spec = WanLinkSettingsInput(
        **{
            "name": "ISP1",
            "type": "WIRED",
            "interfaces": ["GE3"],
            "mode": "PRIVATE",
            "discovery": "USER_DEFINED",
            "orchestrator_service_reachable": True,
            "orchestrator_service_reachable_backup": True,
        }
    )
    link = _apply(spec)["ISP1"]
    assert link["orchestratorServiceReachable"] is True
    assert link["orchestratorServiceReachableBackup"] is True


def test_unset_reachability_is_omitted_from_patch():
    spec = WanLinkSettingsInput(
        name="ISP2",
        type="WIRED",
        interfaces=["GE4"],
        mode="PUBLIC",
        discovery="USER_DEFINED",
    )
    link = _apply(spec)["ISP2"]
    assert "orchestratorServiceReachable" not in link
    assert "orchestratorServiceReachableBackup" not in link


def test_undeclared_wan_link_fields_are_forwarded():
    spec = WanLinkSettingsInput(
        **{
            "name": "ISP1",
            "type": "WIRED",
            "interfaces": ["GE3"],
            "mode": "PRIVATE",
            "discovery": "USER_DEFINED",
            "encrypt_overlay": False,
        }
    )
    link = _apply(spec)["ISP1"]
    assert link["encryptOverlay"] is False
