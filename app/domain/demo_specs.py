"""Reproducible demonstration inputs. No simulated outputs are stored here."""

from app.domain.models import SimulationSpec


def generalization_specs(*, confirmed: bool = False) -> dict[str, SimulationSpec]:
    """Additional reaction inputs; calculated product values are never prefilled."""
    definitions = {
        "shift": ("水煤气变换", {"Carbon Monoxide": 1/3, "Water": 2/3},
                  {"Carbon Monoxide": -1, "Water": -1, "Carbon Dioxide": 1, "Hydrogen": 1},
                  "Carbon Monoxide", 0.3),
        "reverse_shift": ("逆水煤气变换", {"Carbon Dioxide": 1/3, "Hydrogen": 2/3},
                          {"Carbon Dioxide": -1, "Hydrogen": -1,
                           "Carbon Monoxide": 1, "Water": 1}, "Carbon Dioxide", 0.2),
        "methanation": ("二氧化碳甲烷化", {"Carbon Dioxide": 1/6, "Hydrogen": 5/6},
                        {"Carbon Dioxide": -1, "Hydrogen": -4, "Methane": 1, "Water": 2},
                        "Carbon Dioxide", 0.1),
    }
    specs = {}
    for key, (title, composition, stoichiometry, base, conversion) in definitions.items():
        specs[key] = SimulationSpec.model_validate({
            "title": title, "reactor_type": "conversion", "fluid_package": "Peng-Robinson",
            "components": [{"user_name": name, "hysys_name": name} for name in stoichiometry],
            "feeds": [{"name": "Feed", "temperature": {"value": 300, "unit": "degC"},
                       "pressure": {"value": 1000, "unit": "kPa"},
                       "total_flow": {"value": 300, "unit": "kmol/h"},
                       "flow_basis": "molar", "composition": composition, "phase": "gas"}],
            "reactions": [{"id": "R1", "equation": str(stoichiometry),
                           "stoichiometry": stoichiometry, "base_component": base,
                           "conversion": conversion}],
            "known_conversion": conversion,
            "assumptions": [{"text": "反应器绝热运行，压降为0 kPa", "confirmed": confirmed}],
        })
    return specs


def toluene_spec(*, confirmed: bool = False) -> SimulationSpec:
    return SimulationSpec.model_validate({
        "title": "甲苯歧化：10000 kg/h，50%转化率",
        "reactor_type": "conversion",
        "fluid_package": "Peng-Robinson",
        "components": [{"user_name": name, "hysys_name": name} for name in (
            "Toluene", "Benzene", "o-Xylene", "m-Xylene", "p-Xylene",
        )],
        "feeds": [{
            "name": "Feed", "temperature": {"value": 380, "unit": "degC"},
            "pressure": {"value": 2500, "unit": "kPa"},
            "total_flow": {"value": 10000, "unit": "kg/h"},
            "flow_basis": "mass", "composition": {"Toluene": 1.0},
        }],
        "known_conversion": 0.5,
        "reactions": [{
            "id": f"R-{isomer}", "equation": f"2 Toluene -> Benzene + {isomer}",
            "stoichiometry": {"Toluene": -2, "Benzene": 1, isomer: 1},
        } for isomer in ("o-Xylene", "m-Xylene", "p-Xylene")],
        "assumptions": [
            {"text": "邻、间、对二甲苯按等选择性分配", "confirmed": confirmed},
            {"text": "反应器绝热运行，压降为0 kPa", "confirmed": confirmed},
        ],
    })


def reforming_spec(*, confirmed: bool = False) -> SimulationSpec:
    return SimulationSpec.model_validate({
        "title": "甲烷蒸汽重整：600℃与710℃",
        "reactor_type": "equilibrium", "fluid_package": "Peng-Robinson",
        "components": [{"user_name": name, "hysys_name": name} for name in (
            "Methane", "Water", "Carbon Monoxide", "Carbon Dioxide", "Hydrogen",
        )],
        "feeds": [{
            "name": "Feed", "temperature": {"value": 520, "unit": "degC"},
            "pressure": {"value": 1350, "unit": "kPa"},
            "total_flow": {"value": 3700, "unit": "kmol/h"},
            "flow_basis": "molar", "composition": {"Methane": 1/3.7, "Water": 2.7/3.7},
            "phase": "gas",
        }],
        "reactions": [
            {"id": "SMR", "equation": "CH4 + H2O <=> CO + 3H2", "reversible": True,
             "stoichiometry": {"Methane": -1, "Water": -1, "Carbon Monoxide": 1,
                               "Hydrogen": 3}},
            {"id": "WGS", "equation": "CO + H2O <=> CO2 + H2", "reversible": True,
             "stoichiometry": {"Carbon Monoxide": -1, "Water": -1,
                               "Carbon Dioxide": 1, "Hydrogen": 1}},
        ],
        "operating_cases": [{
            "name": f"{temperature}C",
            "outlet_temperature": {"value": temperature, "unit": "degC"},
            "outlet_pressure": {"value": 1350, "unit": "kPa"},
            "pressure_drop": {"value": 0, "unit": "kPa"},
        } for temperature in (600, 710)],
        "equilibrium_data_available": confirmed,
        "assumptions": [{
            "text": "甲烷1000 kmol/h、水2700 kmol/h；按8000小时/年计；零压降；"
                    "使用实机支持的HYSYS热力学平衡数据",
            "confirmed": confirmed,
        }],
    })
