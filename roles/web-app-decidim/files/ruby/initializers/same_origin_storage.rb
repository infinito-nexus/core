# nocheck: mirrored-unit-test - a Rails initializer the Dockerfile copies into /code/config/initializers; it patches ActiveStorage while Decidim boots and only loads inside that Rails app
require "active_storage/service/disk_service"
require "active_storage/service/s3_service"
require "rack/attack"

module InfinitoSameOriginStorage
  SIGNATURES = {
    [ActiveStorage::Service::S3Service, :url_for_direct_upload] => [
      [:req, :key], [:keyreq, :expires_in], [:keyreq, :content_type],
      [:keyreq, :content_length], [:keyreq, :checksum], [:key, :custom_metadata]
    ],
    [ActiveStorage::Service::DiskService, :url_for_direct_upload] => [
      [:req, :key], [:keyreq, :expires_in], [:keyreq, :content_type],
      [:keyreq, :content_length], [:keyreq, :checksum], [:key, :custom_metadata]
    ],
    [ActiveStorage::Service::S3Service, :headers_for_direct_upload] => [
      [:req, :key], [:keyreq, :content_type], [:keyreq, :checksum], [:key, :filename],
      [:key, :disposition], [:key, :custom_metadata], [:keyrest, :**]
    ],
    [ActiveStorage::Service::S3Service, :upload] => [
      [:req, :key], [:req, :io], [:key, :checksum], [:key, :filename], [:key, :content_type],
      [:key, :disposition], [:key, :custom_metadata], [:keyrest, :**]
    ],
    [Decidim::ContentRenderers::BlobRenderer, :blob_url] => [
      [:req, :blob], [:opt, :variation]
    ],
    [Decidim::ContentRenderers::BlobRenderer, :local_blob_url] => [
      [:req, :blob], [:opt, :variation]
    ]
  }.freeze

  SIGNATURES.each do |(owner, method), expected|
    actual = owner.instance_method(method).parameters
    next if actual == expected

    raise "#{owner}##{method} takes #{actual.inspect}; the same-origin storage patch " \
          "was written against #{expected.inspect} (activestorage 7.2.2.2, decidim 0.31.6)"
  end

  module DirectUpload
    def url_for_direct_upload(key, expires_in:, content_type:, content_length:, checksum:, custom_metadata: {})
      instrument :url, key: key do |payload|
        token = ActiveStorage.verifier.generate(
          { key: key, content_type: content_type, content_length: content_length, checksum: checksum, service_name: name },
          expires_in: expires_in,
          purpose: :blob_token
        )
        payload[:url] = Rails.application.routes.url_helpers.update_rails_disk_service_path(token)
      end
    end

    def headers_for_direct_upload(key, content_type:, **)
      { "Content-Type" => content_type }
    end
  end

  module LocalBlobUrl
    protected

    def blob_url(blob, variation = nil)
      local_blob_url(blob, variation)
    end
  end

  def self.storage_read?(request)
    (request.get? || request.head?) &&
      request.path.start_with?("#{ActiveStorage.routes_prefix}/blobs/", "#{ActiveStorage.routes_prefix}/representations/")
  end
end

ActiveStorage::Service::S3Service.prepend(InfinitoSameOriginStorage::DirectUpload)
Decidim::ContentRenderers::BlobRenderer.prepend(InfinitoSameOriginStorage::LocalBlobUrl)
Rails.application.config.active_storage.resolve_model_to_route = :rails_storage_proxy

Rails.application.routes.prepend do
  scope ActiveStorage.routes_prefix do
    get "/blobs/redirect/:signed_id/*filename" => "active_storage/blobs/proxy#show"
    get "/blobs/proxy/:signed_id/*filename" => "active_storage/blobs/proxy#show"
    get "/blobs/:signed_id/*filename" => "active_storage/blobs/proxy#show"
    get "/representations/redirect/:signed_blob_id/:variation_key/*filename" => "active_storage/representations/proxy#show"
    get "/representations/proxy/:signed_blob_id/:variation_key/*filename" => "active_storage/representations/proxy#show"
    get "/representations/:signed_blob_id/:variation_key/*filename" => "active_storage/representations/proxy#show"
  end
end

Rack::Attack.safelist("same-origin storage reads") { |request| InfinitoSameOriginStorage.storage_read?(request) }
