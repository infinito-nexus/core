# frozen_string_literal: true

require "fileutils"
require "json"
require "minitest/autorun"
require "open3"
require "tmpdir"

class DecidimSameOriginStoragePatchTest < Minitest::Test
  SCRIPT = File.expand_path(
    "../../../../../../../roles/web-app-decidim/files/ruby/initializers/same_origin_storage.rb",
    __dir__
  )

  PREFIX = "/rails/active_storage"

  REQUESTS = [
    ["GET", "#{PREFIX}/blobs/redirect/SIGNED/logo.png"],
    ["HEAD", "#{PREFIX}/representations/proxy/SIGNED/VARIANT/logo.png"],
    ["POST", "#{PREFIX}/blobs/SIGNED/logo.png"],
    ["PUT", "#{PREFIX}/disk/signed-token"],
    ["GET", "#{PREFIX}/disk/signed-token"],
    ["GET", "/processes"],
  ].freeze

  LIBRARIES = {
    "active_storage/service/disk_service.rb" => <<~'RUBY',
      class ActiveStorage::Service::DiskService < ActiveStorage::Service
        def url_for_direct_upload(key, expires_in:, content_type:, content_length:, checksum:, custom_metadata: {})
          "/rails/active_storage/disk/stock-#{key}"
        end
      end
    RUBY
    "active_storage/service/s3_service.rb" => <<~'RUBY',
      class ActiveStorage::Service::S3Service < ActiveStorage::Service
        def name = "seaweedfs"

        def url_for_direct_upload(key, expires_in:, content_type:, content_length:, checksum:, custom_metadata: {})
          "https://api.seaweedfs.s3.example.com/decidim/#{key}?X-Amz-Signature=presigned"
        end

        def headers_for_direct_upload(key, content_type:, checksum:, filename: nil, disposition: nil, custom_metadata: {}, **)
          { "Content-Type" => content_type, "Content-MD5" => checksum, "x-amz-meta-key" => key }
        end

        def upload(key, io, checksum: nil, filename: nil, content_type: nil, disposition: nil, custom_metadata: {}, **); end
      end
    RUBY
    "rack/attack.rb" => <<~'RUBY',
      module Rack
        class Attack
          def self.safelists = (@safelists ||= {})

          def self.safelist(name, &block)
            safelists[name] = block
          end

          def self.safelisted?(request) = safelists.values.any? { |block| block.call(request) }
        end
      end
    RUBY
  }.freeze

  PRELUDE = <<~'RUBY'
    require "json"

    module ActiveStorage
      class Service
        def instrument(_operation, payload = {})
          yield payload
        end
      end

      module Verifier
        def self.generate(message, expires_in:, purpose:)
          @issued = { "message" => message, "expires_in" => expires_in, "purpose" => purpose }
          "signed-token"
        end

        def self.issued = @issued
      end

      def self.verifier = Verifier

      def self.routes_prefix = "/rails/active_storage"
    end

    module Decidim
      module ContentRenderers
        class BlobRenderer
          protected

          def blob_url(blob, variation = nil)
            "https://api.seaweedfs.s3.example.com/decidim/#{blob}/#{variation}"
          end

          def local_blob_url(blob, variation = nil)
            return "/rails/active_storage/blobs/redirect/#{blob}/file" if variation.nil?

            "/rails/active_storage/representations/redirect/#{blob}/#{variation}/file"
          end
        end
      end
    end

    module UrlHelpers
      def self.update_rails_disk_service_path(token) = "#{ActiveStorage.routes_prefix}/disk/#{token}"
    end

    class RouteSet
      def initialize
        @routes = []
        @prefix = ""
      end

      def url_helpers = UrlHelpers

      def prepend(&block)
        instance_eval(&block)
      end

      def scope(prefix)
        @prefix = prefix
        yield
      ensure
        @prefix = ""
      end

      def get(mapping)
        mapping.each { |path, action| @routes << [@prefix + path, action] }
      end
    end

    module Rails
      ActiveStorageConfig = Struct.new(:resolve_model_to_route)
      Config = Struct.new(:active_storage)

      module Application
        def self.config = (@config ||= Config.new(ActiveStorageConfig.new(:rails_storage_redirect)))

        def self.routes = (@routes ||= RouteSet.new)
      end

      def self.application = Application
    end
  RUBY

  DRIVER = <<~'RUBY'
    load ARGV.fetch(0)
    Request = Struct.new(:request_method, :path) do
      def get? = request_method == "GET"

      def head? = request_method == "HEAD"
    end
    service = ActiveStorage::Service::S3Service.new
    renderer = Decidim::ContentRenderers::BlobRenderer.new
    puts JSON.generate(
      {
        "resolve_model_to_route" => Rails.application.config.active_storage.resolve_model_to_route,
        "direct_upload_url" => service.url_for_direct_upload(
          "key-1", expires_in: 300, content_type: "image/png", content_length: 12, checksum: "c2hh"
        ),
        "direct_upload_token" => ActiveStorage.verifier.issued,
        "direct_upload_headers" => service.headers_for_direct_upload(
          "key-1", content_type: "image/png", checksum: "c2hh", filename: "logo.png"
        ),
        "blob_url" => renderer.send(:blob_url, "blob-1"),
        "representation_url" => renderer.send(:blob_url, "blob-1", "variant-1"),
        "blob_url_public" => Decidim::ContentRenderers::BlobRenderer.public_method_defined?(:blob_url),
        "safelisted" => JSON.parse(ENV.fetch("REQUESTS")).map { |verb, path| Rack::Attack.safelisted?(Request.new(verb, path)) },
      }
    )
  RUBY

  # @return [Array(Hash, String, Process::Status)] what the patched services answer, stderr and status
  def boot
    Dir.mktmpdir do |library|
      LIBRARIES.each do |path, source|
        FileUtils.mkdir_p(File.join(library, File.dirname(path)))
        File.write(File.join(library, path), source)
      end
      stdout, stderr, status = Open3.capture3(
        { "REQUESTS" => REQUESTS.to_json },
        RbConfig.ruby, "-I", library, "-e", "#{PRELUDE}\n#{DRIVER}", SCRIPT
      )
      [status.success? ? JSON.parse(stdout) : {}, stderr, status]
    end
  end

  def test_active_storage_routes_proxy_through_the_app
    report, stderr, status = boot

    assert_predicate status, :success?, stderr
    assert_equal "rails_storage_proxy", report.fetch("resolve_model_to_route")
  end

  def test_a_direct_upload_is_signed_for_the_same_origin_disk_route
    report, stderr, status = boot

    assert_predicate status, :success?, stderr
    assert_equal "#{PREFIX}/disk/signed-token", report.fetch("direct_upload_url")
    assert_equal "blob_token", report.fetch("direct_upload_token").fetch("purpose")
    assert_equal(
      {
        "key" => "key-1", "content_type" => "image/png", "content_length" => 12,
        "checksum" => "c2hh", "service_name" => "seaweedfs",
      },
      report.fetch("direct_upload_token").fetch("message")
    )
    assert_equal({ "Content-Type" => "image/png" }, report.fetch("direct_upload_headers"))
  end

  def test_rich_text_blobs_render_through_the_app_route
    report, stderr, status = boot

    assert_predicate status, :success?, stderr
    assert_equal "#{PREFIX}/blobs/redirect/blob-1/file", report.fetch("blob_url")
    assert_equal "#{PREFIX}/representations/redirect/blob-1/variant-1/file", report.fetch("representation_url")
    refute report.fetch("blob_url_public")
  end

  def test_only_storage_reads_skip_the_request_throttle
    report, stderr, status = boot

    assert_predicate status, :success?, stderr
    assert_equal [true, true, false, false, false, false], report.fetch("safelisted")
  end
end
