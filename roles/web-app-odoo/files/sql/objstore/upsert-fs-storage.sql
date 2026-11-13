-- Register the object store as the default `fs.storage` for attachments.
-- Caller passes %(code)s, %(options)s and %(force_db_rules)s plus the fields
-- of the attachment_storage form of meta/forms.yml as named_args.
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
	%(storage_name)s,
	%(code)s,
	's3',
	%(options)s,
	%(directory_path)s,
	%(use_as_default_for_attachments)s,
	%(force_db_rules)s,
	True,
	True,
	False,
	'marker_file',
	%(is_cacheable)s,
	%(storage_base_url)s,
	%(is_directory_path_in_url)s,
	30,
	NOW(),
	NOW()
)
ON CONFLICT (code) DO UPDATE SET
	name = %(storage_name)s,
	protocol = 's3',
	options = %(options)s,
	directory_path = %(directory_path)s,
	use_as_default_for_attachments = %(use_as_default_for_attachments)s,
	force_db_for_default_attachment_rules = %(force_db_rules)s,
	check_connection_method = 'marker_file',
	is_cacheable = %(is_cacheable)s,
	base_url = %(storage_base_url)s,
	is_directory_path_in_url = %(is_directory_path_in_url)s,
	s3_signed_url_expiration = 30,
	write_date = NOW();
