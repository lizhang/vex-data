## ADDED Requirements

### Requirement: POST /query/execute accepts SearchQuery and returns inline results
The endpoint SHALL accept a `SearchQuery` JSON body, build Athena SQL via `query_builder.build_query()`, execute it synchronously, and return a `QueryResponse` with all result rows in the same HTTP response. No separate polling endpoints are needed.

#### Scenario: Successful query returns rows
- **WHEN** `POST /query/execute` receives a valid `SearchQuery`
- **THEN** the response SHALL be HTTP 200 with body `{ "entity", "source_table", "sql_executed", "total", "rows": [...] }`

#### Scenario: Empty result set
- **WHEN** the Athena query returns zero rows
- **THEN** the response SHALL be HTTP 200 with `"total": 0` and `"rows": []`

#### Scenario: Athena query times out
- **WHEN** the query does not complete within 60 seconds
- **THEN** the endpoint SHALL return HTTP 504 with `{ "error": "Query timed out", "execution_id": "<id>" }`

#### Scenario: Invalid entity value
- **WHEN** `entity` is not one of `"events"`, `"matches"`, `"team"`
- **THEN** the endpoint SHALL return HTTP 422 (Pydantic validation error)

### Requirement: Query builder routes to correct strategy
`query_builder.build_query(query, db)` SHALL select one of 5 strategies based on `entity`, `filter.event`, and `orderBy` according to the decision tree in `query_rule.md`.

#### Scenario: entity="events" always uses EVENTS strategy
- **WHEN** `entity = "events"`
- **THEN** the generated SQL SHALL query `{db}.events` with no JOINs

#### Scenario: entity="matches" always uses MATCHES strategy
- **WHEN** `entity = "matches"`
- **THEN** the generated SQL SHALL query `{db}.matches` with no JOINs

#### Scenario: entity="team" with event filter uses TEAM_EVENT
- **WHEN** `entity = "team"` AND `filter.event.name` or `filter.event.sku` is set
- **THEN** the generated SQL SHALL query `{db}.team_event_summary`

#### Scenario: entity="team" with orderBy="score" and no time filter uses TEAM_SKILL
- **WHEN** `entity = "team"` AND `orderBy = "score"` AND `filter.time` is absent
- **THEN** the generated SQL SHALL join `{db}.teams` and `{db}.team_skill_summary`

#### Scenario: entity="team" with orderBy="score" and time filter uses TEAM_MATCH_SCORE
- **WHEN** `entity = "team"` AND `orderBy = "score"` AND `filter.time` is set
- **THEN** the generated SQL SHALL join `{db}.teams`, `{db}.matches`, and `{db}.events`

#### Scenario: entity="team" default uses TEAM_RANKING
- **WHEN** `entity = "team"` AND no event filter AND `orderBy` is not `"score"`
- **THEN** the generated SQL SHALL join `{db}.teams` and `{db}.rankings` with GROUP BY aggregates

#### Scenario: TEAM_RANKING with time filter adds events join
- **WHEN** `entity = "team"` default AND `filter.time` is set
- **THEN** the generated SQL SHALL also LEFT JOIN `{db}.events` via `rankings.event_id` and apply time conditions to `e.start_date` / `e.end_date`

### Requirement: Query builder uses parameterized queries
All user-supplied values SHALL be passed as Athena `ExecutionParameters` (`?` placeholders). No raw user input SHALL appear in the SQL string.

#### Scenario: String filter value is parameterized
- **WHEN** `filter.location.city = "Los Angeles"` is provided
- **THEN** the SQL string SHALL contain `LOWER(city) LIKE LOWER(?)` and `"Los Angeles"` SHALL appear in `ExecutionParameters`, not in the SQL string

#### Scenario: Integer filter value is parameterized
- **WHEN** `filter.season_id = 190` is provided
- **THEN** the SQL string SHALL contain `p_season_id = ?` and `"190"` SHALL appear in `ExecutionParameters`

### Requirement: Sort and column fields are allowlisted
The `orderBy` value SHALL be resolved through a per-strategy allowlist dict. The raw `orderBy` string SHALL never be embedded in SQL.

#### Scenario: Valid orderBy maps to allowlisted expression
- **WHEN** `orderBy = "time"` with `entity = "events"`
- **THEN** the ORDER BY clause SHALL be exactly `ORDER BY start_date ASC`

#### Scenario: Unsupported orderBy for strategy produces no ORDER BY
- **WHEN** `orderBy = "ranking"` with `entity = "events"`
- **THEN** the generated SQL SHALL contain no ORDER BY clause

### Requirement: selectTop is bounded
`selectTop` SHALL default to 25 when absent and be capped at 1000 regardless of the value provided.

#### Scenario: Default limit applied
- **WHEN** `selectTop` is absent from the request
- **THEN** the generated SQL SHALL contain `LIMIT 25`

#### Scenario: Oversized limit is capped
- **WHEN** `selectTop = 5000`
- **THEN** the generated SQL SHALL contain `LIMIT 1000`
