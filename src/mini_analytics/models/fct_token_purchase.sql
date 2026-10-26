CREATE OR REPLACE VIEW fct_token_purchase AS
SELECT
    p.id                                              AS purchase_id,
    p.token_id                                        AS token_id,
    t.book_id                                         AS book_id,
    b.author_id                                       AS author_id,
    b.title                                           AS book_title,
    a.name                                            AS author_name,
    p.state                                           AS state,
    (p.state = 'purchased')::BOOLEAN                  AS is_purchased,
    CAST(p.price_cents AS INTEGER)                    AS price_cents,
    COALESCE(p.flow_type, 'unknown')                  AS flow_type,
    CAST(p.purchase_date AS DATE)                     AS purchase_date,
    CAST(p.created_at AS TIMESTAMP)                   AS created_at
FROM token_purchases p
LEFT JOIN tokens  t ON t.id = p.token_id
LEFT JOIN books   b ON b.id = t.book_id
LEFT JOIN authors a ON a.id = b.author_id;
