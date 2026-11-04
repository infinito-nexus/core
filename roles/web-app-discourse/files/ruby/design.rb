# nocheck: mirrored-unit-test - runs in the Discourse console against ColorScheme, Theme,
# SiteSetting, UploadCreator and PluginStore; they only exist once the application has booted

require "base64"
require "digest"
require "json"
require "tempfile"

payload = JSON.parse($stdin.read)
mark = payload.fetch("mark")
changed = []

theme = Theme.find_default
dark_base_id = ColorScheme::NAMES_TO_ID_MAP.fetch("Dark")
seeded_dark_id =
  ColorScheme
    .where(base_scheme_id: dark_base_id, theme_id: nil)
    .where.not(name: payload.fetch("dark_name"))
    .order(:id)
    .pick(:id)

def ensure_scheme(name, base_name, colors, changed)
  scheme = ColorScheme.find_by(name: name)
  scheme ||=
    ColorScheme.create_from_base(name: name, base_scheme_id: ColorScheme::NAMES_TO_ID_MAP.fetch(base_name))
  current = scheme.colors.to_h { |color| [color.name, color.hex.downcase] }
  wanted = colors.to_h { |key, hex| [key, hex.delete_prefix("#").downcase] }
  return scheme if wanted.all? { |key, hex| current[key] == hex }

  ColorSchemeRevisor.revise(scheme, colors: wanted.map { |key, hex| { name: key, hex: hex } })
  changed << "scheme:#{name}"
  scheme.reload
end

def own_upload?(mark, setting)
  stored = PluginStore.get(mark, setting)
  stored.is_a?(Hash) && SiteSetting.public_send(setting)&.id == stored["upload_id"]
end

def ensure_upload(setting, entry, mark, changed)
  data = Base64.decode64(entry.fetch("b64"))
  digest = Digest::SHA1.hexdigest(data)
  current = SiteSetting.public_send(setting)
  own = own_upload?(mark, setting)
  unless own || current.nil? || current.id.negative?
    puts "design_upload_skipped=#{setting}"
    return
  end
  return if own && PluginStore.get(mark, setting)["sha1"] == digest

  Tempfile.create(["design", File.extname(entry.fetch("name"))]) do |file|
    file.binmode
    file.write(data)
    file.rewind
    upload =
      UploadCreator.new(file, entry.fetch("name"), for_site_setting: true).create_for(Discourse.system_user.id)
    raise "upload #{setting} failed: #{upload.errors.full_messages.join(", ")}" if upload.errors.any?
    SiteSetting.public_send("#{setting}=", upload)
    PluginStore.set(mark, setting, { "sha1" => digest, "upload_id" => upload.id })
  end
  changed << "upload:#{setting}"
end

if payload.fetch("enabled")
  light = ensure_scheme(payload.fetch("light_name"), "Light", payload.fetch("light"), changed)
  dark = ensure_scheme(payload.fetch("dark_name"), "Dark", payload.fetch("dark"), changed)

  if [nil, light.id].include?(theme.color_scheme_id)
    if theme.color_scheme_id != light.id
      theme.update!(color_scheme_id: light.id)
      changed << "theme:light"
    end
  else
    puts "design_light_skipped=#{theme.color_scheme_id}"
  end

  if [nil, seeded_dark_id, dark.id].include?(theme.dark_color_scheme_id)
    if theme.dark_color_scheme_id != dark.id
      theme.update!(dark_color_scheme_id: dark.id)
      changed << "theme:dark"
    end
  else
    puts "design_dark_skipped=#{theme.dark_color_scheme_id}"
  end

  component = Theme.find_by(name: payload.fetch("component_name"), component: true)
  component ||=
    Theme.create!(name: payload.fetch("component_name"), component: true, user_id: Discourse.system_user.id)
  field = component.theme_fields.find_by(target_id: Theme.targets[:common], name: "scss")
  if field&.value != payload.fetch("scss")
    component.set_field(target: :common, name: :scss, value: payload.fetch("scss"))
    component.save!
    changed << "component"
  end
  error = component.theme_fields.find_by(target_id: Theme.targets[:common], name: "scss")&.error
  raise "design component does not compile: #{error}" if error.present?
  unless theme.child_themes.exists?(id: component.id)
    theme.add_relative_theme!(:child, component)
    changed << "component:attached"
  end

  title = payload.fetch("title")
  own_title = PluginStore.get(mark, "title")
  if title.present? && SiteSetting.title != title
    if [own_title, SiteSetting.defaults[:title]].include?(SiteSetting.title)
      SiteSetting.title = title
      PluginStore.set(mark, "title", title)
      changed << "title"
    else
      puts "design_title_skipped=true"
    end
  end

  payload.fetch("uploads").each { |setting, entry| ensure_upload(setting, entry, mark, changed) }
else
  light = ColorScheme.find_by(name: payload.fetch("light_name"))
  dark = ColorScheme.find_by(name: payload.fetch("dark_name"))
  if light && theme.color_scheme_id == light.id
    theme.update!(color_scheme_id: nil)
    changed << "theme:light"
  end
  if dark && theme.dark_color_scheme_id == dark.id
    theme.update!(dark_color_scheme_id: seeded_dark_id)
    changed << "theme:dark"
  end
  component = Theme.find_by(name: payload.fetch("component_name"), component: true)
  if component
    component.destroy!
    changed << "component"
  end
  [light, dark].compact.each do |scheme|
    scheme.destroy!
    changed << "scheme:#{scheme.name}"
  end
  if PluginStore.get(mark, "title").present?
    SiteSetting.remove_override!(:title) if SiteSetting.title == PluginStore.get(mark, "title")
    PluginStore.remove(mark, "title")
    changed << "title"
  end
  payload.fetch("upload_settings").each do |setting|
    next if PluginStore.get(mark, setting).nil?
    SiteSetting.remove_override!(setting) if own_upload?(mark, setting)
    PluginStore.remove(mark, setting)
    changed << "upload:#{setting}"
  end
end

Stylesheet::Manager.cache.clear

puts "design_changed=#{changed.any?}"
puts "design_changes=#{changed.join(",")}"
