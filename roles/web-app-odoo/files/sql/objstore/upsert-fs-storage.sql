-- Register the object store as the default `fs.storage` for attachments.
-- Caller passes %(code)s, %(name)s, %(options)s, %(bucket)s and
-- %(force_db_rules)s as named_args.
INSERT INTO fs_storage (
	name,
	code,
	protocol,
	options,
	directory_path,
	use_as_default_for_attachments,
	force_db_for_default_attachment_rules,
	autovacuum_gc,
	optimizes_directory_path,
	eval_options_from_env,
	check_connection_method,
	is_cacheable,
	base_url,
	is_directory_path_in_url,
	s3_signed_url_expiration,
	create_date,
	write_date
) VALUES (
	%(name)s,
	%(code)s,
	's3',
	%(options)s,
	%(bucket)s,
	True,
	%(force_db_rules)s,
	True,
	True,
	False,
	'marker_file',
	True,
	'',
	False,
	30,
	NOW(),
	NOW()
)
ON CONFLICT (code) DO UPDATE SET
	name = %(name)s,
	protocol = 's3',
	options = %(options)s,
	directory_path = %(bucket)s,
	use_as_default_for_attachments = True,
	force_db_for_default_attachment_rules = %(force_db_rules)s,
	check_connection_method = 'marker_file',
	is_cacheable = True,
	base_url = '',
	is_directory_path_in_url = False,
	s3_signed_url_expiration = 30,
	write_date = NOW();
