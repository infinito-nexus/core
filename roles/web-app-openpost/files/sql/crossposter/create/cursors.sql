CREATE TABLE IF NOT EXISTS crossposter.cursors (
    route text PRIMARY KEY,
    cursor text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
