# nocheck: mirrored-unit-test - Rails loads it as an initializer inside the GitLab webservice;
# OmniAuth and Gitlab::Middleware come from the GitLab image and are not loadable anywhere else
require "omniauth_openid_connect"

module InfinitoNetworkOrigins
  ORIGINS = ENV.fetch("INFINITO_NETWORK_BASE_URLS").split.to_h { |url| uri = URI(url); [uri.host, uri.origin] }.freeze
  PLAINTEXT_HOSTS = ORIGINS.select { |_, origin| origin.start_with?("http://") }.keys.freeze

  def self.plaintext?
    Thread.current[:infinito_plaintext_request]
  end

  class PlaintextRequest
    def initialize(app)
      @app = app
    end

    def call(env)
      Thread.current[:infinito_plaintext_request] = PLAINTEXT_HOSTS.include?(Rack::Request.new(env).host)
      @app.call(env)
    ensure
      Thread.current[:infinito_plaintext_request] = nil
    end
  end

  class PlaintextSession
    def initialize(app)
      @app = app
    end

    def call(env)
      options = env["rack.session.options"]
      options[:secure] = false if options && InfinitoNetworkOrigins.plaintext?
      @app.call(env)
    end
  end

  module PlaintextSameSite
    private

    def ssl?
      !InfinitoNetworkOrigins.plaintext? && super
    end
  end

  module RequestOriginCallback
    def redirect_uri
      super.sub(client_options.redirect_uri, "#{full_host}#{callback_path}")
    end
  end
end

Rails.application.config.middleware.insert_before(0, InfinitoNetworkOrigins::PlaintextRequest)
Rails.application.config.middleware.use(InfinitoNetworkOrigins::PlaintextSession)

canonical_full_host = OmniAuth.config.full_host
OmniAuth.config.full_host = lambda do |env|
  InfinitoNetworkOrigins::ORIGINS.fetch(Rack::Request.new(env).host) do
    canonical_full_host.respond_to?(:call) ? canonical_full_host.call(env) : canonical_full_host
  end
end

Rails.application.reloader.to_prepare do
  Gitlab::Middleware::SameSiteCookies.prepend(InfinitoNetworkOrigins::PlaintextSameSite)
  OmniAuth::Strategies::OpenIDConnect.prepend(InfinitoNetworkOrigins::RequestOriginCallback)
end
