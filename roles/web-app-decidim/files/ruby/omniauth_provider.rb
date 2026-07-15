    if ENV["OIDC_ENABLED"].to_s == "true"
      require "omniauth_openid_connect"
      ENV["SSL_CERT_FILE"] = ENV["CURL_CA_BUNDLE"] if ENV["CURL_CA_BUNDLE"] && File.exist?(ENV["CURL_CA_BUNDLE"].to_s)
      # SWD.url_builder defaults to URI::HTTPS regardless of the issuer scheme;
      # a plain-http issuer (Tor .onion) must discover over http as well.
      if URI.parse(ENV.fetch("OIDC_ISSUER")).scheme == "http"
        SWD.url_builder = URI::HTTP
        WebFinger.url_builder = URI::HTTP
      end
      provider(
        :openid_connect,
        name: :openid_connect,
        scope: [:openid, :email, :profile],
        response_type: :code,
        discovery: true,
        issuer: ENV.fetch("OIDC_ISSUER"),
        client_options: {
          host: URI.parse(ENV.fetch("OIDC_ISSUER")).host,
          identifier: ENV.fetch("OIDC_CLIENT_ID"),
          secret:     ENV.fetch("OIDC_CLIENT_SECRET"),
          redirect_uri: "#{ENV.fetch('APPLICATION_HOST').chomp('/')}/users/auth/openid_connect/callback"
        }
      )
    end
