# Query Builder Rules

## Overview

`/query/execute` accepts a `SearchQuery` with four fields: `entity`, `filter`, `orderBy`, `selectTop`.

**Entities**: `"events"`, `"matches"`, `"team"`.

`filter` is a `FilterGroup` — either `{"and": [...]}` or `{"or": [...]}`, one level, no nesting.
Each condition: `{"field": "...", "op": "eq|neq|gt|lt|contains", "value": ...}`.

`orderBy` is an `OrderBy` object: `{"field": "...", "direction": "asc|desc"}`.

---

## Routing Decision Tree

```
entity = "events"
    → Strategy: EVENTS
    → Table: events

entity = "matches"
    → Strategy: MATCHES
    → Table: matches

entity = "team"
    ├── orderBy.field ∈ {teams.best_skill_score, teams.worst_skill_score, teams.avg_skill_score}
    │       → Strategy: TEAM_SKILL
    │       → Tables: teams t LEFT JOIN team_skill_summary s
    ├── orderBy.field ∈ {teams.high_score, teams.average_points, teams.total_points}
    │       → Strategy: TEAM_SCORE
    │       → Tables: teams t LEFT JOIN team_score_summary s
    └── default (all other orderBy.field values, or null)
            → Strategy: TEAM_EVENT
            → Table: team_event_summary
              + LEFT JOIN teams t  (only when location filter fields present)
```

---

## Strategy: EVENTS

**Table**: `{db}.events`

### SQL template
```sql
SELECT *
FROM {db}.events
WHERE {conditions}
ORDER BY {order}
LIMIT {limit}
```

### Filter → WHERE

| filter.field | op | SQL condition |
|---|---|---|
| `season_id` | eq | `p_season_id = ?` |
| `program_id` | eq | `p_program_id = ?` |
| `events.name` | contains | `LOWER(name) LIKE LOWER(?)` — param: `%value%` |
| `events.sku` | eq | `sku = ?` |
| `events.city` | eq | `city = ?` |
| `events.country` | eq | `country = ?` |
| `events.region` | contains | `LOWER(region) LIKE LOWER(?)` |
| `events.venue` | contains | `LOWER(venue) LIKE LOWER(?)` |
| `events.postcode` | eq | `postcode = ?` |
| `events.start_time` | gt | `start_date > TIMESTAMP ?` |
| `events.end_time` | lt | `end_date < TIMESTAMP ?` |

### orderBy.field → ORDER BY

| orderBy.field | SQL |
|---|---|
| `events.time` | `start_date {dir}` |
| any other | _(no ORDER BY)_ |

### Example
```json
{
  "entity": "events",
  "filter": { "and": [
    { "field": "season_id",      "op": "eq",       "value": 190 },
    { "field": "events.country", "op": "eq",       "value": "United States" }
  ]},
  "orderBy": { "field": "events.time", "direction": "asc" },
  "selectTop": 20
}
```
```sql
SELECT * FROM vex_data.events
WHERE p_season_id = ?
  AND country = ?
ORDER BY start_date ASC
LIMIT 20
-- params: [190, "United States"]
```

---

## Strategy: MATCHES

**Table**: `{db}.matches`

### SQL template
```sql
SELECT *
FROM {db}.matches
WHERE {conditions}
ORDER BY {order}
LIMIT {limit}
```

### Filter → WHERE

| filter.field | op | SQL condition |
|---|---|---|
| `season_id` | eq | `p_season_id = ?` |
| `program_id` | eq | `p_program_id = ?` |
| `events.sku` | eq | `event_sku = ?` |
| `events.name` | contains | `LOWER(event_name) LIKE LOWER(?)` |
| `teams.number` | eq | `EXISTS (SELECT 1 FROM UNNEST(red_teams) t WHERE t.number = ?) OR EXISTS (SELECT 1 FROM UNNEST(blue_teams) t WHERE t.number = ?)` — two params |
| `matches.start_time` | gt | `COALESCE(started_time, scheduled_time) > TIMESTAMP ?` |
| `matches.end_time` | lt | `started_time IS NOT NULL AND started_time + INTERVAL '5' MINUTE < TIMESTAMP ?` |

### orderBy.field → ORDER BY

| orderBy.field | SQL |
|---|---|
| `matches.time` | `scheduled_time {dir}` |
| `matches.score` | `CASE WHEN EXISTS (SELECT 1 FROM UNNEST(red_teams) t WHERE t.number = ?) THEN red_score ELSE blue_score END {dir}` |
| any other | _(no ORDER BY)_ |

> **Constraint**: `orderBy.field = "matches.score"` requires a `teams.number` filter condition — rejected with 422 if absent. The `teams.number` value used in the WHERE clause is reused as the param in the CASE expression.

### Example
```json
{
  "entity": "matches",
  "filter": { "and": [
    { "field": "season_id",    "op": "eq", "value": 190 },
    { "field": "teams.number", "op": "eq", "value": "1234Z" }
  ]},
  "orderBy": { "field": "matches.score", "direction": "desc" }
}
```
```sql
SELECT * FROM vex_data.matches
WHERE p_season_id = ?
  AND (EXISTS (SELECT 1 FROM UNNEST(red_teams) t WHERE t.number = ?)
       OR  EXISTS (SELECT 1 FROM UNNEST(blue_teams) t WHERE t.number = ?))
ORDER BY CASE WHEN EXISTS (SELECT 1 FROM UNNEST(red_teams) t WHERE t.number = ?)
              THEN red_score ELSE blue_score END DESC
LIMIT 25
-- params: [190, "1234Z", "1234Z", "1234Z"]
```

---

## Strategy: TEAM_EVENT

**Trigger**: `entity = "team"`, `orderBy.field` not in skill-score or score-summary field sets (default).

**Base table**: `{db}.team_event_summary tes`

**Teams join** — added when any `teams.city`, `teams.country`, `teams.region`, or `teams.postcode` filter is present (those columns are not in `team_event_summary`):
```sql
LEFT JOIN {db}.teams t
  ON  tes.team_id      = t.team_id
  AND tes.p_season_id  = t.p_season_id
  AND tes.p_program_id = t.p_program_id
```

### SQL template (no location filter)
```sql
SELECT *
FROM {db}.team_event_summary
WHERE {conditions}
ORDER BY {order}
LIMIT {limit}
```

### SQL template (with location filter)
```sql
SELECT tes.*
FROM {db}.team_event_summary tes
LEFT JOIN {db}.teams t
  ON  tes.team_id      = t.team_id
  AND tes.p_season_id  = t.p_season_id
  AND tes.p_program_id = t.p_program_id
WHERE {conditions}
ORDER BY {order}
LIMIT {limit}
```

### Filter → WHERE

| filter.field | op | SQL condition | note |
|---|---|---|---|
| `season_id` | eq | `p_season_id = ?` | |
| `program_id` | eq | `p_program_id = ?` | |
| `events.sku` | eq | `event_sku = ?` | |
| `events.name` | contains | `LOWER(event_name) LIKE LOWER(?)` | |
| `teams.number` | eq | `team_number = ?` | |
| `teams.name` | contains | `LOWER(team_name) LIKE LOWER(?)` | |
| `teams.city` | eq | `t.city = ?` | requires teams join |
| `teams.country` | eq | `t.country = ?` | requires teams join |
| `teams.region` | contains | `LOWER(t.region) LIKE LOWER(?)` | requires teams join |
| `teams.postcode` | eq | `t.postcode = ?` | requires teams join |
| `events.start_time` | gt | `event_start_date > TIMESTAMP ?` | |
| `events.end_time` | lt | `event_start_date < TIMESTAMP ?` | |

### orderBy.field → ORDER BY

| orderBy.field | SQL |
|---|---|
| `rankings.rank` | `ranking {dir}` |
| `events.skills_rank` | `skills_rank {dir}` |
| `events.score` | `best_score {dir}` |
| `events.time` | `event_start_date {dir}` |
| null / default | `ranking ASC` |

### Example
```json
{
  "entity": "team",
  "filter": { "and": [
    { "field": "season_id",   "op": "eq",       "value": 190 },
    { "field": "events.name", "op": "contains", "value": "Regional Championship" }
  ]},
  "orderBy": { "field": "rankings.rank", "direction": "asc" },
  "selectTop": 10
}
```
```sql
SELECT * FROM vex_data.team_event_summary
WHERE p_season_id = ?
  AND LOWER(event_name) LIKE LOWER(?)
ORDER BY ranking ASC
LIMIT 10
-- params: [190, "%Regional Championship%"]
```

---

## Strategy: TEAM_SKILL

**Trigger**: `entity = "team"`, `orderBy.field` ∈ `{teams.best_skill_score, teams.worst_skill_score, teams.avg_skill_score}`.

**Tables**: `{db}.teams t LEFT JOIN {db}.team_skill_summary s`

### SQL template
```sql
SELECT
  t.team_id, t.number, t.team_name, t.organization,
  t.program_id, t.program_name,
  t.city, t.region, t.postcode, t.country, t.grade, t.registered,
  s.best_skill_score, s.worst_skill_score, s.avg_skill_score,
  s.best_skill_event_id, s.worst_skill_event_id
FROM {db}.teams t
LEFT JOIN {db}.team_skill_summary s
  ON  t.team_id      = s.team_id
  AND t.p_season_id  = s.p_season_id
  AND t.p_program_id = s.p_program_id
WHERE {conditions}
ORDER BY {order}
LIMIT {limit}
```

### Filter → WHERE (applied to `t` alias)

| filter.field | op | SQL condition |
|---|---|---|
| `season_id` | eq | `t.p_season_id = ?` |
| `program_id` | eq | `t.p_program_id = ?` |
| `teams.number` | eq | `t.number = ?` |
| `teams.name` | contains | `LOWER(t.team_name) LIKE LOWER(?)` |
| `teams.city` | eq | `t.city = ?` |
| `teams.country` | eq | `t.country = ?` |
| `teams.region` | contains | `LOWER(t.region) LIKE LOWER(?)` |
| `teams.postcode` | eq | `t.postcode = ?` |

Event and time filter fields are not applicable to this strategy.

### orderBy.field → ORDER BY

| orderBy.field | SQL |
|---|---|
| `teams.best_skill_score` | `s.best_skill_score {dir}` |
| `teams.worst_skill_score` | `s.worst_skill_score {dir}` |
| `teams.avg_skill_score` | `s.avg_skill_score {dir}` |

### Example
```json
{
  "entity": "team",
  "filter": { "and": [
    { "field": "season_id",  "op": "eq", "value": 190 },
    { "field": "program_id", "op": "eq", "value": 1 }
  ]},
  "orderBy": { "field": "teams.best_skill_score", "direction": "desc" },
  "selectTop": 25
}
```
```sql
SELECT
  t.team_id, t.number, t.team_name, t.organization,
  t.program_id, t.program_name, t.city, t.region, t.postcode, t.country, t.grade, t.registered,
  s.best_skill_score, s.worst_skill_score, s.avg_skill_score,
  s.best_skill_event_id, s.worst_skill_event_id
FROM vex_data.teams t
LEFT JOIN vex_data.team_skill_summary s
  ON t.team_id = s.team_id AND t.p_season_id = s.p_season_id AND t.p_program_id = s.p_program_id
WHERE t.p_season_id = ?
  AND t.p_program_id = ?
ORDER BY s.best_skill_score DESC
LIMIT 25
-- params: [190, 1]
```

---

## Strategy: TEAM_SCORE

**Trigger**: `entity = "team"`, `orderBy.field` ∈ `{teams.high_score, teams.average_points, teams.total_points}`.

**Tables**: `{db}.teams t LEFT JOIN {db}.team_score_summary s`

### SQL template
```sql
SELECT
  t.team_id, t.number, t.team_name, t.organization,
  t.program_id, t.program_name,
  t.city, t.region, t.postcode, t.country, t.grade, t.registered,
  s.high_score, s.average_points, s.total_points, s.best_score_event_id
FROM {db}.teams t
LEFT JOIN {db}.team_score_summary s
  ON  t.team_id      = s.team_id
  AND t.p_season_id  = s.p_season_id
  AND t.p_program_id = s.p_program_id
WHERE {conditions}
ORDER BY {order}
LIMIT {limit}
```

### Filter → WHERE

Same as TEAM_SKILL — applied to `t` alias. Event and time filter fields are not applicable.

### orderBy.field → ORDER BY

| orderBy.field | SQL |
|---|---|
| `teams.high_score` | `s.high_score {dir}` |
| `teams.average_points` | `s.average_points {dir}` |
| `teams.total_points` | `s.total_points {dir}` |

### Example
```json
{
  "entity": "team",
  "filter": { "and": [
    { "field": "season_id",  "op": "eq", "value": 190 },
    { "field": "program_id", "op": "eq", "value": 1 }
  ]},
  "orderBy": { "field": "teams.high_score", "direction": "desc" },
  "selectTop": 10
}
```
```sql
SELECT
  t.team_id, t.number, t.team_name, t.organization,
  t.program_id, t.program_name, t.city, t.region, t.postcode, t.country, t.grade, t.registered,
  s.high_score, s.average_points, s.total_points, s.best_score_event_id
FROM vex_data.teams t
LEFT JOIN vex_data.team_score_summary s
  ON t.team_id = s.team_id AND t.p_season_id = s.p_season_id AND t.p_program_id = s.p_program_id
WHERE t.p_season_id = ?
  AND t.p_program_id = ?
ORDER BY s.high_score DESC
LIMIT 10
-- params: [190, 1]
```

---

## General Rules

1. **Default limit**: `selectTop` defaults to `25` if not provided; maximum capped at `1000`.
2. **NULL safety**: Only non-null filter fields are added to WHERE.
3. **Filter group logic**: `filter.and` → conditions joined with `AND`; `filter.or` → conditions joined with `OR`. No nesting.
4. **SQL injection prevention**: All user values go through Athena `ExecutionParameters` (`?` placeholders). Never interpolate raw user input into SQL.
5. **Table whitelisting**: Tables are selected entirely by routing logic — user input never determines which table is queried.
6. **Field allowlist**: `filter.field` is looked up in a per-strategy hard-coded dict. Unknown fields are rejected with 422.
7. **Sort allowlist**: `orderBy.field` is resolved through a per-strategy dict to a fixed SQL expression. The raw value is never embedded in SQL.

   | orderBy.field | Strategy | SQL expression |
   |---|---|---|
   | `events.time` | EVENTS | `start_date {dir}` |
   | `matches.time` | MATCHES | `scheduled_time {dir}` |
   | `matches.score` | MATCHES | CASE red/blue alliance (see MATCHES section) |
   | `rankings.rank` | TEAM_EVENT | `ranking {dir}` |
   | `events.skills_rank` | TEAM_EVENT | `skills_rank {dir}` |
   | `events.score` | TEAM_EVENT | `best_score {dir}` |
   | `events.time` | TEAM_EVENT | `event_start_date {dir}` |
   | `teams.best_skill_score` | TEAM_SKILL | `s.best_skill_score {dir}` |
   | `teams.worst_skill_score` | TEAM_SKILL | `s.worst_skill_score {dir}` |
   | `teams.avg_skill_score` | TEAM_SKILL | `s.avg_skill_score {dir}` |
   | `teams.high_score` | TEAM_SCORE | `s.high_score {dir}` |
   | `teams.average_points` | TEAM_SCORE | `s.average_points {dir}` |
   | `teams.total_points` | TEAM_SCORE | `s.total_points {dir}` |

8. **Partition pruning**: Always include `season_id` and `program_id` in filters — they map to `p_season_id` / `p_program_id` partition columns.
9. **LIKE matching**: `contains` op → `LOWER(col) LIKE LOWER(?)`, param wrapped as `%value%`.
10. **Exact matching**: `eq` op → `col = ?`.
11. **Time values**: ISO 8601 with timezone offset, e.g. `"2026-01-02T00:00:00-05:00"`. Passed directly as the `TIMESTAMP ?` parameter.

---

## Security

- User values → Athena `ExecutionParameters` (`?` placeholders). Never interpolated into SQL.
- `filter.field` validated against a hard-coded per-strategy allowlist; unknown fields rejected with `422`.
- Table selection is pure routing logic — user input never determines which table is queried.
- `orderBy.field` resolved through a per-strategy allowlist dict; raw value never embedded in SQL.
- `selectTop` capped at `1000`.
