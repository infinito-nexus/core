name = ENV.fetch('GITLAB_MCP_TOKEN_NAME')
username = ENV.fetch('GITLAB_MCP_TOKEN_OWNER')
lifetime_days = Integer(ENV.fetch('GITLAB_MCP_TOKEN_LIFETIME_DAYS'))

user = User.find_by_username(username)
abort("MISSING_OWNER #{username}") if user.nil?

user.personal_access_tokens.active.where(name: name).find_each(&:revoke!)

token = user.personal_access_tokens.create!(
  name: name,
  scopes: ['mcp'],
  expires_at: Date.current.advance(days: lifetime_days)
)

puts 'CHANGED'
puts token.token
