# frozen_string_literal: true

require "minitest/autorun"
require "open3"

class ApiSessionSkipTest < Minitest::Test
  SCRIPT = File.expand_path(
    "../../../../../../roles/web-app-mastodon/files/ruby/api_session_skip.rb",
    __dir__
  )

  DRIVER = <<~RUBY
    module Rails
      def self.prepare_blocks
        @prepare_blocks ||= []
      end

      def self.application
        self
      end

      def self.config
        self
      end

      def self.to_prepare(&block)
        prepare_blocks << block
      end
    end

    module Api
      class BaseController
        Request = Struct.new(:session_options)

        def self.callbacks
          @callbacks ||= []
        end

        def self.prepend_before_action(&block)
          callbacks << block
        end

        def request
          @request ||= Request.new({})
        end
      end
    end

    load ARGV[0]
    puts Api::BaseController.callbacks.size
    Rails.prepare_blocks.each(&:call)
    puts Api::BaseController.callbacks.size
    controller = Api::BaseController.new
    Api::BaseController.callbacks.each { |callback| controller.instance_exec(&callback) }
    puts controller.request.session_options[:skip].inspect
  RUBY

  # Loads the initializer against stubbed Rails and Api::BaseController in a child ruby.
  #
  # @return [Array(Array<String>, String, Process::Status)] stdout lines, stderr and status
  def run_driver
    stdout, stderr, status = Open3.capture3(RbConfig.ruby, "-e", DRIVER, SCRIPT)
    [stdout.lines.map(&:strip), stderr, status]
  end

  def test_registration_waits_for_to_prepare
    lines, stderr, status = run_driver

    assert_predicate status, :success?, stderr
    assert_equal "0", lines[0]
    assert_equal "1", lines[1]
  end

  def test_api_requests_skip_the_session_commit
    lines, stderr, status = run_driver

    assert_predicate status, :success?, stderr
    assert_equal "true", lines[2]
  end
end
