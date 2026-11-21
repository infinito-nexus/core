# nocheck: mirrored-unit-test - a Rails initializer that subscribes to Decidim's
# omniauth notifications and writes through Decidim::User; it only runs inside the
# booted Decidim app
#
# Env:
#   OIDC_ENABLED: "true" activates the subscription.
#   OIDC_GROUPS_CLAIM: name of the groups claim in the userinfo response.
#   OIDC_ADMIN_GROUP: groups claim path that grants Decidim::User#admin.
#   OIDC_USER_MANAGER_GROUP: groups claim path that grants the user_manager role.
#   DECIDIM_BOOTSTRAP_ADMIN_EMAIL: email of the account the deploy converges itself.

if ENV["OIDC_ENABLED"].to_s == "true"
  Rails.application.config.after_initialize do
    infinito_rbac = proc do |*args|
      data = args.last.to_h.deep_symbolize_keys
      user = Decidim::User.find_by(id: data[:user_id])
      next if user.nil?
      next if user.email.to_s.casecmp?(ENV.fetch("DECIDIM_BOOTSTRAP_ADMIN_EMAIL"))
      next unless user.identities.exists?(provider: data[:provider].to_s)

      raw_info = data.dig(:raw_data, :extra, :raw_info) || {}
      groups = Array(raw_info[ENV.fetch("OIDC_GROUPS_CLAIM").to_sym]).map(&:to_s)

      roles = Array(user.roles) - ["user_manager"]
      roles += ["user_manager"] if groups.include?(ENV.fetch("OIDC_USER_MANAGER_GROUP"))
      user.admin = groups.include?(ENV.fetch("OIDC_ADMIN_GROUP"))
      user.roles = roles
      user.save!(validate: false) if user.changed?
    end

    ActiveSupport::Notifications.subscribe("decidim.user.omniauth_registration", &infinito_rbac)
    ActiveSupport::Notifications.subscribe("decidim.user.omniauth_login", &infinito_rbac)
  end
end
