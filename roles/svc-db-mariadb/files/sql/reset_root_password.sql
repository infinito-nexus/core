FLUSH PRIVILEGES;

SET @sql_local := CONCAT(
  "ALTER USER IF EXISTS 'root'@'localhost' IDENTIFIED BY ", QUOTE(@root_pwd), ";"
);
PREPARE stmt FROM @sql_local;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @sql_any := CONCAT(
  "ALTER USER IF EXISTS 'root'@'%' IDENTIFIED BY ", QUOTE(@root_pwd), ";"
);
PREPARE stmt FROM @sql_any;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

FLUSH PRIVILEGES;
