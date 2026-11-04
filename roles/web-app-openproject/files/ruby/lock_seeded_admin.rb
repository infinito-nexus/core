# nocheck: mirrored-unit-test - runs in the OpenProject console against User and Setting;
# the models only exist once OpenProject has booted
platform_login = ENV.fetch("OPENPROJECT_ADMIN_LOGIN")

User.where(login: "admin", mail: Setting.seed_admin_user_mail).find_each do |user|
  next if user.login.casecmp?(platform_login) || user.locked?

  user.locked!
  puts "Locked seeded account #{user.login}"
end
