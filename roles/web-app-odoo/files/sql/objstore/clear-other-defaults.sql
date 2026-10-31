-- Release the attachment default held by a storage of another engine.
-- Caller passes %(code)s as named_args.
UPDATE fs_storage SET
	use_as_default_for_attachments = False,
	force_db_for_default_attachment_rules = NULL,
	write_date = NOW()
WHERE code <> %(code)s
  AND use_as_default_for_attachments;
