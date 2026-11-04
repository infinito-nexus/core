# Param: label  name InfinitoSteps.run puts before every stdout line of the step and into its [FAIL] verdict
# Param: block  the step; exit(0) ends only the step, abort or an exception fails only the step
#
# Exit: InfinitoSteps.finish exits 1 when any step failed, after every step ran.
require 'stringio'

module InfinitoSteps
  @failed = []

  def self.run(label)
    stdout = $stdout
    $stdout = StringIO.new
    failure = nil
    begin
      yield
    rescue SystemExit => e
      failure = e.message.delete_prefix('[FAIL] ') unless e.success?
    rescue StandardError, ScriptError => e
      failure = "#{e.class}: #{e.message}"
    ensure
      captured = $stdout.string
      $stdout = stdout
      captured.each_line { |line| puts "#{label}: #{line}" }
    end
    return if failure.nil?

    @failed << label
    puts "#{label}: [FAIL] #{failure}"
  end

  def self.finish
    abort("[FAIL] failed steps: #{@failed.join(', ')}") unless @failed.empty?
  end
end
