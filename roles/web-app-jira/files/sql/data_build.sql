SELECT ps.propertyvalue
FROM propertyentry AS pe
INNER JOIN propertystring AS ps ON pe.id = ps.id
WHERE pe.property_key = 'jira.version.patched';
