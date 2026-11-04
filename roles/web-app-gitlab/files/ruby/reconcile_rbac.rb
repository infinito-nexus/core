# Env (from the container):
#   GITLAB_RBAC_ADMINISTRATORS  JSON list of {username, email, name} holding the administrator role
#   GITLAB_RBAC_EXTERNALS       JSON list of {username, email, name} holding the external role
#   GITLAB_RBAC_KEEP_ADMINS     JSON list of usernames that stay administrators outside the role group
#
# Exit: 0 with one "CHANGED <username> admin=<bool> external=<bool>" line per changed account,
# else "UNCHANGED", on stdout; 1 with the validation errors on stderr.
require 'json'
require 'set'

def resolve_ids(members)
  members.filter_map do |member|
    user = User.find_by_username(member.fetch('username'))
    email = member.fetch('email')
    user ||= User.find_by_any_email(email) unless email.empty?
    user&.id
  end.to_set
end

administrators = resolve_ids(JSON.parse(ENV.fetch('GITLAB_RBAC_ADMINISTRATORS')))
externals = resolve_ids(JSON.parse(ENV.fetch('GITLAB_RBAC_EXTERNALS')))
keep = JSON.parse(ENV.fetch('GITLAB_RBAC_KEEP_ADMINS')).map(&:downcase).to_set
changed = false

User.where(user_type: :human).find_each do |user|
  admin = administrators.include?(user.id) || keep.include?(user.username.downcase)
  external = !admin && externals.include?(user.id)
  next if user.admin? == admin && user.external? == external

  user.admin = admin
  user.external = external
  abort("could not update '#{user.username}': #{user.errors.full_messages.join(', ')}") unless user.save

  puts "CHANGED #{user.username} admin=#{admin} external=#{external}"
  changed = true
end

puts 'UNCHANGED' unless changed
