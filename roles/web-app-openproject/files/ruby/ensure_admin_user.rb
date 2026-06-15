pw    = ENV.fetch("OPENPROJECT_ADMIN_PASSWORD")
login = ENV.fetch("OPENPROJECT_ADMIN_LOGIN")
mail  = ENV.fetch("OPENPROJECT_ADMIN_EMAIL")

user = User.find_by(login: login) || User.new(
  login: login,
  mail: mail,
  firstname: "Admin",
  lastname: "User",
  password: pw,
  password_confirmation: pw,
)
user.admin = true
user.save!
puts "Administrator #{login} ensured and set as admin."
