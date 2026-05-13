# Search Rule Reference

## Filter

Each filter condition has a `field`, an `op` (operation), and a `value`.
Conditions are grouped under a single `"and"` or `"or"` key (one level only, no nesting).

### Operations
| op       | Meaning              |
|----------|----------------------|
| eq       | exact match          |
| neq      | not equal            |
| gt       | greater than         |
| lt       | less than            |
| contains | substring / partial  |

### Filter Fields

**Location** (applies to teams or events)

| Field           | op       | Notes                        | maps to curated table
|-----------------|----------|------------------------------|----------------------
| teams.city      | eq       | full city name               |teams.city
| teams.postcode  | eq       |                              |teams.postcode
| teams.country   | eq       | full country name            |teams.country
| teams.region    | contains |                              |teams.region
| events.city     | eq       | full city name               |events.city
| events.postcode | eq       |                              |events.postcode
| events.country  | eq       | full country name            |events.country
| events.region   | contains |                              |events.region 
| events.venue    | contains |                              |events.venue

**Event**

| Field       | op       | maps to curated table
|-------------|----------|-------------------------
| events.name | contains |events.name
| events.sku  | eq       |events.sku

**Time** — always a range: `gt` on start + `lt` on end

| Field               | op | maps to curated table
|---------------------|----|-------------------------
| events.start_time   | gt |events.start_date
| events.end_time     | lt |events.end_date
| matches.start_time  | gt |eariler of (matches.scheduled_time, matches.started_time)
| matches.end_time    | lt |matches.started_time + 5 mins

**Team**

| Field        | op       | maps to curated table
|--------------|----------|------------------------
| teams.name   | contains |teams.team_name
| teams.number | eq       |teams.number

**Program / Season**

| Field      | op | maps to curated table
|------------|----|------------------------
| program_id | eq | p_program_id
| season_id  | eq | p_season_id

---

## orderBy

Single object: `{"field": "<field>", "direction": "asc" | "desc"}`

### Skill score
Only valid with `season_id` / `program_id` filter. Cannot be combined with location, event, or time filters.

| Field                  | When to use                      | maps to curated table
|------------------------|----------------------------------|--------------------------
| teams.best_skill_score | user asks for best skill score   | team_skill_summary.best_skill_score
| teams.worst_skill_score| user asks for worst skill score  | team_skill_summary.worst_skill_score
| teams.avg_skill_score  | user asks for average skill score| team_skill_summary.avg_skill_score

### Skills rank
Supports event / team / location / season_id / program_id filters. Not valid with matches' time filter.

| Field             | When to use              | maps to curated table
|-------------------|--------------------------|-----------------------
| events.skills_rank| user mentions skill rank | team_event_summary.skills_rank

### Rankings
Supports event / team / location / season_id / program_id filters. Not valid with matches time filter.

| Field         | When to use                              | maps to curated table
|---------------|------------------------------------------|------------------------
| rankings.rank | user says "top", "best", "highest ranked"| team_event_summary.ranking

### Score

| Field               | When to use                                  | Filter restriction                 |  maps to curated table
|---------------------|----------------------------------------------|------------------------------------|---------------------------
| events.score        | score in event context                       | not valid with matches time        | team_event_summary.score
| matches.score       | score in matches context                     | must have a team                   | matches.red_score if match red teams, otherwise blud team
| teams.high_score    | user mentions team's high score              | team + season_id / program_id only | team_score_summary.high_score
| teams.average_points| user mentions team's average points          | team + season_id / program_id only | team_score_summary.average_points
| teams.total_points  | user mentions team's total points            | team + season_id / program_id only | team_score_summary.total_points

### Time

| Field        | When to use                                      |   maps to curated table
|--------------|--------------------------------------------------|----------------------------
| events.time  | user says "latest", "upcoming", "recent" (events)| events.start_date
| matches.time | user says "latest", "upcoming", "recent" (matches)| matches.scheduled_time
