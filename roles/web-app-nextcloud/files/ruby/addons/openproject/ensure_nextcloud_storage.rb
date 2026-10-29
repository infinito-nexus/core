# nocheck: mirrored-unit-test - runs in the OpenProject console against
# Storages::NextcloudStorage; the model only exists once OpenProject has booted
# Param PROVISION_INPUT: defined ahead of this script on the same stdin, with the keys
# nextcloud_host, storage_name, nc_op_client_secret, rotate_op_secret,
# nc_oauth_client_id and nc_oauth_client_secret.
require "json"

host = PROVISION_INPUT.fetch("nextcloud_host").sub(%r{/+\z}, "")
name = PROVISION_INPUT.fetch("storage_name")
nc_client_id = PROVISION_INPUT.fetch("nc_oauth_client_id").to_s.strip
nc_client_secret = PROVISION_INPUT.fetch("nc_oauth_client_secret").to_s.strip
nc_op_client_secret = PROVISION_INPUT.fetch("nc_op_client_secret").to_s.strip
rotate_op_secret = PROVISION_INPUT.fetch("rotate_op_secret") == true

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

if application && nc_client_id.empty? && nc_op_client_secret.empty?
  application.destroy
  storage.reload
  application = nil
end

redirect_uri = [
  File.join(host, "apps/integration_openproject/oauth-redirect"),
  File.join(host, "index.php/apps/integration_openproject/oauth-redirect")
].join("\n")

if application.nil?
  result = ::OAuth::Applications::CreateService
    .new(user: creator)
    .call(
      name: "#{name} (Nextcloud)",
      redirect_uri: redirect_uri,
      scopes: "api_v3",
      confidential: true,
      owner: creator,
      integration: storage
    )
  if result.is_a?(ServiceResult) && !result.success?
    raise "OAuth application creation failed: #{result.errors.full_messages.join('; ')}"
  end

  application = result.is_a?(ServiceResult) ? result.result : result
  op_client_secret = application.plaintext_secret if application.respond_to?(:plaintext_secret)
  storage.reload
elsif rotate_op_secret || nc_op_client_secret.empty? || !application.secret_matches?(nc_op_client_secret)
  application.renew_secret
  application.save!
  op_client_secret = application.plaintext_secret || application.secret
  storage.reload
end

application.update!(redirect_uri: redirect_uri) if application.redirect_uri != redirect_uri

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
  oauth_application_secret_issued: !op_client_secret.nil?
)
