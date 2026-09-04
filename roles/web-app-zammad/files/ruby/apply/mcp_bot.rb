# nocheck: mirrored-unit-test - runs in the Zammad console against User, Role and Token,
# and depends on the before_create hook the live models supply; none of it is callable
# outside the Zammad image
#
# Give the MCP adapter a read-only Zammad agent and pin its API token.
#
# Zammad overwrites any token handed to create with a generated one, but only
# in before_create, so the chosen value is assigned afterwards. The column is
# plain text and the model renews it the same way.
#
# Read-only comes from the group access level, not from the role: an agent with
# `read` on its groups passes the show policies and fails the create/change
# ones. The Agent role itself is required, because ticket and organization
# reads are gated on `ticket.agent`.
#
# Environment:
#   MCP_BOT_LOGIN, MCP_BOT_EMAIL, MCP_BOT_FIRSTNAME, MCP_BOT_LASTNAME,
#   MCP_BOT_PASSWORD: the agent to converge.
#   MCP_API_TOKEN:    the token value the adapter presents.
#   MCP_TOKEN_LABEL:  the token's human label.

UserInfo.current_user_id = 1

Setting.set('api_token_access', true)

bot = User.find_or_initialize_by(login: ENV.fetch('MCP_BOT_LOGIN'))
bot.email     = ENV.fetch('MCP_BOT_EMAIL')
bot.firstname = ENV.fetch('MCP_BOT_FIRSTNAME')
bot.lastname  = ENV.fetch('MCP_BOT_LASTNAME')
bot.password  = ENV.fetch('MCP_BOT_PASSWORD')
bot.active    = true
bot.roles     = Role.where(name: %w[Agent])
bot.save!

group = Group.find_or_create_by!(name: 'Users') { |g| g.active = true }
bot.group_names_access_map = { group.name => %w[read] }
bot.save!

label = ENV.fetch('MCP_TOKEN_LABEL')
token = Token.find_by(action: 'api', user_id: bot.id, name: label)
token ||= Token.create!(
  action:      'api',
  persistent:  true,
  user:        bot,
  name:        label,
  preferences: { permission: %w[ticket.agent] }
)
token.preferences = { permission: %w[ticket.agent] }
token.token = ENV.fetch('MCP_API_TOKEN')
token.save!
