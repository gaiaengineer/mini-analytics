# Scripts, CLI, and the YAML format

Everything runs through one CLI: `mini-analytics`. Four commands. You rarely need Python directly.

## First-time setup (once per machine)

```bash
git clone https://github.com/gaiaengineer/mini-analytics.git
cd mini-analytics

python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

This creates a local virtualenv and installs the project plus its dev dependencies (pytest, ruff).

After this, the CLI is at `.venv/bin/mini-analytics`. You can either call that directly (recommended) or run `source .venv/bin/activate` first so plain `mini-analytics` works.

## Everyday workflow

```bash
# Pull fresh CSVs from S3 into data/raw/ (only when you want new data)
.venv/bin/mini-analytics fetch

# Load the CSVs, register model views, print row counts
.venv/bin/mini-analytics ingest

# Rebuild every dashboard as static HTML into build/
.venv/bin/mini-analytics build

# Or do both in one step — fetch first, then build:
.venv/bin/mini-analytics build --refresh

# Serve build/ on localhost
python3 -m http.server --directory build 8765
# open http://localhost:8765/
```

To iterate on a dashboard: edit the YAML, re-run `build` (without `--refresh`), refresh the browser. The HTTP server doesn't need restarting and you don't re-hit S3 every iteration.

## The four CLI commands

### `ingest`

```
.venv/bin/mini-analytics ingest
```

Opens a DuckDB connection, runs the loader picked in `sources.yml` (currently `csv`), registers the three model views, and prints one line per view with its row count.

Expected output with the demo dataset:

```
 view               kind    rows
 authors            source      240
 books              source      438
 tokens             source    9,835
 token_purchases    source    4,762
 ga_events          source  278,994
 fct_token_purchase model     4,762
 dim_book           model       438
 dim_author         model       240
```

If the row counts look wrong, start debugging there. Usually it means a CSV is missing: rerun `python3 scripts/make_demo_data.py`.

### `tables`

```
.venv/bin/mini-analytics tables
```

Lists every view currently registered and the type of every column. Useful when you're writing SQL and can't remember whether it's `purchase_date` or `date_purchased`, or whether GMV is in cents or dollars.

### `query`

```
.venv/bin/mini-analytics query "SELECT ..."
```

Runs arbitrary SQL against the registered views and prints the result as a nicely-formatted table. All model views are available. Example:

```bash
.venv/bin/mini-analytics query \
  "SELECT name, gmv_cents/100.0 AS usd FROM dim_author ORDER BY gmv_cents DESC LIMIT 5"
```

This is your go-to for validating metrics before or after a build.

### `fetch`

```
.venv/bin/mini-analytics fetch
```

Pulls the most-recently-modified `*.csv` from each S3 prefix configured in `sources.yml`'s `[s3]` block, downloading it as `data/raw/<table>.csv`. Prints a summary table (S3 key, last-modified, byte size). Requires AWS credentials in the standard chain — env vars or `~/.aws/credentials` profile. **Credentials are never read from `sources.yml`.**

If your `sources.yml` has no `[s3]` block, this command exits with an error.

### `build`

```
.venv/bin/mini-analytics build
# fetch fresh data from S3 first:
.venv/bin/mini-analytics build --refresh
# or with custom paths:
.venv/bin/mini-analytics build \
  --sources sources.yml \
  --dashboards src/mini_analytics/dashboards \
  --out build
```

What it does, in order:

1. Opens a DuckDB connection (ingest + model views).
2. Loads every `*.yml` in `src/mini_analytics/dashboards/`.
3. For each YAML: runs every block's SQL against the warehouse, produces a Plotly chart (or KPI div, or HTML table), writes one CSV per block to `build/<id>/exports/`.
4. Renders the HTML page via a Jinja template and writes it to `build/<id>/index.html`.
5. Writes a landing page at `build/index.html` linking to every dashboard.

Output is fully self-contained under `build/` — you can copy that folder anywhere.

## `sources.yml`

Picks the active loader and (optionally) tells `fetch` where to pull CSVs from:

```yaml
loader: csv

csv:
  root: data/raw

# Optional — only used by `mini-analytics fetch` and `build --refresh`.
s3:
  bucket: your-export-bucket
  region: us-east-1
  profile: mini-analytics      # name of the local AWS profile, NOT the secret
  download_to: data/raw
  prefixes:
    authors:         exports/authors/
    books:           exports/books/
    tokens:          exports/tokens/
    token_purchases: exports/token_purchases/
```

`profile` names a profile in `~/.aws/credentials`. The actual access key + secret never live in this file. Set the profile up once with `aws configure --profile mini-analytics`. (If `aws` CLI isn't installed, write the profile by hand — see `docs/running-locally.md`.)

To add a database loader (e.g. Postgres), the `loader:` line and a `[postgres]` block are all that change. The `[s3]` block stays as-is for the fetch path.

## The dashboard YAML format

Each dashboard is one YAML file in `src/mini_analytics/dashboards/`. One file = one HTML page. Minimal skeleton:

```yaml
id: my_dashboard              # slug — becomes the URL path
title: Human-readable title
description: One-line pitch shown under the title.

blocks:
  - id: my_block_1
    type: kpi
    title: Total GMV
    format: currency
    sql: |
      SELECT SUM(price_cents) / 100.0 AS value
      FROM fct_token_purchase WHERE is_purchased

  - id: my_block_2
    type: line
    title: GMV by month
    format: currency
    x: month
    y: gmv
    sql: |
      SELECT date_trunc('month', purchase_date)::DATE AS month,
             SUM(price_cents) / 100.0 AS gmv
      FROM fct_token_purchase
      WHERE is_purchased AND purchase_date IS NOT NULL
      GROUP BY 1 ORDER BY 1
```

### Supported block types

| Type | What it renders | SQL must return |
|---|---|---|
| `kpi` | A single big number with a label and optional subtitle. | One row, first column = the scalar. |
| `line` | Line chart (x/y axes). | Rows with the `x` and `y` columns; optional `color` for multi-line. |
| `area_stacked` | Filled stacked area chart. Always full-width. | `x`, `y`, `color` columns. |
| `bar` | Bar chart, vertical or horizontal. | `x`, `y` columns; optional `color`. For horizontal, set `orientation: h` and put the numeric measure on `x`. |
| `histogram` | Histogram of one variable. | A column matching `x`; optional `color` for overlay. `nbins` optional. |
| `scatter` | Scatter plot (one point per row). | `x`, `y` columns; optional `color` (categorical) and `size` (column that drives marker size). |
| `table` | HTML table. Always full-width. | Any columns — they all become table columns. |
| `note` | Prose callout for methodology, caveats, or domain context. Full-width, warm-ivory styling, rendered above the KPI strip so business users see it before the numbers. | `body` (required) instead of `sql`. Paragraphs split on blank lines; `**bold**` and `` `code` `` are recognised. No CSV export. |

### Every field you can put on a block

| Field | Type | Used by | Notes |
|---|---|---|---|
| `id` | string | all | Unique slug. Becomes the CSV file name and the block's HTML id. |
| `type` | string | all | One of the block types above. |
| `title` | string | all | Shown at the top of the block (and as the KPI label). |
| `description` | string | all (optional) | Small grey subtitle under the block title. |
| `sql` | string | all non-note | The query. **Dashboards should read from model views** (`dim_author`, `dim_book`, `fct_token_purchase`). Note blocks must NOT have `sql`. |
| `body` | string | note only | Paragraphs of text (blank-line separated). Supports `**bold**` and `` `code` ``. Required for notes. |
| `x`, `y`, `color` | string | charts | Column names from the SQL result to plot on each axis / encoding. |
| `format` | string | KPIs + y/x axis | `currency`, `percent`, `integer`, `number`. Controls how values display. |
| `subtitle` | string | KPI (optional) | Extra context under the big number. |
| `orientation` | `h`/`v` | bar | Horizontal bar charts are easier to read when labels are long. |
| `height` | int | charts | Override the default 320px chart height (e.g. 520 for 20-row horizontal bars). |
| `nbins` | int | histogram | Number of buckets. |
| `size` | string | scatter | Column whose values drive the marker size. Must be positive (use `+ N` in SQL if some values are 0). |
| `wide` | bool | non-KPI | Force the block to span the full dashboard width. |

### How KPI layout works

Every block of type `kpi` is pulled out of the main grid and shown as a compact tile in a strip at the top of the page. Everything else (charts and tables) flows below in a responsive two-column grid, with `area_stacked`, `table`, and any block with `wide: true` taking the full width.

## Adding a new dashboard — step by step

1. Create a new file: `src/mini_analytics/dashboards/my_new_dashboard.yml`.
2. Fill in `id`, `title`, `description`, and a list of blocks following the skeleton above.
3. Test the SQL for each block in isolation first:
   ```bash
   .venv/bin/mini-analytics query "<your SQL>"
   ```
   This surfaces SQL errors before they break a build.
4. Run `.venv/bin/mini-analytics build`. Look for `rendered my_new_dashboard → ...` in the output.
5. Open `http://localhost:8765/my_new_dashboard/` (remember the trailing slash).
6. Iterate: edit YAML, re-run `build`, refresh browser.

The landing page at `http://localhost:8765/` auto-picks up the new dashboard — no extra registration needed.

## Editing an existing dashboard

Same loop:
1. Open the YAML under `src/mini_analytics/dashboards/`.
2. Edit.
3. `.venv/bin/mini-analytics build`.
4. Refresh the browser.

Rule of thumb: a dashboard change that takes more than 5 minutes probably means the model views (`src/mini_analytics/models/*.sql`) need a new column — consider adding it there before inlining a giant join into a block's SQL. Model-view changes benefit every dashboard; inline joins benefit only one.

## Running the tests

```bash
.venv/bin/pytest -q
```

Exists at two levels:

- **Data integrity** (`tests/test_csv_loader.py`, `tests/test_models.py`) — loader registers all views with the right row counts; types are pinned; model views expose stable sums. These are the guardrails that catch accidental schema drift.
- **Rendering** (`tests/test_renderer.py`) — the Revenue Overview dashboard YAML actually produces a usable HTML page with Plotly, CSV exports, and download buttons wired up. If you change the renderer, these should catch obvious regressions.

Adding a new dashboard doesn't require adding a test, but if a block's query is load-bearing for a decision, it's cheap to add a `test_xxx` that asserts its result.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `ValueError: Unknown loader '...'` | Typo in `sources.yml`. | Set `loader: csv`. |
| `FileNotFoundError: CSV not found for 'authors'` | `data/raw/` is missing a file. | Restore the CSV. |
| `ParserException: syntax error at or near "window"` | Using a reserved word as a column alias. | Rename the alias (we use `series` instead of `window`). |
| A chart looks cropped / labels missing | Too much in too little width. | Add `wide: true` to the block, or shorten labels. |
| Table shows `NaT` or `645.0` | Old pandas rendering. | Already handled by the renderer; make sure you're on the current code. |
| `404` from local HTTP server | URL missing trailing slash. | `http://localhost:8765/revenue_overview/` (note the slash). |
