# nocheck: mirrored-unit-test - runs in the Zammad console against User, Role,
# Group and PasswordHash; the constants only exist once Zammad has booted
#
# Environment:
#   ADMIN_LOGIN, ADMIN_EMAIL, ADMIN_FIRSTNAME, ADMIN_LASTNAME, ADMIN_PASSWORD:
#     the platform administrator from lookup('users', 'platform_administrator').
# Output:
#   "administrator: changed" or "administrator: unchanged".

UserInfo.current_user_id = 1

login = ENV.fetch("ADMIN_LOGIN")
email = ENV.fetch("ADMIN_EMAIL")
password = ENV.fetch("ADMIN_PASSWORD")

admin = User.find_by(login: login) || User.find_by(email: email) || User.new(login: login)
admin.login     = login
admin.email     = email
admin.firstname = ENV.fetch("ADMIN_FIRSTNAME")
admin.lastname  = ENV.fetch("ADMIN_LASTNAME")
admin.active    = true
admin.password  = password unless admin.password.present? && PasswordHash.verified?(admin.password, password)

roles = Role.where(name: %w[Admin Agent]).to_a
roles_changed = admin.roles.map(&:id).sort != roles.map(&:id).sort
changed = admin.new_record? || admin.changed? || roles_changed

admin.roles = roles if roles_changed
admin.save! if admin.changed? || admin.new_record?

users_group = Group.find_or_create_by!(name: "Users") { |group| group.active = true }
unless admin.group_names_access_map[users_group.name] == ["full"]
  admin.group_names_access_map = { users_group.name => "full" }
  admin.save!
  changed = true
end

puts(changed ? "administrator: changed" : "administrator: unchanged")
