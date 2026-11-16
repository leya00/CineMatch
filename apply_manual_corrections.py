#!/usr/bin/env python3
"""Safely merge manually verified QIDs into auto-matching output (stdlib only).

This step is a DATA CURATION operation, not model evaluation.
The original matches/review_queue/evaluation files are never changed.
"""
from __future__ import annotations
import argparse
import csv
import re
import sys
from pathlib import Path

QID = re.compile(r"Q[1-9][0-9]*$")
OVERRIDE_FIELDS = {"redial_movie_id", "wikidata_qid", "review_status", "review_notes"}


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"Missing header: {path}")
        return list(reader.fieldnames), list(reader)


def load_overrides(path: Path) -> dict[str, dict[str, str]]:
    fields, rows = read_csv(path)
    if not OVERRIDE_FIELDS.issubset(set(fields)):
        raise ValueError(f"Manual override CSV needs columns: {sorted(OVERRIDE_FIELDS)}")
    verified: dict[str, dict[str, str]] = {}
    seen: set[str] = set()
    for row_index, row in enumerate(rows, 2):
        movie_id = (row.get("redial_movie_id") or "").strip()
        status = (row.get("review_status") or "").strip().lower()
        qid = (row.get("wikidata_qid") or "").strip()
        if not movie_id or not movie_id.isdecimal():
            raise ValueError(f"Invalid ReDial ID at line {row_index}: {movie_id!r}")
        if movie_id in seen:
            raise ValueError(f"Duplicate override for ReDial ID {movie_id}")
        seen.add(movie_id)
        if status not in {"verified", "pending", "rejected"}:
            raise ValueError(f"Invalid review_status at line {row_index}: {status!r}")
        if status == "verified":
            if not QID.fullmatch(qid):
                raise ValueError(f"Invalid verified QID at line {row_index}: {qid!r}")
            verified[movie_id] = row
        # pending or rejected entries must not enter accepted matches
    return verified


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def apply_corrections(matches_path: Path, overrides_path: Path, output_dir: Path) -> dict[str, int]:
    fields, matches = read_csv(matches_path)
    required = {"redial_movie_id", "wikidata_qid", "match_status", "match_reason", "wikidata_url"}
    if not required.issubset(set(fields)):
        raise ValueError(f"Matcher output needs columns: {sorted(required)}")
    if len({row["redial_movie_id"] for row in matches}) != len(matches):
        raise ValueError("Duplicate ReDial IDs in matches.csv")
    overrides = load_overrides(overrides_path)
    unknown = set(overrides) - {row["redial_movie_id"] for row in matches}
    if unknown:
        print(f"Note: {len(unknown)} verified overrides not in current matching batch; retained in source CSV for later batches.")
    out_fields = fields + ["mapping_source", "manual_review_notes"]
    final_rows = []
    manual_count = auto_count = 0
    for old in matches:
        row = dict(old)
        movie_id = row["redial_movie_id"]
        if movie_id in overrides:
            override = overrides[movie_id]
            qid = override["wikidata_qid"].strip()
            row["wikidata_qid"] = qid
            row["match_status"] = "manual_verified"
            row["match_reason"] = "Human-reviewed override (not an automated prediction)"
            row["wikidata_url"] = f"https://www.wikidata.org/wiki/{qid}"
            row["mapping_source"] = "human_review"
            row["manual_review_notes"] = (override.get("review_notes") or "").strip()
            manual_count += 1
        elif row["match_status"] == "auto_matched":
            row["mapping_source"] = "auto_match"
            row["manual_review_notes"] = ""
            auto_count += 1
        else:
            row["mapping_source"] = "unresolved"
            row["manual_review_notes"] = ""
        final_rows.append(row)
    # Save separate derivatives so original evaluation.json is still meaningful.
    write_csv(output_dir / "final_matches.csv", out_fields, final_rows)
    pending = [r for r in final_rows if r["match_status"] not in {"manual_verified", "auto_matched"}]
    write_csv(output_dir / "final_review_queue.csv", out_fields, pending)
    return {"rows_processed": len(final_rows), "manual_verified": manual_count,
            "auto_matched": auto_count, "remaining_for_review": len(pending)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matches", type=Path, default=Path("outputs/matches.csv"))
    parser.add_argument("--overrides", type=Path, default=Path("data/manual_overrides.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs"))
    args = parser.parse_args()
    try:
        result = apply_corrections(args.matches, args.overrides, args.output_dir)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print("Manual corrections applied:")
    for key, value in result.items():
        print(f"  {key}: {value}")
    print(f"Saved {args.output_dir / 'final_matches.csv'} and final_review_queue.csv")


if __name__ == "__main__":
    sys.exit(main())
