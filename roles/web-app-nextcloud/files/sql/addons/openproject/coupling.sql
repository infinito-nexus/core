SELECT
    storage.id,
    storage.created_at,
    storage.name,
    storage.host,
    application.uid,
    application.updated_at,
    client.client_id,
    client.updated_at
FROM storages AS storage
LEFT JOIN oauth_applications AS application
    ON
        storage.id = application.integration_id
        AND application.integration_type LIKE 'Storages::%'
LEFT JOIN oauth_clients AS client
    ON
        storage.id = client.integration_id
        AND client.integration_type LIKE 'Storages::%'
WHERE
    storage.provider_type = 'Storages::NextcloudStorage'
    AND (rtrim(storage.host, '/') = %(host)s OR storage.name = %(name)s)
ORDER BY storage.id, application.id, client.id;
