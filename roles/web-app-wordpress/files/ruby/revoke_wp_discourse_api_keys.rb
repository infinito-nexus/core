ApiKey.where(
  user_id: User.find_by_username("system").id,
  description: "WP Discourse Integration",
  revoked_at: nil,
).update_all(revoked_at: Time.current)
puts "Revoked existing WP Discourse API keys."
