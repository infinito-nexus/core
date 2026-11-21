# frozen_string_literal: true

if ENV["OIDC_ENABLED"] == "true"
  module InfinitoOidcRoleSync
    MANAGED_ROLE_NAMES = %w(Admin Moderator).freeze

    def find_for_omniauth(auth, signed_in_resource = nil)
      user = super
      InfinitoOidcRoleSync.sync(user, auth) if user&.persisted? && auth.provider.to_s == "openid_connect"
      user
    end

    def self.groups_from(auth)
      raw_info = auth["extra"] && auth["extra"]["raw_info"]
      Array(raw_info && raw_info[ENV.fetch("OIDC_RBAC_GROUPS_CLAIM")]).map(&:to_s)
    end

    def self.target_role_name(groups)
      return "Admin" if groups.include?(ENV.fetch("OIDC_RBAC_ADMINISTRATOR_GROUP"))
      return "Moderator" if groups.include?(ENV.fetch("OIDC_RBAC_MODERATOR_GROUP"))

      nil
    end

    def self.sync(user, auth)
      current = user.role_id && UserRole.find_by(id: user.role_id)
      return if current && !MANAGED_ROLE_NAMES.include?(current.name)

      target_name = target_role_name(groups_from(auth))
      target = target_name && UserRole.find_by!(name: target_name)
      return if user.role_id == target&.id

      user.update!(role: target)
    end
  end

  Rails.application.config.to_prepare do
    User.singleton_class.prepend(InfinitoOidcRoleSync)
  end
end
