# nocheck: mirrored-unit-test - runs in `gitlab-rails runner` against the User model,
# which comes from the GitLab image and is not loadable anywhere else
#
# Env (from the container):
#   GITLAB_ROOT_USERNAME  login of the built-in break-glass account
#   GITLAB_ROOT_PASSWORD  password it must accept afterwards
#
# Exit: 0 with [CHANGED] or [UNCHANGED] on stdout, 1 with [FAIL] on stderr.
#
# password_automatically_set makes User#valid_password? return false whatever the
# password is (app/models/user.rb), so a realign that leaves it set locks the
# account out instead of recovering it.
username = ENV.fetch('GITLAB_ROOT_USERNAME')
password = ENV.fetch('GITLAB_ROOT_PASSWORD')

user = User.find_by_username(username)
abort("[FAIL] no GitLab user named '#{username}'") if user.nil?

if user.valid_password?(password) && !user.password_automatically_set?
  puts "[UNCHANGED] #{username} already accepts the declared password"
  exit(0)
end

user.password = user.password_confirmation = password
user.password_automatically_set = false
user.save!

puts "[CHANGED] #{username} was realigned with the declared password"
