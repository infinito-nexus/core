# nocheck: mirrored-unit-test - runs in the Zammad console against Setting, Store and
# Service::SystemAssets::ProductLogo; the constants only exist once Zammad has booted
#
# Environment:
#   DESIGN_TITLE:         product name to show; empty hands the name back.
#   DESIGN_DEFAULT_NAMES: JSON list of product names the deployment may replace.
# Constant prepended on stdin:
#   DESIGN_LOGO_B64: base64 of the lockup SVG; empty hands the logo back.
# Output:
#   "design-branding: changed" or "design-branding: unchanged".

require "base64"
require "digest"
require "json"

UserInfo.current_user_id = 1

MARK = "infinito_design_branding".freeze
LOGO = Service::SystemAssets::ProductLogo
LOGO_OBJECT = "System::Logo".freeze

title = ENV.fetch("DESIGN_TITLE")
logo = Base64.decode64(DESIGN_LOGO_B64).force_encoding("UTF-8")
recorded = Setting.exists?(name: MARK) ? Setting.get(MARK).to_h : {}
mark = recorded.dup

name = Setting.get("product_name")
if title.empty?
  Setting.set("product_name", mark["previous_name"]) if mark["applied_name"] && name == mark["applied_name"]
  mark = mark.except("applied_name", "previous_name")
elsif name != title && (JSON.parse(ENV.fetch("DESIGN_DEFAULT_NAMES")) + [mark["applied_name"]]).include?(name)
  mark["previous_name"] ||= name
  mark["applied_name"] = title
  Setting.set("product_name", title)
end

stored = Store.list(object: LOGO_OBJECT, o_id: LOGO::PRODUCT_LOGO_RAW).first
stored_digest = stored && Digest::SHA256.hexdigest(stored.content)
if logo.empty?
  if mark["logo_sha256"] && stored_digest == mark["logo_sha256"]
    [LOGO::PRODUCT_LOGO_RAW, LOGO::PRODUCT_LOGO_RESIZED].each { |o_id| Store.remove(object: LOGO_OBJECT, o_id: o_id) }
    Setting.set("product_logo", mark["previous_logo"])
  end
  mark = mark.except("logo_sha256", "previous_logo")
else
  digest = Digest::SHA256.hexdigest(logo)
  if stored_digest != digest && (stored.nil? || stored_digest == mark["logo_sha256"])
    mark["previous_logo"] ||= Setting.get("product_logo")
    Setting.set("product_logo", LOGO.store(logo))
    mark["logo_sha256"] = digest
  end
end

if mark == recorded
  puts "design-branding: unchanged"
else
  if mark.empty?
    Setting.find_by(name: MARK).destroy!
  else
    Setting.create_if_not_exists(
      title:       "Infinito design branding mark",
      name:        MARK,
      area:        "Core",
      description: "Records the product name and logo the deployment applied.",
      options:     {},
      state:       {},
      preferences: {},
      frontend:    false
    )
    Setting.set(MARK, mark)
  end
  puts "design-branding: changed"
end
