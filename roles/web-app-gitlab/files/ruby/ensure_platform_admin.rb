# nocheck: mirrored-unit-test - runs in `gitlab-rails runner` against User,
# Organizations::Organization and Users::CreateService, which come from the GitLab
# image and are not loadable anywhere else
#
# Env (from the container):
#   GITLAB_ADMIN_USERNAME  login of the platform administrator
#   GITLAB_ADMIN_EMAIL     primary address of the account
#   GITLAB_ADMIN_NAME      display name of the account
#   GITLAB_ADMIN_PASSWORD  password it must accept afterwards
#   GITLAB_ADMIN_SSO_UID   openid_connect extern_uid (preferred_username) to link, empty without SSO
#
# Exit: 0 with [CHANGED] or [UNCHANGED] on stdout, 1 with [FAIL] on stderr.
username = ENV.fetch('GITLAB_ADMIN_USERNAME')
email = ENV.fetch('GITLAB_ADMIN_EMAIL')
display_name = ENV.fetch('GITLAB_ADMIN_NAME')
password = ENV.fetch('GITLAB_ADMIN_PASSWORD')
sso_uid = ENV.fetch('GITLAB_ADMIN_SSO_UID')

user = User.find_by_username(username) || User.find_by_any_email(email)
changes = []

if user.nil?
  organization = Organizations::Organization.default_organization
  abort("[FAIL] no default organization to create '#{username}' in") if organization.nil?

  result = Users::CreateService.new(
    nil,
    username: username,
    name: display_name,
    email: email,
    password: password,
    password_confirmation: password,
    skip_confirmation: true,
    organization_id: organization.id
  ).execute
  abort("[FAIL] could not create '#{username}': #{result.message}") unless result.success?

  user = User.find_by_username(username)
  abort("[FAIL] '#{username}' is absent after a successful create") if user.nil?
  changes << 'created'
end

unless user.admin?
  user.admin = true
  changes << 'admin'
end

unless user.valid_password?(password) && !user.password_automatically_set?
  user.password = user.password_confirmation = password
  user.password_automatically_set = false
  changes << 'password'
end

identity = nil
unless sso_uid.empty?
  holder = Identity.with_extern_uid('openid_connect', sso_uid).where.not(user_id: user.id).take
  abort("[FAIL] the openid_connect identity '#{sso_uid}' belongs to user #{holder.user_id}, not to '#{username}'") if holder

  identity = user.identities.find_or_initialize_by(provider: 'openid_connect')
  if identity.extern_uid == sso_uid
    identity = nil
  else
    identity.extern_uid = sso_uid
    changes << 'sso identity'
  end
end

if changes.empty?
  puts "[UNCHANGED] #{username} is an administrator and accepts the declared password"
  exit(0)
end

user.save!
identity&.save!
puts "[CHANGED] #{username}: #{changes.join(', ')}"
