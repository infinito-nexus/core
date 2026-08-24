# Bind Zammad Smart Assist to the platform LiteLLM gateway.
#
# Order matters: ai_provider is the boolean "a provider is configured", and its
# validator (Setting::Validation::AIProvider) reads ai_provider_config, so the
# config hash has to land first or the flag is refused. Writing the config runs
# AI::Provider::CustomOpenAI.ping!, so this script fails outright when the
# gateway is unreachable or rejects the virtual key.
#
# Environment:
#   AI_URL:   OpenAI-compatible base URL of the gateway (provider appends /chat/completions).
#   AI_MODEL: model name the gateway serves.
#   AI_TOKEN: this role's virtual key; optional, sent as a bearer when present.

UserInfo.current_user_id = 1

config = {
  "provider" => "custom_open_ai",
  "url"      => ENV.fetch("AI_URL"),
  "model"    => ENV.fetch("AI_MODEL"),
}

token = ENV.fetch("AI_TOKEN", "")
config["token"] = token unless token.empty?

Setting.set("ai_provider_config", config)
Setting.set("ai_provider", true)

Setting.set("ai_assistance_ticket_summary", true)
Setting.set("ai_assistance_text_tools", true)

stored = Setting.get("ai_provider_config") || {}
raise "ai_provider_config url is #{stored['url'].inspect}, expected #{ENV.fetch('AI_URL').inspect}" if stored["url"] != ENV.fetch("AI_URL")
raise "ai_provider is #{Setting.get('ai_provider').inspect}, expected true" unless Setting.get("ai_provider")
