# frozen_string_literal: true

require "minitest/autorun"
require "open3"

class RunStepsTest < Minitest::Test
  DRIVER = File.expand_path(
    "../../../../../../roles/web-app-gitlab/files/ruby/run_steps.rb",
    __dir__
  )

  RAILS_RUNNER_STDIN = 'eval($stdin.read, TOPLEVEL_BINDING, "stdin")'

  # @param steps [Hash{String => String}] step label to its Ruby body
  # @return [Array(String, String, Process::Status)] stdout, stderr and status
  def run_steps(steps)
    program = +File.read(DRIVER)
    steps.each do |label, body|
      program << "\nInfinitoSteps.run('#{label}') do\n#{body}\nend\n"
    end
    program << "InfinitoSteps.finish\n"
    Open3.capture3(RbConfig.ruby, "-e", RAILS_RUNNER_STDIN, stdin_data: program)
  end

  def test_an_early_exit_ends_only_its_own_step
    stdout, _stderr, status = run_steps(
      "first" => "puts '[UNCHANGED] first'\nexit(0)\nputs 'unreachable'",
      "second" => "puts '[CHANGED] second'"
    )

    assert_predicate status, :success?
    assert_equal "first: [UNCHANGED] first\nsecond: [CHANGED] second\n", stdout
  end

  def test_an_abort_fails_its_step_and_the_others_still_run
    stdout, stderr, status = run_steps(
      "first" => "abort('[FAIL] no user named root')",
      "second" => "puts '[UNCHANGED] second'"
    )

    refute_predicate status, :success?
    assert_includes stdout, "first: [FAIL] no user named root\n"
    assert_includes stdout, "second: [UNCHANGED] second\n"
    assert_match(/\[FAIL\] failed steps: first$/, stderr)
  end

  def test_an_exception_fails_its_step_by_name
    stdout, _stderr, status = run_steps(
      "first" => "puts 'before'\nraise ArgumentError, 'record invalid'",
      "second" => "puts '[UNCHANGED] second'"
    )

    refute_predicate status, :success?
    assert_includes stdout, "first: before\nfirst: [FAIL] ArgumentError: record invalid\n"
    assert_includes stdout, "second: [UNCHANGED] second\n"
  end

  def test_every_failed_step_is_named
    stdout, stderr, status = run_steps(
      "first" => "abort('[FAIL] one')",
      "second" => "puts '[CHANGED] two'",
      "third" => "exit(3)"
    )

    refute_predicate status, :success?
    assert_includes stdout, "second: [CHANGED] two\n"
    assert_includes stdout, "third: [FAIL] exit\n"
    assert_match(/\[FAIL\] failed steps: first, third$/, stderr)
  end

  def test_locals_stay_inside_their_step
    stdout, _stderr, status = run_steps(
      "first" => "user = 'root'\nputs \"[UNCHANGED] \#{user}\"",
      "second" => "puts(defined?(user) ? '[FAIL] leaked' : '[UNCHANGED] isolated')"
    )

    assert_predicate status, :success?
    assert_includes stdout, "second: [UNCHANGED] isolated\n"
  end
end
