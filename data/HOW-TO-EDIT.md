# Hand-editing data when the feed breaks

The results feed is unofficial and will break roughly once a season. When it
does, the app keeps running on the last good data, and GitHub emails you that
a scheduled run failed. Here's how to enter a week (or a final table) by hand.
You need nothing but a browser and this repo.

## Entering a week's scores

1. Open `data/2026/week-NN.json` (NN = the gameweek, e.g. `week-07.json`).
2. For each finished match, fill in the score:
   ```json
   "score": { "h": 2, "a": 1 }
   ```
   Leave unplayed matches as `"score": { "h": null, "a": null }`.
3. **Do not change the `id` fields.** Scoring matches on team id, not name.
   If a match already has real ids from a previous fetch, keep them.
4. Commit. The validator runs automatically; if it's happy, the app shows the
   scores next time anyone opens it. If it fails, read the error — it tells you
   exactly which line is wrong.

## Entering a final table (promotion/relegation settlement)

1. Open `data/standings.json`.
2. Find the division under `divisions` and set each club's `rank`.
3. Keep the `id` fields intact — settlement uses them.
4. Commit; the validator checks it.

## Golden rules

- Never edit `id` values. They are the feed's stable club ids and everything
  scores off them.
- Scores are integers 0–30 or `null`. No strings, no blanks.
- A stale week is survivable. A stale month is not — enter data within a few days.
