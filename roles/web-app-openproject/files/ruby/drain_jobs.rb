# frozen_string_literal: true

performer = GoodJob::JobPerformer.new("*")
performed = 0
failed = 0

while (result = Rails.application.executor.wrap { performer.next })
  performed += 1
  next unless result.unhandled_error

  failed += 1
  warn("drain_jobs: #{result.unhandled_error.class}: #{result.unhandled_error.message}")
end

if GoodJob.respond_to?(:v4_ready?) && !GoodJob.v4_ready?
  abort("drain_jobs: GoodJob still holds unfinished jobs that the next major cannot run; " \
        "run the worker of this major until they finish, then deploy again")
end

puts("drain_jobs: performed #{performed} job(s), #{failed} failed")
