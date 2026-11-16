#!/usr/bin/env python3
"""Build a HUMAN review sheet after a CineMatch matching run.

Includes all unresolved films without a verified manual override, plus a
reproducible random quality-audit sample of automatically matched films from
outside the original top-30 pilot.

This script DOES NOT validate suggested QIDs, change the matcher, import manual
corrections or alter any original outputs. Uses only the Python stdlib.

Run from the CineMatch_Matching_v0_2_1 folder:
    python prepare_review_sheet.py --sample-size 12
"""
from __future__ import annotations
import argparse
import csv
import random
import re
from pathlib import Path

FIELDS = [
    'review_type', 'priority_rank', 'redial_movie_id', 'redial_title',
    'release_year', 'mentions', 'automatic_status', 'automatic_reason',
    'suggested_wikidata_qid', 'suggested_wikidata_title',
    'match_score', 'score_margin', 'suggested_wikidata_url',
    'candidate_1', 'candidate_2', 'candidate_3',
    'verified_wikidata_qid', 'review_status', 'review_notes',
]


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open('r', encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f'CSV has no header: {path}')
        return list(reader)


def create_review_sheet(
    matches_path: Path, candidates_path: Path, overrides_path: Path,
    output_path: Path, sample_size: int = 12, seed: int = 42,
    pilot_cutoff: int = 30,
) -> dict[str, int]:
    matches = read_rows(matches_path)
    candidates = read_rows(candidates_path)
    overrides = read_rows(overrides_path)
    required = {'redial_movie_id', 'priority_rank', 'match_status', 'redial_title'}
    if matches and not required.issubset(matches[0]):
        raise ValueError(f'matches.csv missing fields: {sorted(required - set(matches[0]))}')
    ids = [r['redial_movie_id'].strip() for r in matches]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate redial_movie_id values in matches.csv')

    verified_ids = {
        (r.get('redial_movie_id') or '').strip()
        for r in overrides
        if (r.get('review_status') or '').strip().casefold() == 'verified'
        and re.fullmatch(r'Q[1-9]\d*', (r.get('wikidata_qid') or '').strip())
    }
    options: dict[str, list[dict[str, str]]] = {}
    for row in candidates:
        mid = (row.get('redial_movie_id') or '').strip()
        options.setdefault(mid, []).append(row)
    for mid in options:
        options[mid].sort(key=lambda r: int(r.get('rank') or 999))

    unresolved = [r for r in matches if r['match_status'] != 'auto_matched'
                  and r['redial_movie_id'] not in verified_ids]
    audit_eligible = [r for r in matches if r['match_status'] == 'auto_matched'
                      and int(r['priority_rank']) > pilot_cutoff]
    rng = random.Random(seed)
    selected = rng.sample(audit_eligible, k=min(sample_size, len(audit_eligible)))
    to_review = [('needs_review', r) for r in unresolved] + [('auto_match_audit', r) for r in selected]
    to_review.sort(key=lambda pair: int(pair[1]['priority_rank']))
    rows = []
    for kind, row in to_review:
        movie_id = row['redial_movie_id']
        ranked = options.get(movie_id, [])
        candidate_summaries = [
            f"{c.get('candidate_qid','')} | {c.get('candidate_title','')} "
            f"({c.get('candidate_years','')}) | score {c.get('score','')}"
            for c in ranked[:3]
        ]
        candidate_summaries += [''] * (3 - len(candidate_summaries))
        rows.append({
            'review_type': kind,
            'priority_rank': row.get('priority_rank',''),
            'redial_movie_id': movie_id,
            'redial_title': row.get('redial_title',''),
            'release_year': row.get('release_year',''),
            'mentions': row.get('mentions',''),
            'automatic_status': row['match_status'],
            'automatic_reason': row.get('match_reason',''),
            'suggested_wikidata_qid': row.get('suggested_wikidata_qid',''),
            'suggested_wikidata_title': row.get('suggested_wikidata_title',''),
            'match_score': row.get('match_score',''),
            'score_margin': row.get('score_margin',''),
            'suggested_wikidata_url': row.get('wikidata_url',''),
            'candidate_1': candidate_summaries[0],
            'candidate_2': candidate_summaries[1],
            'candidate_3': candidate_summaries[2],
            'verified_wikidata_qid': '',  # Human input, NEVER auto-populated
            'review_status': 'pending',
            'review_notes': '',
        })
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return {
        'matching_rows_processed': len(matches),
        'verified_overrides_already_present': len([i for i in ids if i in verified_ids]),
        'unresolved_for_human_review': len(unresolved),
        'automatic_matches_selected_for_audit': len(selected),
        'review_sheet_rows': len(rows),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--matches', type=Path, default=Path('outputs/matches.csv'))
    parser.add_argument('--candidates', type=Path, default=Path('outputs/candidates.csv'))
    parser.add_argument('--overrides', type=Path, default=Path('data/manual_overrides.csv'))
    parser.add_argument('--output', type=Path, default=Path('outputs/review_plan_100.csv'))
    parser.add_argument('--sample-size', type=int, default=12)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--pilot-cutoff', type=int, default=30)
    args = parser.parse_args()
    if args.sample_size < 0 or args.pilot_cutoff < 0:
        parser.error('sample-size and pilot-cutoff must be non-negative')
    try:
        counts = create_review_sheet(args.matches, args.candidates, args.overrides,
                                     args.output, args.sample_size, args.seed, args.pilot_cutoff)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    for key, value in counts.items():
        print(f'{key}: {value}')
    print(f'Saved review worksheet: {args.output}')
    print('Review QIDs yourself, then copy VERIFIED rows into data/manual_overrides.csv.')
    print('Do not mark any match verified purely because it was a top suggestion.')


if __name__ == '__main__':
    main()
