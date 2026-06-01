UserInfo.current_user_id = 1

source = LdapSource.find_or_initialize_by(name: ENV.fetch("LDAP_NAME"))
source.preferences = {
  "host"              => ENV.fetch("LDAP_HOST"),
  "port"              => Integer(ENV.fetch("LDAP_PORT")),
  "ssl"               => "off",
  "ssl_verify"        => false,
  "bind_user"         => ENV.fetch("LDAP_BIND_DN"),
  "bind_pw"           => ENV.fetch("LDAP_BIND_PW"),
  "base_dn"           => ENV.fetch("LDAP_BASE_DN"),
  "user_filter"       => "(objectClass=inetOrgPerson)",
  "user_uid"          => ENV.fetch("LDAP_UID_ATTR"),
  "user_attributes"   => {
    ENV.fetch("LDAP_UID_ATTR") => "login",
    "givenName"                => "firstname",
    "sn"                       => "lastname",
    "mail"                     => "email",
  },
  "group_filter"      => "(objectClass=groupOfNames)",
  "group_uid"         => "dn",
  "group_role_map"    => {},
  "unassigned_users"  => "skip_sync",
}
source.active = true
source.save!

# ImportJob refuses to sync without this ("Sync cancelled. Ldap integration deactivated.").
Setting.set("ldap_integration", true)

# Sync now so LDAP users exist in Zammad's user table before the first form sign-in.
begin
  job = ImportJob.new(name: "Import::Ldap", payload: source.preferences)
  job.start
  warn "LDAP sync result: #{job.result.inspect}" if job.result.present?
rescue StandardError => e
  warn "LDAP sync failed (#{e.class}: #{e.message}); users will sync on next scheduled job"
end
