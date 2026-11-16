# CineMatch — ReDial → Wikidata Movie Matching (v0.2.1 + manual corrections)

A **conservative entity-resolution pipeline**. It takes ReDial's `movies_with_mentions.csv`, searches the official Wikidata Action API, and resolves year-specific English Wikipedia sitelinks when initial search is uncertain. It checks candidates' titles/English aliases, `publication date (P577)` and `instance of (P31)`, and exports matches plus a manual-review queue. It does **not** modify the original ReDial training and test files.

## Requirements

- Python **3.10+** (no packages to install; uses the standard library).
- Internet access on your machine for Wikidata requests. **Version 0.2 has passed local unit tests, but its live query behaviour has not yet been verified.**
- A **meaningful contact email or project URL in your User-Agent**, per Wikimedia's API policy. If you use an email, use an address you are comfortable exposing to the service's operators.

## Run from this folder

**Windows PowerShell:**

```powershell
python wikidata_matcher.py --limit 30 --user-agent "CineMatchMatcher/0.2 (contact: your-email@example.com)"
```

**Mac/Linux:**

```bash
python3 wikidata_matcher.py --limit 30 --user-agent "CineMatchMatcher/0.2 (contact: your-email@example.com)"
```

Replace the example contact address with your own. Do not leave the placeholder unchanged.

After inspecting v0.2 evaluation, try 100 popular movies:

```powershell
python wikidata_matcher.py --limit 100 --user-agent "CineMatchMatcher/0.2 (contact: your-email@example.com)"
```

Re-running inside your existing project folder will **reuse cached API responses**, though the first 30 rows will still be recomputed locally. If using this ZIP as a new folder, previous cache is not included. API results are cached in `.cache/wikidata.sqlite3`. A slow rate (at least 1 request every 1.2 seconds by default), sequential requests, and handling for 429/503 responses are built in.

To test with *only previously cached responses* (note: new sitelink lookups may not be cached yet, causing `api_error`):

```powershell
python wikidata_matcher.py --limit 30 --offline
```

## What's new in v0.2

The initial run achieved 28/30 correct top-ranked candidates, with 23/23 accepted mappings correct *against the provided reference labels*. Two top suggestions, **It (2017)** and **Seven (1995)**, were unrelated entities. The new fallback requests an exact English Wikipedia article title through Wikidata's `wbgetentities` `sites=enwiki` method, for example `It (2017 film)` or `Seven (1995 film)`. Returned items are scored with the **same** film/year safeguards. Short titles like `It` remain in manual review even if their highest-ranked result is correct.

All 12 local tests pass, including simulated examples for these two errors. The 30-movie performance **has not yet been remeasured on live Wikidata** and could remain unchanged if the fallback does not resolve an item.

See `EVALUATION_FINDINGS.md` for the pilot analysis.

## Outputs

| File | Meaning |
|---|---|
| `outputs/matches.csv` | One row per attempted ReDial movie, including separate **accepted** `wikidata_qid` (blank unless auto-matched) and `suggested_wikidata_qid`, heuristic score (0–100), and status |
| `outputs/review_queue.csv` | Movies that were **not** automatically accepted, including unresolved and API errors |
| `outputs/candidates.csv` | Five best candidate QIDs per movie, with evidence useful for reviewing manually |
| `outputs/evaluation.json` | Evaluation against the 30 user-provided reference QIDs; only available for processed reference rows |

**Statuses:**
- `auto_matched`: conservative acceptance based on title or alias, matching year, evidence it is a film, and a gap over competing candidates.
- `needs_review`: plausible candidate but ambiguous, missing year, conflicting year, uncertain title, or close alternative.
- `not_found`: no sufficiently convincing candidate. This is NOT proof no corresponding movie exists in Wikidata. A low-confidence suggestion may still be shown in its separate suggestion columns.
- `api_error`: request failed; retry when connectivity recovers.

**Critical:** `match_score` is a *heuristic ranking score*, **not** a calibrated percentage probability. Auto-accepted QIDs should be sampled for review before being treated as production quality. Single-digit or very short titles are not auto-accepted.

## Your 30 checked movies

`data/reference_labels_30.csv` contains the 30 ReDial IDs and QIDs from your message. Entry #9 (Wonder Woman, 2017) is corrected to **Q20502242**; the initially selected Q27204179 represents *Professor Marston & The Wonder Women*. Note that the other labels are user-provided and have not all been independently verified. We preserve these labels only for evaluation: the matcher **never uses their QIDs during matching**. This avoids leaking test answers into predictions.

The 30 most-mentioned films form a useful *smoke-test set*, but they are not random and do not establish dataset-wide accuracy. After the pilot, sample a random group of rare, ambiguous and missing-year records for independent review.

## How to review

1. Open `outputs/review_queue.csv` and `outputs/candidates.csv` in Excel.
2. For any uncertain movie, open `https://www.wikidata.org/wiki/Q...` and inspect **title, year and whether the entity is the film rather than a book/series/soundtrack**.
3. Record final QIDs and corrections **in a separate, human-verified mapping CSV**. Don't edit the originals. The non-accepted `suggested_wikidata_qid` is not a verified match.
4. Run the first 30 and inspect `outputs/evaluation.json`. If mistakes appear, improve the algorithm before moving to 100.

## What this version does *not* do

- Does not automatically collect full genres/cast/directors yet. That comes **after** we establish a validated mapping.
- Does not query the entire Wikidata dump or claim to have matched all 6,924 movies.
- Does not deduplicate remakes or group film franchises unless entity IDs confirm they are the same film.
- Does not automatically update a future application's live database.

## Data rights

Wikidata's **structured data** is published under CC0; it does not follow that linked images or movie posters are CC0. ReDial is licensed **CC BY 4.0**, and if you publish transformed ReDial data, preserve the required attribution, copyright/licence information and change notices. Review rights and privacy practices again before launching CineMatch.

- [Wikidata API / access guide](https://www.wikidata.org/wiki/Wikidata:Data_access)
- [Wikimedia API rate limits](https://www.mediawiki.org/wiki/Wikimedia_APIs/Rate_limits)
- [ReDial project](https://redialdata.github.io/website/)


## v0.2.1: persistent human corrections

Your **live v0.2 evaluation** found **30/30 correct top-ranked candidates** and **24/24 correct auto-accepted matches** against the first 30 reference labels. Six items were correctly held for review: *It (2017)*, *Die Hard (1988)*, *The Matrix (1999)*, *Guardians of the Galaxy (2014)*, *John Wick (2014)* and *Inception (2010)*. The shortlist is highly popular movies, so accuracy cannot be generalised to all 6,924 titles.

In this update, `data/manual_overrides.csv` **preloads those six mappings from your previously checked reference spreadsheet** with `review_status=verified`. These are *user-verified labels*, not independent third-party reaudits; change any QID/status if new inspection shows a problem. This is a data-curation step, not an improvement in algorithmic accuracy.

**Run after any normal match run:**

```powershell
python wikidata_matcher.py --limit 30 --user-agent "CineMatchMatcher/0.2 (contact: your-email@example.com)"
python apply_manual_corrections.py
```

The second command makes no API calls and reads your `outputs/matches.csv`. It produces:

- `outputs/final_matches.csv`: both accepted machine matches and human-verified overrides; adds `mapping_source` and `manual_review_notes`.
- `outputs/final_review_queue.csv`: only unresolved rows after applying verified overrides.

**Important:** `outputs/matches.csv`, `outputs/review_queue.csv`, `outputs/candidates.csv` and `outputs/evaluation.json` are **not overwritten**. In particular, manual QIDs don't feed into the matcher or its evaluation. Keep those raw outputs as the honest baseline when comparing algorithms.

### Review a new ambiguous movie

1. Locate its row in the normal `outputs/review_queue.csv` and its alternatives in `outputs/candidates.csv`.
2. Check the film on Wikidata (title, year, director/other distinguishing facts, and film type).
3. Append one row to `data/manual_overrides.csv`: `redial_movie_id,wikidata_qid,verified,reason for review`. If unresolved, use `pending` and it will not be accepted.
4. Run `python apply_manual_corrections.py` again. **No need to repeat Wikidata API searches.**

For real deployment, evaluate on a held-out set independent of records used to tune heuristics; data-curation overrides must not count toward automatic matcher accuracy.
