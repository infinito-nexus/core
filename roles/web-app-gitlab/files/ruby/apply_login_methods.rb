# nocheck: mirrored-unit-test - runs in `gitlab-rails runner` against ApplicationSetting,
# which comes from the GitLab image and is not loadable anywhere else
#
# Env (from the container):
#   GITLAB_LOGIN_NATIVE        "true" keeps the password and passkey form on the web sign-in page
#   GITLAB_LOGIN_REGISTRATION  "true" opens local self-registration
#
# Exit: 0 with [CHANGED] or [UNCHANGED] on stdout, 1 with [FAIL] on stderr.
wanted = {
  password_authentication_enabled_for_web: ENV.fetch('GITLAB_LOGIN_NATIVE') == 'true',
  signup_enabled: ENV.fetch('GITLAB_LOGIN_REGISTRATION') == 'true'
}

settings = ApplicationSetting.current_without_cache
abort('[FAIL] GitLab holds no application settings row') if settings.nil?

drift = wanted.reject { |key, value| settings.public_send(key) == value }
summary = wanted.map { |key, value| "#{key}=#{value}" }.join(', ')

if drift.empty?
  puts "[UNCHANGED] #{summary}"
  exit(0)
end

settings.update!(drift)
puts "[CHANGED] #{summary}"
