# frozen_string_literal: true

# Minitest plugin writing a junit-xml report to INFINITO_JUNIT_REPORT.

require "minitest"

module Minitest
  class InfinitoJUnitReporter < AbstractReporter
    # @param path [String] file the junit report is written to
    def initialize(path)
      super()
      @path = path
      @results = []
    end

    def record(result)
      @results << result
    end

    def report
      require "fileutils"
      FileUtils.mkdir_p(File.dirname(@path))
      File.write(@path, document)
    end

    private

    def document
      body = @results.map { |result| testcase(result) }
      ['<?xml version="1.0" encoding="utf-8"?>', "<testsuites>", *body, "</testsuites>", ""].join("\n")
    end

    def testcase(result)
      seconds = format("%.6f", result.time)
      head = "<testcase name=#{escape(result.name)} " \
             "classname=#{escape(result.klass)} time=\"#{seconds}\""
      body = outcome(result)
      body.empty? ? "#{head}/>" : "#{head}>#{body}</testcase>"
    end

    def outcome(result)
      return "" if result.failures.empty?

      failure = result.failures.first
      message = escape("#{failure.class}: #{failure.message}")
      return "<skipped message=#{message}/>" if result.skipped?

      tag = failure.is_a?(UnexpectedError) ? "error" : "failure"
      "<#{tag} message=#{message}/>"
    end

    def escape(value)
      quoted = value.to_s
                    .gsub("&", "&amp;")
                    .gsub("<", "&lt;")
                    .gsub(">", "&gt;")
                    .gsub('"', "&quot;")
      %("#{quoted}")
    end
  end

  # @param _options [Hash] minitest runner options, unused
  def self.plugin_infinito_junit_init(_options)
    path = ENV.fetch("INFINITO_JUNIT_REPORT", nil)
    reporter << InfinitoJUnitReporter.new(path) unless path.nil? || path.empty?
  end
end

Minitest.extensions << "infinito_junit"
