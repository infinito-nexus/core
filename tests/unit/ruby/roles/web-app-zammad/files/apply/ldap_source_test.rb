# frozen_string_literal: true

require "json"
require "minitest/autorun"
require "open3"

class ZammadLdapSourceKeysTest < Minitest::Test
  SCRIPT = File.expand_path(
    "../../../../../../../roles/web-app-zammad/files/ruby/apply/ldap_source.rb",
    __dir__
  )

  ADMINISTRATOR_DN = "cn=web-app-zammad-administrator,ou=Roles,dc=Example,dc=org"

  PRELUDE = <<~'RUBY'
    require "json"

    module UserInfo
      def self.current_user_id=(_id); end
    end

    class NilClass
      def present? = false
    end

    FakeRole = Struct.new(:id, :name)

    class Role
      ALL = [FakeRole.new(1, "Admin"), FakeRole.new(2, "Agent")].freeze

      def self.where(active:, name:)
        raise ArgumentError, "only active roles are granted" unless active == true

        ALL.select { |role| Array(name).include?(role.name) }
      end
    end

    class LdapSource
      attr_accessor :preferences, :active

      def self.find_or_initialize_by(name:) = new

      def save!
        puts JSON.generate(preferences)
      end
    end

    module Setting
      def self.set(_name, _value); end
    end

    class ImportJob
      def initialize(name:, payload:); end

      def start; end

      def result = nil
    end
  RUBY

  # @return [Array(Hash, String, Process::Status)] the saved LdapSource preferences, stderr and status
  def apply
    stdout, stderr, status = Open3.capture3(
      {
        "LDAP_GROUP_ROLE_MAP" => { ADMINISTRATOR_DN => %w[Admin Agent] }.to_json,
        "LDAP_USER_ATTRIBUTES" => { "givenName" => "firstname", "telephoneNumber" => "phone", "mail" => "email" }.to_json,
        "LDAP_NAME" => "Infinito LDAP",
        "LDAP_HOST" => "ldap",
        "LDAP_PORT" => "389",
        "LDAP_BIND_DN" => "cn=administrator,dc=example,dc=org",
        "LDAP_BIND_PW" => "bind-secret",
        "LDAP_BASE_DN" => "ou=users,dc=example,dc=org",
        "LDAP_USER_FILTER" => "(objectClass=inetOrgPerson)",
        "LDAP_UID_ATTR" => "uid",
        "LDAP_GROUP_FILTER" => "(objectClass=groupOfNames)",
      },
      RbConfig.ruby, "-e", "#{PRELUDE}\nload ARGV[0]", SCRIPT
    )
    [status.success? ? JSON.parse(stdout) : {}, stderr, status]
  end

  def test_attribute_names_are_the_lowercase_keys_net_ldap_hands_over
    preferences, stderr, status = apply

    assert_predicate status, :success?, stderr
    assert_equal(
      { "givenname" => "firstname", "telephonenumber" => "phone", "mail" => "email" },
      preferences.fetch("user_attributes")
    )
  end

  def test_group_dns_are_the_lowercase_keys_ldap_group_reads
    preferences, stderr, status = apply

    assert_predicate status, :success?, stderr
    assert_equal({ ADMINISTRATOR_DN.downcase => %w[1 2] }, preferences.fetch("group_role_map"))
  end

  def test_directory_users_outside_the_mapped_groups_keep_the_signup_role
    preferences, stderr, status = apply

    assert_predicate status, :success?, stderr
    assert_equal "sigup_roles", preferences.fetch("unassigned_users")
  end
end
