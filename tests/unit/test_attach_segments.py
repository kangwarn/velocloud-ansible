from datetime import UTC, datetime
from uuid import UUID

import pytest

from pyvelo.client.enums.configuration import (
    ConfigurationModuleName,
    ConfigurationModuleType,
)
from pyvelo.client.enums.enterprise import NetworkSegmentType
from pyvelo.client.models.configuration.common import SegmentMetadata
from pyvelo.client.models.configuration.device_settings.lan import LanSettings
from pyvelo.client.models.configuration.device_settings.root import DeviceSettingsData
from pyvelo.client.models.configuration.device_settings.refs import DeviceSettingsRefs
from pyvelo.client.models.configuration.device_settings.segment import (
    DeviceSegment,
    DynamicVpnConfig,
    EdgeToEdgeDetail,
    SegmentVpn,
)
from pyvelo.client.models.configuration.firewall.root import FirewallData
from pyvelo.client.models.configuration.firewall.rules import FirewallOutboundRule
from pyvelo.client.models.configuration.firewall.rule_action import OutboundRuleAction
from pyvelo.client.models.configuration.firewall.rule_match import OutboundRuleMatch
from pyvelo.client.models.configuration.firewall.segment import FirewallSegment
from pyvelo.client.models.configuration.qos.root import QosData
from pyvelo.client.models.configuration.qos.rule import (
    QosRule,
    QosRuleAction,
    QosRuleMatch,
    RouteAction,
)
from pyvelo.client.models.configuration.qos.scheduler import QosScheduler, QosSettings
from pyvelo.client.models.configuration.qos.segment import QosSegment
from pyvelo.client.schemas.configuration import (
    DeviceSettingsConfigurationModule,
    EnterpriseConfigurationProfile,
    FirewallConfigurationModule,
    QosConfigurationModule,
)
from pyvelo.config.resolver import ResolverContext
from pyvelo_intent.config.state import ConfigState

from ansible_collections.velocloud.api.plugins.module_utils.topology import (
    _DEFAULT_QOS_DEFAULTS,
    _DEFAULT_QOS_RULES,
    attach_segments_to_profile,
)

_TS = datetime(2024, 1, 1, tzinfo=UTC)
_GLOBAL_LID = UUID("a5befd45-8290-4b52-b7d9-6de3256be153")
_CORP_LID = UUID("cb0cfcd4-8dbc-48ef-ba91-2b10cb1d2eba")
_CUSTOM_QOS_LID = UUID("11111111-1111-4111-8111-111111111111")


def _meta(name: str, segment_id: int, logical_id: UUID) -> SegmentMetadata:
    return SegmentMetadata(
        name=name,
        segment_id=segment_id,
        type_=NetworkSegmentType.REGULAR,
        segment_logical_id=logical_id,
    )


def _custom_qos_rule(
    name: str = "Custom", *, rule_logical_id: UUID | None = _CUSTOM_QOS_LID
) -> QosRule:
    return QosRule(
        name=name,
        match=QosRuleMatch(),
        action=QosRuleAction(
            route_type="edge2Any",
            edge_to_edge_route_action=RouteAction(),
            edge_to_data_center_route_action=RouteAction(),
            edge_to_cloud_route_action=RouteAction(),
            qos=QosSettings(
                rx_scheduler=QosScheduler(),
                tx_scheduler=QosScheduler(),
            ),
        ),
        rule_logical_id=rule_logical_id,
    )


def _profile_state() -> ConfigState:
    global_meta = _meta("Global Segment", 0, _GLOBAL_LID)
    ds = DeviceSettingsConfigurationModule(
        name="deviceSettings",
        data=DeviceSettingsData(
            lan=LanSettings(),
            segments=[
                DeviceSegment(
                    segment=global_meta,
                    vpn=SegmentVpn(
                        enabled=True,
                        edge_to_edge_detail=EdgeToEdgeDetail(
                            dynamic=DynamicVpnConfig(enabled=True)
                        ),
                    ),
                )
            ],
        ),
        created=_TS,
        modified=_TS,
        id_=200,
        type_=ConfigurationModuleType.ENTERPRISE,
        description=None,
        configuration_id=31,
        enterprise_logical_id=None,
        schema_version=None,
        version=None,
        metadata=None,
    )
    qos = QosConfigurationModule(
        name="QOS",
        data=QosData(
            segments=[
                QosSegment(segment=global_meta, rules=[_custom_qos_rule("Custom")])
            ]
        ),
        created=_TS,
        modified=_TS,
        id_=202,
        type_=ConfigurationModuleType.ENTERPRISE,
        description=None,
        configuration_id=31,
        enterprise_logical_id=None,
        schema_version=None,
        version=None,
        metadata=None,
    )
    fw = FirewallConfigurationModule(
        name="firewall",
        data=FirewallData(
            segments=[
                FirewallSegment(
                    segment=global_meta,
                    firewall_logging_enabled=True,
                    outbound=[
                        FirewallOutboundRule(
                            name="DenyAll",
                            match=OutboundRuleMatch(),
                            action=OutboundRuleAction(allow_or_deny="deny"),
                        )
                    ],
                )
            ]
        ),
        created=_TS,
        modified=_TS,
        id_=201,
        type_=ConfigurationModuleType.ENTERPRISE,
        description=None,
        configuration_id=31,
        enterprise_logical_id=None,
        schema_version=None,
        version=None,
        metadata=None,
    )
    profile = EnterpriseConfigurationProfile(
        name="Test Profile",
        id_=31,
        modules=[ds, qos, fw],
    )
    state = ConfigState(
        edge_config=None,
        profile_config=profile,
        target_type="profile",
        resolver_context=ResolverContext(),
    )
    state.take_snapshot()
    return state


def test_attach_writes_factory_defaults_on_all_three_modules():
    state = _profile_state()
    corp = _meta("Corp Segment", 1, _CORP_LID)
    original_segments = [
        module.data.segments[0].model_dump() for module in state.profile_config.modules
    ]

    assert attach_segments_to_profile(state, corp, NetworkSegmentType.REGULAR, 17)

    ds_names = [
        s.segment.name for s in state.profile_config.device_settings.data.segments
    ]
    qos_names = [s.segment.name for s in state.profile_config.qos.data.segments]
    fw_names = [s.segment.name for s in state.profile_config.firewall.data.segments]
    assert ds_names == ["Global Segment", "Corp Segment"]
    assert qos_names == ["Global Segment", "Corp Segment"]
    assert fw_names == ["Global Segment", "Corp Segment"]

    corp_ds = state.profile_config.device_settings.data.segments[1]
    assert corp_ds.vpn.enabled is False
    assert corp_ds.vpn.edge_to_edge_detail.dynamic.enabled is False

    corp_qos = state.profile_config.qos.data.segments[1]
    assert len(corp_qos.rules) == 22
    assert len(corp_qos.defaults) == 4
    assert [r.name for r in corp_qos.rules] == [
        spec.name for spec in _DEFAULT_QOS_RULES
    ]
    assert "Custom" not in [r.name for r in corp_qos.rules]
    assert [r.name for r in corp_qos.defaults] == [
        spec.name for spec in _DEFAULT_QOS_DEFAULTS
    ]
    # Factory rules omit ruleLogicalId so VCO can assign it; they must not
    # reuse the existing Global Segment rule id.
    assert state.profile_config.qos.data.segments[0].rules[0].rule_logical_id == (
        _CUSTOM_QOS_LID
    )
    assert all(r.rule_logical_id is None for r in corp_qos.rules)
    web = next(rule for rule in corp_qos.rules if rule.name == "Web")
    assert web.match.application_class_id == 19
    assert web.action.edge_to_cloud_route_action.route_policy == "direct"
    assert web.action.edge_to_edge_route_action.route_policy == "gateway"
    assert corp_qos.defaults[0].match.proto == 17
    assert corp_qos.defaults[0].action.qos.type_ == "realtime"

    corp_fw = state.profile_config.firewall.data.segments[1]
    assert corp_fw.firewall_logging_enabled is False
    assert [r.name for r in corp_fw.outbound] == ["AllowAny"]
    assert corp_fw.outbound[0].action.allow_or_deny == "allow"

    refs = state.profile_config.device_settings.refs.segment
    assert isinstance(refs, list)
    assert str(refs[0].logical_id) == str(_CORP_LID)

    changed = set(state.get_changed_modules())
    assert ConfigurationModuleName.DEVICE_SETTINGS in changed
    assert ConfigurationModuleName.QOS in changed
    assert ConfigurationModuleName.FIREWALL in changed
    assert [
        module.data.segments[0].model_dump() for module in state.profile_config.modules
    ] == original_segments


def test_attach_is_idempotent():
    state = _profile_state()
    corp = _meta("Corp Segment", 1, _CORP_LID)
    assert attach_segments_to_profile(state, corp, NetworkSegmentType.REGULAR, 17)
    assert not attach_segments_to_profile(state, corp, NetworkSegmentType.REGULAR, 17)
    assert len(state.profile_config.device_settings.data.segments) == 2
    assert len(state.profile_config.qos.data.segments) == 2
    assert len(state.profile_config.firewall.data.segments) == 2


def test_attach_completes_partial_attachment_without_resetting_existing_settings():
    state = _profile_state()
    corp = _meta("Corp Segment", 1, _CORP_LID)
    assert attach_segments_to_profile(state, corp, NetworkSegmentType.REGULAR, 17)
    corp_ds = state.profile_config.device_settings.data.segments[1]
    corp_ds.vpn.enabled = True
    state.profile_config.qos.data.segments.pop()
    state.profile_config.firewall.data.segments.pop()
    state.take_snapshot()

    assert attach_segments_to_profile(state, corp, NetworkSegmentType.REGULAR, 17)
    assert corp_ds.vpn.enabled is True
    assert len(state.profile_config.device_settings.refs.segment) == 1
    assert set(state.get_changed_modules()) == {
        ConfigurationModuleName.QOS,
        ConfigurationModuleName.FIREWALL,
    }


def test_attach_without_existing_segments_or_optional_modules():
    state = _profile_state()
    device_settings = state.profile_config.device_settings
    device_settings.data.segments.clear()
    state.profile_config.modules = [device_settings]
    state.take_snapshot()
    corp = _meta("Corp Segment", 1, _CORP_LID)

    assert attach_segments_to_profile(state, corp, NetworkSegmentType.REGULAR, 17)
    assert [s.segment.name for s in device_settings.data.segments] == ["Corp Segment"]
    assert set(state.get_changed_modules()) == {ConfigurationModuleName.DEVICE_SETTINGS}
    assert not attach_segments_to_profile(state, corp, NetworkSegmentType.REGULAR, 17)


@pytest.mark.parametrize("ref_format", ["typed", "dict", "none"])
def test_attach_preserves_existing_references_and_normalizes_singletons(ref_format):
    state = _profile_state()
    global_segment = state.profile_config.device_settings.data.segments[0].segment
    attach_segments_to_profile(state, global_segment, NetworkSegmentType.REGULAR, 1)
    device_settings = state.profile_config.device_settings
    if ref_format == "typed":
        device_settings.refs.segment = device_settings.refs.segment[0]
    elif ref_format == "dict":
        existing = device_settings.refs.segment[0].model_dump(by_alias=True)
        device_settings.refs = {"deviceSettings:segment": existing, "other": []}
    else:
        device_settings.refs = None
    corp = _meta("Corp Segment", 1, _CORP_LID)

    assert attach_segments_to_profile(state, corp, NetworkSegmentType.REGULAR, 17)
    assert not attach_segments_to_profile(state, corp, NetworkSegmentType.REGULAR, 17)
    if isinstance(device_settings.refs, DeviceSettingsRefs):
        refs = device_settings.refs.segment
        logical_ids = [str(ref.logical_id) for ref in refs]
    else:
        refs = device_settings.refs["deviceSettings:segment"]
        logical_ids = [str(ref["logicalId"]) for ref in refs]
        if ref_format == "dict":
            assert device_settings.refs["other"] == []
    assert logical_ids == (
        [str(_CORP_LID)] if ref_format == "none" else [str(_GLOBAL_LID), str(_CORP_LID)]
    )
