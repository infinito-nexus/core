# nocheck: mirrored-unit-test - runs in the Decidim console against Decidim::Organization; the model only exists once Rails has booted
organization = Decidim::Organization.first
if organization
  puts "Organization present: #{organization.host}"
else
  name = ENV.fetch("DECIDIM_ORG_NAME")
  ActiveRecord::Base.transaction do
    organization = Decidim::Organization.create!(
      name: { Decidim.default_locale => name },
      host: ENV.fetch("DECIDIM_ORG_HOST"),
      reference_prefix: name,
      default_locale: Decidim.default_locale,
      available_locales: Decidim.available_locales,
      available_authorizations: [],
      external_domain_allowlist: ["decidim.org", "github.com"],
      users_registration_mode: :enabled,
      badges_enabled: true,
      send_welcome_notification: true,
      file_upload_settings: Decidim::OrganizationSettings.default(:upload),
      colors: { primary: "#53bf40", secondary: "#4053bf", tertiary: "#bf4053" }
    )
    Decidim::System::CreateDefaultHelpPages.call(organization)
    Decidim::System::CreateDefaultContentBlocks.call(organization)
  end
  puts "Organization created: #{organization.host}"
end
