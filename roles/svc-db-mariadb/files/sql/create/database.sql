SET @sql := CONCAT(
  'CREATE DATABASE IF NOT EXISTS `', @db_name, '` ',
  'CHARACTER SET ', @charset, ' ',
  'COLLATE ', @collation, ';'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
