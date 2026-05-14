# VEX Data Pipeline — Plan

## Current Status

| File | State |
|------|-------|
| `requirements.txt` | done |
| `.env.example` | done |
| `app/__init__.py` | done |
| `app/api/__init__.py` | done |
| `app/api/routes/__init__.py` | done |
| `app/services/__init__.py` | done |
| `app/models/__init__.py` | done |
| `app/config.py` | done |
| `app/services/query_builder/query_rule.md` | done |
| `app/services/query_builder/search_rule_reference.md` | done |
| `app/services/query_builder/implementation_plan.md` | done |
| `app/models/schemas.py` | done — `FilterCondition`/`FilterGroup`/`OrderBy`/`SearchQuery` |
| `app/services/robotevents.py` | **on hold** (RobotEvents API unavailable) |
| `app/services/s3.py` | needs update (partition path scheme) |
| `app/services/query_builder/__init__.py` | done — re-exports `build_query` |
| `app/services/query_builder/config.py` | done — FIELDS / ORDERS / STRATEGIES registries + handlers |
| `app/services/query_builder/query_builder.py` | done — generic 6-step pipeline |
| `app/services/etl.py` | **on hold** (curate route deferred) |
| `app/services/athena.py` | **pending** |
| `app/api/routes/ingest.py` | **on hold** (RobotEvents API unavailable) |
| `app/api/routes/curate.py` | **on hold** (deferred — curated data seeded directly) |
| `app/api/routes/query.py` | **pending** |
| `app/main.py` | **pending** |
| `scripts/seed_sample_data.py` | **pending** — generates and uploads sample Parquet to S3 |
| `template.yaml` | **pending** — SAM/CloudFormation infra template |
| `samconfig.toml` | **pending** — SAM CLI deployment config |

---

## Overview

Python FastAPI project that:
1. Pulls historical VEX robotics data from 5 RobotEvents API v2 endpoints (all programs)
2. Stores raw JSON in S3 (raw layer)
3. Cleans into 5 base Parquet tables + 2 derived summary tables (curated layer)
4. Exposes Athena query endpoints with a domain-specific JSON query interface

**S3 layout:**
- Bucket: `vex-search-data-v1`
- Raw:     `s3://vex-search-data-v1/raw/{entity}/p_season_id={s}/p_program_id={p}/{timestamp}.json`
- Curated (season-scoped):  `s3://vex-search-data-v1/curated/{entity}/p_season_id={s}/p_program_id={p}/{timestamp}.parquet`
- Curated (event-scoped):   `s3://vex-search-data-v1/curated/{entity}/p_season_id={s}/p_program_id={p}/p_event_id={e}/{timestamp}.parquet`
- Athena: `s3://vex-search-data-v1/athena-results/`

---

## Project Structure

```
vex-data/
├── app/
│   ├── __init__.py
│   ├── main.py                           # FastAPI app + Mangum handler for Lambda
│   ├── config.py                         ✓ done
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes/
│   │       ├── __init__.py
│   │       ├── ingest.py                 # ON HOLD — POST /ingest/{entity|all}
│   │       ├── curate.py                 # ON HOLD — POST /curate/{entity|all}
│   │       └── query.py                  # POST /query/create-tables, /query/execute
│   ├── services/
│   │   ├── __init__.py
│   │   ├── robotevents.py                # ON HOLD — async httpx, 5 direct endpoints
│   │   ├── s3.py                         # JSON + Parquet upload/download, partition paths
│   │   ├── etl.py                        # ON HOLD — 5 base cleaners + 2 derived builders
│   │   ├── athena.py                     # DDL, synchronous execute+poll
│   │   └── query_builder/                ✓ done
│   │       ├── __init__.py               # re-exports build_query
│   │       ├── config.py                 # FIELDS / ORDERS / STRATEGIES + handlers
│   │       ├── query_builder.py          # generic 6-step pipeline
│   │       ├── query_rule.md             # routing rules and SQL templates
│   │       ├── search_rule_reference.md  # filter / orderBy field reference
│   │       └── implementation_plan.md    # implementation plan
│   └── models/
│       ├── __init__.py
│       └── schemas.py                    ✓ done — all Pydantic models
├── scripts/
│   └── seed_sample_data.py              # generates + uploads sample Parquet to S3
├── curated/                              ✓ done — Athena DDL files
│   ├── events.sql
│   ├── teams.sql
│   ├── matches.sql
│   ├── skills.sql
│   ├── rankings.sql
│   ├── team_event_summary.sql
│   ├── team_skill_summary.sql
|   └── team_score_summary.sql
├── template.yaml                         # SAM/CloudFormation infra template
├── samconfig.toml                        # SAM CLI deployment config
├── requirements.txt                      ✓ done
└── .env.example                          ✓ done
```

---

## Data Flow

```
RobotEvents API  (https://www.robotevents.com/api/v2)
      │  Authorization: Bearer {ROBOTEVENTS_API_KEY}
      │  5 direct endpoints, per_page=250, all pages fetched concurrently
      ▼
POST /ingest/{entity}   →  saves list[dict] as JSON
      ▼
s3://vex-search-data-v1/raw/{entity}/p_season_id={s}/p_program_id={p}/{timestamp}.json
      ▼
POST /curate/{entity}
  base tables:    reads raw JSON → clean/flatten → write per partition
  derived tables: joins/aggregates curated Parquets → write per (season, program)
      ▼
s3://vex-search-data-v1/curated/{entity}/p_season_id={s}/p_program_id={p}/[p_event_id={e}/]{timestamp}.parquet
      ▼
POST /query/create-tables  →  CREATE EXTERNAL TABLE (DDL from curated/*.sql)
      ▼
Athena  vex_data database, Glue catalog
      ▼
POST /query/execute  →  SearchQuery JSON → query_builder.py → SQL → poll → QueryResponse
```

---

## RobotEvents API — 5 Direct Endpoints

All endpoints are top-level, paginated (`per_page=250`), auth `Bearer {ROBOTEVENTS_API_KEY}`.

| Entity | Endpoint | Key filter params |
|--------|----------|-------------------|
| events | `GET /events` | `season[]`, `program[]` |
| teams | `GET /teams` | `season[]`, `program[]` |
| matches | `GET /matches` | `season[]`, `program[]`, `event[]` |
| skills | `GET /skills` | `season[]`, `program[]`, `event[]` |
| rankings | `GET /rankings` | `season[]`, `program[]`, `event[]` |

Client methods in `app/services/robotevents.py`:
- `get_events(season_id, program_ids?)`
- `get_teams(season_id, program_ids?)`
- `get_matches(season_id, program_ids?, event_ids?)`
- `get_skills(season_id, program_ids?, event_ids?)`
- `get_rankings(season_id, program_ids?, event_ids?)`

---

## Environment Config (`.env`)

```
ROBOTEVENTS_API_KEY=...

S3_BUCKET=vex-search-data-v1
S3_RAW_PREFIX=raw
S3_CURATED_PREFIX=curated

AWS_REGION=us-east-1
ATHENA_DATABASE=vex_data
ATHENA_OUTPUT_LOCATION=s3://vex-search-data-v1/athena-results/

AWS_ACCESS_KEY_ID=        # optional — omit to use IAM role
AWS_SECRET_ACCESS_KEY=
```

---

## API Endpoints

### Ingest (`app/api/routes/ingest.py`)

| Method | Path | Request body |
|--------|------|-------------|
| POST | `/ingest/events` | `{ season_id, program_ids? }` |
| POST | `/ingest/teams` | `{ season_id, program_ids? }` |
| POST | `/ingest/matches` | `{ season_id, program_ids?, event_ids? }` |
| POST | `/ingest/skills` | `{ season_id, program_ids?, event_ids? }` |
| POST | `/ingest/rankings` | `{ season_id, program_ids?, event_ids? }` |
| POST | `/ingest/all` | `{ season_id, program_ids? }` — runs all five in sequence |

Response: `{ entity, records_fetched, s3_key }`

### Curate (`app/api/routes/curate.py`)

| Method | Path | Notes |
|--------|------|-------|
| POST | `/curate/events` | base table |
| POST | `/curate/teams` | base table |
| POST | `/curate/matches` | base table, event-scoped partitions |
| POST | `/curate/skills` | base table, event-scoped partitions |
| POST | `/curate/rankings` | base table, event-scoped partitions |
| POST | `/curate/team_event_summary` | derived — joins rankings + skills + events + teams |
| POST | `/curate/team_skill_summary` | derived — aggregates skills per team |
| POST | `/curate/all` | runs all seven in order |

All curate endpoints accept `{ season_id, program_ids? }`.
Response: `{ entity, records_written, s3_keys: [...] }`

### Query (`app/api/routes/query.py`)

| Method | Path | Returns |
|--------|------|---------|
| POST | `/query/create-tables` | `{ status, database }` |
| POST | `/query/execute` | `QueryResponse` (inline results, synchronous) |

---

## `/query/execute` — SearchQuery Schema

Source of truth: `app/models/schemas.py`. Full field reference: `app/services/query_builder/search_rule_reference.md`.

```python
class FilterCondition(BaseModel):
    field: str                                      # dot-notation, e.g. "teams.city"
    op: Literal["eq", "neq", "gt", "lt", "contains"]
    value: Union[str, int, float]

class FilterGroup(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    and_: Optional[list[FilterCondition]] = Field(None, alias="and")
    or_:  Optional[list[FilterCondition]] = Field(None, alias="or")

class OrderBy(BaseModel):
    field: str                                      # e.g. "rankings.rank"
    direction: Literal["asc", "desc"]

class SearchQuery(BaseModel):
    entity: str = Field(..., pattern="^(events|matches|team)$")
    filter: Optional[FilterGroup] = None
    orderBy: Optional[OrderBy] = None
    selectTop: Optional[int] = None                 # default 25, clamped to [1, 1000]
```

### Filter field → column mapping (see `search_rule_reference.md` for full list)

| Field | op(s) | Column |
|-------|-------|--------|
| `teams.city` | eq | `teams.city` |
| `teams.postcode` | eq | `teams.postcode` |
| `teams.country` | eq | `teams.country` |
| `teams.region` | contains | `teams.region` |
| `teams.name` | contains | `teams.team_name` |
| `teams.number` | eq | `teams.number` |
| `events.city` | eq | `events.city` |
| `events.postcode` | eq | `events.postcode` |
| `events.country` | eq | `events.country` |
| `events.region` | contains | `events.region` |
| `events.venue` | contains | `events.venue` |
| `events.name` | contains | `events.name` |
| `events.sku` | eq | `events.sku` |
| `events.start_time` | gt | `events.start_date` |
| `events.end_time` | lt | `events.end_date` |
| `matches.start_time` | gt | `COALESCE(started_time, scheduled_time)` |
| `matches.end_time` | lt | `started_time + INTERVAL '5' MINUTE` (excluded when `started_time IS NULL`) |
| `program_id` | eq | `p_program_id` (partition) |
| `season_id` | eq | `p_season_id` (partition) |

### op → SQL operator

| op | SQL |
|----|-----|
| `eq` | `col = ?` |
| `neq` | `col != ?` |
| `gt` | `col > ?` |
| `lt` | `col < ?` |
| `contains` | `LOWER(col) LIKE LOWER(?)` with `%value%` |

---

## Query Builder (`app/services/query_builder/`)

**Design**: data-driven, two-file split — `config.py` holds all data (FIELDS, ORDERS, STRATEGIES, JOIN recipes, special handlers, validators); `query_builder.py` holds a generic 6-step pipeline that never branches on specific fields. Adding a new field/orderBy/strategy/constraint is a one-line edit in `config.py`.

Full design details: `app/services/query_builder/implementation_plan.md`. SQL templates and routing rules: `query_rule.md`.

### Routing Decision Tree

Routing is driven by `entity` and `orderBy.field`:

```
entity = "events"   → EVENTS     → vex_data.events

entity = "matches"  → MATCHES    → vex_data.matches

entity = "team"
    orderBy.field ∈ {teams.best_skill_score, teams.worst_skill_score, teams.avg_skill_score}
        → TEAM_SKILL    → teams LEFT JOIN team_skill_summary
    orderBy.field ∈ {teams.high_score, teams.average_points, teams.total_points}
        → TEAM_SCORE    → teams LEFT JOIN team_score_summary
    default (all other orderBy.field values, or null)
        → TEAM_EVENT    → team_event_summary  (+ optional events / teams JOINs)
```

### 6-step pipeline (`query_builder.py`)

```
1. Select strategy           ← entity, orderBy.field
2. Resolve filter fields     ← FIELDS map + strategy.special_handlers
3. Resolve orderBy field     ← ORDERS map + strategy
4. Compose FROM + JOINs      ← strategy.base + tables referenced by fields
5. Build WHERE + ORDER BY    ← from resolved columns/handlers
6. Validate                  ← strategy.validators (e.g., matches.score needs teams.number)
```

```python
def build_query(q: SearchQuery, db: str = "vex_data") -> tuple[str, list]:
    strategy = select_strategy(q)                 # 1
    conditions, is_or = _extract_conditions(q)
    _validate(q, strategy)                        # 6 (cheap; runs early)

    referenced = set()
    where_frags, where_params = [], []
    for c in conditions:                          # 2
        sql, params, table = _resolve_filter(c, strategy)
        where_frags.append(sql); where_params.extend(params)
        if table: referenced.add(table)

    order_sql, order_params, order_table = _resolve_order(q, strategy, conditions)  # 3
    if order_table: referenced.add(order_table)

    if strategy.name == "TEAM_SKILL": referenced.add("team_skill_summary")
    if strategy.name == "TEAM_SCORE": referenced.add("team_score_summary")
    join_sql = _build_joins(strategy, referenced, db)                                # 4

    # 5 — assemble
    ...
```

### `config.py` — pure data

```python
FIELDS = {
    "season_id":         FieldSpec(column="{base}.p_season_id"),
    "events.name":       FieldSpec(column="events.name"),
    "events.start_time": FieldSpec(column="events.start_date", require_op="gt"),
    "teams.city":        FieldSpec(column="teams.city"),
    "matches.start_time": FieldSpec(handler=_match_start_handler, require_op="gt"),
    # ... see search_rule_reference.md for full list
}

ORDERS = {
    "events.time":            OrderSpec(column="events.start_date"),
    "matches.score":          OrderSpec(handler=_matches_score_order),
    "rankings.rank":          OrderSpec(column="team_event_summary.ranking"),
    "teams.best_skill_score": OrderSpec(column="team_skill_summary.best_skill_score"),
    # ...
}

STRATEGIES = {
    "MATCHES": Strategy(
        name="MATCHES", base="matches", select_cols="*",
        accessible_tables=frozenset({"matches", "events"}),
        join_recipes={"events": _J_EVENTS_FROM_MATCHES},
        special_handlers={"teams.number": _match_team_number_handler},
        validators=((_matches_score_requires_team_number,
                     "orderBy.field='matches.score' requires a teams.number filter"),),
    ),
    # ... EVENTS, TEAM_EVENT, TEAM_SKILL, TEAM_SCORE
}
```

### Key implementation properties

- **No aliases**: every column reference is full `table.column` everywhere — in `FIELDS`, generated SQL, and error messages.
- **Parameterized queries**: all values → Athena `ExecutionParameters` (`?` placeholders); no interpolation.
- **Field allowlist**: `FilterCondition.field` looked up in `FIELDS` dict; unknown fields → 422.
- **Sort allowlist**: `orderBy.field` resolved through `ORDERS` dict to a fixed SQL expression; raw value never embedded.
- **Auto-join**: tables referenced by `table.column` fields trigger their `join_recipes` entry; canonical column always used (no denormalization shortcuts).
- **Special handlers** confined to per-strategy `special_handlers` (UNNEST for `teams.number` in MATCHES) and per-field `FieldSpec.handler` (COALESCE for `matches.start_time`, INTERVAL for `matches.end_time`, CASE for `matches.score` ORDER BY).
- **selectTop** clamped to `[1, 1000]`, default 25.

### Strategy → table and orderBy field mapping

| Strategy | Table(s) | orderBy field → SQL expression |
|----------|----------|-------------------------------|
| EVENTS | `events` | `events.time` → `start_date {dir}` |
| MATCHES | `matches` | `matches.time` → `scheduled_time {dir}`, `matches.score` → `red_score {dir}` or `blue_score {dir}` (resolved by team alliance; requires `teams.name` or `teams.number` in filter) |
| TEAM_EVENT | `team_event_summary` | `rankings.rank` → `ranking {dir}`, `events.skills_rank` → `skills_rank {dir}`, `events.score` → `best_score {dir}`, `events.time` → `event_start_date {dir}` |
| TEAM_SKILL | `teams LEFT JOIN team_skill_summary` | `teams.best_skill_score` → `s.best_skill_score {dir}`, `teams.worst_skill_score` → `s.worst_skill_score {dir}`, `teams.avg_skill_score` → `s.avg_skill_score {dir}` |
| TEAM_SCORE | `teams LEFT JOIN team_score_summary` | `teams.high_score` → `s.high_score {dir}`, `teams.average_points` → `s.average_points {dir}`, `teams.total_points` → `s.total_points {dir}` |

---

## `/query/execute` Return Schemas

All responses:
```json
{
  "entity": "...",
  "source_table": "...",
  "sql_executed": "SELECT ...",
  "total": 42,
  "rows": [ ... ]
}
```

### `entity="events"` → all columns from `events` table

### `entity="matches"` → all columns from `matches` table (`red_teams`/`blue_teams` as arrays)

### `entity="team"` → TEAM_EVENT (`team_event_summary`)

```json
{
  "event_id": 51498, "event_sku": "RE-VRC-24-7676",
  "event_name": "World Championship", "event_start_date": "2025-04-23T00:00:00",
  "team_id": 178234, "team_number": "1234Z", "team_name": "Apex Robotics",
  "organization": "Lincoln High School",
  "ranking": 1, "wins": 9, "losses": 1, "ties": 0,
  "best_score": 132, "best_skills_score": 153, "skills_rank": 2
}
```

### `entity="team"` → TEAM_SKILL (`teams + team_skill_summary`)

```json
{
  "team_id": 178234, "number": "1234Z", "team_name": "Apex Robotics",
  "organization": "Lincoln High School", "program_id": 1, "program_name": "VRC",
  "city": "Los Angeles", "region": "California", "postcode": "90001",
  "country": "United States", "grade": "High School", "registered": true,
  "best_skill_score": 153, "worst_skill_score": 87, "avg_skill_score": 121,
  "best_skill_event_id": 51498, "worst_skill_event_id": 49201
}
```

### `entity="team"` → TEAM_SCORE (`teams + team_score_summary`)

```json
{
  "team_id": 178234, "number": "1234Z", "team_name": "Apex Robotics",
  "organization": "Lincoln High School", "program_id": 1, "program_name": "VRC",
  "city": "Los Angeles", "region": "California", "postcode": "90001",
  "country": "United States", "grade": "High School", "registered": true,
  "high_score": 158, "average_points": 112.4, "total_points": 2248,
  "best_score_event_id": 51498
}
```

---

## Curated Table Schemas (from `curated/*.sql`)

### `events` — partitioned by `(p_season_id, p_program_id)`
`event_id, sku, name, program_id, program_name, season_id, season_name, start_date, end_date, city, region, postcode, country, venue, event_type, level, divisions ARRAY<STRUCT<id:BIGINT,name:STRING>>`

### `teams` — partitioned by `(p_season_id, p_program_id)`
`team_id, number, team_name, organization, program_id, program_name, city, region, postcode, country, grade, registered`

### `matches` — partitioned by `(p_season_id, p_program_id, p_event_id)`
`match_id, event_id, event_sku, event_name, division_id, division_name, round, round_name, instance, matchnum, scheduled_time, started_time, field, scored, red_score, blue_score, red_teams ARRAY<STRUCT<team_id:BIGINT,number:STRING>>, blue_teams ARRAY<STRUCT<team_id:BIGINT,number:STRING>>`

### `skills` — partitioned by `(p_season_id, p_program_id, p_event_id)`
`event_id, event_sku, team_id, team_number, team_name, type, score, attempts, rank, skills_stop_time, created_at`

### `rankings` — partitioned by `(p_season_id, p_program_id, p_event_id)`
`event_id, event_sku, division_id, division_name, team_id, team_number, team_name, rank, wins, losses, ties, wp, ap, sp, high_score, average_points, total_points`

### `team_event_summary` — derived, partitioned by `(p_season_id, p_program_id)`
Aggregates matches + skills per team per event. No location columns (join `teams` if needed).
`event_id, event_sku, event_name, event_start_date, team_id, team_number, team_name, organization, ranking, wins, losses, ties, best_score, best_skills_score, skills_rank`

### `team_skill_summary` — derived, partitioned by `(p_season_id, p_program_id)`
Aggregates skills per team across whole season.
`team_id, team_number, team_name, organization, best_skill_score, worst_skill_score, avg_skill_score, best_skill_event_id, worst_skill_event_id`

### `team_score_summary` — derived, partitioned by `(p_season_id, p_program_id)`
Aggregates rankings per team across whole season. See `curated/table.md` for derivation notes.
`team_id, team_number, team_name, organization, high_score, average_points, total_points, best_score_event_id`

> **Note**: `team_score_summary.sql` currently has a duplicate `best_score_event_id` column — line 13 should likely be `worst_score_event_id`. Confirm before implementing the seed script and ETL.

---

## ETL Rules (`app/services/etl.py`)

### Base cleaners — `list[dict]` → `pyarrow.Table`

| Entity | Key transformations |
|--------|---------------------|
| `events` | Flatten `program{id,name}`, `season{id,name}`, `location`; keep `divisions` as list of `{id,name}`; parse `start`/`end` → timestamp |
| `teams` | Flatten `program{id,name}`, `location`; direct mapping of all fields |
| `matches` | Flatten `event{id,sku,name}`, `division{id,name}`; extract `alliances` → `red_teams`/`blue_teams` as list of `{team_id,number}`; parse timestamps |
| `skills` | Flatten `event{id,sku}`, `team{id,number,name}`; map `type`, `score`, `attempts`, `rank`, `skills_stop_time`, `created_at` |
| `rankings` | Flatten `event{id,sku}`, `team{id,number,name}`, `division{id,name}`; map all W/L/T/WP/AP/SP/high_score fields |

Each cleaner groups records by partition key(s) and writes one Parquet file per partition.

### Derived summary builders

**`team_event_summary`** — reads curated rankings + events + teams + skills Parquets; merges on `(event_id, team_id)`; aggregates skills by type; writes per `(season_id, program_id)`.

**`team_skill_summary`** — reads curated skills Parquet; groups by `(season_id, program_id, team_id)`; computes `best`, `worst`, `avg` scores and event IDs for best/worst; writes per `(season_id, program_id)`.

---

## Implementation Order (remaining)

> Ingest and curate routes are on hold. Focus is the query layer + infrastructure.

1. ✓ Rewrite `app/models/schemas.py` — `FilterCondition`, `FilterGroup`, `OrderBy`, `SearchQuery`
2. ✓ Write `app/services/query_builder/{config.py, query_builder.py, __init__.py}` — 5 strategies (EVENTS, MATCHES, TEAM_EVENT, TEAM_SKILL, TEAM_SCORE) driven by `orderBy.field` allowlist; generic 6-step pipeline
3. Confirm `team_score_summary.sql` line 13 — fix duplicate `best_score_event_id` (likely `worst_score_event_id`)
4. Update `app/services/s3.py` — partition-keyed paths (`p_season_id/p_program_id/p_event_id`)
5. Write `scripts/seed_sample_data.py` — generate sample rows for all 8 curated tables, write as Parquet, upload to correct S3 partition paths
6. Write `app/services/athena.py` — DDL from `curated/*.sql` + synchronous execute+poll
7. Write `app/api/routes/query.py` — `/create-tables` + `/execute`
8. Write `app/main.py` — register query router only
9. Write `template.yaml` + `samconfig.toml` — SAM infrastructure template

**On hold** (resume when RobotEvents API is available):
- `app/services/robotevents.py` (update to 5 direct endpoints)
- `app/services/etl.py`
- `app/api/routes/ingest.py`
- `app/api/routes/curate.py`

---

## Sample Data Seeding (`scripts/seed_sample_data.py`)

Generates realistic sample rows for all 7 curated tables, converts to Parquet with the correct pyarrow schema, and uploads to the expected S3 partition paths. Intended as a one-time setup step to enable query-layer development without the RobotEvents API.

**Workflow** — sample data is built locally first, then uploaded to S3:
1. **Generate locally** — script materializes rows in memory and writes Parquet files to a local staging directory (e.g. `./sample_data/{table}/...parquet`) using the pyarrow schemas matching `curated/*.sql`. This lets you inspect / re-run the generation without S3 round-trips.
2. **Upload to S3** — script then uploads each local Parquet file to its corresponding Hive-partitioned path under `s3://vex-search-data-v1/curated/...` via `boto3` / `app.services.s3`.
3. Local staging directory can be deleted after a successful upload, or kept for re-uploads.

**Seed parameters** (argparse flags with defaults):
- `--season 190 --program 1` (VRC)
- `--events 10 --teams 100 --matches-per-event 10`
- `--seed 42` (deterministic)
- `--staging-dir ./sample_data`, `--skip-upload`, `--clean`

**Tables seeded and S3 paths written:**

| Table | S3 path |
|-------|---------|
| `events` | `curated/events/p_season_id=190/p_program_id=1/{ts}.parquet` |
| `teams` | `curated/teams/p_season_id=190/p_program_id=1/{ts}.parquet` |
| `matches` | `curated/matches/p_season_id=190/p_program_id=1/p_event_id={e}/{ts}.parquet` |
| `skills` | `curated/skills/p_season_id=190/p_program_id=1/p_event_id={e}/{ts}.parquet` |
| `rankings` | `curated/rankings/p_season_id=190/p_program_id=1/p_event_id={e}/{ts}.parquet` |
| `team_event_summary` | `curated/team_event_summary/p_season_id=190/p_program_id=1/{ts}.parquet` |
| `team_skill_summary` | `curated/team_skill_summary/p_season_id=190/p_program_id=1/{ts}.parquet` |
| `team_score_summary` | `curated/team_score_summary/p_season_id=190/p_program_id=1/{ts}.parquet` |

**Schema fidelity**: pyarrow schemas in `scripts/sample_data_schemas.py` are the single source of truth — column names, types, and nested ARRAY<STRUCT> shapes match `curated/*.sql` so Athena can read the files without a schema mismatch.

**Partition discovery**: the curated DDLs use partition projection (`TBLPROPERTIES projection.enabled=true`). Athena resolves partitions directly from S3 path templates at query time — no `MSCK REPAIR TABLE` step needed after seeding.

Run: `python scripts/seed_sample_data.py`

---

## SAM Infrastructure Template (`template.yaml`)

Deployed with `sam deploy --guided` (first time) or `sam deploy` (subsequent).
Config persisted in `samconfig.toml`.

### Resources

| Resource | Type | Notes |
|----------|------|-------|
| `VexDataBucket` | `AWS::S3::Bucket` | bucket name `vex-search-data-v1`; versioning enabled |
| `AthenaWorkgroup` | `AWS::Athena::WorkGroup` | output to `s3://vex-search-data-v1/athena-results/`; enforce workgroup config |
| `GlueDatabase` | `AWS::Glue::Database` | database name `vex_data` |
| `AppRole` | `AWS::IAM::Role` | Lambda execution role; S3 read/write on `vex-search-data-v1`; Athena + Glue full access |
| `VexDataFunction` | `AWS::Serverless::Function` | FastAPI wrapped with Mangum; handler `app.main.handler`; runtime Python 3.12 |
| `VexDataApi` | `AWS::Serverless::HttpApi` | routes all traffic to `VexDataFunction` |

### `template.yaml` structure

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Transform: AWS::Serverless-2016-10-31

Parameters:
  RobotEventsApiKey:
    Type: String
    NoEcho: true
  AthenaDatabase:
    Type: String
    Default: vex_data

Globals:
  Function:
    Runtime: python3.12
    Timeout: 30
    MemorySize: 512
    Environment:
      Variables:
        S3_BUCKET: !Ref VexDataBucket
        ATHENA_DATABASE: !Ref AthenaDatabase
        ATHENA_OUTPUT_LOCATION: !Sub s3://${VexDataBucket}/athena-results/
        ROBOTEVENTS_API_KEY: !Ref RobotEventsApiKey

Resources:
  VexDataBucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketName: vex-search-data-v1
      VersioningConfiguration:
        Status: Enabled

  AthenaWorkgroup:
    Type: AWS::Athena::WorkGroup
    Properties:
      Name: vex-data-wg
      WorkGroupConfiguration:
        ResultConfiguration:
          OutputLocation: !Sub s3://${VexDataBucket}/athena-results/
        EnforceWorkGroupConfiguration: true

  GlueDatabase:
    Type: AWS::Glue::Database
    Properties:
      CatalogId: !Ref AWS::AccountId
      DatabaseInput:
        Name: !Ref AthenaDatabase

  AppRole:
    Type: AWS::IAM::Role
    Properties:
      AssumeRolePolicyDocument: { ... lambda.amazonaws.com ... }
      ManagedPolicyArns:
        - arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
      Policies:
        - PolicyName: VexDataAccess
          PolicyDocument:
            Statement:
              - Effect: Allow
                Action: [ s3:GetObject, s3:PutObject, s3:ListBucket ]
                Resource: [ !GetAtt VexDataBucket.Arn, !Sub "${VexDataBucket.Arn}/*" ]
              - Effect: Allow
                Action: [ athena:*, glue:* ]
                Resource: "*"

  VexDataFunction:
    Type: AWS::Serverless::Function
    Properties:
      Handler: app.main.handler     # Mangum adapter entry point
      Role: !GetAtt AppRole.Arn
      CodeUri: .
      Events:
        Api:
          Type: HttpApi
          Properties:
            ApiId: !Ref VexDataApi
            Path: /{proxy+}
            Method: ANY

  VexDataApi:
    Type: AWS::Serverless::HttpApi

Outputs:
  ApiUrl:
    Value: !Sub https://${VexDataApi}.execute-api.${AWS::Region}.amazonaws.com
```

### `app/main.py` Mangum adapter

```python
from mangum import Mangum
app = FastAPI(...)
# ... register routers ...
handler = Mangum(app)   # AWS Lambda entry point
```

Add `mangum>=0.17.0` to `requirements.txt`.

---

## Verification

1. `pip install -r requirements.txt` + fill `.env`
2. **One-time** (only if tables already exist from a prior deploy): drop all 8 curated tables in the Athena console so the new partition-projection DDLs apply — Athena does not allow altering projection on existing tables.
3. `python scripts/seed_sample_data.py` → verify 8 curated Parquet sets appear in `s3://vex-search-data-v1/curated/`
4. `uvicorn app.main:app --reload`
5. `POST /query/create-tables` → verify `vex_data` database + 8 tables in Athena console
6. `POST /query/execute {"entity":"events","filter":{"and":[{"field":"season_id","op":"eq","value":190},{"field":"events.country","op":"eq","value":"United States"}]},"orderBy":{"field":"events.time","direction":"asc"},"selectTop":20}`
7. `POST /query/execute {"entity":"matches","filter":{"and":[{"field":"season_id","op":"eq","value":190},{"field":"teams.number","op":"eq","value":"1234Z"}]},"orderBy":{"field":"matches.score","direction":"desc"}}` → team alliance resolved for score column
8. `POST /query/execute {"entity":"team","filter":{"and":[{"field":"season_id","op":"eq","value":190}]},"orderBy":{"field":"rankings.rank","direction":"asc"},"selectTop":1}` → TEAM_EVENT strategy
9. `POST /query/execute {"entity":"team","filter":{"and":[{"field":"season_id","op":"eq","value":190},{"field":"program_id","op":"eq","value":1}]},"orderBy":{"field":"teams.best_skill_score","direction":"desc"},"selectTop":25}` → TEAM_SKILL strategy
10. `POST /query/execute {"entity":"team","filter":{"and":[{"field":"season_id","op":"eq","value":190},{"field":"events.name","op":"contains","value":"Regional Championship"}]},"orderBy":{"field":"rankings.rank","direction":"asc"},"selectTop":10}` → TEAM_EVENT strategy
11. `POST /query/execute {"entity":"team","filter":{"and":[{"field":"season_id","op":"eq","value":190},{"field":"program_id","op":"eq","value":1}]},"orderBy":{"field":"teams.high_score","direction":"desc"},"selectTop":10}` → TEAM_SCORE strategy

**SAM deploy:**
```bash
sam build
sam deploy --guided    # first time — saves answers to samconfig.toml
sam deploy             # subsequent deploys
```
