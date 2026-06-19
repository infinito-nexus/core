require "json"

host = ENV.fetch("NEXTCLOUD_HOST").sub(%r{/+\z}, "")
name = ENV.fetch("STORAGE_NAME")
nc_client_id = ENV["NC_OAUTH_CLIENT_ID"].to_s.strip
nc_client_secret = ENV["NC_OAUTH_CLIENT_SECRET"].to_s.strip
nc_has_op_secret = ENV["NC_HAS_OP_SECRET"].to_s.strip

admins = User.where(admin: true)
creator =
  (admins.respond_to?(:active) ? admins.active.first : nil) ||
  admins.first ||
  User.where(login: "admin").first

raise "No administrator user available to own the Nextcloud storage" if creator.nil?

storage = Storages::NextcloudStorage.find_by(host: host) ||
          Storages::NextcloudStorage.find_by(name: name)

if storage.nil?
  storage = Storages::NextcloudStorage.new(
    name: name,
    host: host,
    creator: creator
  )
  storage.authentication_method = "two_way_oauth2" if storage.respond_to?(:authentication_method=)
  storage.save!
else
  storage.update!(host: host) if storage.host != host
end

application = storage.oauth_application
op_client_secret = nil

if application && nc_client_id.empty? && nc_has_op_secret.empty?
  application.destroy
  storage.reload
  application = nil
end

if application.nil?
  result = ::OAuth::Applications::CreateService
    .new(user: creator)
    .call(
      name: "#{name} (Nextcloud)",
      redirect_uri: File.join(host, "index.php/apps/integration_openproject/oauth-redirect"),
      scopes: "api_v3",
      confidential: true,
      owner: creator,
      integration: storage
    )
  application = result.is_a?(ServiceResult) ? result.result : result
  op_client_secret = application.plaintext_secret if application.respond_to?(:plaintext_secret)
  storage.reload
end

if nc_client_id.present? && nc_client_secret.present?
  client = storage.oauth_client
  if client.nil? || client.client_id != nc_client_id
    if client
      client.destroy
      storage.reload
    end
    ::OAuthClients::CreateService
      .new(user: creator)
      .call(client_id: nc_client_id, client_secret: nc_client_secret, integration: storage)
    storage.reload
  end
end

puts JSON.generate(
  storage_id: storage.id,
  openproject_client_id: storage.oauth_application&.uid,
  openproject_client_secret: op_client_secret,
  nc_oauth_client_id: storage.oauth_client&.client_id,
  oauth_application_created: !op_client_secret.nil?
)
