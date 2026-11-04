# Env (from the container):
#   OPENPROJECT_ADMIN_MEMBERS  JSON list of the logins holding the administrator role
#   OPENPROJECT_ADMIN_SPARED   JSON list of logins the reconcile never provisions or changes
#
# Exit: 0 with one "CHANGED <login> <change>" line per provisioned or changed account,
# else "UNCHANGED", on stdout.
require "json"

members = JSON.parse(ENV.fetch("OPENPROJECT_ADMIN_MEMBERS")).map(&:downcase)
spared  = JSON.parse(ENV.fetch("OPENPROJECT_ADMIN_SPARED")).map(&:downcase)
changed = false

(members - spared).each do |login|
  next if User.by_login(login).exists?
  next unless LdapAuthSource.find_user(login)

  puts "CHANGED #{login} provisioned"
  changed = true
end

User.where(type: User.name).find_each do |user|
  login = user.login.downcase
  next if spared.include?(login)

  wanted = members.include?(login)
  next if user.admin? == wanted

  user.update_column(:admin, wanted)
  puts "CHANGED #{user.login} admin=#{wanted}"
  changed = true
end

puts "UNCHANGED" unless changed
