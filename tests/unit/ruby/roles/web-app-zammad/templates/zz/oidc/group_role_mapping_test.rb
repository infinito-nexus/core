# frozen_string_literal: true

require "json"
require "minitest/autorun"
require "open3"

class ZammadOidcGroupRoleMappingTest < Minitest::Test
  TEMPLATE = File.expand_path(
    "../../../../../../../../roles/web-app-zammad/templates/zz/oidc/group_role_mapping.rb.j2",
    __dir__
  )

  ADMINISTRATOR_GROUP = "/roles/web-app-zammad/administrator"
  AGENT_GROUP = "/roles/web-app-zammad/agent"
  EMAIL = "alice@example.org"

  GROUP_ROLE_MAP = { ADMINISTRATOR_GROUP => %w[Admin Agent], AGENT_GROUP => %w[Agent] }.freeze
  PROFILE_CLAIMS = { "firstname" => "given_name", "email" => "email" }.freeze
  ADDRESS_FIELDS = { "city" => "locality" }.freeze

  ROLES = [
    { "id" => 1, "name" => "Admin", "active" => true },
    { "id" => 2, "name" => "Agent", "active" => true },
    { "id" => 3, "name" => "Customer", "active" => true },
  ].freeze

  LINKED = [{ "uid" => "alice", "user_id" => 7 }].freeze

  PRELUDE = <<~'RUBY'
    require "json"

    module Rails
      def self.application = self
      def self.config = self
      def self.logger = self

      def self.after_initialize
        yield
      end

      def self.error
        puts "error: #{yield}"
      end
    end

    FakeRole = Struct.new(:id, :name, :active)

    class Role
      ALL = JSON.parse(ENV.fetch("ROLES")).map { |row| FakeRole.new(row.fetch("id"), row.fetch("name"), row.fetch("active")) }

      def self.where(**conditions)
        ALL.select { |role| conditions.all? { |column, wanted| Array(wanted).include?(role.public_send(column)) } }
      end
    end

    class RoleSet < Array
      def reset
        puts "roles reset"
        self
      end
    end

    class FakeUser
      attr_reader :id, :login, :source

      def initialize(row)
        @id = row.fetch("id")
        @login = row.fetch("login")
        @source = row.fetch("source")
        @saved = row.fetch("profile")
        @current = @saved.dup
        @role_names = row.fetch("roles")
        @refused = row.fetch("refused")
      end

      def email = @current["email"]

      def roles
        RoleSet.new(@role_names.map { |name| Role::ALL.find { |role| role.name == name } })
      end

      def roles=(roles)
        raise "last_admin_check_by_role" if @refused.include?("roles")

        @role_names = roles.map(&:name)
      end

      def assign_attributes(profile)
        @current = @current.merge(profile)
      end

      def changed? = @current != @saved

      def save!
        raise "Email address is invalid" if @refused.include?("profile")

        @saved = @current.dup
      end

      def restore_attributes
        @current = @saved.dup
      end

      def state
        ["user", id, login, "roles=#{@role_names.sort.join(',')}", *@current.sort.map { |key, value| "#{key}=#{value}" }].join(" ")
      end
    end

    class Relation
      def initialize(users)
        @users = users
      end

      def not(id:)
        Relation.new(@users.reject { |user| user.id == id })
      end

      def exists?(email:)
        @users.any? { |user| user.email == email }
      end

      def find_by(login:)
        @users.find { |user| user.login == login }
      end
    end

    class User
      ALL = JSON.parse(ENV.fetch("USERS")).map { |row| FakeUser.new(row) }

      def self.where(*condition)
        return Relation.new(ALL) if condition.empty?
        raise ArgumentError, condition.inspect unless condition == ["source LIKE ?", "Ldap::%"]

        Relation.new(ALL.select { |user| user.source.to_s.start_with?("Ldap::") })
      end

      def self.create_from_hash!(hash)
        user = FakeUser.new(
          "id" => 100, "login" => hash.fetch("uid"), "source" => nil,
          "profile" => {}, "roles" => ["Customer"], "refused" => []
        )
        ALL << user
        puts "created user #{user.login}"
        user
      end
    end

    FakeAuthorization = Struct.new(:uid, :user)

    class Authorization
      LINKS = JSON.parse(ENV.fetch("AUTHORIZATIONS"))

      def self.find_from_hash(hash)
        link = LINKS.find { |row| row.fetch("uid") == hash.fetch("uid") }
        link && FakeAuthorization.new(link.fetch("uid"), User::ALL.find { |user| user.id == link.fetch("user_id") })
      end

      if ENV.fetch("AUTHORIZATION_API") == "zammad-7.1.2"
        def self.create_from_hash(hash, user = nil)
          FakeAuthorization.new(hash.fetch("uid"), user || User.create_from_hash!(hash))
        end
      else
        def self.create_from_hash!(hash, user = nil)
          FakeAuthorization.new(hash.fetch("uid"), user || User.create_from_hash!(hash))
        end
      end
    end
  RUBY

  DRIVER = <<~'RUBY'
    template = ARGV.fetch(0)
    source = File.read(template)
    JSON.parse(ENV.fetch("RENDERED")).each do |expression, literal|
      source = source.gsub("{{ #{expression} }}") { literal }
    end
    abort "#{template} holds Jinja the driver does not render" if source.include?("{{")
    eval(source, TOPLEVEL_BINDING, template)
    auth_hash = JSON.parse(ENV.fetch("AUTH_HASH"))
    authorization = Authorization.public_send(ENV.fetch("HOOK"), auth_hash)
    puts "signed in as user #{authorization.user.id}"
    User::ALL.each { |user| puts user.state }
  RUBY

  # @param id [Integer] Zammad user id
  # @param login [String] Zammad login
  # @param source [String, nil] import source, "Ldap::<id>" for a directory account
  # @param profile [Hash{String=>String}] stored profile fields
  # @param refused [Array<String>] writes Zammad refuses for this user: "profile", "roles"
  # @return [Hash] one row for the stubbed User model
  def user(id: 7, login: "alice", source: "Ldap::1", profile: { "email" => EMAIL, "firstname" => "Alice" }, refused: [])
    { "id" => id, "login" => login, "source" => source, "profile" => profile, "roles" => ["Customer"], "refused" => refused }
  end

  # @param hook [String] the Authorization class method the sign-in reaches: find_from_hash or create_from_hash
  # @param users [Array<Hash>] Zammad users
  # @param authorizations [Array<Hash>] existing Authorization rows as uid and user_id
  # @param groups [Array<String>, nil] groups claim of the response, nil for no claim
  # @param raw_info [Hash] claims of the userinfo response
  # @param roles [Array<Hash>] Zammad roles
  # @param group_role_map [Hash, String] ZAMMAD_OIDC_GROUP_ROLE_MAP as the deploy renders it
  # @param api [String] "zammad-7.1.2" for Zammad's Authorization API, anything else for one without create_from_hash
  # @return [Array(Array<String>, String, Process::Status)] stdout lines, stderr and status
  def sign_in(hook:, users:, authorizations: [], groups: [ADMINISTRATOR_GROUP], raw_info: {}, roles: ROLES,
              group_role_map: GROUP_ROLE_MAP, api: "zammad-7.1.2")
    info = { "email" => EMAIL }
    info["groups"] = groups unless groups.nil?
    rendered = {
      "ZAMMAD_OIDC_GROUP_ROLE_MAP | to_json | to_json" => group_role_map.to_json.to_json,
      "RBAC.GROUP.CLAIM | to_json" => "groups".to_json,
      "ZAMMAD_OIDC_PROFILE_CLAIMS | to_json | to_json" => PROFILE_CLAIMS.to_json.to_json,
      "OIDC.ATTRIBUTES.ADDRESS | to_json" => "address".to_json,
      "ZAMMAD_OIDC_ADDRESS_FIELDS | to_json | to_json" => ADDRESS_FIELDS.to_json.to_json,
    }
    auth_hash = { "provider" => "openid_connect", "uid" => "alice", "info" => info, "extra" => { "raw_info" => raw_info } }
    stdout, stderr, status = Open3.capture3(
      {
        "RENDERED" => rendered.to_json,
        "ROLES" => roles.to_json,
        "USERS" => users.to_json,
        "AUTHORIZATIONS" => authorizations.to_json,
        "AUTHORIZATION_API" => api,
        "HOOK" => hook,
        "AUTH_HASH" => auth_hash.to_json,
      },
      RbConfig.ruby, "-e", "#{PRELUDE}\n#{DRIVER}", TEMPLATE
    )
    [stdout.lines.map(&:strip), stderr, status]
  end

  def test_a_directory_account_is_linked_by_its_login
    lines, stderr, status = sign_in(hook: "create_from_hash", users: [user])

    assert_predicate status, :success?, stderr
    assert_equal ["signed in as user 7", "user 7 alice roles=Admin,Agent email=#{EMAIL} firstname=Alice"], lines
  end

  def test_a_local_account_with_the_same_login_is_not_linked
    lines, stderr, status = sign_in(hook: "create_from_hash", users: [user(source: nil)])

    assert_predicate status, :success?, stderr
    assert_includes lines, "signed in as user 100"
    assert_includes lines, "user 7 alice roles=Customer email=#{EMAIL} firstname=Alice"
  end

  def test_a_directory_account_holding_the_same_email_is_not_linked
    lines, stderr, status = sign_in(hook: "create_from_hash", users: [user(id: 9, login: "asmith")])

    assert_predicate status, :success?, stderr
    assert_includes lines, "signed in as user 100"
    assert_includes lines, "user 9 asmith roles=Customer email=#{EMAIL} firstname=Alice"
  end

  def test_the_patch_installs_on_the_zammad_authorization_api
    lines, stderr, status = sign_in(hook: "find_from_hash", users: [user], authorizations: LINKED)

    assert_predicate status, :success?, stderr
    assert_equal ["signed in as user 7", "user 7 alice roles=Admin,Agent email=#{EMAIL} firstname=Alice"], lines
  end

  def test_a_patch_target_that_disappeared_stops_the_boot
    _lines, stderr, status = sign_in(hook: "find_from_hash", users: [user], authorizations: LINKED, api: "renamed")

    refute_predicate status, :success?
    assert_includes stderr, "Authorization.create_from_hash does not take 2 argument(s) any more"
  end

  def test_a_deactivated_role_leaves_the_roles_unchanged
    roles = ROLES.map { |role| role["name"] == "Admin" ? role.merge("active" => false) : role }
    lines, stderr, status = sign_in(hook: "find_from_hash", users: [user], authorizations: LINKED, roles: roles)

    assert_predicate status, :success?, stderr
    assert_includes lines, "error: zz_oidc_group_role_mapping: Admin is not an active Zammad role, left the roles of user 7 unchanged"
    assert_includes lines, "user 7 alice roles=Customer email=#{EMAIL} firstname=Alice"
  end

  def test_a_renamed_role_leaves_the_roles_unchanged
    roles = ROLES.map { |role| role["name"] == "Admin" ? role.merge("name" => "Administrator") : role }
    lines, stderr, status = sign_in(hook: "find_from_hash", users: [user], authorizations: LINKED, roles: roles)

    assert_predicate status, :success?, stderr
    assert_includes lines, "error: zz_oidc_group_role_mapping: Admin is not an active Zammad role, left the roles of user 7 unchanged"
    assert_includes lines, "user 7 alice roles=Customer email=#{EMAIL} firstname=Alice"
  end

  def test_a_map_rendered_as_a_string_stops_the_boot
    _lines, stderr, status = sign_in(
      hook: "find_from_hash", users: [user], authorizations: LINKED,
      group_role_map: "{'#{ADMINISTRATOR_GROUP}': ['Admin', 'Agent']}"
    )

    refute_predicate status, :success?
    assert_includes stderr, "the group to role map rendered as String, not a Hash"
  end

  def test_both_sign_in_paths_apply_the_profile
    {
      "find_from_hash" => LINKED,
      "create_from_hash" => [],
    }.each do |hook, authorizations|
      lines, stderr, status = sign_in(
        hook: hook, users: [user], authorizations: authorizations,
        raw_info: { "given_name" => "Alicia", "address" => { "locality" => "Berlin" } }
      )

      assert_predicate status, :success?, stderr
      assert_includes lines, "user 7 alice roles=Admin,Agent city=Berlin email=#{EMAIL} firstname=Alicia", hook
    end
  end

  def test_a_refused_profile_write_does_not_break_the_sign_in
    lines, stderr, status = sign_in(
      hook: "find_from_hash", users: [user(refused: ["profile"])], authorizations: LINKED,
      raw_info: { "given_name" => "Alicia" }
    )

    assert_predicate status, :success?, stderr
    assert_equal(
      [
        "error: zz_oidc_group_role_mapping: Zammad refused the profile of user 7: Email address is invalid",
        "signed in as user 7",
        "user 7 alice roles=Admin,Agent email=#{EMAIL} firstname=Alice",
      ],
      lines
    )
  end

  def test_a_refused_role_write_does_not_break_the_sign_in
    lines, stderr, status = sign_in(hook: "find_from_hash", users: [user(refused: ["roles"])], authorizations: LINKED)

    assert_predicate status, :success?, stderr
    assert_equal(
      [
        "roles reset",
        "error: zz_oidc_group_role_mapping: Zammad refused [\"Admin\", \"Agent\"] for user 7: last_admin_check_by_role",
        "signed in as user 7",
        "user 7 alice roles=Customer email=#{EMAIL} firstname=Alice",
      ],
      lines
    )
  end
end
