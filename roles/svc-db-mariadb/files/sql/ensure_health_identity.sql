SET SESSION sql_log_bin = 0;
SET @sql_create := "CREATE USER IF NOT EXISTS 'mysql'@'localhost' IDENTIFIED VIA unix_socket";
PREPARE stmt FROM @sql_create;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
