# nocheck: mirrored-unit-test - runs in the Zammad console against User and
# UserInfo.current_user_id; the constants only exist once Zammad has booted
UserInfo.current_user_id = 1

api_bot = User.find_or_initialize_by(login: ENV.fetch("API_BOT_LOGIN"))
api_bot.email     = ENV.fetch("API_BOT_EMAIL")
api_bot.firstname = ENV.fetch("API_BOT_FIRSTNAME")
api_bot.lastname  = ENV.fetch("API_BOT_LASTNAME")
api_bot.password  = ENV.fetch("API_BOT_PASSWORD")
api_bot.active    = true
api_bot.roles     = Role.where(name: %w[Admin Agent])
api_bot.save!

users_group = Group.find_or_create_by!(name: "Users") { |g| g.active = true }
api_bot.group_names_access_map = { users_group.name => "full" }
api_bot.save!
