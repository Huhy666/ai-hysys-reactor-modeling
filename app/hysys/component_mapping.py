from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class MatchStatus(StrEnum):
    EXACT = "exact"
    ALIAS = "alias"
    AMBIGUOUS = "ambiguous"
    NOT_FOUND = "not_found"


class ComponentMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    status: MatchStatus
    hysys_name: str | None = None
    candidates: list[str] = Field(default_factory=list)
    requires_confirmation: bool = False


COMPONENT_ALIASES: dict[str, tuple[str, ...]] = {
    "Methane": ("methane", "甲烷", "ch4"),
    "Water": ("water", "steam", "水", "水蒸气", "蒸汽", "h2o"),
    "Carbon Monoxide": ("carbon monoxide", "一氧化碳", "co"),
    "Carbon Dioxide": ("carbon dioxide", "二氧化碳", "co2"),
    "Hydrogen": ("hydrogen", "氢", "氢气", "h2"),
    "Toluene": ("toluene", "甲苯", "c7h8"),
    "Benzene": ("benzene", "苯", "c6h6"),
    "o-Xylene": ("o-xylene", "ortho-xylene", "邻二甲苯"),
    "m-Xylene": ("m-xylene", "meta-xylene", "间二甲苯"),
    "p-Xylene": ("p-xylene", "para-xylene", "对二甲苯"),
}

AMBIGUOUS_ALIASES: dict[str, tuple[str, ...]] = {
    "二甲苯": ("o-Xylene", "m-Xylene", "p-Xylene"),
    "xylene": ("o-Xylene", "m-Xylene", "p-Xylene"),
    "c8h10": ("o-Xylene", "m-Xylene", "p-Xylene"),
}


def _normalize(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def resolve_component(user_name: str) -> ComponentMatch:
    query = user_name.strip()
    normalized = _normalize(query)
    if not normalized:
        return ComponentMatch(
            query=user_name,
            status=MatchStatus.NOT_FOUND,
            requires_confirmation=True,
        )

    for hysys_name in COMPONENT_ALIASES:
        if normalized == _normalize(hysys_name):
            return ComponentMatch(
                query=query,
                status=MatchStatus.EXACT,
                hysys_name=hysys_name,
            )

    ambiguous = AMBIGUOUS_ALIASES.get(normalized)
    if ambiguous:
        return ComponentMatch(
            query=query,
            status=MatchStatus.AMBIGUOUS,
            candidates=list(ambiguous),
            requires_confirmation=True,
        )

    matches = [
        hysys_name
        for hysys_name, aliases in COMPONENT_ALIASES.items()
        if normalized in {_normalize(alias) for alias in aliases}
    ]
    if len(matches) == 1:
        return ComponentMatch(
            query=query,
            status=MatchStatus.ALIAS,
            hysys_name=matches[0],
        )
    if len(matches) > 1:
        return ComponentMatch(
            query=query,
            status=MatchStatus.AMBIGUOUS,
            candidates=matches,
            requires_confirmation=True,
        )
    return ComponentMatch(
        query=query,
        status=MatchStatus.NOT_FOUND,
        requires_confirmation=True,
    )
