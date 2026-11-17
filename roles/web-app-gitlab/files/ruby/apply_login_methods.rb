# nocheck: mirrored-unit-test - runs in `gitlab-rails runner` against ApplicationSetting,
# which comes from the GitLab image and is not loadable anywhere else
#
# Env (from the container):
#   GITLAB_APPLICATION_SETTINGS  JSON of the general form of meta/forms.yml: each managed application setting mapped to its value
#   GITLAB_LOGIN_2FA             "true" lets the deploy own the enforcement; "false" leaves it as an admin set it
#   GITLAB_LOGIN_2FA_ENFORCED    "true" sends every account without a second factor to enrollment
#   GITLAB_OBJSTORE_ENABLED      "true" while the artifacts live in object storage; "false" turns incremental
#                                logging off, because update! validates the whole row and GitLab refuses
#                                ci_job_live_trace_enabled without object storage for artifacts
#
# Exit: 0 with [CHANGED] or [UNCHANGED] on stdout, 1 with [FAIL] on stderr.
require 'json'

wanted = JSON.parse(ENV.fetch('GITLAB_APPLICATION_SETTINGS')).transform_keys(&:to_sym)
if ENV.fetch('GITLAB_LOGIN_2FA') == 'true'
  wanted[:require_two_factor_authentication] = ENV.fetch('GITLAB_LOGIN_2FA_ENFORCED') == 'true'
end
wanted[:two_factor_grace_period] = 0 if wanted[:require_two_factor_authentication]
wanted[:ci_job_live_trace_enabled] = false unless ENV.fetch('GITLAB_OBJSTORE_ENABLED') == 'true'

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
