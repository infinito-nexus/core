email    = ENV.fetch("DECIDIM_ADMIN_EMAIL")
password = ENV.fetch("DECIDIM_ADMIN_PASSWORD")
organization = Decidim::Organization.first
user = Decidim::User.find_or_initialize_by(nickname: 'administrator', organization: organization)
is_new = user.new_record?
user.email = email
user.name = 'Administrator'
user.admin = true
user.confirmed_at = Time.current
user.tos_agreement = true
user.accepted_tos_version = organization.tos_version
if is_new || !user.valid_password?(password)
  user.password = password
  user.password_confirmation = password
end
user.password_updated_at = Time.current if user.respond_to?(:password_updated_at)
user.save!
puts "Admin user ready: #{user.email}"
