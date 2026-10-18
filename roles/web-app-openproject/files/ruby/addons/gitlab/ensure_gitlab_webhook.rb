require "json"

login = ENV.fetch("OPENPROJECT_GITLAB_BOT_LOGIN")
mail = ENV.fetch("OPENPROJECT_GITLAB_BOT_MAIL")
password = ENV.fetch("OPENPROJECT_GITLAB_BOT_PASSWORD")
token_name = ENV.fetch("OPENPROJECT_GITLAB_TOKEN_NAME")
webhook_secret = ENV.fetch("OPENPROJECT_GITLAB_WEBHOOK_SECRET")
held_token = ENV.fetch("OPENPROJECT_GITLAB_API_TOKEN", "")

changed = false

user = User.find_by(login: login)
if user.nil?
  user = User.new(
    login: login,
    firstname: "Infinito",
    lastname: "GitLab",
    mail: mail,
    admin: true,
    language: "en"
  )
  user.password = password
  user.password_confirmation = password
  user.activate
  user.save!
  changed = true
end

api_token = nil
unless held_token.empty?
  existing = Token::API.find_by_plaintext_value(held_token)
  api_token = held_token if existing && existing.user_id == user.id
end

if api_token.nil?
  Token::API.where(user_id: user.id).destroy_all
  token = Token::API.create!(user: user, token_name: token_name)
  api_token = token.plain_value
  changed = true
end

settings = Setting.plugin_openproject_gitlab_integration || {}
wanted = settings.merge(
  "gitlab_user_id" => user.id,
  "webhook_secret" => webhook_secret
)
if settings != wanted
  Setting.plugin_openproject_gitlab_integration = wanted
  changed = true
end

puts "CHANGED" if changed
puts JSON.generate("api_token" => api_token, "gitlab_user_id" => user.id)
