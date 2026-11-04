# frozen_string_literal: true

# Every API response re-encrypts and resends the cookie session it read, so a landing XHR that
# lands after the one-click SSO POST overwrites omniauth.state and the callback fails csrf_detected.
Rails.application.config.to_prepare do
  Api::BaseController.prepend_before_action { request.session_options[:skip] = true }
end
