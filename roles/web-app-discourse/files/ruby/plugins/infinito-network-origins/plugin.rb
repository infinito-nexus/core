# frozen_string_literal: true
# nocheck: mirrored-unit-test, comments-valid - Discourse loads this as a plugin and reads its
# metadata from the header comments below; Discourse and SiteSetting only exist inside its boot
# name: infinito-network-origins
# about: Answers every network sibling of the forum under its own origin
# version: 1.0.0
# authors: Infinito.Nexus

module ::InfinitoNetworkOrigins
  HTTPS_BY_HOST =
    ENV
      .fetch("INFINITO_NETWORK_BASE_URLS", "")
      .split
      .to_h do |url|
        uri = URI(url)
        [uri.host, uri.scheme == "https"]
      end
      .freeze

  class RequestOrigin
    def initialize(app)
      @app = app
    end

    def call(env)
      host = Rack::Request.new(env).host
      Thread.current[:infinito_network_host] = HTTPS_BY_HOST.key?(host) ? host : nil
      @app.call(env)
    ensure
      Thread.current[:infinito_network_host] = nil
    end
  end

  module CurrentHostname
    def current_hostname
      Thread.current[:infinito_network_host] || super
    end
  end

  module ForceHttps
    def force_https
      host = Thread.current[:infinito_network_host]
      host ? HTTPS_BY_HOST.fetch(host) : super
    end

    def force_https?
      force_https
    end
  end

  module IconCachePerHost
    def get_set_cache(key, &block)
      super("#{key}-#{Discourse.current_hostname}", &block)
    end
  end

  module ClientSettingsPerHost
    def client_settings_json
      (client_settings_jsons[provider.current_site] ||= {})[Discourse.current_hostname] ||=
        client_settings_json_uncached
    rescue => e
      Rails.logger.error("Error while retrieving client_settings_json: #{e.message}")
      ""
    end

    def client_settings_hash
      (client_settings_hashes[provider.current_site] ||= {})[Discourse.current_hostname] ||=
        client_settings_hash_uncached
    end
  end
end

Rails.configuration.middleware.insert_before(0, InfinitoNetworkOrigins::RequestOrigin)

after_initialize do
  Discourse.singleton_class.prepend(InfinitoNetworkOrigins::CurrentHostname)
  SiteSetting.singleton_class.prepend(InfinitoNetworkOrigins::ForceHttps)
  SiteSetting.singleton_class.prepend(InfinitoNetworkOrigins::ClientSettingsPerHost)
  SiteIconManager.singleton_class.prepend(InfinitoNetworkOrigins::IconCachePerHost)
end
