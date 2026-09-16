# nocheck: mirrored-unit-test - runs in the Discourse console against User and its
# password validators; the models only exist once the application has booted

email = ENV.fetch("DISCOURSE_ADMIN_EMAIL")
username = ENV.fetch("DISCOURSE_ADMIN_USERNAME")
password = ENV.fetch("DISCOURSE_ADMIN_PASSWORD")

user = User.find_by_email(email) || User.new(email: email)
user.username = username
user.password = password unless user.confirm_password?(password)
user.active = true
user.save!

user.grant_admin!
user.change_trust_level!(1) if user.trust_level < 1
user.email_tokens.update_all(confirmed: true)
user.activate
