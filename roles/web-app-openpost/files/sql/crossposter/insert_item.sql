INSERT INTO crossposter.items (
    route, source_uri, source_url, target, network, state, payload
)
VALUES (
    %(route)s,
    %(source_uri)s,
    %(source_url)s,
    %(target)s,
    %(network)s,
    'pending',
    %(payload)s
)
ON CONFLICT (source_uri, target) DO NOTHING;
