# Dashboards — reference

Every dashboard, every block, every metric — with the plain-English definition and how it's calculated. The underlying SQL lives in the corresponding YAML file under `src/mini_analytics/dashboards/`; you can always go read the source query.

## Global conventions (applies to every dashboard)

- **Money** is stored in cents throughout. Dashboards divide by 100 for display. `$5.00` means `price_cents = 500`.
- **GMV** means "gross merchandise value" = sum of `price_cents` / 100 on **purchased** rows only (not prepared).
- **Purchased** specifically means `state = 'purchased'`, i.e. the sale went through. `initiated`, `prepared`, and `failed` rows are never counted toward GMV or volume.
- **Time-series blocks** filter `purchase_date IS NOT NULL`. A handful of purchased rows have a missing date and are excluded from date-based charts.
- **Every chart** has a **Download CSV** button; KPI and `note` blocks don't (nothing to export).
- **Build timestamp** appears in the footer of every page, so you always know how fresh the numbers are.

### Domain context that shapes every metric

The data describes a **digital book marketplace** where each token is one numbered digital copy of a book. There is no physical stock. Two facts about the domain affect how every metric should be read:

1. **Books have a supply type that isn't in the CSVs.** A book can be unlimited-supply (the author can keep issuing copies; no target) or limited-supply (a fixed maximum). Limited books can optionally allow resale. The data can't tell these apart, so per-book "purchase rate" is directional, not a retail sell-through figure. See [architecture.md](architecture.md#the-business-behind-the-data).
2. **A copy is reserved *before* the buyer completes payment.** A token that's "issued but not purchased" can mean four different things: the buyer abandoned checkout, the payment provider declined, the marketplace failed to record the payment, or it's an unlimited-supply book that simply hasn't sold this batch yet. The dashboards can't distinguish these.

The four dashboards most affected by this — Token Issuance & Purchases, Token Lifecycle, Conversion Funnel, Primary vs Resale — carry a visible `note` block at the top calling this out to business users. Look for the warm-ivory callouts.

The demo dataset covers January 2025 → June 2026 for sales, and the last 90 days of that for web analytics.

---

## 1. Revenue Overview

File: [`revenue_overview.yml`](../src/mini_analytics/dashboards/revenue_overview.yml) · Question it answers: *How's business?*

### KPIs (top of page)

| KPI | What it means | Calculation |
|---|---|---|
| **Total GMV** | Cumulative revenue from completed sales. | `SUM(price_cents) / 100` over `fct_token_purchase WHERE is_purchased`. |
| **Tokens purchased** | Total count of completed purchases. | `COUNT(*)` over `fct_token_purchase WHERE is_purchased`. |
| **Avg selling price** | Mean price across all completed purchases. | `AVG(price_cents) / 100` over `fct_token_purchase WHERE is_purchased`. |
| **Authors with sales** | Number of distinct authors who have sold at least one token. | `COUNT(DISTINCT author_id)` over purchased rows with non-null author. |

### Charts

| Block | What it shows | How it's calculated |
|---|---|---|
| **GMV by month** | Monthly revenue as a line chart. One point per month. | Group purchased rows by `date_trunc('month', purchase_date)`, sum `price_cents/100`. |
| **GMV by flow type (monthly)** | Same dollars as above, but stacked by whether the sale was primary, resale, or unknown. | Same as GMV by month, additionally grouped by `flow_type`. |
| **Daily purchases · 30-day rolling avg** | Smoothed momentum — average purchases per day over a trailing 30-day window. | Count purchases per day, then apply a 30-row trailing `AVG() OVER (ORDER BY day ROWS BETWEEN 29 PRECEDING AND CURRENT ROW)`. |

---

## 2. Author Leaderboard

File: [`author_leaderboard.yml`](../src/mini_analytics/dashboards/author_leaderboard.yml) · Question it answers: *Who's selling?*

### KPIs

| KPI | Meaning | Calculation |
|---|---|---|
| **Authors in catalog** | Total authors, whether they've sold or not. | `COUNT(*)` over `dim_author`. |
| **Authors with sales** | Authors with at least $0.01 in GMV. | `COUNT(*)` over `dim_author WHERE gmv_cents > 0`. |
| **Share with ≥1 sale** | Authors with sales ÷ total authors. | `COUNT(*) FILTER (WHERE gmv_cents > 0) / COUNT(*)`. |
| **Median GMV (selling authors)** | Half of selling authors earn below this. | 50th percentile of `gmv_cents/100` among selling authors (`quantile_cont(..., 0.5)`). |

### Charts

| Block | What it shows | How it's calculated |
|---|---|---|
| **Top 20 authors by GMV** | Horizontal bar — highest revenue at top. | `dim_author.gmv_cents` ordered DESC, LIMIT 20. Sorted ASC before rendering so highest ends up at the top of the horizontal bar. |
| **GMV concentration** | Histogram of per-author GMV across selling authors. Long right tail = a few whales dominate. | Buckets `dim_author.gmv_cents/100` for all authors where `gmv_cents > 0`. 30 bins. |
| **Top 50 authors — detail** | Table with book count, tokens issued/sold, GMV, avg price per token. | Straight select from `dim_author` ordered by GMV, LIMIT 50. Avg price = `gmv_cents / 100 / tokens_sold` (NULL when no sales). |

---

## 3. Token Lifecycle & Quality

File: [`token_lifecycle.yml`](../src/mini_analytics/dashboards/token_lifecycle.yml) · Question it answers: *How is the issue-to-purchase flow working, and what's the data-quality picture?*

### KPIs

| KPI | Meaning | Calculation |
|---|---|---|
| **Tokens issued** | Every token ever issued. | `COUNT(*)` over `tokens`. |
| **Tokens with any purchase row** | Distinct tokens that have at least one attempt (`initiated` / `prepared` / `purchased` / `failed`). | `COUNT(DISTINCT token_id)` over `token_purchases` (raw). |
| **Tokens purchased** | Distinct tokens that reached `state = 'purchased'`. | `COUNT(DISTINCT token_id)` over `fct_token_purchase WHERE is_purchased`. |
| **Purchase rate** | Purchased ÷ issued. | `tokens_purchased / tokens_issued`. |

### Charts

| Block | What it shows | How it's calculated |
|---|---|---|
| **Token lifecycle funnel** | Three-stage bar chart: Issued → Has purchase → Purchased. | Three UNION ALL'd counts: `tokens`, `DISTINCT token_id` from `token_purchases`, `DISTINCT token_id` from purchased rows. |
| **Purchase rate by book** | Histogram: for each book, what share of its issued tokens have been purchased? | `tokens_sold / token_count` from `dim_book`, bucketed into 25 bins. Books with `token_count = 0` excluded. |
| **Price distribution by flow type** | Histogram of prices, overlaid by primary/resale/unknown. | `price_cents/100` from purchased rows, colored by `flow_type`, 25 bins. |
| **Unknown-flow purchases — audit** | Table listing every purchased row where `flow_type = 'unknown'`. This should trend to zero over time. | All columns from `fct_token_purchase WHERE is_purchased AND flow_type = 'unknown'`. |

---

## 4. Primary vs Resale Mix

File: [`primary_vs_resale.yml`](../src/mini_analytics/dashboards/primary_vs_resale.yml) · Question it answers: *How important is the secondary market — and is it growing?*

### KPIs

| KPI | Meaning | Calculation |
|---|---|---|
| **Primary GMV** | Revenue from purchases directly from the author. | `SUM(price_cents)/100` where `flow_type = 'purchase_from_author'` and purchased. |
| **Resale GMV** | Revenue from resale transactions. | `SUM(price_cents)/100` where `flow_type = 'purchase_from_resale'` and purchased. |
| **Resale share of GMV** | What fraction of total GMV came from resale. | `resale_gmv / total_gmv`. |
| **Resale price premium** | Are resellers charging more than authors do? | `AVG(resale_price) / AVG(primary_price) − 1`. Negative means resale is *cheaper* than primary. |

### Charts

| Block | What it shows | How it's calculated |
|---|---|---|
| **Monthly GMV by flow type** | Stacked area: monthly dollars split by flow. | Group by `date_trunc('month', purchase_date)` and `flow_type`, sum price. |
| **Monthly purchase volume by flow type** | Stacked area: monthly count of purchases split by flow. Shows the *mix of transactions*, not just dollars. | Same grouping, `COUNT(*)` instead of SUM. |
| **Resale share of GMV — monthly** | Line: what % of each month's GMV came from resale. | Per month: resale GMV ÷ total GMV. |
| **Flow-type price & volume stats** | Summary table: purchases, GMV, avg / median / p90 price, per flow. | Standard aggregates + `quantile_cont(..., 0.5)` and `quantile_cont(..., 0.9)` grouped by flow. |
| **Books with the most resale activity** | Top 20 books ranked by resale GMV — useful for seeing which titles have a real secondary market. | Sum resale-only purchases per book, sort by resale GMV desc. |

---

## 5. Price Distribution

File: [`price_distribution.yml`](../src/mini_analytics/dashboards/price_distribution.yml) · Question it answers: *How are tokens priced? Is pricing drifting?*

### KPIs

| KPI | Meaning | Calculation |
|---|---|---|
| **Min price** | Cheapest completed sale. | `MIN(price_cents)/100` over purchased. |
| **Median price** | 50th percentile of completed sales. | `quantile_cont(price_cents/100, 0.5)`. |
| **Avg selling price** | Mean across completed sales. | `AVG(price_cents)/100`. |
| **Max price** | Priciest completed sale. | `MAX(price_cents)/100`. |

### Charts

| Block | What it shows | How it's calculated |
|---|---|---|
| **Price distribution (all purchased tokens)** | Histogram of every purchased price (40 bins). | `price_cents/100` over all purchased rows. |
| **Price by flow type (overlay)** | Same histogram, overlaid by `flow_type` (so you can see if resale skews higher/lower). | Same, color = flow_type, 30 bins. |
| **Price percentiles by flow type** | Table with p10 / p25 / p50 / p75 / p90 per flow. | `quantile_cont` at each percentile, grouped by `flow_type`. |
| **Avg & median price by month** | Line chart of both statistics per month. | Per month: `AVG(price_cents/100)` and `quantile_cont(price_cents/100, 0.5)`, unioned and coloured by statistic name. |
| **Avg selling price per author** | Histogram of each selling author's typical per-token price. | `dim_author.gmv_cents / tokens_sold / 100` for authors with `tokens_sold > 0`. 30 bins. |

---

## 6. Purchase Velocity

File: [`purchase_velocity.yml`](../src/mini_analytics/dashboards/purchase_velocity.yml) · Question it answers: *What's the momentum? When do people actually buy?*

### KPIs — anchored to the *most recent* `purchase_date` in the data

"Last 30 days" means "the 30 days ending on the latest date in the dataset", not literal calendar-today. This keeps the KPIs meaningful even if the data feed falls behind.

| KPI | Meaning | Calculation |
|---|---|---|
| **Last 30 days** | Purchases in the 30 days ending at the most recent date in the data. | `COUNT(*)` where `purchase_date` is in `(latest − 30d, latest]`. |
| **Previous 30 days** | Purchases in the 30 days before that window. | `COUNT(*)` where `purchase_date` is in `(latest − 60d, latest − 30d]`. |
| **30-day growth** | `last_30d / prev_30d − 1`. | Negative = slowing. |
| **Best single day** | Most purchases on any single `purchase_date`. | `MAX(daily_count)`. |

### Charts

| Block | What it shows | How it's calculated |
|---|---|---|
| **Daily purchases** | Raw per-day counts (full time range). | `COUNT(*)` per `purchase_date`. |
| **7-day vs 30-day rolling average** | Two lines on the same axis — short-term noise vs long-term trend. | Per day: 7-row trailing mean and 30-row trailing mean of daily count, unioned with a `series` label. |
| **Average purchases by weekday** | Bar: average daily purchases on each weekday (Mon…Sun). | Group daily counts by `extract('dow' FROM day)`, take `AVG`, order Mon first. |
| **Monthly purchases** | Bar: total purchases per calendar month. | `COUNT(*)` grouped by `date_trunc('month', purchase_date)`. |
| **Top 10 single days by purchases** | Table: date, purchases, GMV. | Per day: count + sum. Top 10 by count, then date desc. |

---

## 7. Per-Book Purchase Rate

File: [`per_book_purchases.yml`](../src/mini_analytics/dashboards/per_book_purchases.yml) · Question it answers: *For each book, what share of its issued tokens have actually been purchased?*

> **Not retail sell-through.** Each token is an copy issued *before* third-party checkout runs. A low per-book rate can reflect an unlimited-supply title still in distribution, a limited-supply title that simply hasn't run out yet, or a checkout problem. This dashboard is triage, not a performance grade. The dashboard carries a `note` callout with the full caveat.

### KPIs

| KPI | Meaning | Calculation |
|---|---|---|
| **Books with issued tokens** | Catalog size, counting only books that have at least one issued token. | `COUNT(*)` from `dim_book WHERE token_count > 0`. |
| **Books fully purchased** | Books where every issued token is now purchased. | Where `tokens_sold = token_count` (and count > 0). |
| **Books with zero purchases** | Books with issued tokens but none purchased. | Where `tokens_sold = 0` and `token_count > 0`. |
| **Avg purchase rate** | Average of `tokens_purchased / tokens_issued` across books with issued tokens. | `AVG(tokens_sold::double / token_count)`. |

### Charts

| Block | What it shows | How it's calculated |
|---|---|---|
| **Purchase rate by book** | Histogram: for each book, what share of issued tokens were purchased. Mass at 0% = books with no completed purchases yet; mass at 100% = books where every issue cleared. | `tokens_sold / token_count` for every book with issued tokens, 25 bins. |
| **Books per purchase-rate bucket** | Same data, bucketed into business-friendly ranges: 0%, 1–24%, 25–49%, 50–74%, 75–99%, 100%. | CASE WHEN on the ratio, then COUNT per bucket. |
| **Fully-purchased books, by issue size** | Table: books where every issued token has been purchased, ordered by issue size. | `dim_book WHERE tokens_sold = token_count AND token_count > 0` ordered by `token_count DESC`. |
| **Books with issued tokens but no purchases (largest first)** | Table: books with the most issued tokens and zero completed purchases. | `dim_book WHERE tokens_sold = 0 AND token_count > 0` ordered by `token_count DESC`. |

---

## 8. Conversion Funnel (attempts → purchased)

File: [`conversion_funnel.yml`](../src/mini_analytics/dashboards/conversion_funnel.yml) · Question it answers: *Of every token someone tried to buy, how many went through — and where do the rest drop off?*

> **Data note — `state` has four values.** In the `token_purchases` CSV, `state` can be `initiated`, `prepared`, `purchased`, or `failed`. Only `purchased` counts as a sale. A token can have rows in more than one state over time (someone initiates, prepares, and buys). This dashboard treats **any** row as an "attempt".

### KPIs

| KPI | Meaning | Calculation |
|---|---|---|
| **Tokens attempted** | Distinct tokens with at least one row in any state. | `COUNT(DISTINCT token_id)` over `token_purchases`. |
| **Tokens purchased** | Distinct tokens that reached `purchased`. | Same, filtered to `state = 'purchased'`. |
| **Attempts → purchased** | Conversion rate. | `purchased ÷ attempted`. |
| **Attempts that never sold** | Lost tokens — tried but never completed. | `attempted − purchased`. |

### Charts

| Block | What it shows | How it's calculated |
|---|---|---|
| **Monthly conversion rate** | Per month of first-seen token (`MIN(created_at)` of any row), what share ultimately purchased. | Group tokens by month of first touch, divide purchased count by total count. |
| **Furthest stage reached — non-purchased attempts** | For the tokens that didn't sell, how far through the funnel did they get? `initiated` → `prepared` → `failed`. Shows where leaks are. | Per token: `MAX(state_ordinal)` where ordinal is 1=initiated, 2=prepared, 3=failed, 4=purchased. Chart filters out 4. |
| **Conversion rate by flow type** | Does primary convert better than resale? | Per token: converted = any `purchased` row exists; flow_type = the purchased row's flow (or any row's, if no purchase). Rate = `converted / total` per flow. |
| **Conversion rate by price band** | Does cheaper convert better? Bands: `$0–1`, `$1–3`, `$3–5`, `$5–10`, `$10+`. | Per token: price = purchased row's price if exists, else average of the attempts. Bucket, then rate. |
| **Worst-converting books (≥3 attempts)** | Books with ≥3 attempts and the lowest conversion — where is checkout UX or pricing failing? | Join per-token attempts up to books, aggregate, filter `HAVING COUNT(*) >= 3`, sort ascending by conversion. |

> **What we can't compute from this schema:** actual "time to purchase". The `created_at` column is the row's *write* timestamp and can post-date `purchase_date` by days (ETL lag, not UX). Of 487 purchased rows with both timestamps present, 443 have `created_at > purchase_date`. Don't use their difference as a UX signal.

---

## 9. Token Issuance & Purchases

File: [`token_issuance.yml`](../src/mini_analytics/dashboards/token_issuance.yml) · Question it answers: *For each book, how does token issuance compare to completed purchases, and where are the gaps?*

> **Not retail inventory.** Tokens are issued before the payment provider checkout runs. A "gap" between issued and purchased can reflect abandoned checkouts, the payment provider declines, state-transition bugs on our side, or an unlimited-supply book with more issued tokens than the market has absorbed yet. The dashboard carries a `note` callout explaining the four possible reasons.

### KPIs

| KPI | Meaning | Calculation |
|---|---|---|
| **Tokens issued** | Total issuance across the catalog. | `SUM(token_count)` over `dim_book`. |
| **Tokens purchased** | Issued tokens that reached `state = 'purchased'` (cleared the payment provider). | `SUM(tokens_sold)` over `dim_book`. |
| **Overall purchase rate** | `Σ purchased ÷ Σ issued`. | SUM/SUM, not avg of ratios. |
| **Median purchase rate (per book)** | Middle book's `tokens_sold / token_count` across books with issued tokens. | `quantile_cont(ratio, 0.5)`. |

### Charts

| Block | What it shows | How it's calculated |
|---|---|---|
| **Every book — issued vs purchased** (scatter) | One dot per book. X = `token_count` (issued), Y = `tokens_sold` (purchased). Dots on the diagonal had every issue purchased; dots hugging the X-axis have mostly unpurchased issued tokens. Marker size scales with GMV; colour bins by purchase-rate bucket. | `dim_book WHERE token_count > 0`, with a derived `purchase_bucket` CASE and `marker_size = gmv_cents + 100` so zero-GMV books still render. |
| **Average purchase rate by issuance size** | Does issuing more tokens per book reduce the share purchased? Bucketed into `1`, `2–5`, `6–10`, `11–50`, `51+`. | `AVG(tokens_sold / token_count)` per issue-size bucket. |
| **Books with the largest issuance–purchase gap** | Books with the biggest `token_count − tokens_sold`. Triage list, not a verdict. | Straight select with `ORDER BY unpurchased DESC`. |
| **Books where nearly all issued tokens have been purchased (≥90%)** | For limited-supply books these are candidates for another issue; for unlimited-supply books the author can just keep issuing. | `WHERE tokens_sold::DOUBLE / token_count >= 0.9`. |

---

## 10. Catalog Concentration & Pareto

File: [`catalog_concentration.yml`](../src/mini_analytics/dashboards/catalog_concentration.yml) · Question it answers: *How fragile is revenue? What happens if our top author leaves?*

### KPIs

| KPI | Meaning | Calculation |
|---|---|---|
| **Top-1 author share** | Highest-grossing author ÷ total GMV. | `MAX(gmv_cents) / SUM(gmv_cents)` over `dim_author`. |
| **Top-10 authors share** | Top-10 combined. | Rank authors by GMV, sum top 10, divide by total. |
| **Top-10 books share** | Same for books. | Same logic over `dim_book`. |
| **Author GMV Gini** | 0 = perfectly equal (all authors earn the same), 1 = one author captures everything. | `(2 · Σ(i · x_i) / (n · Σx_i)) − (n + 1) / n` where `x_i` is GMV sorted ascending and `i` is the 1-based index. |

### Charts

| Block | What it shows | How it's calculated |
|---|---|---|
| **Lorenz curve — authors** | X = cumulative share of authors (sorted low-to-high GMV). Y = cumulative share of GMV. Diagonal = equality; more bowed = more concentrated. | Sort authors by GMV asc, compute running cumulative GMV share. |
| **Top-10 authors / Top-10 books — individual share** | Horizontal bars of each entity's share of total GMV. | `gmv_cents / SUM(gmv_cents)` for the top 10, rendered as percents. |
| **Top-10 authors' share of GMV — monthly** | For each month, what share of *that month's* GMV came from that month's top-10 authors? Rising = revenue is concentrating further. | Per month, rank authors by monthly GMV and sum top-10. |
| **"If this author left… (top 5)"** | Counterfactual table: each of top-5 authors, their GMV, remaining GMV without them, and the percent of total you'd lose. | Straightforward subtraction from the total. |

---

## 11. Author Segmentation & Activity Tiers

File: [`author_segmentation.yml`](../src/mini_analytics/dashboards/author_segmentation.yml) · Question it answers: *Who are our whales, regulars, one-hitters, and dormant authors?*

### Tier rules (applied in this order)

| Tier | Definition |
|---|---|
| **Never-sold** | `gmv_cents = 0`. |
| **Dormant** | Sold something ever, but last sale is > 60 days before the dataset's latest `purchase_date`. |
| **Whale** | Lifetime GMV ≥ $100 (`gmv_cents ≥ 10000`), and sold in the last 60 days. |
| **Regular** | Lifetime GMV $10–$100, and sold in the last 60 days. |
| **One-hitter** | Lifetime GMV < $10 (but > 0), and sold in the last 60 days. |

"Last 60 days" is anchored to `MAX(purchase_date)` in the data, not calendar-today.

### KPIs

One KPI per tier (count of authors). Shown as a five-tile strip: Whales, Regulars, One-hitters, Dormant, Never-sold.

### Charts

| Block | What it shows | How it's calculated |
|---|---|---|
| **Authors per active tier** | Bar chart of the four active tiers (excludes Never-sold so the rest are readable). | `GROUP BY tier` with the CASE logic above. |
| **Share of GMV by tier — monthly** | Stacked area: each month's GMV split by author tier. Tier uses *lifetime* GMV so whales stay whales across the whole chart. | Per month: sum `price_cents` grouped by the author's lifetime-based tier. |
| **Rising stars** (last 30d > prior 30d) | Authors whose last-30d GMV beat their prior-30d GMV (both > 0). | Per author, two windowed sums anchored to latest date; filter `last30 > prev30`. |
| **Falling stars** (last 30d < prior 30d) | Mirror — authors who sold recently but slowed. | Same, filter `last30 < prev30`. |
| **Days since last sale** | Histogram of `date_diff('day', last_sale, latest)` across authors who've ever sold. | Bimodal = churn problem; tight-left = healthy. |
