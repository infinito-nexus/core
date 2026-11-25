CREATE TABLE IF NOT EXISTS crossposter.items (
    id bigserial PRIMARY KEY,
    route text NOT NULL,
    source_uri text NOT NULL,
    source_url text NOT NULL,
    target text NOT NULL,
    network text NOT NULL,
    state text NOT NULL,
    payload jsonb NOT NULL,
    publication_id text NOT NULL DEFAULT '',
    attempts integer NOT NULL DEFAULT 0,
    resends integer NOT NULL DEFAULT 0,
    next_attempt_at timestamptz NOT NULL DEFAULT now(),
    last_error text NOT NULL DEFAULT '',
    notified_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_uri, target)
);
