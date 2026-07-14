BEGIN;
UPDATE ir_cron SET active = true WHERE id IN (SELECT id FROM infinito_ir_cron_pause);
DROP TABLE IF EXISTS infinito_ir_cron_pause;
COMMIT;
