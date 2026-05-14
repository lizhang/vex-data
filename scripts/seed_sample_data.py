"""Generate sample VEX data locally, then upload to S3.

Workflow:
  1. Generate base rows (events, teams, matches, skills, rankings) deterministically.
  2. Aggregate derived rows (team_event_summary, team_skill_summary, team_score_summary).
  3. Write all 8 tables as Parquet under --staging-dir, mirroring the S3 Hive layout.
  4. Upload each Parquet to S3 unless --skip-upload.

Usage:
  python scripts/seed_sample_data.py
  python scripts/seed_sample_data.py --season 190 --program 1 --events 10 --teams 100
  python scripts/seed_sample_data.py --skip-upload --clean
"""

from __future__ import annotations

import argparse
import random
import shutil
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

# Make repo root importable when run as `python scripts/seed_sample_data.py`
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.services import s3 as s3_helper  # noqa: E402
from scripts.sample_data_schemas import SCHEMAS  # noqa: E402


PROGRAM_NAMES = {1: "VRC", 4: "VEXU", 41: "VIQC"}
CITIES = [
    ("Los Angeles", "California", "90001", "United States"),
    ("Houston", "Texas", "77002", "United States"),
    ("Boston", "Massachusetts", "02108", "United States"),
    ("Chicago", "Illinois", "60601", "United States"),
    ("Seattle", "Washington", "98101", "United States"),
    ("Toronto", "Ontario", "M5H 2N2", "Canada"),
    ("London", "England", "SW1A 1AA", "United Kingdom"),
    ("Beijing", "Beijing", "100000", "China"),
    ("Sydney", "New South Wales", "2000", "Australia"),
    ("Mexico City", "CDMX", "01000", "Mexico"),
]


# ── Generation ─────────────────────────────────────────────────────────────

def generate_events(n: int, season_id: int, program_id: int, rng: random.Random) -> list[dict]:
    events: list[dict] = []
    base_date = datetime(2026, 1, 4)
    for i in range(n):
        event_id = 10_000_000 + season_id * 1000 + i
        city, region, postcode, country = rng.choice(CITIES)
        start = base_date + timedelta(days=i * 7)
        end = start + timedelta(days=1)
        divisions = [
            {"id": event_id * 10 + d, "name": f"Division {chr(65 + d)}"}
            for d in range(rng.randint(1, 3))
        ]
        events.append({
            "event_id": event_id,
            "sku": f"RE-{season_id}-EV-{i:05d}",
            "name": f"Sample Regional {i+1}",
            "program_id": program_id,
            "program_name": PROGRAM_NAMES.get(program_id, f"Program {program_id}"),
            "season_id": season_id,
            "season_name": f"Season {season_id}",
            "start_date": start,
            "end_date": end,
            "city": city,
            "region": region,
            "postcode": postcode,
            "country": country,
            "venue": f"{city} Convention Center",
            "event_type": "tournament",
            "level": rng.choice(["Regional", "Signature", "World"]),
            "divisions": divisions,
        })
    return events


def generate_teams(n: int, season_id: int, program_id: int, rng: random.Random) -> list[dict]:
    teams: list[dict] = []
    for i in range(n):
        team_id = 20_000_000 + season_id * 10000 + i
        number = f"{1000 + i}{rng.choice('ABCDEFGHJKMNPQ')}"
        city, region, postcode, country = rng.choice(CITIES)
        teams.append({
            "team_id": team_id,
            "number": number,
            "team_name": f"Team {number}",
            "organization": f"Robotics Club {i+1}",
            "program_id": program_id,
            "program_name": PROGRAM_NAMES.get(program_id, f"Program {program_id}"),
            "city": city,
            "region": region,
            "postcode": postcode,
            "country": country,
            "grade": rng.choice(["High School", "Middle School", "College"]),
            "registered": True,
        })
    return teams


def generate_matches(events: list[dict], teams: list[dict], k_per_event: int, rng: random.Random) -> list[dict]:
    matches: list[dict] = []
    for event in events:
        division = event["divisions"][0]
        event_teams = rng.sample(teams, min(len(teams), max(4, k_per_event * 2)))
        for m in range(k_per_event):
            red_pool = rng.sample(event_teams, 2)
            remaining = [t for t in event_teams if t not in red_pool]
            blue_pool = rng.sample(remaining, 2)
            match_id = event["event_id"] * 1000 + m
            scheduled = event["start_date"] + timedelta(minutes=m * 10)
            started = scheduled + timedelta(seconds=rng.randint(0, 60))
            matches.append({
                "match_id": match_id,
                "event_id": event["event_id"],
                "event_sku": event["sku"],
                "event_name": event["name"],
                "division_id": division["id"],
                "division_name": division["name"],
                "round": rng.randint(1, 6),
                "round_name": rng.choice(["Qualification", "Quarterfinal", "Semifinal", "Final"]),
                "instance": 1,
                "matchnum": m + 1,
                "scheduled_time": scheduled,
                "started_time": started,
                "field": rng.choice(["Field 1", "Field 2", "Field 3"]),
                "scored": True,
                "red_score": rng.randint(0, 200),
                "blue_score": rng.randint(0, 200),
                "red_teams": [{"team_id": t["team_id"], "number": t["number"]} for t in red_pool],
                "blue_teams": [{"team_id": t["team_id"], "number": t["number"]} for t in blue_pool],
            })
    return matches


def generate_skills(events: list[dict], teams: list[dict], rng: random.Random) -> list[dict]:
    skills: list[dict] = []
    for event in events:
        participating = rng.sample(teams, min(len(teams), rng.randint(10, 30)))
        for team in participating:
            for skill_type in ["driver", "programming"]:
                if rng.random() < 0.7:
                    skills.append({
                        "event_id": event["event_id"],
                        "event_sku": event["sku"],
                        "team_id": team["team_id"],
                        "team_number": team["number"],
                        "team_name": team["team_name"],
                        "type": skill_type,
                        "score": rng.randint(0, 100),
                        "attempts": rng.randint(1, 3),
                        "rank": 0,  # filled in below
                        "skills_stop_time": rng.randint(0, 60),
                        "created_at": event["start_date"] + timedelta(hours=rng.randint(1, 8)),
                    })
    # Assign ranks per (event_id, type)
    by_event_type: dict[tuple[int, str], list[dict]] = defaultdict(list)
    for row in skills:
        by_event_type[(row["event_id"], row["type"])].append(row)
    for group in by_event_type.values():
        group.sort(key=lambda r: -r["score"])
        for i, row in enumerate(group):
            row["rank"] = i + 1
    return skills


def generate_rankings(events: list[dict], matches: list[dict], teams_by_id: dict[int, dict], rng: random.Random) -> list[dict]:
    teams_per_event: dict[int, set[int]] = defaultdict(set)
    for m in matches:
        for t in m["red_teams"] + m["blue_teams"]:
            teams_per_event[m["event_id"]].add(t["team_id"])

    rankings: list[dict] = []
    for event in events:
        division = event["divisions"][0]
        team_ids = list(teams_per_event[event["event_id"]])
        rng.shuffle(team_ids)
        for rank_idx, team_id in enumerate(team_ids, start=1):
            team = teams_by_id[team_id]
            wins = rng.randint(0, 8)
            losses = rng.randint(0, 8)
            ties = rng.randint(0, 2)
            high_score = rng.randint(50, 250)
            total_points = (wins * 3 + ties) * rng.randint(50, 150)
            played = max(1, wins + losses + ties)
            rankings.append({
                "event_id": event["event_id"],
                "event_sku": event["sku"],
                "division_id": division["id"],
                "division_name": division["name"],
                "team_id": team_id,
                "team_number": team["number"],
                "team_name": team["team_name"],
                "rank": rank_idx,
                "wins": wins,
                "losses": losses,
                "ties": ties,
                "wp": wins * 2 + ties,
                "ap": rng.randint(0, 30),
                "sp": rng.randint(0, 80),
                "high_score": high_score,
                "average_points": round(total_points / played, 2),
                "total_points": total_points,
            })
    return rankings


# ── Derivation ─────────────────────────────────────────────────────────────

def derive_team_event_summary(events: list[dict], matches: list[dict], teams_by_id: dict[int, dict], rankings: list[dict], skills: list[dict]) -> list[dict]:
    events_by_id = {e["event_id"]: e for e in events}

    rank_by_event_team: dict[tuple[int, int], int] = {
        (r["event_id"], r["team_id"]): r["rank"] for r in rankings
    }
    best_skill_by_event_team: dict[tuple[int, int], int] = defaultdict(int)
    skill_rank_by_event_team: dict[tuple[int, int], int] = {}
    for s in skills:
        key = (s["event_id"], s["team_id"])
        best_skill_by_event_team[key] = max(best_skill_by_event_team[key], s["score"])
        if key not in skill_rank_by_event_team or s["rank"] < skill_rank_by_event_team[key]:
            skill_rank_by_event_team[key] = s["rank"]

    record: dict[tuple[int, int], dict[str, int]] = defaultdict(
        lambda: {"wins": 0, "losses": 0, "ties": 0, "best_score": 0}
    )

    for m in matches:
        red_ids = [t["team_id"] for t in m["red_teams"]]
        blue_ids = [t["team_id"] for t in m["blue_teams"]]
        rs, bs = m["red_score"], m["blue_score"]
        if rs > bs:
            red_outcome, blue_outcome = "wins", "losses"
        elif bs > rs:
            red_outcome, blue_outcome = "losses", "wins"
        else:
            red_outcome = blue_outcome = "ties"

        for tid in red_ids:
            r = record[(m["event_id"], tid)]
            r[red_outcome] += 1
            r["best_score"] = max(r["best_score"], rs)
        for tid in blue_ids:
            r = record[(m["event_id"], tid)]
            r[blue_outcome] += 1
            r["best_score"] = max(r["best_score"], bs)

    result: list[dict] = []
    for (event_id, team_id), r in record.items():
        team = teams_by_id[team_id]
        event = events_by_id[event_id]
        result.append({
            "event_id": event_id,
            "event_sku": event["sku"],
            "event_name": event["name"],
            "event_start_date": event["start_date"],
            "team_id": team_id,
            "team_number": team["number"],
            "team_name": team["team_name"],
            "organization": team["organization"],
            "ranking": rank_by_event_team.get((event_id, team_id), 0),
            "wins": r["wins"],
            "losses": r["losses"],
            "ties": r["ties"],
            "best_score": r["best_score"],
            "best_skills_score": best_skill_by_event_team.get((event_id, team_id), 0),
            "skills_rank": skill_rank_by_event_team.get((event_id, team_id), 0),
        })
    return result


def derive_team_skill_summary(skills: list[dict], teams_by_id: dict[int, dict]) -> list[dict]:
    by_team: dict[int, list[dict]] = defaultdict(list)
    for s in skills:
        by_team[s["team_id"]].append(s)

    result: list[dict] = []
    for team_id, rows in by_team.items():
        team = teams_by_id[team_id]
        scores = [r["score"] for r in rows]
        best = max(scores)
        worst = min(scores)
        best_event = next(r["event_id"] for r in rows if r["score"] == best)
        worst_event = next(r["event_id"] for r in rows if r["score"] == worst)
        result.append({
            "team_id": team_id,
            "team_number": team["number"],
            "team_name": team["team_name"],
            "organization": team["organization"],
            "best_skill_score": best,
            "worst_skill_score": worst,
            "avg_skill_score": sum(scores) // len(scores),
            "best_skill_event_id": best_event,
            "worst_skill_event_id": worst_event,
        })
    return result


def derive_team_score_summary(matches: list[dict], teams_by_id: dict[int, dict]) -> list[dict]:
    by_team_scores: dict[int, list[tuple[int, int]]] = defaultdict(list)  # team_id -> [(score, event_id)]

    for m in matches:
        for t in m["red_teams"]:
            by_team_scores[t["team_id"]].append((m["red_score"], m["event_id"]))
        for t in m["blue_teams"]:
            by_team_scores[t["team_id"]].append((m["blue_score"], m["event_id"]))

    result: list[dict] = []
    for team_id, score_events in by_team_scores.items():
        team = teams_by_id[team_id]
        scores = [s for s, _ in score_events]
        high = max(scores)
        best_event = next(e for s, e in score_events if s == high)
        result.append({
            "team_id": team_id,
            "team_number": team["number"],
            "team_name": team["team_name"],
            "organization": team["organization"],
            "high_score": high,
            "average_points": round(sum(scores) / len(scores), 2),
            "total_points": sum(scores),
            "best_score_event_id": best_event,
        })
    return result


# ── Write + upload ─────────────────────────────────────────────────────────

def write_parquet(rows: list[dict], schema: pa.Schema, local_path: Path) -> None:
    local_path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows, schema=schema)
    pq.write_table(table, local_path, compression="snappy")


def partition_rows_2col(rows: list[dict], season_id: int, program_id: int) -> dict[tuple[int, int], list[dict]]:
    return {(season_id, program_id): rows}


def partition_rows_3col(rows: list[dict], season_id: int, program_id: int) -> dict[tuple[int, int, int], list[dict]]:
    groups: dict[tuple[int, int, int], list[dict]] = defaultdict(list)
    for row in rows:
        groups[(season_id, program_id, row["event_id"])].append(row)
    return groups


def write_and_collect(
    table: str,
    rows: list[dict],
    season_id: int,
    program_id: int,
    event_scoped: bool,
    staging_dir: Path,
    timestamp: str,
) -> list[tuple[Path, str]]:
    """Write Parquet per partition. Returns [(local_path, s3_key)]."""
    schema = SCHEMAS[table]
    pairs: list[tuple[Path, str]] = []

    if event_scoped:
        partitions = partition_rows_3col(rows, season_id, program_id)
        for (s, p, e), part_rows in partitions.items():
            key = s3_helper.curated_key(table, season_id=s, program_id=p, timestamp=timestamp, event_id=e)
            local_path = staging_dir / key
            write_parquet(part_rows, schema, local_path)
            pairs.append((local_path, key))
    else:
        partitions = partition_rows_2col(rows, season_id, program_id)
        for (s, p), part_rows in partitions.items():
            key = s3_helper.curated_key(table, season_id=s, program_id=p, timestamp=timestamp)
            local_path = staging_dir / key
            write_parquet(part_rows, schema, local_path)
            pairs.append((local_path, key))

    print(f"  {table}: {len(rows)} rows -> {len(pairs)} file(s)")
    return pairs


def clean_local(staging_dir: Path) -> None:
    if staging_dir.exists():
        shutil.rmtree(staging_dir)


def clean_s3(table_names: list[str], season_id: int, program_id: int) -> None:
    for table in table_names:
        keys = s3_helper.list_curated_keys(table, season_id=season_id, program_id=program_id)
        if keys:
            print(f"  deleting {len(keys)} S3 objects under curated/{table}/p_season_id={season_id}/p_program_id={program_id}/")
            s3_helper.delete_keys(keys)


def upload_pairs(pairs: list[tuple[Path, str]]) -> None:
    for local_path, key in pairs:
        with open(local_path, "rb") as f:
            s3_helper._client().put_object(Bucket=settings.s3_bucket, Key=key, Body=f.read())


# ── Main ───────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=190, help="p_season_id partition value")
    parser.add_argument("--program", type=int, default=1, help="p_program_id partition value")
    parser.add_argument("--events", type=int, default=10, help="number of events to generate")
    parser.add_argument("--teams", type=int, default=100, help="number of teams in the pool")
    parser.add_argument("--matches-per-event", type=int, default=10, help="matches generated per event")
    parser.add_argument("--seed", type=int, default=42, help="random seed for determinism")
    parser.add_argument("--staging-dir", type=Path, default=Path("./sample_data"), help="local Parquet output directory")
    parser.add_argument("--skip-upload", action="store_true", help="write locally only; do not upload to S3")
    parser.add_argument("--clean", action="store_true", help="delete prior local + S3 partition contents before writing")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    timestamp = "20260512T000000Z"

    table_names = list(SCHEMAS.keys())

    if args.clean:
        print("Cleaning prior staging dir + S3 partitions...")
        clean_local(args.staging_dir)
        if not args.skip_upload:
            clean_s3(table_names, args.season, args.program)

    print(f"Generating sample data (season={args.season}, program={args.program}, events={args.events}, teams={args.teams})...")
    events = generate_events(args.events, args.season, args.program, rng)
    teams = generate_teams(args.teams, args.season, args.program, rng)
    teams_by_id = {t["team_id"]: t for t in teams}
    matches = generate_matches(events, teams, args.matches_per_event, rng)
    skills = generate_skills(events, teams, rng)
    rankings = generate_rankings(events, matches, teams_by_id, rng)

    print("Deriving aggregations...")
    team_event_summary = derive_team_event_summary(events, matches, teams_by_id, rankings, skills)
    team_skill_summary = derive_team_skill_summary(skills, teams_by_id)
    team_score_summary = derive_team_score_summary(matches, teams_by_id)

    print(f"Writing Parquet under {args.staging_dir}/ ...")
    all_pairs: list[tuple[Path, str]] = []
    all_pairs += write_and_collect("events", events, args.season, args.program, False, args.staging_dir, timestamp)
    all_pairs += write_and_collect("teams", teams, args.season, args.program, False, args.staging_dir, timestamp)
    all_pairs += write_and_collect("matches", matches, args.season, args.program, True, args.staging_dir, timestamp)
    all_pairs += write_and_collect("skills", skills, args.season, args.program, True, args.staging_dir, timestamp)
    all_pairs += write_and_collect("rankings", rankings, args.season, args.program, True, args.staging_dir, timestamp)
    all_pairs += write_and_collect("team_event_summary", team_event_summary, args.season, args.program, False, args.staging_dir, timestamp)
    all_pairs += write_and_collect("team_skill_summary", team_skill_summary, args.season, args.program, False, args.staging_dir, timestamp)
    all_pairs += write_and_collect("team_score_summary", team_score_summary, args.season, args.program, False, args.staging_dir, timestamp)

    if args.skip_upload:
        print(f"\nDone. {len(all_pairs)} Parquet file(s) under {args.staging_dir}/ — S3 upload skipped.")
        return

    print(f"\nUploading {len(all_pairs)} Parquet file(s) to s3://{settings.s3_bucket}/ ...")
    upload_pairs(all_pairs)
    print("Done.")


if __name__ == "__main__":
    main()
