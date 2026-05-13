# Implementation Plan: query_builder (config + pipeline split)

## Context

`build_query(SearchQuery) → (sql, params)` translates the domain-specific JSON query into parameterized Athena SQL. Design goal: **one global field map + one global orderBy map**, both using full `table.column` references (no aliases). Strategies only declare their base table, accessible tables, and join recipes. The builder auto-composes joins from which tables the user's fields reference.

**File split** — all data and field-specific handlers live in `config.py`; the generic pipeline lives in `query_builder.py`. Adding a new field, join, or constraint is a one-line edit in `config.py` — pipeline never changes.

Source of truth: `query_rule.md` (this directory).

---

## Architecture (6-step pipeline, all data-driven)

```
1. Select strategy           ← entity, orderBy.field
2. Resolve filter fields     ← FIELDS map + strategy.special_handlers
3. Resolve orderBy field     ← ORDERS map + strategy
4. Compose FROM + JOINs      ← strategy.base + tables referenced by fields
5. Build WHERE + ORDER BY    ← from resolved columns/handlers
6. Validate                  ← strategy.validators (e.g., matches.score needs teams.number)
```

**Key principles:**
- Every column reference is `table.column` — no aliases anywhere.
- One canonical column per field; joins auto-added when canonical table is reachable but not yet present.
- Per-strategy "special handlers" override specific fields where SQL diverges (UNNEST, COALESCE, etc.).
- Validation runs LAST; if it fails, the built SQL is discarded with 422.

---

## Files

| File | Action | Contents |
|------|--------|----------|
| `app/models/schemas.py` | Rewrite | `FilterCondition`, `FilterGroup`, `OrderBy`, `SearchQuery` |
| `app/services/query_builder/__init__.py` | Create | `from .query_builder import build_query` |
| `app/services/query_builder/config.py` | Create | Dataclasses, JOIN recipes, special handlers, validators, `FIELDS`, `ORDERS`, `STRATEGIES`, routing sets |
| `app/services/query_builder/query_builder.py` | Create | Generic pipeline (`build_query` + helpers); imports everything else from `config` |

Module layout after implementation:

```
app/services/query_builder/
├── __init__.py                  # re-exports build_query
├── config.py                    # ~250 lines of pure data + tiny handlers
├── query_builder.py             # ~120 lines of generic pipeline
├── query_rule.md
├── search_rule_reference.md
└── implementation_plan.md       # this file
```

---

## Step 1 — `schemas.py` rewrite

```python
class FilterCondition(BaseModel):
    field: str
    op: Literal["eq", "neq", "gt", "lt", "contains"]
    value: Union[str, int, float]

class FilterGroup(BaseModel):
    and_: list[FilterCondition] | None = Field(None, alias="and")
    or_:  list[FilterCondition] | None = Field(None, alias="or")
    model_config = {"populate_by_name": True}

class OrderBy(BaseModel):
    field: str
    direction: Literal["asc", "desc"]

class SearchQuery(BaseModel):
    entity: str = Field(..., pattern="^(events|matches|team)$")
    filter: FilterGroup | None = None
    orderBy: OrderBy | None = None
    selectTop: int | None = None
```

---

## Step 2 — `config.py` core data structures

```python
@dataclass(frozen=True)
class FieldSpec:
    column: str | None = None        # canonical "table.column", or "{base}.col" for partition
    handler: Callable | None = None  # (op, value) -> (sql, params); overrides column
    require_op: str | None = None    # if set, op must equal this

@dataclass(frozen=True)
class OrderSpec:
    column: str | None = None        # "table.column" expression
    handler: Callable | None = None  # (direction, conditions) -> (sql, params)

@dataclass(frozen=True)
class Strategy:
    name: str
    base: str                            # base table name (no alias)
    select_cols: str                     # explicit SELECT list (or "*")
    accessible_tables: frozenset[str]    # tables this strategy can join to
    join_recipes: dict[str, str]         # tablename -> JOIN SQL fragment (uses {db})
    special_handlers: dict[str, Callable]  # field_name -> (op, value) -> (sql, params)
    special_orders: dict[str, OrderSpec]   # orderBy.field overrides (rare)
    default_order: str | None            # full SQL fragment, e.g. "team_event_summary.ranking ASC"
    validators: tuple                    # ((predicate(q) -> bool, message), ...)
```

---

## Step 3 — `config.py` global FIELDS map

Each entry: field name → canonical column (table-prefixed) or a special handler.

```python
FIELDS = {
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
```

Special handlers (live in `config.py` because they're field-specific configuration):

```python
def _match_start_handler(op, value):
    return "COALESCE(matches.started_time, matches.scheduled_time) > TIMESTAMP ?", [value]

def _match_end_handler(op, value):
    return ("matches.started_time IS NOT NULL "
            "AND matches.started_time + INTERVAL '5' MINUTE < TIMESTAMP ?"), [value]

def _match_team_number_handler(op, value):
    if op != "eq":
        raise HTTPException(422, "teams.number in matches requires op=eq")
    return ("(EXISTS (SELECT 1 FROM UNNEST(matches.red_teams) t WHERE t.number = ?) "
            "OR EXISTS (SELECT 1 FROM UNNEST(matches.blue_teams) t WHERE t.number = ?))",
            [value, value])
```

The generic op-emit function (`_emit_op`) lives in `query_builder.py` since it's pipeline logic, not field-specific.

---

## Step 4 — `config.py` global ORDERS map and order handlers

```python
ORDERS = {
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

def _matches_score_order(direction, conditions):
    team_no = _find_value(conditions, "teams.number")   # validator guarantees presence
    return (f"CASE WHEN EXISTS (SELECT 1 FROM UNNEST(matches.red_teams) t WHERE t.number = ?) "
            f"THEN matches.red_score ELSE matches.blue_score END {direction.upper()}",
            [team_no])
```

---

## Step 5 — `config.py` strategy registry + routing sets + validators + helpers

```python
SKILL_SCORE_FIELDS  = {"teams.best_skill_score", "teams.worst_skill_score", "teams.avg_skill_score"}
SCORE_SUMMARY_FIELDS = {"teams.high_score", "teams.average_points", "teams.total_points"}

# JOIN recipes use full table names everywhere; {db} replaced at build time
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

STRATEGIES = {
    "EVENTS": Strategy(
        name="EVENTS",
        base="events",
        select_cols="*",
        accessible_tables=frozenset({"events"}),
        join_recipes={},
        special_handlers={},
        special_orders={},
        default_order=None,
        validators=(),
    ),

    "MATCHES": Strategy(
        name="MATCHES",
        base="matches",
        select_cols="*",
        accessible_tables=frozenset({"matches", "events"}),
        join_recipes={"events": _J_EVENTS_FROM_MATCHES},
        # teams.number in matches uses UNNEST, NOT a teams join → handler override
        special_handlers={"teams.number": _match_team_number_handler},
        special_orders={},
        default_order=None,
        validators=(
            (lambda q: not (q.orderBy and q.orderBy.field == "matches.score"
                            and not _has_field(q, "teams.number")),
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
        special_handlers={},
        special_orders={},
        default_order="team_event_summary.ranking ASC",
        validators=(),
    ),

    "TEAM_SKILL": Strategy(
        name="TEAM_SKILL",
        base="teams",
        select_cols=(
            "teams.team_id, teams.number, teams.team_name, teams.organization, "
            "teams.program_id, teams.program_name, teams.city, teams.region, "
            "teams.postcode, teams.country, teams.grade, teams.registered, "
            "team_skill_summary.best_skill_score, team_skill_summary.worst_skill_score, "
            "team_skill_summary.avg_skill_score, team_skill_summary.best_skill_event_id, "
            "team_skill_summary.worst_skill_event_id"
        ),
        accessible_tables=frozenset({"teams", "team_skill_summary"}),
        join_recipes={"team_skill_summary": _J_TSS_FROM_TEAMS},
        special_handlers={},
        special_orders={},
        default_order=None,
        validators=(),
    ),

    "TEAM_SCORE": Strategy(
        name="TEAM_SCORE",
        base="teams",
        select_cols=(
            "teams.team_id, teams.number, teams.team_name, teams.organization, "
            "teams.program_id, teams.program_name, teams.city, teams.region, "
            "teams.postcode, teams.country, teams.grade, teams.registered, "
            "team_score_summary.high_score, team_score_summary.average_points, "
            "team_score_summary.total_points, team_score_summary.best_score_event_id"
        ),
        accessible_tables=frozenset({"teams", "team_score_summary"}),
        join_recipes={"team_score_summary": _J_TSCORE_FROM_TEAMS},
        special_handlers={},
        special_orders={},
        default_order=None,
        validators=(),
    ),
}
```

Note: `TEAM_SKILL` and `TEAM_SCORE` always need their summary table for the SELECT columns. The pipeline `build_query` adds these tables unconditionally to `referenced` for the join phase.

`config.py` also exports two small lookup helpers used by handlers and validators (they only touch the SearchQuery / condition list, no SQL):

```python
def _has_field(q, field_name):
    fg = q.filter
    if not fg: return False
    return any(c.field == field_name for c in (fg.and_ or []) + (fg.or_ or []))

def _find_value(conditions, field_name):
    for c in conditions:
        if c.field == field_name: return c.value
    return None
```

---

## Step 6 — `query_builder.py` pipeline functions

`query_builder.py` imports everything it needs from `config`:

```python
from fastapi import HTTPException
from app.models.schemas import SearchQuery
from .config import (
    FIELDS, ORDERS, STRATEGIES, SKILL_SCORE_FIELDS, SCORE_SUMMARY_FIELDS,
    Strategy, FieldSpec, OrderSpec,
)
```

Then defines the generic pipeline — these functions never reference specific fields, strategies, or columns:

```python
# Generic op-to-SQL emitter (used for standard fields without a custom handler)
_TIME_COL_HINTS = ("start_date", "end_date", "scheduled_time", "started_time")
def _is_time_col(col): return any(h in col for h in _TIME_COL_HINTS)

def _emit_op(col, op, value):
    if op == "contains": return f"LOWER({col}) LIKE LOWER(?)", [f"%{value}%"]
    if op == "eq":       return f"{col} = ?",  [value]
    if op == "neq":      return f"{col} != ?", [value]
    if op == "gt":
        return (f"{col} > TIMESTAMP ?", [value]) if _is_time_col(col) else (f"{col} > ?", [value])
    if op == "lt":
        return (f"{col} < TIMESTAMP ?", [value]) if _is_time_col(col) else (f"{col} < ?", [value])
    raise HTTPException(422, f"Unsupported op {op!r}")

def select_strategy(q: SearchQuery) -> Strategy:
    if q.entity == "events":  return STRATEGIES["EVENTS"]
    if q.entity == "matches": return STRATEGIES["MATCHES"]
    f = q.orderBy.field if q.orderBy else None
    if f in SKILL_SCORE_FIELDS:   return STRATEGIES["TEAM_SKILL"]
    if f in SCORE_SUMMARY_FIELDS: return STRATEGIES["TEAM_SCORE"]
    return STRATEGIES["TEAM_EVENT"]

def _table_of(column: str) -> str | None:
    """Return the table prefix from a 'table.column' string."""
    if not column or "." not in column: return None
    return column.split(".", 1)[0]

def _extract(q):
    fg = q.filter
    if not fg: return [], False
    if fg.and_ is not None and fg.or_ is not None:
        raise HTTPException(422, "filter must contain exactly one of 'and' or 'or'")
    return (fg.and_ or fg.or_ or []), bool(fg.or_)

def _resolve_filter(condition, strategy):
    """Returns (sql_fragment, params, referenced_table_or_None)."""
    # 1. Strategy-specific override (e.g., teams.number in MATCHES)
    if condition.field in strategy.special_handlers:
        sql, params = strategy.special_handlers[condition.field](condition.op, condition.value)
        return sql, params, None   # special handlers don't trigger joins

    # 2. Global FIELDS lookup
    spec = FIELDS.get(condition.field)
    if not spec:
        raise HTTPException(422, f"Unknown filter field {condition.field!r}")
    if spec.require_op and condition.op != spec.require_op:
        raise HTTPException(422, f"Field {condition.field!r} requires op={spec.require_op!r}")

    if spec.handler:
        sql, params = spec.handler(condition.op, condition.value)
        return sql, params, None

    # spec.column path
    col = spec.column.replace("{base}", strategy.base)
    table = _table_of(col)
    if table and table not in strategy.accessible_tables:
        raise HTTPException(422,
            f"Field {condition.field!r} (table {table}) not accessible in {strategy.name}")
    sql, params = _emit_op(col, condition.op, condition.value)
    return sql, params, table

def _resolve_order(q, strategy, conditions):
    """Returns (order_sql, params, referenced_table_or_None)."""
    if q.orderBy is None:
        if strategy.default_order:
            return strategy.default_order, [], _table_of(strategy.default_order)
        return "", [], None

    spec = strategy.special_orders.get(q.orderBy.field) or ORDERS.get(q.orderBy.field)
    if not spec:
        raise HTTPException(422,
            f"orderBy.field {q.orderBy.field!r} not supported by {strategy.name}")

    if spec.handler:
        sql, params = spec.handler(q.orderBy.direction, conditions)
        return sql, params, None    # handlers manage their own tables
    col = spec.column.replace("{base}", strategy.base)
    table = _table_of(col)
    if table and table not in strategy.accessible_tables:
        raise HTTPException(422,
            f"orderBy.field {q.orderBy.field!r} (table {table}) not accessible in {strategy.name}")
    return f"{col} {q.orderBy.direction.upper()}", [], table

def build_joins(strategy, referenced_tables, db):
    """Emit JOIN clauses for each referenced table that isn't the base."""
    needed = referenced_tables - {strategy.base, None}
    parts = []
    for table in sorted(needed):  # deterministic ordering
        recipe = strategy.join_recipes.get(table)
        if not recipe:
            raise HTTPException(422,
                f"No join recipe for table {table!r} in {strategy.name}")
        parts.append(recipe.format(db=db))
    return " ".join(parts)

def validate(q, strategy):
    for predicate, msg in strategy.validators:
        if not predicate(q):
            raise HTTPException(422, msg)

def build_query(q: SearchQuery, db: str = "vex_data") -> tuple[str, list]:
    strategy = select_strategy(q)
    conditions, is_or = _extract(q)
    validate(q, strategy)

    # Resolve all conditions; collect referenced tables for joins
    referenced = set()
    where_frags, where_params = [], []
    for c in conditions:
        sql, params, table = _resolve_filter(c, strategy)
        where_frags.append(sql)
        where_params.extend(params)
        if table: referenced.add(table)

    # Resolve orderBy
    order_sql, order_params, order_table = _resolve_order(q, strategy, conditions)
    if order_table: referenced.add(order_table)

    # Auto-add summary joins for TEAM_SKILL / TEAM_SCORE (always needed for SELECT cols)
    if strategy.name == "TEAM_SKILL": referenced.add("team_skill_summary")
    if strategy.name == "TEAM_SCORE": referenced.add("team_score_summary")

    join_sql = build_joins(strategy, referenced, db)

    where_sql = ""
    if where_frags:
        joiner = " OR " if is_or else " AND "
        where_sql = "WHERE " + joiner.join(where_frags)

    order_clause = f"ORDER BY {order_sql}" if order_sql else ""
    limit = max(1, min(q.selectTop or 25, 1000))

    sql = (f"SELECT {strategy.select_cols} FROM {db}.{strategy.base} "
           f"{join_sql} {where_sql} {order_clause} LIMIT {limit}")
    sql = " ".join(sql.split())
    return sql, where_params + order_params
```

`select_cols` (the per-strategy SELECT column list) is a plain string attribute on each `Strategy` entry — so the pipeline only needs `strategy.select_cols`.

`_has_field` and `_find_value` are imported from `config.py` (see Step 5).

---

## Corner Cases (all handled by the generic pipeline)

| Case | Handling |
|------|----------|
| No `filter` | `WHERE` omitted |
| Empty `and`/`or` array | `WHERE` omitted |
| Both `and` and `or` set | 422 |
| Unknown `filter.field` | 422 (FIELDS lookup miss) |
| Field references table not in `strategy.accessible_tables` | 422 (e.g. `events.name` in TEAM_SKILL) |
| Field has `require_op` mismatch (e.g. `events.start_time` with `eq`) | 422 |
| Unknown `orderBy.field` | 422 |
| `orderBy.field` references inaccessible table | 422 |
| No `orderBy` | Use `strategy.default_order` (only TEAM_EVENT has one) |
| `matches.score` orderBy without `teams.number` filter | 422 (validator) |
| `teams.number` in MATCHES with op ≠ `eq` | 422 (UNNEST handler enforces) |
| `selectTop` None / 0 / negative / >1000 | Clamped to `[1, 1000]`, default 25 |
| `teams.city` filter in TEAM_EVENT | Auto-adds teams join via `join_recipes["teams"]` |
| `events.name` filter in MATCHES | Auto-adds events join (uses canonical, NOT denormalized `matches.event_name`) |
| `rankings.rank` orderBy in TEAM_EVENT | Column is `team_event_summary.ranking` — no join needed |
| Multiple conditions on same field | All emitted, joined with AND/OR |
| Same `teams.number` value used for both WHERE (UNNEST) and ORDER BY CASE in `matches.score` | Validator guarantees presence; `_find_value` extracts; documented |

---

## Maintainability Wins

1. **Add a new filter field** → one line in `config.FIELDS`.
2. **Add a new orderBy field** → one line in `config.ORDERS`.
3. **Add a new strategy** → one entry in `config.STRATEGIES` (table + joins + validators); `query_builder.py` is untouched.
4. **Add a new join recipe** → one line in `strategy.join_recipes`.
5. **Add a new constraint** → one tuple in `strategy.validators`.
6. **Add a new op** → extend `_emit_op` in `query_builder.py` once; applies everywhere.
7. **Trace any column** → grep `table.column` literally; it appears verbatim in `config.py` and in generated SQL.
8. **No aliases** → `teams.city` means `teams.city` everywhere.
9. **Config vs logic split** → `config.py` is reviewable data (no SQL assembly); `query_builder.py` is reviewable logic (no per-field branching).

---

## Tradeoffs

- **Joins over denorm shortcuts**: when `events.name` is filtered in TEAM_EVENT or MATCHES, we JOIN `events` rather than using the denormalized `event_name` column. Athena handles this fine, but the SQL has one extra join. Worth it for the single canonical source.
- **Special handlers** still exist for UNNEST and time-derivation cases; they're confined to `strategy.special_handlers` / `FIELDS[*].handler` and don't pollute the main pipeline.

---

## Verification

Manual queries (after `seed_sample_data.py`):

1. EVENTS: `season_id`, `events.country eq "United States"`, `orderBy=events.time asc` → straight `SELECT * FROM vex_data.events WHERE events.p_season_id=? AND events.country=? ORDER BY events.start_date ASC`
2. MATCHES + score: `season_id`, `teams.number eq "1234Z"`, `orderBy=matches.score desc` → UNNEST WHERE + CASE ORDER BY
3. MATCHES + score without `teams.number` → 422
4. TEAM_EVENT default: `events.name contains "Regional"` → JOINs events; ORDER BY `team_event_summary.ranking ASC`
5. TEAM_EVENT + location: `teams.city eq "Los Angeles"` → JOINs teams
6. TEAM_SKILL: `orderBy=teams.best_skill_score desc` → JOIN team_skill_summary
7. TEAM_SCORE: `orderBy=teams.high_score desc` → JOIN team_score_summary
8. Unknown field `foo.bar` → 422
9. `events.start_time` with `op=eq` → 422
10. `teams.city` filter in TEAM_SKILL → uses base `teams` directly, no extra join
11. `selectTop=9999` → SQL has `LIMIT 1000`
