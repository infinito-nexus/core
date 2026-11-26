# frozen_string_literal: true

require "json"
require "minitest/autorun"
require "open3"

class ZammadOidcSettingsAutoLinkTest < Minitest::Test
  SCRIPT = File.expand_path(
    "../../../../../../../roles/web-app-zammad/files/ruby/apply/oidc_settings.rb",
    __dir__
  )

  AUTO_LINK = "auth_third_party_auto_link_at_inital_login"

  PRELUDE = <<~'RUBY'
    require "json"

    module UserInfo
      def self.current_user_id=(_id); end
    end

    module Setting
      def self.set(name, value)
        puts JSON.generate([name, value])
      end
    end

    class User
      def self.find_by(login:) = nil
    end
  RUBY

  # @return [Array(Array<Array>, String, Process::Status)] every Setting.set as name and value, stderr and status
  def apply
    stdout, stderr, status = Open3.capture3(
      {
        "ZAMMAD_FQDN" => "zammad.example.org",
        "ZAMMAD_HTTP_TYPE" => "https",
        "OIDC_BUTTON_TEXT" => "SSO",
        "OIDC_CLIENT_ID" => "zammad",
        "OIDC_ISSUER_URL" => "https://auth.example.org/realms/main",
        "OIDC_SCOPE" => "openid profile email",
        "OIDC_UID_FIELD" => "preferred_username",
        "OIDC_ADMIN_LOGIN" => "Administrator",
      },
      RbConfig.ruby, "-e", "#{PRELUDE}\nload ARGV[0]", SCRIPT
    )
    [stdout.lines.map { |line| JSON.parse(line) }, stderr, status]
  end

  def test_no_sso_login_links_an_account_by_email
    writes, stderr, status = apply

    assert_predicate status, :success?, stderr
    assert_equal [false], writes.select { |name, _value| name == AUTO_LINK }.map(&:last)
  end
end
