"""Generate a fictional dataset for Mini Analytics.

    python3 scripts/make_demo_data.py [--out data/raw] [--seed 7]

Writes the same five tables the loader reads (authors, books, tokens,
token_purchases, ga_events) with the same columns and types as the real
exports. Every name, title and number is invented. The generator is seeded,
so the same seed always produces the same files.

Standard library only, so it runs before the project is installed.
"""

import argparse
import csv
import gzip
import math
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

SALES_START = date(2025, 1, 1)
SALES_END = date(2026, 6, 30)
GA_DAYS = 90                         # website events cover the last 90 days of sales
SITE = "https://bookmarket.example"

FIRST = ("Ada Bea Cal Dara Eli Faye Gil Hana Ines Jun Kai Lena Milo Nora Omar Pia Quinn Rosa "
         "Sami Tess Uma Vik Wren Yara Zane Aiko Bruno Chloe Dev Elsa Femi Greta Hugo Isla "
         "Jonah Kira Luca Maya Niko Olive Paz Remy Sora Theo Vera Wes Ximena Yuki").split()
LAST = ("Abara Bell Castell Dunmore Ekwueme Farrow Galloway Hartley Ito Jansen Kowal Lindqvist "
        "Marlow Novak Okafor Pereira Quaid Rasmussen Sato Thorne Underhill Vance Whitlock "
        "Yilmaz Zeller Ashby Brennan Calloway Delacroix Ferrante Grayson Holloway Ivanova "
        "Kerrigan Lockwood Moreau Nakamura Oduya Pemberton Rhee Silvana Tamura Valdez").split()
ADJ = ("Silent Salt Paper Hollow Burning Glass Midnight Copper Last Lost Distant Winter "
       "Crimson Quiet Northern Broken Golden Wild Secret Borrowed Velvet Iron Drowned "
       "Little Ninth Painted Sleeping Sunken Tender Restless").split()
NOUN = ("Orchard Harbour Lantern Atlas Garden Kingdom Ledger Tide Archive Choir Meridian "
        "Lighthouse Season Orchid Engine Compass Island Daughter River Hunger Alphabet "
        "Embassy Frontier Observatory Bargain Carousel Inheritance Monsoon Weather").split()
SERIES = ("Chronicles Saga Trilogy Files Mysteries Cycle").split()

PRICES = [299, 399, 499, 500, 699, 799, 999, 1299, 1499, 1999]

COUNTRIES = [  # (country, city, weight)
    ("United States", "New York", 18), ("United States", "Austin", 8), ("United States", "Seattle", 6),
    ("United Kingdom", "London", 10), ("Canada", "Toronto", 7), ("Canada", "Vancouver", 4),
    ("Germany", "Berlin", 6), ("France", "Paris", 5), ("Japan", "Tokyo", 6), ("Singapore", "Singapore", 4),
    ("South Korea", "Seoul", 4), ("Australia", "Sydney", 5), ("India", "Bengaluru", 5),
    ("Brazil", "São Paulo", 4), ("Netherlands", "Amsterdam", 3), ("Spain", "Madrid", 3),
]
DEVICES = [("desktop", "Windows", 27), ("desktop", "Macintosh", 24), ("mobile", "iOS", 23),
           ("mobile", "Android", 20), ("desktop", "Linux", 2), ("tablet", "iOS", 2), ("tablet", "Android", 2)]
TRAFFIC = [("(direct)", "(none)", "(direct)", 34), ("google", "organic", "(organic)", 18),
           ("facebook", "cpc", "spring_launch", 12), ("instagram", "paid", "author_stories", 8),
           ("newsletter", "email", "weekly_picks", 9), ("reddit.com", "referral", "(referral)", 6),
           ("tiktok", "social", "booktok", 7), ("bing", "organic", "(organic)", 2),
           ("linkedin.com", "referral", "(referral)", 2), ("goodreads.com", "referral", "(referral)", 2)]
STATIC_PAGES = [("/", "Explore | Bookmarket"), ("/new", "New releases | Bookmarket"),
                ("/authors", "For authors | Bookmarket"), ("/publish", "Publish your book | Bookmarket"),
                ("/pricing", "Pricing | Bookmarket"), ("/search", "Search | Bookmarket")]


def weighted(rng, items):
    return rng.choices(items, weights=[i[-1] for i in items])[0]


def daterange(start, end):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def make_catalog(rng):
    authors, books, tokens = [], [], []
    names = set()
    for aid in range(1, 241):
        while True:
            name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
            if name not in names:
                names.add(name)
                break
        # a few accounts never filled in a display name, as in real exports
        authors.append({"id": aid, "name": "" if rng.random() < 0.03 else name})

    # Pareto-ish productivity: most authors have one or two books, a few have many
    titles = set()
    bid = tid = 0
    for a in authors:
        if rng.random() < 0.12:
            continue                                   # signed up, never published
        n_books = min(1 + int(rng.paretovariate(1.6)) - 1 + (rng.random() < 0.4), 14)
        series = None
        if n_books >= 4:
            while series is None or series in titles:
                series = f"The {rng.choice(NOUN)} {rng.choice(SERIES)}"
            titles.add(series)
        for k in range(n_books):
            while True:
                title = (f"{series}, Book {k + 1}" if series and k < 5
                         else f"The {rng.choice(ADJ)} {rng.choice(NOUN)}")
                if title not in titles:
                    titles.add(title)
                    break
            bid += 1
            # copies issued per book: many tiny limited runs, some large pools
            appeal = rng.paretovariate(1.2)
            pool = max(1, int(rng.lognormvariate(1.6, 1.25) * (1 + appeal)))
            if rng.random() < 0.08:
                pool += rng.randint(150, 450)
            books.append({"id": bid, "author_id": a["id"], "title": title,
                          "_pool": pool, "_price": rng.choice(PRICES),
                          "_appeal": appeal,
                          "_launch": SALES_START + timedelta(days=int(rng.triangular(-60, 540, 400))),
                          "_resale": rng.random() < 0.2})
            for _ in range(pool):
                tid += 1
                tokens.append({"id": tid, "book_id": bid})
    return authors, books, tokens


def sale_time(rng, day):
    # evenings and weekends sell more
    hour = int(rng.triangular(0, 24, 20)) % 24
    return datetime(day.year, day.month, day.day, hour, rng.randint(0, 59), rng.randint(0, 59),
                    rng.randint(0, 999_999))


def make_purchases(rng, books, tokens):
    by_book = {}
    for t in tokens:
        by_book.setdefault(t["book_id"], []).append(t["id"])
    unsold = {b: list(ids) for b, ids in by_book.items()}
    owned = {b: [] for b in by_book}
    rows, pid = [], 0
    total_days = (SALES_END - SALES_START).days
    for day in daterange(SALES_START, SALES_END):
        progress = (day - SALES_START).days / total_days
        weekend = day.weekday() >= 5
        # growth curve, weekend lift, and a few promo spikes
        rate = 10 + 40 * progress ** 1.3
        rate *= 1.25 if weekend else 1.0
        if day.month in (11, 12) and day.day in (24, 25, 26, 27, 28, 29):
            rate *= 2.2
        live = [b for b in books if b["_launch"] <= day]
        if not live:
            continue
        weights = [b["_appeal"] / (1 + (day - b["_launch"]).days / 365) for b in live]
        for _ in range(max(0, int(rng.gauss(rate, math.sqrt(rate))))):
            b = rng.choices(live, weights=weights)[0]
            resale = b["_resale"] and owned[b["id"]] and rng.random() < 0.06
            if resale:
                token_id, flow = rng.choice(owned[b["id"]]), "purchase_from_resale"
                price = int(b["_price"] * rng.uniform(1.1, 2.4))
            elif unsold[b["id"]]:
                token_id, flow = rng.choice(unsold[b["id"]]), "purchase_from_author"
                price = b["_price"] + (100 if progress > 0.6 and rng.random() < 0.3 else 0)
            else:
                continue                               # sold out, no resale
            state = rng.choices(["purchased", "initiated", "prepared", "failed"],
                                weights=[64, 20, 10, 6])[0]
            if rng.random() < 0.001:
                flow = None                             # occasional missing flow_type
            created = sale_time(rng, day)
            pid += 1
            rows.append({"id": pid, "token_id": token_id, "state": state, "price_cents": price,
                         "flow_type": flow or "",
                         "purchase_date": created.date().isoformat() if state == "purchased" and rng.random() < 0.97 else "",
                         "created_at": created.isoformat(sep=" ")})
            if state == "purchased" and not resale:
                unsold[b["id"]].remove(token_id)
                owned[b["id"]].append(token_id)
    return rows


def make_ga_events(rng, books, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.csv.gz"):
        old.unlink()
    cols = ["event_date", "event_timestamp", "event_name", "user_pseudo_id", "session_id",
            "page_location", "page_title", "device_category", "device_os", "country", "city",
            "traffic_source", "traffic_medium", "traffic_campaign"]
    returning = []                                      # (user_id, device, geo)
    start = SALES_END - timedelta(days=GA_DAYS - 1)
    for i, day in enumerate(daterange(start, SALES_END)):
        sessions = 260 + 3 * i + (90 if day.weekday() >= 5 else 0)
        if day.day in (1, 2) or (day.month == 5 and day.day in (14, 15)):
            sessions = int(sessions * 1.8)              # newsletter / launch days
        rows = []
        for _ in range(int(rng.gauss(sessions, sessions ** 0.5))):
            if returning and rng.random() < 0.38:
                uid, dev, geo = rng.choice(returning)
                new = False
            else:
                uid = f"{rng.randint(10**9, 2 * 10**9)}.{rng.randint(10**9, 2 * 10**9)}"
                dev, geo = weighted(rng, DEVICES), weighted(rng, COUNTRIES)
                returning.append((uid, dev, geo))
                new = True
            src = weighted(rng, TRAFFIC)
            t = datetime(day.year, day.month, day.day, tzinfo=timezone.utc) + timedelta(
                seconds=int(rng.triangular(0, 86_399, 72_000)))
            sid = int(t.timestamp())
            n_pages = max(1, int(rng.expovariate(1 / 3.2)))

            def emit(name, path, title):
                nonlocal t
                rows.append([day.isoformat(), t.isoformat(sep=" "), name, uid, sid, SITE + path, title,
                             dev[0], dev[1], geo[0], geo[1], src[0], src[1], src[2]])
                t += timedelta(seconds=rng.randint(4, 90))

            first = weighted(rng, [(p, 3) for p in STATIC_PAGES[:3]] + [(None, 4)])
            pages = []
            for k in range(n_pages):
                if k == 0 and first[0]:
                    pages.append(first[0])
                elif rng.random() < 0.65:
                    b = rng.choices(books, weights=[x["_appeal"] for x in books])[0]
                    pages.append((f"/books/{b['id']}", f"{b['title']} | Bookmarket"))
                else:
                    pages.append(rng.choice(STATIC_PAGES))
            emit("session_start", *pages[0])
            if new:
                emit("first_visit", *pages[0])
            for path, title in pages:
                emit("page_view", path, title)
                if rng.random() < 0.35:
                    emit("scroll", path, title)
                if rng.random() < 0.3:
                    emit("user_engagement", path, title)
                if rng.random() < 0.08:
                    emit("click", path, title)
            if any(p[0] == "/publish" for p in pages) and rng.random() < 0.5:
                emit("form_start", "/publish", "Publish your book | Bookmarket")
                if rng.random() < 0.15:
                    emit("form_submit", "/publish", "Publish your book | Bookmarket")
            if any(p[0] == "/search" for p in pages):
                emit("view_search_results", "/search", "Search | Bookmarket")
        path = out_dir / f"{day:%Y%m%d}.csv.gz"
        with gzip.open(path, "wt", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(cols)
            w.writerows(rows)


def write_csv(path, rows, cols):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent.parent / "data" / "raw")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    args.out.mkdir(parents=True, exist_ok=True)

    authors, books, tokens = make_catalog(rng)
    purchases = make_purchases(rng, books, tokens)
    write_csv(args.out / "authors.csv", authors, ["id", "name"])
    write_csv(args.out / "books.csv", books, ["id", "author_id", "title"])
    write_csv(args.out / "tokens.csv", tokens, ["id", "book_id"])
    write_csv(args.out / "token_purchases.csv", purchases,
              ["id", "token_id", "state", "price_cents", "flow_type", "purchase_date", "created_at"])
    make_ga_events(rng, books, args.out / "ga_events")
    print(f"wrote {len(authors)} authors, {len(books)} books, {len(tokens)} tokens, "
          f"{len(purchases)} purchase rows and {GA_DAYS} days of web events to {args.out}")


if __name__ == "__main__":
    main()
