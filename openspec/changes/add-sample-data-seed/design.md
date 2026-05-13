## Context

Three changes have shipped or are in flight:
- `vex-query-layer` (umbrella) — proposed the seed script but never specced it in detail.
- `add-sam-infrastructure` — produced `template.yaml` and the S3 bucket.
- `add-athena-query-routes` — added `app/services/athena.py` + `POST /query/execute` and `POST /query/create-tables`.

What's missing: data. The seed script is the last piece that lets a developer go from a fresh clone to a query response. The RobotEvents API is unreachable, so we cannot use the real ingest/curate path; we materialize plausible data directly into curated S3 paths.

Two existing pieces of the codebase shape the design:
- `curated/*.sql` — DDLs use `PARTITIONED BY (p_season_id int, p_program_id int [, p_event_id bigint])` with no partition projection or MSCK setup.
- `app/services/s3.py` — `raw_key()` / `curated_key()` produce `dt={iso-date}/...` paths, predating the Hive-partition decision. The on-hold ingest/curate modules are the only callers.

## Goals / Non-Goals

**Goals:**
- A single command (`python scripts/seed_sample_data.py`) produces a working dataset for query smoke tests.
- All 8 tables are referentially consistent: every `team_id` in `matches`, `skills`, `rankings` exists in `teams`; every `event_id` exists in `events`; derived tables aggregate exactly from generated base rows.
- Athena auto-discovers partitions — no manual `MSCK` or `ALTER TABLE ADD PARTITION` step.
- The path produced by `s3.py` matches what the DDLs expect, so the seed script and any future ingest/curate code share the same path source of truth.
- Deterministic output (random seed) for reproducible test runs.

**Non-Goals:**
- Production-realistic statistics. Distributions are uniform / plausible-looking, not modeled.
- Schema evolution. The script writes the DDL's current schema; any future column changes touch both.
- Continuous backfill. Re-running uploads a new `{ts}.parquet` alongside the previous one; partition-level uniqueness is not enforced (Athena reads all files in a partition).
- Restoring s3.py callers in `etl.py` / `ingest.py` / `curate.py` — those routes stay on hold; we update import sites only if Python imports break.

## Decisions

### 1. Partition projection in DDLs (not MSCK, not a /repair route)

Each curated DDL gains a `TBLPROPERTIES` block enabling partition projection:

```sql
TBLPROPERTIES (
  'projection.enabled' = 'true',
  'projection.p_season_id.type' = 'integer',
  'projection.p_season_id.range' = '180,210',
  'projection.p_program_id.type' = 'integer',
  'projection.p_program_id.range' = '1,100',
  -- event-scoped tables also:
  'projection.p_event_id.type' = 'integer',
  'projection.p_event_id.range' = '1,99999999',
  'storage.location.template'
     = 's3://<bucket>/curated/<table>/p_season_id=${p_season_id}/p_program_id=${p_program_id}/[p_event_id=${p_event_id}/]'
)
```

**Why:** Partition projection lets Athena infer partition values from path templates at query time without a metastore round trip. Removes a `MSCK REPAIR TABLE` post-step from every seed run and from the future ingest/curate flow. Trade-off: ranges are hardcoded; out-of-range partitions are invisible. Range chosen wide enough (`180–210` for season, `1–100` for program) to cover the foreseeable VEX seasons/programs.

**Alternative considered:**
- `MSCK REPAIR TABLE` after seed: one extra round trip per seed run; no benefit at runtime.
- `/query/repair-partitions` route: pushes the maintenance burden into the runtime API; adds surface area for no daily benefit.

### 2. Re-create tables on deploy of this change (Athena DDL constraint)

Athena does not support `ALTER TABLE ... SET TBLPROPERTIES (...)` for projection settings — they have to be on the table at create time. Since `POST /query/create-tables` uses `CREATE EXTERNAL TABLE IF NOT EXISTS`, existing tables won't pick up the new properties.

**Resolution:**
- This change documents a one-time `DROP TABLE` step (run via SQL in Athena console or a temp CLI) before re-running `POST /query/create-tables`.
- Not introducing a `/query/drop-tables` route — it's a one-time concern; not worth the API surface.
- DDL files keep `CREATE EXTERNAL TABLE IF NOT EXISTS` so the route stays idempotent for future runs.

### 3. Aggregate derived tables from generated base rows (option b)

`team_event_summary`, `team_skill_summary`, `team_score_summary` are computed by group-by over the generated base rows, not generated independently:

```
matches + teams + events  ─►  team_event_summary
skills + teams            ─►  team_skill_summary
matches + teams           ─►  team_score_summary
```

**Why:** The query router's `TEAM_EVENT` / `TEAM_SKILL` strategies JOIN derived rows against base rows; independently generated derived tables would produce incoherent JOINs (a team's `best_skill_score` in `team_skill_summary` referencing a `skills` row that doesn't exist). Costs ~30 lines of group-by logic; pays back in test fidelity.

**Implementation:** pure Python dict accumulation, no pandas. The dataset is small (~thousands of rows).

### 4. Single source of truth for pyarrow schemas

A `scripts/sample_data_schemas.py` module exports a dict:

```python
SCHEMAS: dict[str, pa.Schema] = {
    "events": pa.schema([...]),
    "matches": pa.schema([
        ...,
        ("red_teams", pa.list_(pa.struct([
            ("team_id", pa.int64()),
            ("number", pa.string()),
        ]))),
        ...,
    ]),
    ...
}
```

**Why:** Three places want to agree on shape: the DDL (Athena reads), the pyarrow schema (Parquet writes), and the row-generation code (dict shape). Centralizing the pyarrow schema means the generator only has to produce plain Python dicts; pyarrow handles type coercion. If a column is added later, the change is local.

**Risks:** still two-source (DDL + schemas.py). We don't auto-derive one from the other in this change; a future change could generate the pyarrow schema from the DDL.

### 5. Fix s3.py path helpers in place (option a)

`s3.py` is updated to emit Hive paths matching the DDLs. New signatures:

```python
def raw_key(entity, season_id, program_id, timestamp, event_id=None) -> str
def curated_key(entity, season_id, program_id, timestamp, event_id=None) -> str
def list_curated_keys(entity, season_id=None, program_id=None, event_id=None) -> list[str]
```

`raw_key` / `curated_key` callers in `etl.py`, `ingest.py`, `curate.py` are on hold and unused at runtime — they get updated mechanically to compile but aren't tested in this change.

**Why:** Centralizing path construction prevents drift between the seed script today and the curate route tomorrow. The on-hold modules are the only callers; impact is contained.

### 6. CLI shape — argparse with flags

```
python scripts/seed_sample_data.py \
  --season 190 --program 1 \
  --events 10 --teams 100 --matches-per-event 10 \
  --seed 42 \
  --staging-dir ./sample_data \
  [--skip-upload] [--clean]
```

- `--clean`: deletes prior content of `--staging-dir` AND prior S3 objects matching the partition prefixes before writing (uses `boto3` `list_objects_v2` + `delete_objects`).
- Defaults match plan.md (10 events / 100 teams / 10 matches per event).
- `--seed` makes runs deterministic so the same dataset can be re-uploaded after `--clean`.

**Why:** Hardcoded constants force a code edit for every variation (smaller dataset for fast tests, larger for stress). argparse is one-time cost.

### 7. Generation strategy and referential consistency

```
Generation order (deterministic, seeded):

  1. events      ── N events, each with a synthetic event_id
                    and an event-local divisions list
  2. teams       ── M teams, distributed across plausible cities;
                    independent of events
  3. matches     ── for each event: K matches; each match draws
                    2 red + 2 blue teams from the teams pool
  4. skills      ── for each event × team subset: 1–2 skills rows
  5. rankings    ── for each event: one rankings row per team
                    that participated in that event's matches

  6. team_event_summary   ── aggregate matches by (event_id,
                                                   team_id)
                              wins/losses/ties from match scores
  7. team_skill_summary   ── aggregate skills by team_id
                              best / worst / avg skill scores
  8. team_score_summary   ── aggregate matches by team_id
                              high_score / total_points
```

**Random distributions (uniform):** city/region from a 10-element list, match scores `randint(0, 200)`, skill scores `randint(0, 100)`. Plausible-looking, not statistically modeled.

### 8. File layout under staging dir

```
./sample_data/
  events/p_season_id=190/p_program_id=1/{ts}.parquet
  teams/p_season_id=190/p_program_id=1/{ts}.parquet
  matches/p_season_id=190/p_program_id=1/p_event_id={e}/{ts}.parquet
  skills/p_season_id=190/p_program_id=1/p_event_id={e}/{ts}.parquet
  rankings/p_season_id=190/p_program_id=1/p_event_id={e}/{ts}.parquet
  team_event_summary/p_season_id=190/p_program_id=1/{ts}.parquet
  team_skill_summary/p_season_id=190/p_program_id=1/{ts}.parquet
  team_score_summary/p_season_id=190/p_program_id=1/{ts}.parquet
```

Staging path = `<staging_dir>/<curated_key(...)>`. Same key is used for the S3 upload, so the local tree mirrors the S3 layout 1:1.

## Risks / Trade-offs

- **Projection ranges become a maintenance item.** If VEX adds a new program with id `> 100`, queries filtered to that program return empty until the DDL ranges widen. Mitigation: ranges are wide; documented.
- **Re-create tables breaks idempotency of `/query/create-tables` once.** The route still ends in a consistent state, but operator must drop tables first when applying this change. Documented in proposal.
- **No schema cross-check.** DDL and pyarrow schema can drift silently. A future change could add a `make verify-schemas` step.
- **s3.py signature change ripples** — even though the callers are on hold, their imports still get parsed. We update them mechanically; runtime is unchanged.
- **Determinism brittleness.** A change to the random ordering (e.g., adding a new field generation step) shifts every row downstream. Acceptable for sample data; tests should not assert exact row values.
