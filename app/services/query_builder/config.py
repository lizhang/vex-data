"""Configuration for the query builder: field/order/strategy registries and field-specific handlers.

All data lives here. The generic pipeline in query_builder.py never branches on
specific fields or strategies — it only consults these maps.
"""
from dataclasses import dataclass, field
from typing import Callable, Optional

from fastapi import HTTPException


# ── Dataclasses ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FieldSpec:
    column: Optional[str] = None           # canonical "table.column", or "{base}.col" for partition
    handler: Optional[Callable] = None     # (op, value) -> (sql, params); overrides column
    require_op: Optional[str] = None       # if set, op must equal this


@dataclass(frozen=True)
class OrderSpec:
    column: Optional[str] = None           # "table.column" expression
    handler: Optional[Callable] = None     # (direction, conditions) -> (sql, params)


@dataclass(frozen=True)
class Strategy:
    name: str
    base: str                              # base table name (no alias)
    select_cols: str                       # explicit SELECT list (or "*")
    accessible_tables: frozenset           # tables this strategy can join to
    join_recipes: dict                     # tablename -> JOIN SQL fragment (uses {db})
    special_handlers: dict = field(default_factory=dict)
    special_orders: dict = field(default_factory=dict)
    default_order: Optional[str] = None    # full SQL fragment, e.g. "team_event_summary.ranking ASC"
    validators: tuple = ()                 # ((predicate(q) -> bool, message), ...)


# ── Query introspection helpers (used by handlers and validators) ──────────

def _has_field(q, field_name: str) -> bool:
    fg = q.filter
    if not fg:
        return False
    return any(c.field == field_name for c in (fg.and_ or []) + (fg.or_ or []))


def _find_value(conditions, field_name: str):
    for c in conditions:
        if c.field == field_name:
            return c.value
    return None


# ── Field-specific handlers ────────────────────────────────────────────────

def _match_start_handler(op, value):
    return "COALESCE(matches.started_time, matches.scheduled_time) > TIMESTAMP ?", [value]


def _match_end_handler(op, value):
    return (
        "matches.started_time IS NOT NULL "
        "AND matches.started_time + INTERVAL '5' MINUTE < TIMESTAMP ?"
    ), [value]


def _match_team_number_handler(op, value):
    if op != "eq":
        raise HTTPException(status_code=422, detail="teams.number in matches requires op=eq")
    return (
        "(EXISTS (SELECT 1 FROM UNNEST(matches.red_teams) t WHERE t.number = ?) "
        "OR EXISTS (SELECT 1 FROM UNNEST(matches.blue_teams) t WHERE t.number = ?))"
    ), [value, value]


def _matches_score_order(direction, conditions):
    team_no = _find_value(conditions, "teams.number")
    return (
        f"CASE WHEN EXISTS (SELECT 1 FROM UNNEST(matches.red_teams) t WHERE t.number = ?) "
        f"THEN matches.red_score ELSE matches.blue_score END {direction.upper()}"
    ), [team_no]


# ── Global FIELDS map ──────────────────────────────────────────────────────

FIELDS: dict[str, FieldSpec] = {
    # Partition columns — base table prefix substituted at build time
    "season_id":  FieldSpec(column="{base}.p_season_id"),
    "program_id": FieldSpec(column="{base}.p_program_id"),

    # Events
    "events.name":       FieldSpec(column="events.name"),
    "events.sku":        FieldSpec(column="events.sku"),
    "events.city":       FieldSpec(column="events.city"),
    "events.country":    FieldSpec(column="events.country"),
    "events.region":     FieldSpec(column="events.region"),
    "events.venue":      FieldSpec(column="events.venue"),
    "events.postcode":   FieldSpec(column="events.postcode"),
    "events.start_time": FieldSpec(column="events.start_date", require_op="gt"),
    "events.end_time":   FieldSpec(column="events.end_date",   require_op="lt"),

    # Teams
    "teams.name":     FieldSpec(column="teams.team_name"),
    "teams.number":   FieldSpec(column="teams.number"),
    "teams.city":     FieldSpec(column="teams.city"),
    "teams.country":  FieldSpec(column="teams.country"),
    "teams.region":   FieldSpec(column="teams.region"),
    "teams.postcode": FieldSpec(column="teams.postcode"),

    # Matches time (special — COALESCE / INTERVAL)
    "matches.start_time": FieldSpec(handler=_match_start_handler, require_op="gt"),
    "matches.end_time":   FieldSpec(handler=_match_end_handler,   require_op="lt"),
}


# ── Global ORDERS map ──────────────────────────────────────────────────────

ORDERS: dict[str, OrderSpec] = {
    "events.time":             OrderSpec(column="events.start_date"),
    "matches.time":            OrderSpec(column="matches.scheduled_time"),
    "matches.score":           OrderSpec(handler=_matches_score_order),
    "rankings.rank":           OrderSpec(column="team_event_summary.ranking"),
    "events.skills_rank":      OrderSpec(column="team_event_summary.skills_rank"),
    "events.score":            OrderSpec(column="team_event_summary.best_score"),
    "teams.best_skill_score":  OrderSpec(column="team_skill_summary.best_skill_score"),
    "teams.worst_skill_score": OrderSpec(column="team_skill_summary.worst_skill_score"),
    "teams.avg_skill_score":   OrderSpec(column="team_skill_summary.avg_skill_score"),
    "teams.high_score":        OrderSpec(column="team_score_summary.high_score"),
    "teams.average_points":    OrderSpec(column="team_score_summary.average_points"),
    "teams.total_points":      OrderSpec(column="team_score_summary.total_points"),
}


# ── Routing sets (used by select_strategy) ─────────────────────────────────

SKILL_SCORE_FIELDS = frozenset({
    "teams.best_skill_score", "teams.worst_skill_score", "teams.avg_skill_score",
})
SCORE_SUMMARY_FIELDS = frozenset({
    "teams.high_score", "teams.average_points", "teams.total_points",
})


# ── JOIN recipes ───────────────────────────────────────────────────────────

_J_EVENTS_FROM_MATCHES = (
    "LEFT JOIN {db}.events "
    "ON matches.event_id = events.event_id "
    "AND matches.p_season_id = events.p_season_id "
    "AND matches.p_program_id = events.p_program_id"
)

_J_EVENTS_FROM_TES = (
    "LEFT JOIN {db}.events "
    "ON team_event_summary.event_id = events.event_id "
    "AND team_event_summary.p_season_id = events.p_season_id "
    "AND team_event_summary.p_program_id = events.p_program_id"
)

_J_TEAMS_FROM_TES = (
    "LEFT JOIN {db}.teams "
    "ON team_event_summary.team_id = teams.team_id "
    "AND team_event_summary.p_season_id = teams.p_season_id "
    "AND team_event_summary.p_program_id = teams.p_program_id"
)

_J_TSS_FROM_TEAMS = (
    "LEFT JOIN {db}.team_skill_summary "
    "ON teams.team_id = team_skill_summary.team_id "
    "AND teams.p_season_id = team_skill_summary.p_season_id "
    "AND teams.p_program_id = team_skill_summary.p_program_id"
)

_J_TSCORE_FROM_TEAMS = (
    "LEFT JOIN {db}.team_score_summary "
    "ON teams.team_id = team_score_summary.team_id "
    "AND teams.p_season_id = team_score_summary.p_season_id "
    "AND teams.p_program_id = team_score_summary.p_program_id"
)


# ── Validators (predicates over SearchQuery) ───────────────────────────────

def _matches_score_requires_team_number(q) -> bool:
    if not q.orderBy or q.orderBy.field != "matches.score":
        return True
    return _has_field(q, "teams.number")


# ── Strategy registry ──────────────────────────────────────────────────────

_TEAM_T_SELECT = (
    "teams.team_id, teams.number, teams.team_name, teams.organization, "
    "teams.program_id, teams.program_name, teams.city, teams.region, "
    "teams.postcode, teams.country, teams.grade, teams.registered"
)

STRATEGIES: dict[str, Strategy] = {
    "EVENTS": Strategy(
        name="EVENTS",
        base="events",
        select_cols="*",
        accessible_tables=frozenset({"events"}),
        join_recipes={},
    ),

    "MATCHES": Strategy(
        name="MATCHES",
        base="matches",
        select_cols="*",
        accessible_tables=frozenset({"matches", "events"}),
        join_recipes={"events": _J_EVENTS_FROM_MATCHES},
        special_handlers={"teams.number": _match_team_number_handler},
        validators=(
            (_matches_score_requires_team_number,
             "orderBy.field='matches.score' requires a teams.number filter"),
        ),
    ),

    "TEAM_EVENT": Strategy(
        name="TEAM_EVENT",
        base="team_event_summary",
        select_cols="team_event_summary.*",
        accessible_tables=frozenset({"team_event_summary", "events", "teams"}),
        join_recipes={
            "events": _J_EVENTS_FROM_TES,
            "teams":  _J_TEAMS_FROM_TES,
        },
        default_order="team_event_summary.ranking ASC",
    ),

    "TEAM_SKILL": Strategy(
        name="TEAM_SKILL",
        base="teams",
        select_cols=(
            f"{_TEAM_T_SELECT}, "
            "team_skill_summary.best_skill_score, team_skill_summary.worst_skill_score, "
            "team_skill_summary.avg_skill_score, team_skill_summary.best_skill_event_id, "
            "team_skill_summary.worst_skill_event_id"
        ),
        accessible_tables=frozenset({"teams", "team_skill_summary"}),
        join_recipes={"team_skill_summary": _J_TSS_FROM_TEAMS},
    ),

    "TEAM_SCORE": Strategy(
        name="TEAM_SCORE",
        base="teams",
        select_cols=(
            f"{_TEAM_T_SELECT}, "
            "team_score_summary.high_score, team_score_summary.average_points, "
            "team_score_summary.total_points, team_score_summary.best_score_event_id"
        ),
        accessible_tables=frozenset({"teams", "team_score_summary"}),
        join_recipes={"team_score_summary": _J_TSCORE_FROM_TEAMS},
    ),
}
