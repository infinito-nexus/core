INSERT INTO settings ("key", "value", "loadOnStartup")
VALUES ('features.ldap', %(ldap_config)s, TRUE)
ON CONFLICT ("key") DO UPDATE SET
  "value"          = EXCLUDED."value",
  "loadOnStartup"  = TRUE;
