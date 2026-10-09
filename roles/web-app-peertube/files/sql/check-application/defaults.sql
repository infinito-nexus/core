SELECT a.attname
FROM pg_catalog.pg_attribute a
LEFT JOIN pg_catalog.pg_attrdef d
  ON d.adrelid = a.attrelid AND d.adnum = a.attnum
WHERE a.attrelid = 'public.application'::regclass
  AND a.attname IN ('nodeVersion', 'nodeABIVersion')
  AND d.adbin IS NULL;
