BEGIN;
CREATE TABLE IF NOT EXISTS infinito_ir_cron_pause AS SELECT id FROM ir_cron WHERE false;
INSERT INTO infinito_ir_cron_pause
  SELECT id FROM ir_cron
  WHERE active = true
    AND id NOT IN (SELECT id FROM infinito_ir_cron_pause);
UPDATE ir_cron SET active = false WHERE id IN (SELECT id FROM infinito_ir_cron_pause);
COMMIT;
