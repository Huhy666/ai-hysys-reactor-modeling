import pytest

from app.ai.parser import parse_request
from app.domain.models import SourceKind


class InMemoryProvider:
    def __init__(self, payload=None, error=None, response_id="resp-test"):
        self.payload = payload
        self.error = error
        self.last_response_id = response_id

    async def parse_modeling_request(self, text):
        if self.error:
            raise self.error
        return self.payload


def _steam_payload():
    return {
        "title": "甲烷蒸汽重整",
        "components": [
            {"user_name": "甲烷", "formula": "CH4", "hysys_name": "Methane"},
            {"user_name": "水", "formula": "H2O", "hysys_name": "Water"},
        ],
        "feeds": [
            {
                "name": "Feed",
                "temperature": {"value": 520, "unit": "degC"},
                "pressure": {"value": 13.5, "unit": "bar"},
                "total_flow": {"value": 3700, "unit": "kmol/h"},
                "flow_basis": "molar",
                "composition": {"Methane": 0.27027027, "Water": 0.72972973},
                "phase": "gas",
            }
        ],
        "reactions": [
            {
                "id": "R1",
                "equation": "CH4 + H2O <=> CO + 3H2",
                "stoichiometry": {"CH4": -1, "H2O": -1, "CO": 1, "H2": 3},
                "reversible": True,
            }
        ],
        "equilibrium_data_available": True,
    }


def _toluene_payload():
    return {
        "title": "甲苯歧化",
        "components": [
            {"user_name": "甲苯", "formula": "C7H8", "hysys_name": "Toluene"},
            {"user_name": "苯", "formula": "C6H6", "hysys_name": "Benzene"},
        ],
        "feeds": [
            {
                "name": "Feed",
                "temperature": {"value": 380, "unit": "degC"},
                "pressure": {"value": 2.5, "unit": "MPa"},
                "total_flow": {"value": 10000, "unit": "kg/h"},
                "flow_basis": "mass",
                "composition": {"Toluene": 1.0},
                "phase": "liquid",
            }
        ],
        "reactions": [
            {
                "id": "R1",
                "equation": "2C7H8 -> C6H6 + C8H10",
                "stoichiometry": {"C7H8": -2, "C6H6": 1, "C8H10": 1},
            }
        ],
        "known_conversion": 0.5,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [_steam_payload(), _toluene_payload()])
async def test_parse_request_returns_strict_editable_draft(payload):
    result = await parse_request("用户输入", InMemoryProvider(payload))

    assert result.spec is not None
    assert result.issues == []
    assert result.raw_provider_id == "resp-test"
    assert result.spec.components[0].source is SourceKind.AI_EXTRACTED
    assert result.spec.feeds[0].temperature.source is SourceKind.AI_EXTRACTED


@pytest.mark.asyncio
async def test_parse_request_rejects_non_object_payload():
    result = await parse_request("bad", InMemoryProvider("not-json"))

    assert result.spec is None
    assert {issue.code for issue in result.issues} == {"provider_payload_invalid"}


@pytest.mark.asyncio
async def test_parse_request_rejects_unknown_fields():
    payload = _steam_payload() | {"surprise": "not allowed"}

    result = await parse_request("bad", InMemoryProvider(payload))

    assert result.spec is None
    assert {issue.code for issue in result.issues} == {"schema_validation_failed"}


@pytest.mark.asyncio
async def test_parse_request_rejects_quantity_without_unit():
    payload = _steam_payload()
    payload["feeds"][0]["temperature"] = {"value": 520}

    result = await parse_request("bad", InMemoryProvider(payload))

    assert result.spec is None
    assert {issue.code for issue in result.issues} == {"schema_validation_failed"}


@pytest.mark.asyncio
async def test_parse_request_converts_provider_timeout_to_issue():
    result = await parse_request("slow", InMemoryProvider(error=TimeoutError("secret url")))

    assert result.spec is None
    assert {issue.code for issue in result.issues} == {"provider_timeout"}
    assert "secret url" not in result.issues[0].message


@pytest.mark.asyncio
async def test_parse_request_rejects_fabricated_hysys_results():
    payload = _steam_payload() | {"simulation_results": {"Hydrogen": 99.9}}

    result = await parse_request("bad", InMemoryProvider(payload))

    assert result.spec is None
    assert {issue.code for issue in result.issues} == {"schema_validation_failed"}


@pytest.mark.asyncio
async def test_parse_request_canonicalizes_component_and_composition_aliases():
    payload = _steam_payload()
    payload["components"] = [
        {"user_name": "甲烷", "hysys_name": None, "matched": False},
        {"user_name": "水蒸气", "hysys_name": None, "matched": False},
    ]
    payload["feeds"][0]["composition"] = {"甲烷": 10 / 37, "水蒸气": 27 / 37}

    result = await parse_request("用户输入", InMemoryProvider(payload))

    assert result.spec is not None
    assert [(item.hysys_name, item.matched) for item in result.spec.components] == [
        ("Methane", True),
        ("Water", True),
    ]
    assert result.spec.feeds[0].composition == {
        "Methane": pytest.approx(10 / 37),
        "Water": pytest.approx(27 / 37),
    }


@pytest.mark.asyncio
async def test_parse_request_recovers_explicit_reforming_facts_from_user_text():
    payload = _steam_payload()
    payload["reactor_type"] = "gibbs"
    payload["product_distribution_unknown"] = True
    payload["high_temperature"] = True
    payload["feeds"][0]["pressure"] = None
    payload["feeds"][0]["total_flow"] = None
    payload["feeds"][0]["flow_basis"] = None
    payload["feeds"][0]["composition"] = {}
    payload["operating_cases"] = []
    text = (
        "使用 HYSYS 可用的热力学平衡数据，在 Equilibrium Reactor 中模拟。"
        "进料总流量 3700 kmol/h，摩尔组成 Methane=0.27027027、Water=0.72972973，"
        "温度 520 degC，绝对压力 1350 kPa。比较出口温度 600 degC 与 710 degC "
        "两个工况；两个工况出口绝对压力均为 1350 kPa，压降均为 0 kPa。"
    )

    result = await parse_request(text, InMemoryProvider(payload))

    assert result.spec is not None
    assert result.spec.reactor_type.value == "equilibrium"
    assert result.spec.equilibrium_data_available is True
    feed = result.spec.feeds[0]
    assert feed.total_flow.value == 3700
    assert feed.total_flow.unit == "kmol/h"
    assert feed.flow_basis == "molar"
    assert feed.pressure.value == 1350
    assert feed.pressure.unit == "kPa"
    assert feed.composition == {
        "Methane": pytest.approx(0.27027027),
        "Water": pytest.approx(0.72972973),
    }
    assert [item.outlet_temperature.value for item in result.spec.operating_cases] == [
        600,
        710,
    ]
    assert all(item.outlet_pressure.value == 1350 for item in result.spec.operating_cases)
    assert all(item.pressure_drop.value == 0 for item in result.spec.operating_cases)


@pytest.mark.asyncio
async def test_parse_request_discards_provider_reactor_not_stated_by_user():
    payload = _steam_payload() | {"reactor_type": "gibbs"}

    result = await parse_request("请模拟甲烷蒸汽重整", InMemoryProvider(payload))

    assert result.spec is not None
    assert result.spec.reactor_type is None
