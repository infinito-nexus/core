# nocheck: mirrored-unit-test - runs in the Zammad console against User, Role, Group and Token,
# and depends on the before_create hook the live models supply; none of it is callable
# outside the Zammad image
#
# Zammad overwrites a token handed to create in before_create, so the chosen value
# is assigned afterwards, as in mcp_bot.rb.
#
# Environment:
#   ACCESS_REQUEST_BOT_LOGIN, ACCESS_REQUEST_BOT_EMAIL, ACCESS_REQUEST_BOT_PASSWORD: the agent.
#   ACCESS_REQUEST_GROUP:     the group its tickets land in.
#   ACCESS_REQUEST_API_TOKEN: the token value the service presents.
#   ACCESS_REQUEST_TOKEN_LABEL: the token's human label.

UserInfo.current_user_id = 1

Setting.set('api_token_access', true)

bot = User.find_or_initialize_by(login: ENV.fetch('ACCESS_REQUEST_BOT_LOGIN'))
bot.email     = ENV.fetch('ACCESS_REQUEST_BOT_EMAIL')
bot.firstname = 'Access'
bot.lastname  = 'Request'
bot.password  = ENV.fetch('ACCESS_REQUEST_BOT_PASSWORD')
bot.active    = true
bot.roles     = Role.where(name: %w[Agent])
bot.save!

group = Group.find_or_create_by!(name: ENV.fetch('ACCESS_REQUEST_GROUP')) { |g| g.active = true }
bot.group_names_access_map = { group.name => %w[create read change] }
bot.save!

label = ENV.fetch('ACCESS_REQUEST_TOKEN_LABEL')
token = Token.find_by(action: 'api', user_id: bot.id, name: label)
token ||= Token.create!(
  action:      'api',
  persistent:  true,
  user:        bot,
  name:        label,
  preferences: { permission: %w[ticket.agent] }
)
token.preferences = { permission: %w[ticket.agent] }
token.token = ENV.fetch('ACCESS_REQUEST_API_TOKEN')
token.save!
