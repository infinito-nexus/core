# frozen_string_literal: true
# nocheck: mirrored-unit-test - runs in `rails runner` against Greenlight's SiteSetting model; the constants only exist once the app has booted

require "json"

MARK = Rails.root.join("storage", "infinito-design.json")
PROVIDER = "greenlight"

enabled = ENV.fetch("DESIGN_ENABLED") == "true"
defaults = {
  "PrimaryColor" => "#467fcf",
  "PrimaryColorLight" => "#e8eff9",
  "BrandingImage" => ActionController::Base.helpers.image_path("bbb_logo.png"),
}
wanted = {
  "PrimaryColor" => ENV.fetch("DESIGN_PRIMARY"),
  "PrimaryColorLight" => ENV.fetch("DESIGN_PRIMARY_LIGHT"),
  "BrandingImage" => ENV.fetch("DESIGN_LOGO_URL").presence || defaults["BrandingImage"],
}

mark = File.exist?(MARK) ? JSON.parse(File.read(MARK)) : {}
changed = false

wanted.each_key do |name|
  setting = SiteSetting.joins(:setting).find_by(provider: PROVIDER, setting: { name: name })
  next unless setting
  next if name == "BrandingImage" && setting.image.attached?
  next unless setting.value == mark[name] || setting.value == defaults[name]

  target = enabled ? wanted[name] : defaults[name]
  next if setting.value == target

  setting.update!(value: target)
  changed = true
end

if enabled
  if mark != wanted
    File.write(MARK, JSON.generate(wanted))
    changed = true
  end
elsif File.exist?(MARK)
  File.delete(MARK)
  changed = true
end

puts(changed ? "CHANGED" : "NOOP")
