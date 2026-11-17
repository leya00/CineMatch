# CineMatch — ReDial → Wikidata Movie Matching (v0.2.1 + manual corrections)

A conservative entity-resolution pipeline that links movies in the ReDial dataset to Wikidata records, so they can later be enriched and used in a movie recommendation app.
 
It takes ReDial's `movies_with_mentions.csv` and searches the official Wikidata Action API. When the initial search is uncertain, it falls back to year-specific English Wikipedia sitelinks. Each candidate is checked against its title and English aliases, its publication date (`P577`) and its `instance of` (`P31`) value. The pipeline exports the accepted matches plus a manual-review queue for everything it is not sure about. It never modifies the original ReDial training and test files.

## Results at a glance
 
I evaluate against 30 reference labels (see [Reference labels](#reference-labels-and-evaluation)).
 
| Run | Top-ranked candidate correct | Auto-accepted matches correct | Notes |
| --- | --- | --- | --- |
| Initial run | 28/30 | 23/23 | *It* (2017) and *Seven* (1995) were matched to unrelated entities. |
| v0.2 (live) | 30/30 | 24/24 | Fixed by the exact-title sitelink fallback. Six films were correctly held for review: *It* (2017), *Die Hard* (1988), *The Matrix* (1999), *Guardians of the Galaxy* (2014), *John Wick* (2014) and *Inception* (2010). |
 
The 30 films are the most-mentioned in the dataset, so this is a useful smoke test but not a random sample. It does not establish accuracy across all 6,924 titles.

## How matching works
 
1. **Search.** Query the Wikidata Action API for each ReDial movie title.
2. **Score candidates.** Check title or English alias, publication date (`P577`), whether the entity is a film (`P31`), and whether the best candidate clearly beats the alternatives. The result is a heuristic `match_score` from 0 to 100.
3. **Sitelink fallback (added in v0.2).** If the search is uncertain, request the exact English Wikipedia article title through Wikidata's `wbgetentities` method with `sites=enwiki`, for example `It (2017 film)` or `Seven (1995 film)`. Returned items are scored with the same film and year safeguards.
4. **Conservative acceptance.** Only high-confidence candidates are accepted automatically. Single-digit or very short titles (such as *It*) are never auto-accepted, even if the top-ranked result is correct, and go to manual review instead.
5. **Export.** Write matches, a review queue and the best candidates with their evidence.

`match_score` is a heuristic ranking score, **not** a calibrated probability. Auto-accepted QIDs should be sampled and reviewed before being treated as production quality.

## Requirements

- Python 3.10+ (standard library only, nothing to install).
- Internet access for Wikidata requests.
- A meaningful contact email or project URL in your `User-Agent`, as required by Wikimedia's API policy. If you use an email, use an address you are comfortable exposing to the service's operators.
- Version 0.2 passed local unit tests (12 tests, including simulated cases for the *It* and *Seven* errors) and was then evaluated against live Wikidata, with the results above.

## Usage

**Windows PowerShell:**

```powershell
python wikidata_matcher.py --limit 30 --user-agent "CineMatchMatcher/0.2 (contact: your-email@example.com)"
```

**Mac/Linux:**

```bash
python3 wikidata_matcher.py --limit 30 --user-agent "CineMatchMatcher/0.2 (contact: your-email@example.com)"
```

Replace the example contact address with your own. Do not leave the placeholder unchanged.

After checking the evaluation on 30 films, try 100 popular movies:

```powershell
python wikidata_matcher.py --limit 100 --user-agent "CineMatchMatcher/0.2 (contact: your-email@example.com)"
```

Re-running inside your existing project folder will **reuse cached API responses**, though the first 30 rows will still be recomputed locally. If using this ZIP as a new folder, previous cache is not included. API results are cached in `.cache/wikidata.sqlite3`. A slow rate (at least 1 request every 1.2 seconds by default), sequential requests, and handling for 429/503 responses are built in.

**Offline mode.** To run using only previously cached responses:
 
```
python wikidata_matcher.py --limit 30 --offline
```
New sitelink lookups may not be cached yet, which can produce `api_error` rows.

## Outputs
 
| File | Contents |
| --- | --- |
| `outputs/matches.csv` | One row per attempted ReDial movie, with the accepted `wikidata_qid` (blank unless auto-matched), a separate `suggested_wikidata_qid`, the heuristic score (0–100) and a status. |
| `outputs/review_queue.csv` | Movies that were not automatically accepted, including unresolved rows and API errors. |
| `outputs/candidates.csv` | The five best candidate QIDs per movie, with evidence to help manual review. |
| `outputs/evaluation.json` | Evaluation against the 30 reference QIDs, for the reference rows that were processed. |

### Statuses
 
- `auto_matched`: accepted because the title or alias matches, the year matches, there is evidence it is a film, and the candidate has a clear gap over its competitors.
- `needs_review`: a plausible candidate, but ambiguous, missing a year, with a conflicting year, an uncertain title or a close alternative.
- `not_found`: no sufficiently convincing candidate. This is **not** proof that no matching movie exists in Wikidata. A low-confidence suggestion may still appear in the separate suggestion columns.
- `api_error`: the request failed. Retry when connectivity recovers.

## Reference labels and evaluation
 
`data/reference_labels_30.csv` holds the 30 ReDial IDs and Wikidata QIDs I use as reference labels. The matcher never uses these QIDs while matching, so the test answers cannot leak into predictions. They are used only for evaluation.
 
- Entry #9 (*Wonder Woman*, 2017) is corrected to **Q20502242**. My initial choice, Q27204179, is *Professor Marston & The Wonder Women*.
- The other labels were provided by me and have not all been independently verified.
- The 30 most-mentioned films make a useful smoke-test set, but they are not random. After this pilot, the next step is to sample a random group of rare, ambiguous and missing-year records for independent review.

See `EVALUATION_FINDINGS.md` for the pilot analysis.

## Manual corrections (v0.2.1)
 
Human corrections are stored separately from the matcher's output, so the raw results stay an honest baseline.
 
`data/manual_overrides.csv` preloads the six films that were held for review (*It*, *Die Hard*, *The Matrix*, *Guardians of the Galaxy*, *John Wick*, *Inception*), taken from my earlier reference spreadsheet and marked `review_status=verified`. These are labels I checked myself, not independent third-party audits, so change any QID or status if a new inspection shows a problem. This is a data-curation step, **not** an improvement in algorithmic accuracy.
 
Run after any normal match run:
 
```
python wikidata_matcher.py --limit 30 --user-agent "CineMatchMatcher/0.2 (contact: your-email@example.com)"
python apply_manual_corrections.py
```
 
The second command makes no API calls. It reads `outputs/matches.csv` and produces:
 
- `outputs/final_matches.csv`: the accepted machine matches plus the human-verified overrides, with added `mapping_source` and `manual_review_notes` columns.
- `outputs/final_review_queue.csv`: only the rows still unresolved after the verified overrides are applied.
`outputs/matches.csv`, `outputs/review_queue.csv`, `outputs/candidates.csv` and `outputs/evaluation.json` are **not** overwritten, and manual QIDs never feed into the matcher or its evaluation. Keep those raw outputs as the baseline when comparing algorithm changes.

### Reviewing an ambiguous movie
 
1. Find its row in `outputs/review_queue.csv` and its alternatives in `outputs/candidates.csv` (both open fine in Excel).
2. Open `https://www.wikidata.org/wiki/Q...` for each candidate. Check the title, year, director or other distinguishing facts, and that the entity is the film rather than a book, series or soundtrack.
3. Append one row to `data/manual_overrides.csv` in the form `redial_movie_id,wikidata_qid,verified,reason for review`. Use `pending` if it is unresolved, and it will not be accepted. The non-accepted `suggested_wikidata_qid` is **not** a verified match.
4. Run `python apply_manual_corrections.py` again. There is no need to repeat the Wikidata searches.
For a real deployment, evaluate on a held-out set that is independent of the records used to tune the heuristics. Manual overrides must never count toward the matcher's automatic accuracy.



**Critical:** `match_score` is a *heuristic ranking score*, **not** a calibrated percentage probability. Auto-accepted QIDs should be sampled for review before being treated as production quality. Single-digit or very short titles are not auto-accepted.


## Data rights

Wikidata's **structured data** is published under CC0; it does not follow that linked images or movie posters are CC0. ReDial is licensed **CC BY 4.0**, and if you publish transformed ReDial data, preserve the required attribution, copyright/licence information and change notices. Review rights and privacy practices again before launching CineMatch.

- [Wikidata API / access guide](https://www.wikidata.org/wiki/Wikidata:Data_access)
- [Wikimedia API rate limits](https://www.mediawiki.org/wiki/Wikimedia_APIs/Rate_limits)
- [ReDial project](https://redialdata.github.io/website/)
