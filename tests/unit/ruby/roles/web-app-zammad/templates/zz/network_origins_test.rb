# frozen_string_literal: true

require "minitest/autorun"
require "open3"

class ZammadNetworkOriginsTest < Minitest::Test
  TEMPLATE = File.expand_path(
    "../../../../../../../roles/web-app-zammad/templates/zz/network_origins.rb.j2",
    __dir__
  )

  DRIVER = <<~'RUBY'
    module Rails
      def self.prepare_blocks
        @prepare_blocks ||= []
      end

      def self.application = self
      def self.config = self
      def self.middleware = self
      def self.reloader = self

      def self.insert_before(_index, _middleware); end

      def self.to_prepare(&block)
        prepare_blocks << block
      end
    end

    module OmniAuth
      def self.config = self

      def self.full_host=(_full_host); end

      module Strategies
        class OidcDatabase; end
      end
    end

    class Session
      attr_reader :data

      def self.store
        @store ||= []
      end

      def self.open(sid)
        store << new("oidc_sid" => sid)
      end

      def self.all = store.dup

      def self.find_each(&block)
        all.each(&block)
      end

      def self.secure_flag? = true

      def initialize(data)
        @data = data
      end

      def destroy
        self.class.store.delete_if { |record| record.equal?(self) }
      end
    end

    LogoutToken = Struct.new(:sid)

    class Strategy
      SIDS = { "token-a" => "sid-a" }.freeze

      def decode_logout_token(token)
        LogoutToken.new(SIDS.fetch(token))
      end
    end

    class SessionsController
      attr_reader :params

      def initialize(params)
        @params = params
      end

      def oidc_bc_logout
        decoded = oidc_strategy.decode_logout_token(params[:logout_token])
        Session.all.detect { |s| s.data["oidc_sid"] == decoded.sid }&.destroy
      end

      private

      def oidc_strategy
        @oidc_strategy ||= Strategy.new
      end
    end

    template, mode, token = ARGV
    source = File.read(template).sub("{{ ZAMMAD_NETWORK_BASE_URLS | to_json }}", "[]")
    abort "#{template} holds Jinja the driver does not render" if source.include?("{{")
    eval(source, TOPLEVEL_BINDING, template)
    Rails.prepare_blocks.each(&:call) if mode == "patched"
    %w[sid-a sid-a sid-b].each { |sid| Session.open(sid) }
    begin
      SessionsController.new({ logout_token: token }).oidc_bc_logout
      puts "accepted"
    rescue KeyError
      puts "refused"
    end
    puts Session.all.map { |record| record.data["oidc_sid"] }.sort.join(",")
  RUBY

  # @param mode [String] "patched" runs the to_prepare hooks before the logout, "stock" keeps Zammad's own action
  # @param token [String] the logout_token form value
  # @return [Array(Array<String>, String, Process::Status)] stdout lines, stderr and status
  def logout(mode:, token: "token-a")
    stdout, stderr, status = Open3.capture3(RbConfig.ruby, "-e", DRIVER, TEMPLATE, mode, token)
    [stdout.lines.map(&:strip), stderr, status]
  end

  def test_stock_zammad_keeps_the_session_of_the_other_origin
    lines, stderr, status = logout(mode: "stock")

    assert_predicate status, :success?, stderr
    assert_equal %w[accepted sid-a,sid-b], lines
  end

  def test_one_logout_token_ends_the_session_of_every_origin
    lines, stderr, status = logout(mode: "patched")

    assert_predicate status, :success?, stderr
    assert_equal %w[accepted sid-b], lines
  end

  def test_a_refused_logout_token_ends_no_session
    lines, stderr, status = logout(mode: "patched", token: "token-forged")

    assert_predicate status, :success?, stderr
    assert_equal %w[refused sid-a,sid-a,sid-b], lines
  end
end
