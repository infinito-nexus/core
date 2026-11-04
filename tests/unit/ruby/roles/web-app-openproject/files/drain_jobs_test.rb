# frozen_string_literal: true

require "minitest/autorun"
require "open3"

class DrainJobsTest < Minitest::Test
  SCRIPT = File.expand_path(
    "../../../../../../roles/web-app-openproject/files/ruby/drain_jobs.rb",
    __dir__
  )

  PRELUDE = <<~RUBY
    Result = Struct.new(:unhandled_error)

    module Rails
      def self.application
        self
      end

      def self.executor
        self
      end

      def self.wrap
        yield
      end
    end

    module GoodJob
      class JobPerformer
        def initialize(queue_string)
          raise ArgumentError, queue_string unless queue_string == "*"

          @jobs = ENV.fetch("JOBS").split(",")
        end

        def next
          job = @jobs.shift
          return nil if job.nil?

          Result.new(job == "fail" ? RuntimeError.new("boom") : nil)
        end
      end

      if ENV.fetch("V4_READY") != "absent"
        def self.v4_ready?
          ENV.fetch("V4_READY") == "true"
        end
      end
    end
  RUBY

  # @param jobs [String] comma-separated job outcomes, "ok" or "fail"
  # @param v4_ready [String] "true", "false", or "absent" for a GoodJob without the check
  # @return [Array(String, String, Process::Status)] stdout, stderr and status
  def drain(jobs:, v4_ready:)
    Open3.capture3(
      { "JOBS" => jobs, "V4_READY" => v4_ready },
      RbConfig.ruby, "-e", "#{PRELUDE}\nload ARGV[0]", SCRIPT
    )
  end

  def test_every_ready_job_is_performed
    stdout, _stderr, status = drain(jobs: "ok,ok,ok", v4_ready: "true")

    assert_predicate status, :success?
    assert_match(/performed 3 job\(s\), 0 failed/, stdout)
  end

  def test_an_empty_queue_drains_at_once
    stdout, _stderr, status = drain(jobs: "", v4_ready: "true")

    assert_predicate status, :success?
    assert_match(/performed 0 job\(s\)/, stdout)
  end

  def test_a_failing_job_does_not_stop_the_drain
    stdout, stderr, status = drain(jobs: "fail,ok", v4_ready: "true")

    assert_predicate status, :success?
    assert_match(/performed 2 job\(s\), 1 failed/, stdout)
    assert_match(/RuntimeError: boom/, stderr)
  end

  def test_jobs_the_next_good_job_cannot_run_stop_the_step
    _stdout, stderr, status = drain(jobs: "ok", v4_ready: "false")

    refute_predicate status, :success?
    assert_match(/unfinished jobs/, stderr)
  end

  def test_a_good_job_without_the_v4_check_passes
    stdout, _stderr, status = drain(jobs: "ok", v4_ready: "absent")

    assert_predicate status, :success?
    assert_match(/performed 1 job\(s\)/, stdout)
  end
end
