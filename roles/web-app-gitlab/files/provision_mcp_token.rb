name = ENV.fetch('GITLAB_MCP_TOKEN_NAME')
username = ENV.fetch('GITLAB_MCP_TOKEN_OWNER')
display_name = ENV.fetch('GITLAB_MCP_TOKEN_OWNER_NAME')
email = ENV.fetch('GITLAB_MCP_TOKEN_OWNER_EMAIL')
password = ENV.fetch('GITLAB_MCP_TOKEN_OWNER_PASSWORD')
lifetime_days = Integer(ENV.fetch('GITLAB_MCP_TOKEN_LIFETIME_DAYS'))

user = User.find_by_username(username)

if user.nil?
  user = User.new(
    username: username,
    name: display_name,
    email: email,
    password: password,
    password_confirmation: password
  )
  user.skip_confirmation!
  user.save!
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
