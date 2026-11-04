# frozen_string_literal: true

require "json"
require "minitest/autorun"
require "open3"

class DiscourseRbacLoginPluginTest < Minitest::Test
  PLUGIN = File.expand_path(
    "../../../../../../../../roles/web-app-discourse/files/ruby/plugins/infinito-rbac-login/plugin.rb",
    __dir__
  )

  ADMINISTRATOR_GROUP = "/roles/web-app-discourse/administrator"
  MODERATOR_GROUP = "/roles/web-app-discourse/moderator"

  PRELUDE = <<~RUBY
    require "json"

    class FakeUser
      attr_reader :username, :username_lower, :admin, :moderator, :staged

      def initialize(row)
        @username = row.fetch("username")
        @username_lower = @username.downcase
        @admin = row.fetch("admin")
        @moderator = row.fetch("moderator")
        @staged = row.fetch("staged")
      end

      def grant_admin!
        @admin = true
        puts "granted_admin=\#{username}"
      end

      def revoke_admin!
        @admin = false
        puts "revoked_admin=\#{username}"
      end

      def grant_moderation!
        @moderator = true
        puts "granted_moderator=\#{username}"
      end

      def revoke_moderation!
        @moderator = false
        puts "revoked_moderator=\#{username}"
      end
    end

    class User
      def self.normalize_username(name)
        name.to_s.unicode_normalize.downcase
      end
    end

    module SiteSetting
      def self.openid_connect_groups_claim
        "groups"
      end
    end

    FakeResult = Struct.new(:user, :extra_data)
    FakeToken = Struct.new(:extra)

    class OpenIDConnectAuthenticator
      def initialize(user)
        @user = user
      end

      def after_authenticate(_auth_token, existing_account: nil)
        FakeResult.new(@user, { provider: "oidc", uid: "uid-1" })
      end

      def after_create_account(user, _auth_result)
        puts "associated=\#{user.username}"
      end
    end

    def after_initialize
      yield
    end
  RUBY

  DRIVER = <<~RUBY
    scenario = JSON.parse(ENV.fetch("SCENARIO"))
    extra = scenario.fetch("extra")
    token = FakeToken.new(extra && extra.transform_keys(&:to_sym))
    account = scenario.fetch("user") && FakeUser.new(scenario.fetch("user"))

    result = OpenIDConnectAuthenticator.new(account).after_authenticate(token)
    puts "groups=\#{result.extra_data[:infinito_rbac_groups].inspect}"

    signup = scenario.fetch("signup")
    if signup
      created = FakeUser.new(signup)
      OpenIDConnectAuthenticator.new(nil).after_create_account(created, FakeResult.new(created, result.extra_data))
      puts "admin=\#{created.admin} moderator=\#{created.moderator}"
    else
      puts "admin=\#{account.admin} moderator=\#{account.moderator}"
    end
  RUBY

  # @param username [String] Discourse username of the account
  # @param admin [Boolean] admin flag before the sign-in
  # @param moderator [Boolean] moderator flag before the sign-in
  # @param staged [Boolean] whether the account is a staged one
  # @return [Hash] one account row for FakeUser
  def account(username, admin: false, moderator: false, staged: false)
    { "username" => username, "admin" => admin, "moderator" => moderator, "staged" => staged }
  end

  # @param groups [Array<String>, String, nil] groups claim of the userinfo, nil for no claim
  # @param id_token_groups [Array<String>, nil] groups claim of the ID token, nil for no claim
  # @return [Hash] the extra section of the auth token
  def extra(groups, id_token_groups: nil)
    {
      "raw_info" => groups.nil? ? {} : { "groups" => groups },
      "id_token_info" => id_token_groups.nil? ? {} : { "groups" => id_token_groups },
    }
  end

  # @param user [Hash, nil] the account the authenticator resolves, nil for a first sign-in
  # @param extra [Hash, nil] the extra section of the auth token
  # @param signup [Hash, nil] the account the signup creates afterwards, nil for no signup
  # @param env [Hash] container variables to override, nil unsets one
  # @return [Array(Array<String>, String, Process::Status)] stdout lines, stderr and status
  def sign_in(user:, extra:, signup: nil, env: {})
    stdout, stderr, status = Open3.capture3(
      {
        "INFINITO_RBAC_ADMINISTRATOR_GROUP" => ADMINISTRATOR_GROUP,
        "INFINITO_RBAC_MODERATOR_GROUP" => MODERATOR_GROUP,
        "INFINITO_RBAC_KEPT_ADMINISTRATOR" => "Administrator",
        "SCENARIO" => { "user" => user, "extra" => extra, "signup" => signup }.to_json,
      }.merge(env),
      RbConfig.ruby, "-e", "#{PRELUDE}\nload ARGV[0]\n#{DRIVER}", PLUGIN
    )
    [stdout.lines.map(&:strip), stderr, status]
  end

  def test_an_administrator_member_is_granted_admin
    lines, stderr, status = sign_in(user: account("biber"), extra: extra([ADMINISTRATOR_GROUP]))

    assert_predicate status, :success?, stderr
    assert_equal ["granted_admin=biber", "groups=#{[ADMINISTRATOR_GROUP].inspect}", "admin=true moderator=false"], lines
  end

  def test_an_admin_outside_the_administrator_group_is_revoked
    lines, stderr, status = sign_in(user: account("biber", admin: true), extra: extra([]))

    assert_predicate status, :success?, stderr
    assert_equal ["revoked_admin=biber", "groups=[]", "admin=false moderator=false"], lines
  end

  def test_a_moderator_member_is_granted_moderation
    lines, stderr, status = sign_in(user: account("biber"), extra: extra([MODERATOR_GROUP]))

    assert_predicate status, :success?, stderr
    assert_equal ["granted_moderator=biber", "groups=#{[MODERATOR_GROUP].inspect}", "admin=false moderator=true"], lines
  end

  def test_a_moderator_outside_the_moderator_group_is_revoked
    lines, stderr, status = sign_in(user: account("biber", moderator: true), extra: extra([]))

    assert_predicate status, :success?, stderr
    assert_equal ["revoked_moderator=biber", "groups=[]", "admin=false moderator=false"], lines
  end

  def test_admin_and_moderator_flags_follow_their_own_group
    lines, stderr, status = sign_in(user: account("biber", moderator: true), extra: extra([ADMINISTRATOR_GROUP]))

    assert_predicate status, :success?, stderr
    assert_equal ["granted_admin=biber", "revoked_moderator=biber"], lines.first(2)
    assert_equal "admin=true moderator=false", lines.last
  end

  def test_a_group_of_another_application_grants_nothing
    lines, stderr, status = sign_in(
      user: account("biber", admin: true),
      extra: extra(["/roles/web-app-other/administrator"])
    )

    assert_predicate status, :success?, stderr
    assert_equal ["revoked_admin=biber"], lines.first(1)
    assert_equal "admin=false moderator=false", lines.last
  end

  def test_the_kept_administrator_keeps_both_flags_outside_every_group
    lines, stderr, status = sign_in(user: account("administrator", admin: true, moderator: true), extra: extra([]))

    assert_predicate status, :success?, stderr
    assert_equal ["groups=[]", "admin=true moderator=true"], lines
  end

  def test_converged_flags_are_not_rewritten
    lines, stderr, status = sign_in(
      user: account("biber", admin: true, moderator: true),
      extra: extra([ADMINISTRATOR_GROUP, MODERATOR_GROUP])
    )

    assert_predicate status, :success?, stderr
    assert_equal ["groups=#{[ADMINISTRATOR_GROUP, MODERATOR_GROUP].inspect}", "admin=true moderator=true"], lines
  end

  def test_a_missing_groups_claim_changes_nothing
    lines, stderr, status = sign_in(user: account("biber", admin: true, moderator: true), extra: extra(nil))

    assert_predicate status, :success?, stderr
    assert_equal ["groups=nil", "admin=true moderator=true"], lines
  end

  def test_a_token_without_extra_section_changes_nothing
    lines, stderr, status = sign_in(user: account("biber", admin: true), extra: nil)

    assert_predicate status, :success?, stderr
    assert_equal ["groups=nil", "admin=true moderator=false"], lines
  end

  def test_a_groups_claim_that_is_no_list_changes_nothing
    lines, stderr, status = sign_in(user: account("biber", admin: true), extra: extra(ADMINISTRATOR_GROUP))

    assert_predicate status, :success?, stderr
    assert_equal ["groups=nil", "admin=true moderator=false"], lines
  end

  def test_the_id_token_claim_counts_when_the_userinfo_carries_none
    lines, stderr, status = sign_in(user: account("biber"), extra: extra(nil, id_token_groups: [MODERATOR_GROUP]))

    assert_predicate status, :success?, stderr
    assert_equal ["granted_moderator=biber", "groups=#{[MODERATOR_GROUP].inspect}", "admin=false moderator=true"], lines
  end

  def test_a_staged_account_is_left_to_the_signup
    lines, stderr, status = sign_in(user: account("biber", staged: true), extra: extra([ADMINISTRATOR_GROUP]))

    assert_predicate status, :success?, stderr
    assert_equal ["groups=#{[ADMINISTRATOR_GROUP].inspect}", "admin=false moderator=false"], lines
  end

  def test_a_new_account_gets_its_flags_when_it_is_created
    lines, stderr, status = sign_in(
      user: nil,
      extra: extra([ADMINISTRATOR_GROUP, MODERATOR_GROUP]),
      signup: account("mapache")
    )

    assert_predicate status, :success?, stderr
    assert_equal [
      "groups=#{[ADMINISTRATOR_GROUP, MODERATOR_GROUP].inspect}",
      "associated=mapache",
      "granted_admin=mapache",
      "granted_moderator=mapache",
      "admin=true moderator=true",
    ], lines
  end

  def test_a_new_account_without_groups_claim_gets_no_flags
    lines, stderr, status = sign_in(user: nil, extra: extra(nil), signup: account("mapache"))

    assert_predicate status, :success?, stderr
    assert_equal ["groups=nil", "associated=mapache", "admin=false moderator=false"], lines
  end

  def test_a_missing_group_variable_stops_the_plugin_load
    _lines, stderr, status = sign_in(
      user: account("biber"),
      extra: extra([]),
      env: { "INFINITO_RBAC_MODERATOR_GROUP" => nil }
    )

    refute_predicate status, :success?
    assert_match(/INFINITO_RBAC_MODERATOR_GROUP/, stderr)
  end
end
