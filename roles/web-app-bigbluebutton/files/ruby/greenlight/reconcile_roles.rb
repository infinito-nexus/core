# frozen_string_literal: true

require "json"

provider       = "greenlight"
admin_emails   = JSON.parse(ENV.fetch("RBAC_ADMIN_EMAILS")).map { |email| email.to_s.downcase }.reject(&:empty?)
keep_emails    = JSON.parse(ENV.fetch("RBAC_PROTECTED_EMAILS")).map { |email| email.to_s.downcase }
admin_role     = Role.find_by!(name: "Administrator", provider: provider)
user_role      = Role.find_by!(name: "User", provider: provider)
changes        = []

User.where(provider: provider).find_each do |user|
  email = user.email.to_s.downcase
  if admin_emails.include?(email) || keep_emails.include?(email)
    next if user.role_id == admin_role.id

    user.update_columns(role_id: admin_role.id, updated_at: Time.current)
    changes << "promoted #{email}"
  elsif user.role_id == admin_role.id
    user.update_columns(role_id: user_role.id, updated_at: Time.current)
    changes << "demoted #{email}"
  end
end

puts(changes.empty? ? "NOOP" : "CHANGED #{changes.join(', ')}")
