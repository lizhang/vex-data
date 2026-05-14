"""PyArrow schemas matching curated/*.sql — single source of truth for the seed script."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa


_team_ref = pa.struct([
    ("team_id", pa.int64()),
    ("number", pa.string()),
])

_division_ref = pa.struct([
    ("id", pa.int64()),
    ("name", pa.string()),
])


SCHEMAS: dict[str, pa.Schema] = {
    "events": pa.schema([
        ("event_id", pa.int64()),
        ("sku", pa.string()),
        ("name", pa.string()),
        ("program_id", pa.int32()),
        ("program_name", pa.string()),
        ("season_id", pa.int32()),
        ("season_name", pa.string()),
        ("start_date", pa.timestamp("us")),
        ("end_date", pa.timestamp("us")),
        ("city", pa.string()),
        ("region", pa.string()),
        ("postcode", pa.string()),
        ("country", pa.string()),
        ("venue", pa.string()),
        ("event_type", pa.string()),
        ("level", pa.string()),
        ("divisions", pa.list_(_division_ref)),
    ]),

    "teams": pa.schema([
        ("team_id", pa.int64()),
        ("number", pa.string()),
        ("team_name", pa.string()),
        ("organization", pa.string()),
        ("program_id", pa.int32()),
        ("program_name", pa.string()),
        ("city", pa.string()),
        ("region", pa.string()),
        ("postcode", pa.string()),
        ("country", pa.string()),
        ("grade", pa.string()),
        ("registered", pa.bool_()),
    ]),

    "matches": pa.schema([
        ("match_id", pa.int64()),
        ("event_id", pa.int64()),
        ("event_sku", pa.string()),
        ("event_name", pa.string()),
        ("division_id", pa.int64()),
        ("division_name", pa.string()),
        ("round", pa.int32()),
        ("round_name", pa.string()),
        ("instance", pa.int32()),
        ("matchnum", pa.int32()),
        ("scheduled_time", pa.timestamp("us")),
        ("started_time", pa.timestamp("us")),
        ("field", pa.string()),
        ("scored", pa.bool_()),
        ("red_score", pa.int32()),
        ("blue_score", pa.int32()),
        ("red_teams", pa.list_(_team_ref)),
        ("blue_teams", pa.list_(_team_ref)),
    ]),

    "skills": pa.schema([
        ("event_id", pa.int64()),
        ("event_sku", pa.string()),
        ("team_id", pa.int64()),
        ("team_number", pa.string()),
        ("team_name", pa.string()),
        ("type", pa.string()),
        ("score", pa.int32()),
        ("attempts", pa.int32()),
        ("rank", pa.int32()),
        ("skills_stop_time", pa.int32()),
        ("created_at", pa.timestamp("us")),
    ]),

    "rankings": pa.schema([
        ("event_id", pa.int64()),
        ("event_sku", pa.string()),
        ("division_id", pa.int64()),
        ("division_name", pa.string()),
        ("team_id", pa.int64()),
        ("team_number", pa.string()),
        ("team_name", pa.string()),
        ("rank", pa.int32()),
        ("wins", pa.int32()),
        ("losses", pa.int32()),
        ("ties", pa.int32()),
        ("wp", pa.int32()),
        ("ap", pa.int32()),
        ("sp", pa.int32()),
        ("high_score", pa.int32()),
        ("average_points", pa.float64()),
        ("total_points", pa.int32()),
    ]),

    "team_event_summary": pa.schema([
        ("event_id", pa.int64()),
        ("event_sku", pa.string()),
        ("event_name", pa.string()),
        ("event_start_date", pa.timestamp("us")),
        ("team_id", pa.int64()),
        ("team_number", pa.string()),
        ("team_name", pa.string()),
        ("organization", pa.string()),
        ("ranking", pa.int32()),
        ("wins", pa.int32()),
        ("losses", pa.int32()),
        ("ties", pa.int32()),
        ("best_score", pa.int32()),
        ("best_skills_score", pa.int32()),
        ("skills_rank", pa.int32()),
    ]),

    "team_skill_summary": pa.schema([
        ("team_id", pa.int64()),
        ("team_number", pa.string()),
        ("team_name", pa.string()),
        ("organization", pa.string()),
        ("best_skill_score", pa.int32()),
        ("worst_skill_score", pa.int32()),
        ("avg_skill_score", pa.int32()),
        ("best_skill_event_id", pa.int64()),
        ("worst_skill_event_id", pa.int64()),
    ]),

    "team_score_summary": pa.schema([
        ("team_id", pa.int64()),
        ("team_number", pa.string()),
        ("team_name", pa.string()),
        ("organization", pa.string()),
        ("high_score", pa.int32()),
        ("average_points", pa.float64()),
        ("total_points", pa.int32()),
        ("best_score_event_id", pa.int64()),
    ]),
}


# ── Smoke check ────────────────────────────────────────────────────────────

_CURATED_DIR = Path(__file__).resolve().parents[1] / "curated"
_ddl_tables = {p.stem for p in _CURATED_DIR.glob("*.sql")}

_missing = _ddl_tables - SCHEMAS.keys()
_extra = SCHEMAS.keys() - _ddl_tables
assert not _missing, f"SCHEMAS missing entries for DDL files: {sorted(_missing)}"
assert not _extra, f"SCHEMAS has entries with no matching DDL file: {sorted(_extra)}"
