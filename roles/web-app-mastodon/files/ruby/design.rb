# frozen_string_literal: true
# nocheck: mirrored-unit-test - runs in `rails runner` against Mastodon's
# live Setting, SiteUpload and Form::AdminSettings models
#
# Param: MASTODON_DESIGN_PAYLOAD  base64 JSON {css, begin, end, title, mark,
#   uploads: {var => base64 PNG or nil}}, prepended on stdin; `mark` names the
#   Setting that records {var => {sha, file}} of the uploads this script made

require "base64"
require "digest"
require "json"
require "tmpdir"

payload = JSON.parse(Base64.strict_decode64(MASTODON_DESIGN_PAYLOAD))
changes = []
form = Form::AdminSettings.new
form_changes = 0

current = Setting.custom_css.to_s
block_pattern = /\n?#{Regexp.escape(payload["begin"])}.*?#{Regexp.escape(payload["end"])}\n?/m
foreign = current.gsub(block_pattern, "\n").strip
css = payload["css"].to_s.strip
block = css.empty? ? "" : "#{payload["begin"]}\n#{css}\n#{payload["end"]}"
wanted = [foreign, block].reject(&:empty?).join("\n\n")
if wanted != current.strip
  form.custom_css = wanted
  form_changes += 1
  changes << "custom_css"
end

title = payload["title"].to_s
stored_title = Setting.find_by(var: "site_title")
if !block.empty? && !title.empty? && Setting.site_title != title
  form.site_title = title
  form_changes += 1
  changes << "site_title"
elsif block.empty? && !title.empty? && stored_title&.value == title
  stored_title.destroy!
  changes << "site_title removed"
end

marks = JSON.parse(Setting[payload["mark"]] || "{}")
uploaded = {}
Dir.mktmpdir do |dir|
  payload.fetch("uploads", {}).each do |var, encoded|
    upload = SiteUpload.find_by(var: var)
    ours = !upload.nil? && marks.dig(var, "file") == upload.file_file_name
    if encoded.nil?
      if ours
        upload.destroy!
        changes << "#{var} removed"
      end
      marks.delete(var)
      next
    end
    bytes = Base64.strict_decode64(encoded)
    sha = Digest::SHA256.hexdigest(bytes)
    next if ours && marks.dig(var, "sha") == sha

    path = File.join(dir, "#{var}.png")
    File.binwrite(path, bytes)
    form.public_send(:"#{var}=", File.open(path))
    uploaded[var] = sha
    form_changes += 1
    changes << var
  end

  raise "Form::AdminSettings rejected the design: #{form.errors.full_messages.join(", ")}" if form_changes.positive? && !form.save
end

uploaded.each { |var, sha| marks[var] = { "sha" => sha, "file" => SiteUpload.find_by!(var: var).file_file_name } }
Setting[payload["mark"]] = JSON.generate(marks) if JSON.parse(Setting[payload["mark"]] || "{}") != marks

puts(changes.empty? ? "DESIGN_UNCHANGED" : "DESIGN_CHANGED #{changes.join(",")}")
