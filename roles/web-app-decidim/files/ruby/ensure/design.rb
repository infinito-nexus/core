# nocheck: mirrored-unit-test - runs in the Decidim console against Decidim::Organization, ActiveStorage and the ActiveRecord metadata table; the models only exist once Rails has booted
require "base64"
require "digest"
require "json"
require "stringio"

payload = JSON.parse(Base64.strict_decode64(DECIDIM_DESIGN_PAYLOAD))
mark = "infinito-design-"
state_key = "infinito_design_state"
metadata = ActiveRecord::Base.connection_pool.internal_metadata
organization = Decidim::Organization.first
state = JSON.parse(metadata[state_key] || "{}")
stored = state.to_json

converge = lambda do |field, wanted|
  current = organization[field] || {}
  entry = state[field]
  ours = !entry.nil? && entry["applied"].all? { |key, value| current[key] == value }
  if wanted.empty?
    state.delete(field)
    next false unless ours

    organization[field] = current.except(*entry["applied"].keys).merge(entry["previous"])
    next true
  end
  next false if entry && !ours
  next false if ours && entry["applied"] == wanted

  previous = current.slice(*wanted.keys)
  restored = current
  if entry
    previous = previous.merge(entry["previous"])
    restored = current.except(*entry["applied"].keys).merge(entry["previous"])
  end
  state[field] = { "applied" => wanted, "previous" => previous }
  organization[field] = restored.merge(wanted)
  true
end

title = payload["title"].to_s
name = title.empty? ? {} : organization.available_locales.index_with { title }
changed = [converge.call("name", name), converge.call("colors", payload["colors"])].any?
organization.save! if changed

%w[logo favicon].each do |slot|
  attachment = organization.public_send(slot)
  bytes = Base64.strict_decode64(payload[slot].to_s)
  owned = attachment.attached? && attachment.filename.to_s.start_with?(mark)
  if bytes.empty?
    next unless owned

    attachment.purge
    changed = true
    next
  end
  next if attachment.attached? && !owned

  blob = owned ? attachment.blob : nil
  next if blob && blob.checksum == Digest::MD5.base64digest(bytes) && blob.service.exist?(blob.key)

  attachment.attach(io: StringIO.new(bytes), filename: [mark, slot, ".png"].join, content_type: "image/png")
  stored_name = organization.reload.public_send(slot).filename.to_s
  raise "the organization rejected the generated #{slot}" unless stored_name.start_with?(mark)

  changed = true
end

metadata[state_key] = state.to_json if state.to_json != stored
puts(changed || state.to_json != stored ? "DESIGN_CHANGED" : "DESIGN_UNCHANGED")
