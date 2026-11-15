# Tims Hockey Challenge

Public page for [geekahedron.com/tools/hockey/](https://geekahedron.com/tools/hockey/) and the daily job that feeds it.

The goal model in `model/` is frozen. `model/logistic_json.py` plus
`model/data/logistic.json` is the numpy-only export of that logistic
pipeline. This tool does not change features, training, or the scoring math.
See `model/README.md` for how the model was built.

The page shows this model's probability that a player scores at least one
non-shootout goal. Two more columns are estimates built from public NHL
stats: a **DDH-style estimate** (a probability) and an **HCH-style** ranking
(this season's goals per game). They are not another site's percentages,
ranks, or picks.

## Page

`web/` is static HTML, CSS, and JS in the same dark theme as
[geekahedron.com/tools/solver/](https://geekahedron.com/tools/solver/). It only
reads JSON:

| File | What the page does with it |
| --- | --- |
| `data/today.json` | Today's three groups. Players sorted by the selected method, a bar per player, team, opponent, home or away, top pick highlighted. The summary lists each method's leader. |
| `data/days/index.json` | The date list. |
| `data/days/YYYY-MM-DD.json` | One slate, including who scored once the games are final. |
| `data/season.json` | Season tracker for every method: per-day pick, value, hit, running hit rate, top-3 hits, and the random baseline. The top-level summary is the model. `by_method` repeats it for each method. |

Views are Today, Past days, and Season. The method menu lists Model, the
DDH-style estimate, and HCH-style. The compare table on Today has a column
per method. A probability method is a number on each player at
`probability.<id>` (0 to 1). A ranking method is `rank.<id>` (1 is first)
plus `style` (goals per game and the other public season totals). The page
does not fetch anything else.

Open it from a local server (fetch does not work from `file://`):

```
cd web && python3 -m http.server 8765
```

Sample JSON for screenshots lives in `tests/fixtures/publish/`. Point the
server at a copy where that tree is named `data/`, or pass `?data=` only for
a folder of the same shape. The live site uses `data/` next to `index.html`.

## Daily job

```
~/tims-venv/bin/python job/run_daily.py --publish ~/tims-hockey/publish
```

Python 3.9. The runner does not use 3.10-only syntax. `model/features.py`,
the fetch modules, and `logistic_json.py` already parse on 3.9; the syntax
check is `tests/test_py39.py` (vermin, target 3.9 or older).

One run:

1. Refreshes finished NHL games from api-web.nhle.com and api.nhle.com into
   `model/raw/` (`fetch_boxscores.compact`, `fetch_pptoi.window`). Prior
   seasons are backfilled once. The current season is scanned from the last
   stored game up to today. Features are rebuilt from `raw/` when the slate
   is scored (`features.load`), not from a saved feature table.
2. Loads today's groups. With `--groups FILE`, the file is local JSON. Without
   it, `TimsGroupsSource` reads `$TIMS_ENV` and queries `HockeyPlayers` on
   `https://use1-prod-th-gateway.rbictg.com/graphql`. The IdToken is minted
   with Cognito `REFRESH_TOKEN_AUTH`. Each player is matched to an NHL id by
   team abbreviation and jersey number (`NJ`/`TB`/`SJ`/`LA` map to
   `NJD`/`TBL`/`SJS`/`LAK`). The old px-api host is not used.
3. Scores every available player with `logistic_json.predict_proba`. The
   joblib pipeline is not loaded. It then adds the DDH-style estimate and
   the HCH-style ranking from public NHL season totals
   (`clones/`, numpy only). Those totals stop at the day before the slate.
   The logistic probabilities, the model pick, and the player order are
   computed first and are not rewritten.
4. Grades every published day whose games are now final. A non-shootout goal
   counts. A group stays pending until each of its teams is `OFF` or `FINAL`.
5. Writes the publish directory: `today.json`, `days/YYYY-MM-DD.json`,
   `days/index.json`, `season.json`.

The recorded pick is whoever the model ranked first that morning (ties
share it, and the hit is the fraction who scored). Top-3 hits are how many
of the first three scored. The random baseline is the share of the group
who scored, which is what a random pick would be expected to hit. The
running hit rate is cumulative hits over cumulative graded picks.

Normalized groups file:

```json
{
  "date": "2026-11-14",
  "groups": [
    {
      "id": 1,
      "players": [
        {
          "nhlPlayerId": 8478402,
          "fullName": "Connor McDavid",
          "team": "EDM",
          "opponent": "SJS",
          "homeAway": "HOME",
          "position": "C"
        }
      ]
    }
  ]
}
```

The Tims adapter also accepts the `pickGroups` shape in
`tests/fixtures/tims_picks.json`. Scratched players are marked unavailable
and are not scored.

Flags: `--date`, `--groups`, `--publish`, `--raw`, `--no-refresh`,
`--no-grade`, `--rescore`, `--backfill-clones`, `--log`. A graded day is not
scored again unless you pass `--rescore`. A still-pending day is scored
again, then graded.

## Backfill on the host

Days published before the two extra columns existed do not have them. This
does not deploy the page and does not rescore the logistic model. It does
not need Tims credentials. It does need network access to `api.nhle.com` and
`api-web.nhle.com`. Run it from the git checkout, then rsync the JSON the
same way the cron does. Copy `web/` by hand only when you want the new page.

```
cd ~/tims-hockey
git pull
~/tims-venv/bin/python job/run_daily.py \
  --publish ~/tims-hockey/publish \
  --backfill-clones \
  --log ~/tims-hockey/logs/backfill.log
rsync -a --delete ~/tims-hockey/publish/ ~/public_html/tools/hockey/data/
```

That walks every `days/YYYY-MM-DD.json` from 2026-11-02 onward. `--backfill-from`
and `--backfill-to` narrow the window. A day that fails is left as it was;
the command exits 1 if any day failed, and rerunning it is safe. Each graded
day then carries hits and picks for all three methods in `season.json`.
The morning cron does not need the flag: a new slate is scored with all
three methods, and grading fills the extra hits from the picks stored that
morning.

## Secrets

Credentials live only in the file named by `TIMS_ENV`, for example
`~/tims-hockey/secrets/tims.env`. That file is outside the repo and outside
`public_html`. `deploy/tims.env.example` lists `TIMS_CLIENT_ID`,
`TIMS_COGNITO_ID`, and `TIMS_REFRESH_TOKEN`. chmod 600.

The job will not use a secrets file under `public_html` or inside the
publish directory. It does not log credential values. The publisher rejects
a document that contains a secret field. The log path is refused if it sits
in the publish directory or under `public_html`.

The picks client is read-only. It sends the refresh call and the
`HockeyPlayers` query, and nothing that submits a pick. It does not start
a magic-link sign-in. If Cognito returns a new refresh token, that value is
written back to the same secrets file. If the refresh token is rejected,
the run logs the failure outside the web root and leaves yesterday's
published JSON in place.

## Server layout and cron

See `deploy/README.md`. The cron line:

```
15 10 * * * TIMS_ENV=$HOME/tims-hockey/secrets/tims.env $HOME/tims-venv/bin/python $HOME/tims-hockey/job/run_daily.py --publish $HOME/tims-hockey/publish --log $HOME/tims-hockey/logs/daily.log && rsync -a --delete $HOME/tims-hockey/publish/ $HOME/public_html/tools/hockey/data/
```

Publish-dir layout after a run:

```
today.json
season.json
days/index.json
days/YYYY-MM-DD.json
```

`rsync` copies that tree to `public_html/tools/hockey/data/`. The HTML is
copied by hand from `web/` when the page changes. Do not rsync the repo, the
raw files, or the secrets file into `public_html`.

## Tests

```
python3 -m venv .venv
.venv/bin/pip install numpy pandas scikit-learn pytest vermin
.venv/bin/python -m pytest
```

* `tests/test_parity.py` — `logistic_json` against `train_utils.X` and a
  sklearn pipeline on `tests/fixtures/feature_rows.json`.
* `tests/test_schema.py` — publish-dir schema, and the page sources.
* `tests/test_py39.py` — vermin, Python 3.9 or older, on `model/`, `job/`, and `tests/`.
* Group parsing, grading, the incremental refresh, the two extra methods,
  and a tiny end-to-end run are the other files in `tests/`.

Rebuild the screenshot fixture with `python tests/build_fixture_site.py`.
Those probabilities are hand-set sample data, not a model run.
