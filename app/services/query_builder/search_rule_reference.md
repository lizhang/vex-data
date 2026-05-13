# SearchQuery Field Reference

## Request Shape

```json
{
  "entity": "events | matches | team",
  "filter": {
    "and": [
      { "field": "season_id",           "op": "eq",       "value": 190 },
      { "field": "teams.city",          "op": "eq",       "value": "Los Angeles" },
      { "field": "events.start_time",   "op": "gt",       "value": "2026-01-02T00:00:00-05:00" }
    ]
  },
  "orderBy": { "field": "rankings.rank", "direction": "asc" },
  "selectTop": 25
}
```

- `filter` uses `"and"` or `"or"` (one level, no nesting).
- `selectTop` defaults to `25`; maximum `1000`.
- Time values are ISO 8601 with timezone offset: `"2026-01-02T00:00:00-05:00"`.

---

## Filter Fields

### Partition (always provide for partition pruning)

| field        | op | curated column  |
|--------------|----|-----------------|
| `season_id`  | eq | `p_season_id`   |
| `program_id` | eq | `p_program_id`  |

### Team location

| field            | op       | curated column    |
|------------------|----------|-------------------|
| `teams.city`     | eq       | `teams.city`      |
| `teams.postcode` | eq       | `teams.postcode`  |
| `teams.country`  | eq       | `teams.country`   |
| `teams.region`   | contains | `teams.region`    |

### Event location

| field             | op       | curated column    |
|-------------------|----------|-------------------|
| `events.city`     | eq       | `events.city`     |
| `events.postcode` | eq       | `events.postcode` |
| `events.country`  | eq       | `events.country`  |
| `events.region`   | contains | `events.region`   |
| `events.venue`    | contains | `events.venue`    |

### Event identity

| field        | op       | curated column |
|--------------|----------|----------------|
| `events.name`| contains | `events.name`  |
| `events.sku` | eq       | `events.sku`   |

### Team identity

| field          | op       | curated column    |
|----------------|----------|-------------------|
| `teams.name`   | contains | `teams.team_name` |
| `teams.number` | eq       | `teams.number`    |

### Time (always a range: `gt` on start, `lt` on end)

| field                | op | curated column              | notes                        |
|----------------------|----|-----------------------------|------------------------------|
| `events.start_time`  | gt | `events.start_date`         |                              |
| `events.end_time`    | lt | `events.end_date`           |                              |
| `matches.start_time` | gt | `COALESCE(started_time, scheduled_time)`  | use actual start if known, else scheduled |
| `matches.end_time`   | lt | `started_time + INTERVAL '5' MINUTE`      | NULL (row excluded) when `started_time IS NULL` |

---

## orderBy Fields and Routing

`orderBy.field` determines both the ORDER BY expression and, for `entity="team"`, which strategy and tables are used.

### `entity="events"` → EVENTS strategy (`events`)

| orderBy.field  | SQL expression          |
|----------------|-------------------------|
| `events.time`  | `start_date {dir}`      |

### `entity="matches"` → MATCHES strategy (`matches`)

| orderBy.field   | SQL expression                                                           |
|-----------------|--------------------------------------------------------------------------|
| `matches.time`  | `scheduled_time {dir}`                                                   |
| `matches.score` | `red_score {dir}` if team in red alliance, else `blue_score {dir}`      |

> **Constraint**: `orderBy.field = "matches.score"` requires `teams.name` or `teams.number` in the filter.
> Requests without a team identity filter are rejected with `422`.
> The score column is resolved at query time:
> team found in `red_teams` → `ORDER BY red_score {dir}`;
> team found in `blue_teams` → `ORDER BY blue_score {dir}`.

### `entity="team"` — routed by `orderBy.field`

#### Skill score fields → TEAM_SKILL (`teams LEFT JOIN team_skill_summary`)

Only valid with `season_id` / `program_id` filter. Cannot combine with location, event, or time filters.

| orderBy.field            | SQL expression              |
|--------------------------|-----------------------------|
| `teams.best_skill_score` | `s.best_skill_score {dir}`  |
| `teams.worst_skill_score`| `s.worst_skill_score {dir}` |
| `teams.avg_skill_score`  | `s.avg_skill_score {dir}`   |

#### Score summary fields → TEAM_SCORE (`teams LEFT JOIN team_score_summary`)

Only valid with team + `season_id` / `program_id` filter.

| orderBy.field          | SQL expression              |
|------------------------|-----------------------------|
| `teams.high_score`     | `s.high_score {dir}`        |
| `teams.average_points` | `s.average_points {dir}`    |
| `teams.total_points`   | `s.total_points {dir}`      |

#### All other team fields → TEAM_EVENT (`team_event_summary`)

Supports event, team, location, `season_id`, `program_id` filters. Not valid with `matches.*` time filters.

| orderBy.field       | SQL expression           |
|---------------------|--------------------------|
| `rankings.rank`     | `ranking {dir}`          |
| `events.skills_rank`| `skills_rank {dir}`      |
| `events.score`      | `best_score {dir}`       |
| `events.time`       | `event_start_date {dir}` |
| _(null / default)_  | `ranking asc`            |

---

## Field Constraints

| orderBy.field   | Required filter field(s)        | Error if missing |
|-----------------|---------------------------------|-----------------|
| `matches.score` | `teams.name` or `teams.number`  | 422             |

---

## SQL Encoding Rules

| Filter type | SQL pattern | Applies to |
|-------------|-------------|------------|
| Partition   | `p_col = ?` | `season_id`, `program_id` |
| Exact       | `col = ?`   | `sku`, `number`, `country`, `postcode` |
| Substring   | `LOWER(col) LIKE LOWER(?)` with `%value%` | `name`, `city`, `region`, `venue`, `team_name` |
| Time `gt`   | `col > TIMESTAMP ?` | start time fields |
| Time `lt`   | `col < TIMESTAMP ?` | end time fields |
| Match end   | `started_time IS NOT NULL AND started_time + INTERVAL '5' MINUTE < TIMESTAMP ?` | `matches.end_time` only |

All user values go through Athena `ExecutionParameters` (`?` placeholders) — never interpolated into SQL.
Unknown `filter.field` values are rejected with `422`. The `orderBy.field` raw value is never embedded in SQL; it resolves to a fixed expression through a per-strategy allowlist.
