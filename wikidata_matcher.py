#!/usr/bin/env python3
"""CineMatch: conservative ReDial -> Wikidata candidate matcher (v0.2; stdlib only).

This script does not use reference_labels.csv to influence its predictions.
It relies on Wikidata's public Action API; you must have internet access.
"""
from __future__ import annotations

import argparse
import csv
from difflib import SequenceMatcher
import json
import re
import sqlite3
import sys
import time
import unicodedata
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API = "https://www.wikidata.org/w/api.php"
FILM_INSTANCE_IDS = {"Q11424", "Q24869", "Q202866", "Q506240", "Q932586"}
NONFILM_DESCRIPTION = re.compile(
    r"\b(film series|film franchise|film studio|film director|film character|"
    r"soundtrack|album|song|novel|book|comic|video game|television series|TV series|"
    r"fictional character|disambiguation|film festival)\b", re.I
)
FILM_DESCRIPTION = re.compile(r"\b(film|movie|motion picture)\b", re.I)
YEAR_SUFFIX = re.compile(r"\s*\((18\d{2}|19\d{2}|20\d{2})\)\s*$")
YEAR_FROM_DATE = re.compile(r"^[+-]?(\d{4})-")
FIELDS = [
    "priority_rank", "redial_movie_id", "redial_title", "cleaned_title", "release_year", "mentions",
    "wikidata_qid", "suggested_wikidata_qid", "suggested_wikidata_title", "wikidata_years", "match_score", "score_margin",
    "match_status", "match_reason", "wikidata_url",
]
CANDIDATE_FIELDS = ["redial_movie_id", "redial_title", "rank", "candidate_qid", "candidate_title",
                    "candidate_years", "description", "score", "title_similarity", "type_signal", "matched_name"]


def normalise_title(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(c for c in value if not unicodedata.combining(c)).casefold()
    value = value.replace("&", " and ").replace("–", "-").replace("—", "-")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def split_title_year(raw: str) -> tuple[str, int | None]:
    raw = " ".join((raw or "").split())
    match = YEAR_SUFFIX.search(raw)
    if not match:
        return raw, None
    return raw[:match.start()].strip(), int(match.group(1))


def load_movies(path: Path) -> list[dict]:
    movies = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        required = {"movieId", "movieName", "nbMentions"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"Expected CSV headers {sorted(required)}; got {reader.fieldnames}")
        for row in reader:
            title, year = split_title_year(row["movieName"])
            movies.append({
                "redial_movie_id": row["movieId"].strip(),
                "redial_title": " ".join(row["movieName"].split()),
                "cleaned_title": title,
                "release_year": year,
                "mentions": int(row["nbMentions"]),
            })
    if len({r["redial_movie_id"] for r in movies}) != len(movies):
        raise ValueError("Repeated ReDial movieId in input CSV")
    movies.sort(key=lambda x: (-x["mentions"], int(x["redial_movie_id"])))
    for rank, movie in enumerate(movies, start=1):
        movie["priority_rank"] = rank
    return movies


class WikidataClient:
    def __init__(self, cache_path: Path, user_agent: str, delay: float = 1.2, offline: bool = False):
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(cache_path)
        self.db.execute("CREATE TABLE IF NOT EXISTS responses (url TEXT PRIMARY KEY, body TEXT NOT NULL)")
        self.agent, self.delay, self.offline = user_agent, delay, offline
        self.last_request_at = 0.0
        self.requests_made = 0
        self.cache_hits = 0

    def request(self, **params) -> dict:
        params = {**params, "format": "json"}
        url = API + "?" + urlencode(sorted(params.items()))
        found = self.db.execute("SELECT body FROM responses WHERE url=?", (url,)).fetchone()
        if found:
            self.cache_hits += 1
            return json.loads(found[0])
        if self.offline:
            raise RuntimeError("Offline cache miss; run again without --offline on an internet-connected computer")
        error = None
        for attempt in range(4):
            pause = self.delay - (time.monotonic() - self.last_request_at)
            if pause > 0:
                time.sleep(pause)
            req = Request(url, headers={"User-Agent": self.agent, "Accept": "application/json"})
            try:
                self.last_request_at = time.monotonic()
                with urlopen(req, timeout=25) as response:
                    result = json.load(response)
                if "error" in result:
                    raise RuntimeError(f"Wikidata API error: {result['error']}")
                self.db.execute("INSERT OR REPLACE INTO responses (url,body) VALUES (?,?)", (url, json.dumps(result)))
                self.db.commit()
                self.requests_made += 1
                return result
            except HTTPError as exc:
                error = exc
                if exc.code not in (429, 500, 502, 503, 504):
                    break
                retry_after = exc.headers.get("Retry-After", "")
                try:
                    seconds = min(180, max(5, int(retry_after)))
                except ValueError:
                    seconds = 5 * (2 ** attempt)
                time.sleep(seconds)
            except (URLError, TimeoutError, OSError) as exc:
                error = exc
                time.sleep(min(15, 2 ** attempt))
        raise RuntimeError(f"Wikidata request failed after retries: {error}")

    def search(self, query: str, limit: int = 12) -> list[str]:
        result = self.request(action="wbsearchentities", search=query, language="en", uselang="en",
                              type="item", limit=limit)
        return [hit["id"] for hit in result.get("search", []) if re.fullmatch(r"Q\d+", hit.get("id", ""))]

    def details(self, qids: list[str]) -> dict[str, dict]:
        if not qids:
            return {}
        result = self.request(action="wbgetentities", ids="|".join(qids),
                              props="labels|descriptions|aliases|claims", languages="en", languagefallback="1")
        return result.get("entities", {})

    def enwiki_lookup(self, article_title: str) -> dict[str, dict]:
        """Resolve an exact English Wikipedia article title to a Wikidata item.

        Wikidata provides its enwiki sitelinks directly through wbgetentities.
        This is an additional *candidate source*, not an automatic validation.
        """
        result = self.request(action="wbgetentities", sites="enwiki", titles=article_title,
                              props="labels|descriptions|aliases|claims", languages="en", languagefallback="1")
        return {
            qid: entity for qid, entity in result.get("entities", {}).items()
            if re.fullmatch(r"Q\d+", qid) and not entity.get("missing")
        }

    def close(self):
        self.db.close()


def entity_claim_ids(entity: dict, prop: str) -> set[str]:
    ids = set()
    for claim in entity.get("claims", {}).get(prop, []):
        datavalue = claim.get("mainsnak", {}).get("datavalue", {})
        val = datavalue.get("value", {})
        if isinstance(val, dict) and val.get("id"):
            ids.add(val["id"])
    return ids


def entity_years(entity: dict) -> list[int]:
    years = set()
    for claim in entity.get("claims", {}).get("P577", []):
        val = claim.get("mainsnak", {}).get("datavalue", {}).get("value", {})
        match = YEAR_FROM_DATE.match(val.get("time", "") if isinstance(val, dict) else "")
        if match:
            years.add(int(match.group(1)))
    return sorted(years)


def english_value(obj: dict, key: str) -> str:
    return obj.get(key, {}).get("en", {}).get("value", "")


def score_candidate(movie: dict, qid: str, entity: dict) -> dict:
    title = english_value(entity, "labels")
    desc = english_value(entity, "descriptions")
    aliases = [alias.get("value", "") for alias in entity.get("aliases", {}).get("en", [])]
    names = [title] + aliases
    source = normalise_title(movie["cleaned_title"])
    name, sim = "", 0.0
    for alternative in names:
        candidate = normalise_title(alternative)
        if not candidate:
            continue
        ratio = SequenceMatcher(None, source, candidate).ratio()
        if candidate == source:
            ratio = 1.0
        if ratio > sim:
            name, sim = alternative, ratio
    years = entity_years(entity)
    yr = movie["release_year"]
    description = desc.lower()
    p31 = entity_claim_ids(entity, "P31")
    if p31 & FILM_INSTANCE_IDS:
        type_signal = "film_instance"
    elif NONFILM_DESCRIPTION.search(description):
        type_signal = "not_film"
    elif FILM_DESCRIPTION.search(description):
        type_signal = "film_description"
    else:
        type_signal = "unconfirmed"

    points = round(sim * 60)
    if yr is not None and yr in years:
        points += 30
    elif yr is not None and years and min(abs(year - yr) for year in years) <= 1:
        points += 8
    elif yr is not None and years:
        points -= 24
    if type_signal == "film_instance":
        points += 10
    elif type_signal == "film_description":
        points += 7
    elif type_signal == "not_film":
        points -= 50
    points = max(0, min(100, points))
    return {"qid": qid, "title": title, "description": desc, "years": years,
            "matched_name": name, "title_similarity": round(sim, 4),
            "type_signal": type_signal, "score": points}


def decide_match(movie: dict, ranked: list[dict]) -> tuple[str, str, float]:
    if not ranked:
        return "not_found", "No candidates returned by Wikidata search", 0.0
    top = ranked[0]
    margin = top["score"] - ranked[1]["score"] if len(ranked) > 1 else top["score"]
    is_film = top["type_signal"] in ("film_instance", "film_description")
    year_confirmed = movie["release_year"] is not None and movie["release_year"] in top["years"]
    # Extremely short titles (e.g. 'It') are always manually reviewed.
    sufficiently_distinct_title = len(normalise_title(movie["cleaned_title"])) >= 4
    if (is_film and year_confirmed and top["title_similarity"] >= 0.93
            and top["score"] >= 94 and margin >= 12 and sufficiently_distinct_title):
        return "auto_matched", "Exact/near-exact title or alias, year, film type, distinct candidate", margin
    if top["score"] >= 55 and top["type_signal"] != "not_film":
        return "needs_review", "Uncertain title, year, type or competing candidates", margin
    return "not_found", "No sufficiently convincing film candidate", margin


def enwiki_title_variants(title: str, year: int | None) -> list[str]:
    """Conservative article-title fallbacks when ordinary search is inconclusive.

    Wikipedia article naming is NOT guaranteed, so unsuccessful lookups must
    never be interpreted as proof that the movie is missing from Wikidata.
    """
    if year is None:
        return []
    return [f"{title} ({year} film)", f"{title} (film)"]


def get_ranked(movie: dict, client: WikidataClient) -> list[dict]:
    title, year = movie["cleaned_title"], movie["release_year"]
    if not title.strip():
        return []
    seen: dict[str, dict] = {}

    def add_entities(entities: dict[str, dict]):
        for qid, entity in entities.items():
            if re.fullmatch(r"Q\d+", qid) and entity and not entity.get("missing"):
                seen[qid] = score_candidate(movie, qid, entity)

    def ranked_candidates() -> list[dict]:
        return sorted(seen.values(), key=lambda c: (c["score"], c["title_similarity"]), reverse=True)

    # Start with regular Wikidata search, preserving existing v0.1 behaviour.
    queries = [title]
    if year:
        queries.append(f"{title} {year} film")
    if len(normalise_title(title)) <= 3 and year:
        queries.reverse()

    for i, query in enumerate(queries):
        qids = client.search(query)
        new_ids = [qid for qid in qids if qid not in seen][:12]
        add_entities(client.details(new_ids))
        ranked = ranked_candidates()
        if i == 0 and decide_match(movie, ranked)[0] == "auto_matched":
            return ranked

    ranked = ranked_candidates()
    if decide_match(movie, ranked)[0] == "auto_matched":
        return ranked

    # Resolve potential English-Wikipedia article titles through Wikidata
    # sitelinks. This addresses generic titles such as "It" and "Seven".
    # We still score the returned entities and require film/year validation.
    # The fallback is never treated as a verified ground-truth mapping.
    for article_title in enwiki_title_variants(title, year):
        add_entities(client.enwiki_lookup(article_title))
        ranked = ranked_candidates()
        if decide_match(movie, ranked)[0] == "auto_matched":
            break
    return ranked


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def evaluate(predictions: list[dict], gold_path: Path) -> dict:
    with gold_path.open("r", encoding="utf-8-sig", newline="") as f:
        gold = {row["redial_movie_id"].strip(): row["gold_qid"].strip() for row in csv.DictReader(f)}
    compared = [p for p in predictions if p["redial_movie_id"] in gold and p["match_status"] != "api_error"]
    correct = [p for p in compared if p["suggested_wikidata_qid"] == gold[p["redial_movie_id"]]]
    auto = [p for p in compared if p["match_status"] == "auto_matched"]
    auto_correct = [p for p in auto if p["wikidata_qid"] == gold[p["redial_movie_id"]]]
    metrics = {
        "gold_labels_available": len(gold),
        "gold_rows_processed": len(compared),
        "top_candidate_accuracy_on_processed_gold": round(len(correct) / len(compared), 4) if compared else None,
        "auto_matched_gold_count": len(auto),
        "auto_match_coverage_on_processed_gold": round(len(auto) / len(compared), 4) if compared else None,
        "manual_review_gold_count": len(compared) - len(auto),
        "auto_match_precision_on_processed_gold": round(len(auto_correct) / len(auto), 4) if auto else None,
        "top_candidate_errors": [
            {"redial_movie_id": p["redial_movie_id"], "title": p["redial_title"],
             "predicted_qid": p["suggested_wikidata_qid"], "gold_qid": gold[p["redial_movie_id"]]}
            for p in compared if p["suggested_wikidata_qid"] != gold[p["redial_movie_id"]]
        ],
        "note": "Top-30 popular titles are not a representative random test set. Gold labels were user supplied, not all independently audited."
    }
    return metrics


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="data/movies_with_mentions.csv", type=Path)
    parser.add_argument("--gold", default="data/reference_labels_30.csv", type=Path)
    parser.add_argument("--limit", type=int, default=30,
                        help="Process top N movies by mentions. Default: 30; use 100 after validation.")
    parser.add_argument("--output-dir", default="outputs", type=Path)
    parser.add_argument("--cache", default=".cache/wikidata.sqlite3", type=Path)
    parser.add_argument("--user-agent", default="", help="Required, e.g. CineMatchMatcher/0.2 (contact: you@example.com)")
    parser.add_argument("--delay", type=float, default=1.2, help="Seconds between network requests (default 1.2)")
    parser.add_argument("--offline", action="store_true", help="Use only previously cached Wikidata responses")
    args = parser.parse_args()
    if not args.offline and ("@" not in args.user_agent and "http" not in args.user_agent):
        parser.error("Provide a meaningful --user-agent containing a contact email or URL (per Wikimedia policy)")
    if args.limit <= 0:
        parser.error("--limit must be positive")
    if args.delay < 0.4:
        parser.error("--delay must be at least 0.4 seconds")
    movies = load_movies(args.input)[:args.limit]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    predictions, all_candidates = [], []
    consecutive_errors = 0
    client = WikidataClient(args.cache, args.user_agent or "CineMatchMatcher/0.2 (offline)", args.delay, args.offline)
    try:
        for i, movie in enumerate(movies, 1):
            try:
                ranked = get_ranked(movie, client)
                status, reason, margin = decide_match(movie, ranked)
                candidate = ranked[0] if ranked else {}
            except (RuntimeError, ValueError) as error:
                status, reason, margin, ranked, candidate = "api_error", str(error), 0.0, [], {}
            record = {**movie,
                      "wikidata_qid": candidate.get("qid", "") if status == "auto_matched" else "",
                      "suggested_wikidata_qid": candidate.get("qid", ""),
                      "suggested_wikidata_title": candidate.get("title", ""),
                      "wikidata_years": "|".join(str(y) for y in candidate.get("years", [])),
                      "match_score": candidate.get("score", ""),
                      "score_margin": margin if candidate else "",
                      "match_status": status, "match_reason": reason,
                      "wikidata_url": f"https://www.wikidata.org/wiki/{candidate['qid']}" if candidate else ""}
            predictions.append(record)
            consecutive_errors = (consecutive_errors + 1) if status == "api_error" else 0
            for rank, c in enumerate(ranked[:5], 1):
                all_candidates.append({"redial_movie_id": movie["redial_movie_id"],
                                       "redial_title": movie["redial_title"], "rank": rank,
                                       "candidate_qid": c["qid"], "candidate_title": c["title"],
                                       "candidate_years": "|".join(str(y) for y in c["years"]),
                                       "description": c["description"], "score": c["score"],
                                       "title_similarity": c["title_similarity"],
                                       "type_signal": c["type_signal"], "matched_name": c["matched_name"]})
            # Persist after every movie, so an interruption doesn't lose already processed rows.
            write_csv(args.output_dir / "matches.csv", FIELDS, predictions)
            write_csv(args.output_dir / "review_queue.csv", FIELDS,
                      [p for p in predictions if p["match_status"] != "auto_matched"])
            write_csv(args.output_dir / "candidates.csv", CANDIDATE_FIELDS, all_candidates)
            print(f"[{i:>3}/{len(movies)}] {movie['cleaned_title'][:35]:35} {status:13} "
                  f"{candidate.get('qid', '-'):<12} score={candidate.get('score', '-')}", flush=True)
            if consecutive_errors >= 3:
                print("Stopping after three API errors in a row. Check internet connectivity, then rerun.")
                break
        if args.gold.exists():
            metrics = evaluate(predictions, args.gold)
            (args.output_dir / "evaluation.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
            print("\nReference-set evaluation:", json.dumps(metrics, indent=2))
        print(f"\nCreated {args.output_dir / 'matches.csv'}, review_queue.csv, candidates.csv")
        print(f"New API calls: {client.requests_made}; cached responses: {client.cache_hits}")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
