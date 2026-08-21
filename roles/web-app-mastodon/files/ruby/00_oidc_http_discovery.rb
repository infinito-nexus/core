# frozen_string_literal: true
# nocheck: mirrored-unit-test - a Rails initializer that monkey-patches the swd gem's
# discovery to accept http issuers; it needs the gem and the boot sequence

if ENV["OIDC_ENABLED"] == "true" && ENV["OIDC_ISSUER"].to_s.start_with?("http://")
  require "swd"
  SWD.url_builder = URI::HTTP
  require "webfinger"
  WebFinger.url_builder = URI::HTTP
end
