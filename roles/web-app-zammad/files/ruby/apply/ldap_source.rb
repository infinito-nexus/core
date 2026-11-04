# nocheck: mirrored-unit-test - runs in the Zammad console against LdapSource; the model
# only exists once Zammad has booted
require "json"

UserInfo.current_user_id = 1

group_role_map = JSON.parse(ENV.fetch("LDAP_GROUP_ROLE_MAP")).to_h do |dn, role_names|
  roles   = Role.where(active: true, name: role_names).to_a
  missing = role_names - roles.map(&:name)
  raise "LDAP group #{dn} grants #{missing.join(', ')}, which is not an active Zammad role" if missing.any?

  [dn.downcase, roles.map { |role| role.id.to_s }]
end

user_attributes = JSON.parse(ENV.fetch("LDAP_USER_ATTRIBUTES")).transform_keys(&:downcase)

source = LdapSource.find_or_initialize_by(name: ENV.fetch("LDAP_NAME"))
source.preferences = {
  "host"              => ENV.fetch("LDAP_HOST"),
  "port"              => Integer(ENV.fetch("LDAP_PORT")),
  "ssl"               => "off",
  "ssl_verify"        => false,
  "bind_user"         => ENV.fetch("LDAP_BIND_DN"),
  "bind_pw"           => ENV.fetch("LDAP_BIND_PW"),
  "base_dn"           => ENV.fetch("LDAP_BASE_DN"),
  "user_filter"       => ENV.fetch("LDAP_USER_FILTER"),
  "user_uid"          => ENV.fetch("LDAP_UID_ATTR").downcase,
  "user_attributes"   => user_attributes,
  "group_filter"      => ENV.fetch("LDAP_GROUP_FILTER"),
  "group_uid"         => "dn",
  "group_role_map"    => group_role_map,
  "unassigned_users"  => "sigup_roles",
}
source.active = true
source.save!

Setting.set("ldap_integration", true)

begin
  job = ImportJob.new(name: "Import::Ldap", payload: source.preferences)
  job.start
  warn "LDAP sync result: #{job.result.inspect}" if job.result.present?
rescue StandardError => e
  warn "LDAP sync failed (#{e.class}: #{e.message}); users will sync on next scheduled job"
end
