CREATE OR REPLACE VIEW dim_book AS
WITH token_counts AS (
    SELECT book_id, COUNT(*) AS token_count
    FROM tokens
    GROUP BY book_id
),
sold AS (
    SELECT t.book_id,
           COUNT(DISTINCT CASE WHEN p.is_purchased THEN p.token_id END) AS tokens_sold,
           COALESCE(SUM(CASE WHEN p.is_purchased THEN p.price_cents END), 0) AS gmv_cents
    FROM fct_token_purchase p
    JOIN tokens t ON t.id = p.token_id
    GROUP BY t.book_id
)
SELECT
    b.id                                   AS id,
    b.author_id                            AS author_id,
    b.title                                AS title,
    COALESCE(tc.token_count, 0)            AS token_count,
    COALESCE(s.tokens_sold, 0)             AS tokens_sold,
    COALESCE(s.gmv_cents, 0)               AS gmv_cents
FROM books b
LEFT JOIN token_counts tc ON tc.book_id = b.id
LEFT JOIN sold         s  ON s.book_id  = b.id;
