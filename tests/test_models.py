def test_model_views_exist(warehouse):
    views = {name for name, _ in warehouse.views()}
    assert {"dim_author", "dim_book", "fct_token_purchase"}.issubset(views)


def test_fct_token_purchase_rowcount_matches_source(warehouse):
    src = warehouse.con.execute("SELECT COUNT(*) FROM token_purchases").fetchone()[0]
    model = warehouse.con.execute("SELECT COUNT(*) FROM fct_token_purchase").fetchone()[0]
    assert src == model


def test_fct_flow_type_is_never_null(warehouse):
    nulls = warehouse.con.execute(
        "SELECT COUNT(*) FROM fct_token_purchase WHERE flow_type IS NULL"
    ).fetchone()[0]
    assert nulls == 0


def test_dim_author_covers_all_authors(warehouse):
    authors = warehouse.con.execute("SELECT COUNT(*) FROM authors").fetchone()[0]
    dim = warehouse.con.execute("SELECT COUNT(*) FROM dim_author").fetchone()[0]
    assert authors == dim


def test_dim_author_preserves_null_names(warehouse):
    """A null-name author must survive the join into dim_author (no WHERE-drops)."""
    null_authors = warehouse.con.execute(
        "SELECT COUNT(*) FROM authors WHERE name IS NULL"
    ).fetchone()[0]
    null_dim = warehouse.con.execute(
        "SELECT COUNT(*) FROM dim_author WHERE name IS NULL"
    ).fetchone()[0]
    assert null_authors == null_dim


def test_dim_book_tokens_sold_counts_purchased_only(warehouse):
    """dim_book.tokens_sold must count only tokens that reached 'purchased' state,
    not tokens with any activity (initiated/prepared/failed). Regression guard."""
    dim_total = warehouse.con.execute("SELECT SUM(tokens_sold) FROM dim_book").fetchone()[0]
    fct_purchased = warehouse.con.execute(
        "SELECT COUNT(DISTINCT token_id) FROM fct_token_purchase WHERE is_purchased"
    ).fetchone()[0]
    assert dim_total == fct_purchased


def test_dim_book_gmv_matches_fct(warehouse):
    """Sum of per-book GMV in dim_book equals sum of purchased price_cents in fct."""
    dim_total = warehouse.con.execute("SELECT SUM(gmv_cents) FROM dim_book").fetchone()[0]
    fct_total = warehouse.con.execute(
        "SELECT SUM(price_cents) FROM fct_token_purchase WHERE is_purchased"
    ).fetchone()[0]
    assert dim_total == fct_total


def test_dim_author_gmv_matches_fct_for_attributed_books(warehouse):
    """Author GMV totals match fct GMV restricted to purchases with a known author."""
    dim_total = warehouse.con.execute("SELECT SUM(gmv_cents) FROM dim_author").fetchone()[0]
    fct_total = warehouse.con.execute(
        "SELECT SUM(price_cents) FROM fct_token_purchase "
        "WHERE is_purchased AND author_id IS NOT NULL"
    ).fetchone()[0]
    assert dim_total == fct_total
