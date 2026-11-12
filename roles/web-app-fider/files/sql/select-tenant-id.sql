-- Returns one row: the id of the tenant the role designs, 0 while no tenant exists.
SELECT COALESCE(MIN(id), 0) FROM tenants;
