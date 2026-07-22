# ⚽ Matchday EPL Predictor — Locked Build Spec

*The single source of truth. Every decision below was resolved in the /grill-me session
and supersedes earlier notes. Build from this.*

---

## The shape of the thing (one paragraph)

A single self-contained `index.html` on free GitHub Pages hosting, backed by a free Firebase
project (identity + picks only), fed by a Python script that GitHub Actions runs on a schedule to
pull EPL data from API-Football and commit it into the repo as JSON files the app reads. No
servers, no monthly cost. Directly modelled on the working "Hit Paydirt" NFL app — the plumbing is
reused; only the football-specific parts change.

---

## Locked decisions

| Area | Decision |
|---|---|
| **Architecture** | GitHub Pages + GitHub Actions Python fetcher committing JSON. Firebase only for identity + picks. Single self-contained `index.html`, no build step. |
| **Results/standings feed** | **API-Football** (api-sports.io), free tier (100 req/day). Covers the **whole English pyramid** incl. National League. Players never call it — the scheduled job does, a few calls/day. |
| **Scoring key (critical)** | Settle every pick by the feed's **stable numeric team id, NOT the club name.** Kills all spelling/abbreviation mis-scoring ("Wolves" vs "Wolverhampton Wanderers"). Build a name↔id map once per division, eyeball it. |
| **Firebase project** | ONE shared project (`world-cup-league-1599a`). Add an `epl_leagues` block ALONGSIDE the World Cup + NFL blocks. **Never replace the rules file.** (Block written — see `firestore.rules`.) |
| **Identity** | Personal join links = identity (link carries `playerId`). Invite-only, no join form. Scorer generates + sends links. Reused unchanged from NFL app. Bragging-rights threat model, no money. |
| **Locks** | **Per-game** — each match locks at its own kickoff. Players choose their own rhythm; handles TV-flexed fixtures with no special cases. (Replaces the earlier per-gameweek rule.) |
| **Weekly scoring** | **3** exact score · **1** correct result (W/D/L) · **0** wrong. Mirrors league points (3 for a win, 1 for a draw). |
| **Season pick — title** | Predict PL champion. **5 points** if correct, 0 if not. (Hardest single call → worth more than one promo/releg club.) |
| **Season picks — promotion/relegation** | **3 points per correctly named club, ANY ORDER, 0 for a miss.** Across the pyramid down to (and including) the League Two ↔ National League boundary. |
| **Dropped** | **Top 4** (fiddly "closeness" scoring, low interest). **Cups / FA Cup unlock** (different competition, not in scope). |
| **Provisional scoring** | From ~10 games to go, score season picks on an "if the season ended today" basis against the current standings, updated weekly. Shown in a SEPARATE "projected" column so real totals never yo-yo. Automatic across all divisions (API-Football gives all standings). |
| **Break fallback** | Validate hard → fail loud (GitHub emails you) → hand-edit the affected week/table from `HOW-TO-EDIT.md`. Id-based scoring guards the silent-rename case. Expect ~once a season. |

---

## Promotion/relegation boundaries in scope

Six boundaries, scored 3 pts per correct club (any order):

1. **Into the Premier League** ← 3 promoted from the Championship
2. **Out of the Premier League** → 3 relegated to the Championship
3. **Into the Championship** ← promoted from League One
4. **Out of the Championship** → relegated to League One
5. **Into League One** ← promoted from League Two
6. **Out of League One** → relegated to League Two
7. **Into League Two** ← promoted from the National League
8. **Out of League Two** → relegated to the National League

*(Stops at the League Two ↔ National League line — we don't predict within the National League.)*
All settleable automatically from API-Football standings. Manual entry only needed if the feed
breaks for a division.

---

## Weekly scoring — worked examples

Actual result **2–1 home win**:

| Player predicts | Points | Why |
|---|---|---|
| 2–1 | **3** | exact score |
| 3–1 | **1** | correct result (home win), wrong score |
| 1–0 | **1** | correct result (home win), wrong score |
| 1–1 | **0** | wrong (predicted draw) |
| 0–2 | **0** | wrong (predicted away win) |

Draw case — actual **1–1**:

| Player predicts | Points | Why |
|---|---|---|
| 1–1 | **3** | exact score |
| 0–0 | **1** | correct result (draw), wrong score |
| 2–2 | **1** | correct result (draw), wrong score |
| 1–0 | **0** | wrong (predicted home win) |

---

## What lives where (repo layout, Hit Paydirt pattern)

```
epl-matchday/                    (one GitHub repo)
  index.html                     the entire app (self-contained)
  data/
    season.json                  weeks, key dates, staleness threshold
    2026/week-NN.json            per-gameweek: fixtures, kickoffs (UTC), scores
    divisions.json               each division's clubs WITH their API-Football team ids
    standings.json               latest standings per division (for provisional scoring)
    HOW-TO-EDIT.md               hand-entry guide for when the feed breaks
  scripts/
    fetch_results.py             pulls API-Football, validates hard, writes week/standings files
    validate_data.py             guards hand-edits; runs in CI on any data change
  .github/workflows/
    fetch.yml                    scheduled fetcher (a few times a week)
    validate.yml                 runs validate_data.py on any data change
  firestore.rules                reference copy (deployed via Firebase console)
```

Firestore holds ONLY: `epl_leagues/{id}` (league + scorer + official season-pick results) and
`epl_leagues/{id}/players/{playerId}` (each person + their picks). Match results are in the repo
JSON, not Firestore.

---

## Data shapes

**A player's stored picks** (`epl_leagues/{id}/players/{playerId}.pred`):
```
pred: {
  weekly: {
    "gw1": { "<fixtureId>": { h: 2, a: 1 }, ... },   // per-match score picks
    ...
  },
  season: {
    champion: <teamId>,                 // 5 pts
    promRel: {                          // 3 pts per correct club, any order
      intoPL:   [<teamId>, <teamId>, <teamId>],
      outOfPL:  [<teamId>, <teamId>, <teamId>],
      intoChamp:[...], outOfChamp:[...],
      intoL1:[...], outOfL1:[...],
      intoL2:[...], outOfL2:[...]
    }
  }
}
```

**Official results** the scorer sets (`epl_leagues/{id}.results`), starts empty:
```
results: {
  champion: <teamId> | '',
  promRel:  '<json or map>' | ''       // rules just check it starts ''
}
```

All ids are **API-Football team ids**. Names are for display only.

---

## Build order

1. **Pipeline first.** Point `fetch_results.py` at API-Football; build the division name↔id map;
   generate the 38 gameweek files + standings. Test hard before the season.
2. **Adapt the app.** Swap to the 20 EPL clubs + colours; per-game locks; implement 3/1/0 in the
   pick cards and table; season-pick UI (champion + the promotion/relegation selectors already
   built).
3. **Add the `epl_leagues` rules block** (done — in `firestore.rules`) and publish via the console
   ALONGSIDE the existing blocks.
4. **Reuse join links + Manage Players** unchanged from the NFL app — generate links, send them.
5. **Provisional scoring** — from 10 games to go, run the season-pick settlement against current
   standings weekly into a separate projected column.

Steps 3–4 are nearly free (lifted from the NFL game). The effort is 1–2.

---

## Standing responsibilities / honest caveats

- The feed is **unofficial** — expect ~one break a season; the validate-hard + hand-edit fallback
  is the safety net. **You are the person who acts on the alarm email.** A stale week is fine; a
  stale month isn't.
- **Not for money** — the join-link identity model trusts the link.
- **Fixtures move** for TV/cups; per-game locks + a "flexed" flag handle it, but the feed must be
  trusted to update kickoff times.
- **Non-August kickoff times** start as placeholders until the feed confirms them; per-game locks
  self-correct as real times arrive.
