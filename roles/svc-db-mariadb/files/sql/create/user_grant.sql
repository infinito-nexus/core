SET @sql_create := CONCAT(
  "CREATE USER IF NOT EXISTS '", @db_user, "'@'%';"
);
PREPARE stmt FROM @sql_create;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @sql_alter := CONCAT(
  "ALTER USER '", @db_user, "'@'%' IDENTIFIED BY ", QUOTE(@db_pwd), ";"
);
PREPARE stmt FROM @sql_alter;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @sql_grant := CONCAT(
  "GRANT ALL PRIVILEGES ON `", @db_name, "`.* TO '", @db_user, "'@'%';"
);
PREPARE stmt FROM @sql_grant;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

FLUSH PRIVILEGES;
