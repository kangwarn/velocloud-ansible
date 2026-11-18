from types import SimpleNamespace

from ansible_collections.velocloud.api.plugins.module_utils.diff import (
    diff_dicts,
    edge_drift,
    profile_drift,
    segment_drift,
)


def test_diff_dicts_compares_supplied_fields_and_nested_dicts():
    desired = {"name": "a", "site": {"city": "NY"}, "ignored_elsewhere": True}
    actual = {"name": "a", "site": {"city": "SF", "state": "NY"}, "extra": 1}
    diff = diff_dicts(desired, actual)
    assert "name" not in diff
    assert diff["site"]["desired"] == {"city": "NY"}
    assert diff["site"]["_nested"]["city"] == {"desired": "NY", "actual": "SF"}
    assert "ignored_elsewhere" in diff


def test_segment_drift_skips_matching_records():
    existing = SimpleNamespace(
        name="seg",
        type_="REGULAR",
        description="",
        data=SimpleNamespace(
            segment_id=1,
            delegate_to_enterprise=True,
            delegate_to_enterprise_proxy=True,
        ),
    )
    spec = {
        "name": "seg",
        "type": "REGULAR",
        "description": "",
        "segment_id": 1,
        "delegate_to_enterprise": True,
        "delegate_to_enterprise_proxy": True,
    }
    assert segment_drift(spec, existing) == {}
    spec["segment_id"] = 99
    assert segment_drift(spec, existing)["segment_id"]["desired"] == 99


def test_profile_and_edge_drift_only_compare_top_level_fields():
    profile = SimpleNamespace(name="p", description="old")
    assert (
        profile_drift({"name": "p", "description": "old", "segments": ["x"]}, profile)
        == {}
    )
    assert "description" in profile_drift({"name": "p", "description": "new"}, profile)

    edge = SimpleNamespace(
        name="e", model_number="virtual", edge_license_id=1, configuration_id=2
    )
    assert edge_drift({"name": "e", "model_number": "virtual"}, edge) == {}
    assert "model_number" in edge_drift({"name": "e", "model_number": "edge520"}, edge)
