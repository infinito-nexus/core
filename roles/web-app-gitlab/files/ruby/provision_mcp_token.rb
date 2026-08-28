# nocheck: mirrored-unit-test - runs in `gitlab-rails runner` against User,
# Organizations::Organization and PersonalAccessToken; the models come from the GitLab
# image and are not loadable anywhere else
name = ENV.fetch('GITLAB_MCP_TOKEN_NAME')
username = ENV.fetch('GITLAB_MCP_TOKEN_OWNER')
display_name = ENV.fetch('GITLAB_MCP_TOKEN_OWNER_NAME')
email = ENV.fetch('GITLAB_MCP_TOKEN_OWNER_EMAIL')
password = ENV.fetch('GITLAB_MCP_TOKEN_OWNER_PASSWORD')
lifetime_days = Integer(ENV.fetch('GITLAB_MCP_TOKEN_LIFETIME_DAYS'))

user = User.find_by_username(username)

if user.nil?
  organization = Organizations::Organization.default_organization
  abort("NO_DEFAULT_ORGANIZATION: cannot place the personal namespace of #{username}") if organization.nil?

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
  abort("OWNER_CREATE_FAILED #{username}: #{result.message}") unless result.success?
  user = User.find_by_username(username)
  abort("OWNER_MISSING_AFTER_CREATE #{username}") if user.nil?
end

abort("OWNER_IS_ADMIN #{username}") if user.admin?

user.personal_access_tokens.active.where(name: name).find_each(&:revoke!)

token = user.personal_access_tokens.create!(
  name: name,
  scopes: ['mcp'],
  expires_at: Date.current.advance(days: lifetime_days)
)

puts 'CHANGED'
puts token.token
