require "json"

def rbac_member_matcher(members)
  usernames = members.map { |member| User.normalize_username(member.fetch("username")) }.compact
  emails = members.map { |member| member.fetch("email").to_s.strip.downcase }.reject(&:empty?)
  ->(user) { usernames.include?(user.username_lower) || emails.include?(user.email.to_s.strip.downcase) }
end

administrators = rbac_member_matcher(JSON.parse(ENV.fetch("DISCOURSE_RBAC_ADMINISTRATORS")))
moderators = rbac_member_matcher(JSON.parse(ENV.fetch("DISCOURSE_RBAC_MODERATORS")))
kept = JSON.parse(ENV.fetch("DISCOURSE_RBAC_KEPT_ADMINISTRATORS")).map { |name| User.normalize_username(name) }

changed = false

User.real.find_each do |user|
  next if kept.include?(user.username_lower)

  if administrators.call(user)
    unless user.admin
      user.grant_admin!
      changed = true
      puts "CHANGED granted_admin=#{user.username}"
    end
  elsif user.admin
    user.revoke_admin!
    changed = true
    puts "CHANGED revoked_admin=#{user.username}"
  end

  if moderators.call(user)
    unless user.moderator
      user.grant_moderation!
      changed = true
      puts "CHANGED granted_moderator=#{user.username}"
    end
  elsif user.moderator
    user.revoke_moderation!
    changed = true
    puts "CHANGED revoked_moderator=#{user.username}"
  end
end

puts "UNCHANGED" unless changed
