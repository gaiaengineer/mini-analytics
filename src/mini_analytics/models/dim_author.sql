CREATE OR REPLACE VIEW dim_author AS
WITH by_author AS (
    SELECT
        author_id,
        SUM(token_count)    AS token_count,
        SUM(tokens_sold)    AS tokens_sold,
        SUM(gmv_cents)      AS gmv_cents,
        COUNT(*)            AS book_count
    FROM dim_book
    WHERE author_id IS NOT NULL
    GROUP BY author_id
)
SELECT
    a.id                                  AS id,
    a.name                                AS name,
    COALESCE(ba.book_count, 0)            AS book_count,
    COALESCE(ba.token_count, 0)           AS token_count,
    COALESCE(ba.tokens_sold, 0)           AS tokens_sold,
    COALESCE(ba.gmv_cents, 0)             AS gmv_cents
FROM authors a
LEFT JOIN by_author ba ON ba.author_id = a.id;
