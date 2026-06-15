name  = ENV.fetch("OPENPROJECT_LDAP_NAME")
login = ENV.fetch("OPENPROJECT_ADMIN_LOGIN")

src  = LdapAuthSource.find_by(name: name)
user = User.find_by(login: login)

if src && user && user.ldap_auth_source_id != src.id
  user.ldap_auth_source_id = src.id
  user.save!(validate: false)
  puts "Linked #{login} to LDAP auth source #{name} for header SSO."
else
  puts "No LDAP link change needed for #{login}."
end
