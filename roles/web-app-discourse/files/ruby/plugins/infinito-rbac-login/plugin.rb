# frozen_string_literal: true
# nocheck: comments-valid - Discourse loads this as a plugin and reads its metadata from the
# header comments below
# name: infinito-rbac-login
# about: Sets the admin and moderator flags from the role groups of every OIDC sign-in
# version: 1.0.0
# authors: Infinito.Nexus

module ::InfinitoRbacLogin
  GROUPS_KEY = :infinito_rbac_groups
  ADMINISTRATOR_GROUP = ENV.fetch("INFINITO_RBAC_ADMINISTRATOR_GROUP")
  MODERATOR_GROUP = ENV.fetch("INFINITO_RBAC_MODERATOR_GROUP")
  KEPT_ADMINISTRATOR = ENV.fetch("INFINITO_RBAC_KEPT_ADMINISTRATOR")

  # @param auth_token [OmniAuth::AuthHash] the token the OIDC strategy hands the authenticator
  # @return [Array<String>, nil] the groups claim, nil when the token carries no list under it
  def self.groups_from(auth_token)
    claim = SiteSetting.openid_connect_groups_claim
    groups = auth_token.extra&.dig(:raw_info, claim) || auth_token.extra&.dig(:id_token_info, claim)
    groups.map(&:to_s) if groups.is_a?(Array)
  end

  # @param user [User] the account that signs in
  # @param groups [Array<String>] the groups claim of the sign-in
  def self.apply(user, groups)
    kept = user.username_lower == User.normalize_username(KEPT_ADMINISTRATOR)
    administrator = kept ? user.admin : groups.include?(ADMINISTRATOR_GROUP)
    if administrator && !user.admin
      user.grant_admin!
    elsif !administrator && user.admin
      user.revoke_admin!
    end

    moderator = groups.include?(MODERATOR_GROUP)
    if moderator && !user.moderator
      user.grant_moderation!
    elsif !moderator && user.moderator
      user.revoke_moderation!
    end
  end

  module Authenticator
    def after_authenticate(auth_token, existing_account: nil)
      result = super
      groups = InfinitoRbacLogin.groups_from(auth_token)
      return result if groups.nil?

      result.extra_data[GROUPS_KEY] = groups
      user = result.user
      InfinitoRbacLogin.apply(user, groups) if user && !user.staged
      result
    end

    def after_create_account(user, auth_result)
      super
      groups = auth_result.extra_data[GROUPS_KEY]
      InfinitoRbacLogin.apply(user, groups) unless groups.nil?
    end
  end

  module NoBootstrapModeration
    private

    # Replaces the whole upstream method: Discourse main (after v2026.10.2) also
    # runs DiscoursePluginRegistry.first_admin_bootstrap callbacks there, which
    # this override would drop; recheck at every Discourse bump.
    # @param _user [User] the only admin, signing in for the first time
    # @return [nil] the moderator flag stays with the moderator role group
    def bootstrap_first_admin(_user)
      nil
    end
  end
end

after_initialize do
  OpenIDConnectAuthenticator.prepend(InfinitoRbacLogin::Authenticator)
  Auth::DefaultCurrentUserProvider.prepend(InfinitoRbacLogin::NoBootstrapModeration)
end
