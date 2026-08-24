# nocheck: mirrored-unit-test - runs in the OpenProject console against User and its
# password validators; the models only exist once OpenProject has booted
pw    = ENV.fetch("OPENPROJECT_ADMIN_PASSWORD")
login = ENV.fetch("OPENPROJECT_ADMIN_LOGIN")
mail  = ENV.fetch("OPENPROJECT_ADMIN_EMAIL")

user = User.find_by(login: login) || User.new(
  login: login,
  mail: mail,
  firstname: "Admin",
  lastname: "User",
)
user.admin = true
if user.new_record? || !user.check_password?(pw)
  user.password = pw
  user.password_confirmation = pw
end
user.force_password_change = false if user.respond_to?(:force_password_change)
user.status = User::STATUSES[:active] if defined?(User::STATUSES) && User::STATUSES.key?(:active)
user.save!
puts "Administrator #{login} ensured and set as admin."
