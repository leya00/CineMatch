# CineMatch v0.1 pilot findings (user-provided output)

Source: `evaluation.json` and `review_queue.csv` from the first 30 most-mentioned ReDial movies.

- 30 gold-labelled movies evaluated (these labels were supplied by the user; not independently audited).
- Top-1 candidate accuracy: **28 / 30 = 93.33%**.
- Auto-accepted: **23 / 30 = 76.67% coverage**.
- Auto-match precision on this sample: **23 / 23 = 100%**.
- Held for review: **7 / 30 = 23.33%**.

## Two bad top candidates

| ReDial ID | Movie | v0.1 top suggestion | Reference QID | Explanation |
|---|---|---|---|---|
| 187028 | It (2017) | Q11661, information technology | Q25136484 | Generic short word collides with unrelated entity |
| 182709 | Seven (1995) | Q908659, Seven Network | Q190908 | Generic title collides with broadcaster |

These bad suggestions were **not** auto-accepted; they were in the manual review queue.

## Five correct suggestions held for review

| Title | Suggested QID | Heuristic score | Margin |
|---|---|---:|---:|
| Die Hard (1988) | Q105598 | 100 | 10 |
| The Matrix (1999) | Q83495 | 100 | 10 |
| Guardians of the Galaxy (2014) | Q5887360 | 100 | 10 |
| John Wick (2014) | Q15732802 | 100 | 10 |
| Inception (2010) | Q25188 | 100 | 10 |

These were withheld because the score margin was below the 12-point threshold. **Do not lower that threshold solely to improve headline coverage.** Inspect `candidates.csv` for the competing items before changing the decision rule.

## v0.2 change to test

Only after first-pass search fails to auto-accept a film, try Wikidata enwiki sitelink article-title lookups such as `It (2017 film)` and `Seven (1995 film)`. The sitelink result becomes one candidate and still goes through title, release-year and film-type verification. No user-provided QIDs are used during predictions.

This should help candidates with generic titles, but **no live v0.2 accuracy claims are made**. Run with `--limit 30` and compare both `evaluation.json` and `review_queue.csv` to the v0.1 results.

A later evaluation should include randomly sampled records, rare films, title variants, and missing release years. Do not treat the popular-first pilot as representative.
