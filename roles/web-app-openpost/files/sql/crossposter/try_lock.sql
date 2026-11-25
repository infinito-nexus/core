SELECT pg_try_advisory_lock(%(lock_id)s) AS held;
