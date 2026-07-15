# frozen_string_literal: true

if ENV["OIDC_ENABLED"] == "true" && ENV["OIDC_ISSUER"].to_s.start_with?("http://")
  require "swd"
  SWD.url_builder = URI::HTTP
  require "webfinger"
  WebFinger.url_builder = URI::HTTP
end
