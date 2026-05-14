"""Generic query builder pipeline.

build_query(SearchQuery) -> (sql, params)

All field-specific knowledge lives in config.py. This module never branches on
specific field names — it consults FIELDS, ORDERS, and STRATEGIES.
"""
import structlog
from fastapi import HTTPException

from app.models.schemas import SearchQuery

from .config import (
    FIELDS,
    ORDERS,
    SCORE_SUMMARY_FIELDS,
    SKILL_SCORE_FIELDS,
    STRATEGIES,
    Strategy,
)


log = structlog.get_logger(__name__)


# ── Op-to-SQL emitter (generic, for fields without a custom handler) ──────

_TIME_COL_HINTS = ("start_date", "end_date", "scheduled_time", "started_time")


def _is_time_col(col: str) -> bool:
    return any(h in col for h in _TIME_COL_HINTS)


def _emit_op(col: str, op: str, value):
    if op == "contains":
        return f"LOWER({col}) LIKE LOWER(?)", [f"%{value}%"]
    if op == "eq":
        return f"{col} = ?", [value]
    if op == "neq":
        return f"{col} != ?", [value]
    if op == "gt":
        return (f"{col} > TIMESTAMP ?", [value]) if _is_time_col(col) else (f"{col} > ?", [value])
    if op == "lt":
        return (f"{col} < TIMESTAMP ?", [value]) if _is_time_col(col) else (f"{col} < ?", [value])
    raise HTTPException(status_code=422, detail=f"Unsupported op {op!r}")


# ── Pipeline steps ────────────────────────────────────────────────────────

def select_strategy(q: SearchQuery) -> Strategy:
    if q.entity == "events":
        return STRATEGIES["EVENTS"]
    if q.entity == "matches":
        return STRATEGIES["MATCHES"]
    # entity == "team"
    f = q.orderBy.field if q.orderBy else None
    if f in SKILL_SCORE_FIELDS:
        return STRATEGIES["TEAM_SKILL"]
    if f in SCORE_SUMMARY_FIELDS:
        return STRATEGIES["TEAM_SCORE"]
    return STRATEGIES["TEAM_EVENT"]


def _table_of(column):
    if not column or "." not in column:
        return None
    return column.split(".", 1)[0]


def _extract_conditions(q: SearchQuery):
    fg = q.filter
    if not fg:
        return [], False
    if fg.and_ is not None and fg.or_ is not None:
        raise HTTPException(
            status_code=422,
            detail="filter must contain exactly one of 'and' or 'or'",
        )
    return (fg.and_ or fg.or_ or []), bool(fg.or_)


def _resolve_filter(condition, strategy: Strategy):
    """Returns (sql_fragment, params, referenced_table_or_None)."""
    # 1. Strategy-specific override (e.g., teams.number in MATCHES uses UNNEST)
    if condition.field in strategy.special_handlers:
        sql, params = strategy.special_handlers[condition.field](condition.op, condition.value)
        return sql, params, None

    # 2. Global FIELDS lookup
    spec = FIELDS.get(condition.field)
    if not spec:
        raise HTTPException(status_code=422, detail=f"Unknown filter field {condition.field!r}")
    if spec.require_op and condition.op != spec.require_op:
        raise HTTPException(
            status_code=422,
            detail=f"Field {condition.field!r} requires op={spec.require_op!r}",
        )

    if spec.handler:
        sql, params = spec.handler(condition.op, condition.value)
        return sql, params, None

    # Standard column path
    col = spec.column.replace("{base}", strategy.base)
    table = _table_of(col)
    if table and table not in strategy.accessible_tables:
        raise HTTPException(
            status_code=422,
            detail=f"Field {condition.field!r} (table {table!r}) not accessible in {strategy.name}",
        )
    sql, params = _emit_op(col, condition.op, condition.value)
    return sql, params, table


def _resolve_order(q: SearchQuery, strategy: Strategy, conditions):
    """Returns (order_sql_no_prefix, params, referenced_table_or_None)."""
    if q.orderBy is None:
        if strategy.default_order:
            return strategy.default_order, [], _table_of(strategy.default_order)
        return "", [], None

    spec = strategy.special_orders.get(q.orderBy.field) or ORDERS.get(q.orderBy.field)
    if not spec:
        raise HTTPException(
            status_code=422,
            detail=f"orderBy.field {q.orderBy.field!r} not supported by {strategy.name}",
        )

    if spec.handler:
        sql, params = spec.handler(q.orderBy.direction, conditions)
        return sql, params, None

    col = spec.column.replace("{base}", strategy.base)
    table = _table_of(col)
    if table and table not in strategy.accessible_tables:
        raise HTTPException(
            status_code=422,
            detail=(
                f"orderBy.field {q.orderBy.field!r} (table {table!r}) "
                f"not accessible in {strategy.name}"
            ),
        )
    return f"{col} {q.orderBy.direction.upper()}", [], table


def _build_joins(strategy: Strategy, referenced_tables, db: str) -> str:
    needed = referenced_tables - {strategy.base, None}
    parts = []
    for table in sorted(needed):
        recipe = strategy.join_recipes.get(table)
        if not recipe:
            raise HTTPException(
                status_code=422,
                detail=f"No join recipe for table {table!r} in {strategy.name}",
            )
        parts.append(recipe.format(db=db))
    return " ".join(parts)


def _validate(q: SearchQuery, strategy: Strategy) -> None:
    for predicate, msg in strategy.validators:
        if not predicate(q):
            raise HTTPException(status_code=422, detail=msg)


# ── Entry point ───────────────────────────────────────────────────────────

def build_query(q: SearchQuery, db: str = "vex_data") -> tuple[str, list]:
    log.info(
        "query_builder.build.start",
        entity=q.entity,
        filter=q.filter.model_dump() if q.filter else None,
        order_by=q.orderBy.model_dump() if q.orderBy else None,
        select_top=q.selectTop,
    )

    strategy = select_strategy(q)
    conditions, is_or = _extract_conditions(q)
    _validate(q, strategy)

    referenced = set()
    where_frags, where_params = [], []
    for c in conditions:
        sql, params, table = _resolve_filter(c, strategy)
        where_frags.append(sql)
        where_params.extend(params)
        if table:
            referenced.add(table)

    order_sql, order_params, order_table = _resolve_order(q, strategy, conditions)
    if order_table:
        referenced.add(order_table)

    # TEAM_SKILL / TEAM_SCORE always need their summary table for SELECT cols
    if strategy.name == "TEAM_SKILL":
        referenced.add("team_skill_summary")
    if strategy.name == "TEAM_SCORE":
        referenced.add("team_score_summary")

    join_sql = _build_joins(strategy, referenced, db)

    where_sql = ""
    if where_frags:
        joiner = " OR " if is_or else " AND "
        where_sql = "WHERE " + joiner.join(where_frags)

    order_clause = f"ORDER BY {order_sql}" if order_sql else ""
    limit = max(1, min(q.selectTop or 25, 1000))

    sql = (
        f"SELECT {strategy.select_cols} FROM {db}.{strategy.base} "
        f"{join_sql} {where_sql} {order_clause} LIMIT {limit}"
    )
    sql = " ".join(sql.split())
    final_params = where_params + order_params
    log.info(
        "query_builder.build.end",
        strategy=strategy.name,
        sql=sql,
        params=final_params,
    )
    return sql, final_params
