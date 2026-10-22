SELECT column_name
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'application'
  AND column_name IN ('nodeVersion', 'nodeABIVersion')
  AND column_default IS NULL;
