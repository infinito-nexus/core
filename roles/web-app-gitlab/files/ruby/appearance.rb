# nocheck: mirrored-unit-test - runs in `rails runner` against the Appearance model of the GitLab image; the model is not loadable anywhere else
# Param: uploads  {field: [extension, base64 content]} prepended on stdin; a field the role owns and that is missing here is removed.
# Param: GITLAB_DESIGN_TITLE  title, PWA name and short name; empty clears the ones the role set.
require 'base64'
require 'digest'
require 'tmpdir'

mark = 'infinito-design-'
fields = %i[logo header_logo favicon pwa_icon]
texts = %i[title pwa_name pwa_short_name]
title = ENV.fetch('GITLAB_DESIGN_TITLE')
appearance = Appearance.first || Appearance.new
owned = ->(field) { appearance.public_send(field).file&.filename.to_s.start_with?(mark) }
marked = fields.any? { |field| owned.call(field) }
changed = false

Dir.mktmpdir do |dir|
  texts.each do |field|
    current = appearance.public_send(field).to_s
    next if current == title || (current.present? && !marked)

    appearance.public_send("#{field}=", title)
    changed = true
  end
  fields.each do |field|
    next if uploads.key?(field) || !owned.call(field)

    appearance.public_send("remove_#{field}=", true)
    changed = true
  end
  uploads.each do |field, (extension, encoded)|
    stored = appearance.public_send(field)
    next if stored.file && !owned.call(field)

    content = Base64.decode64(encoded)
    next if stored.file&.exists? && Digest::SHA256.hexdigest(stored.read) == Digest::SHA256.hexdigest(content)

    path = File.join(dir, "#{mark}#{field}.#{extension}")
    File.binwrite(path, content)
    appearance.public_send("#{field}=", File.open(path))
    changed = true
  end
  appearance.save! if changed
end

puts(changed ? 'CHANGED' : 'OK')
