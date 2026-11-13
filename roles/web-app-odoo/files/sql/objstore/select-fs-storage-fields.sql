-- Param %(code)s: code of the fs_storage row the attachment_storage form of meta/forms.yml manages.
-- Returns one row: the fields of that form mapped to the values the row holds, as JSON text; an empty object before the row exists.
SELECT COALESCE(
	(
		SELECT json_build_object(
			'storage_name', name,
			'directory_path', directory_path,
			'is_cacheable', is_cacheable,
			'use_as_default_for_attachments', use_as_default_for_attachments,
			'storage_base_url', base_url,
			'is_directory_path_in_url', is_directory_path_in_url
		)
		FROM fs_storage
		WHERE code = %(code)s
		LIMIT 1
	),
	'{}'::json
)::text;
