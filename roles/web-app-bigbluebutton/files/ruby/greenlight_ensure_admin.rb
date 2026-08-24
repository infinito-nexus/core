# frozen_string_literal: true
# nocheck: mirrored-unit-test - runs in `rails runner` against Greenlight's User and
# Role models; the constants only exist once the app has booted

require "base64"

new_name            = ENV.fetch("NEW_NAME")
new_email           = ENV.fetch("NEW_EMAIL").downcase
default_admin_email = ENV.fetch("DEFAULT_ADMIN_EMAIL", "admin@example.com").downcase
new_pw_b64          = ENV.fetch("NEW_PASSWORD_B64")

new_pw = Base64.decode64(new_pw_b64)
new_pw = new_pw.force_encoding("UTF-8")
new_pw = new_pw.encode("UTF-8", invalid: :replace, undef: :replace, replace: "?")

def blankish?(v)
  v.nil? || (v.respond_to?(:empty?) && v.empty?)
end

def ensure_attr!(obj, attr, value)
  return false unless obj.respond_to?(attr) && obj.respond_to?(:"#{attr}=")
  cur = obj.public_send(attr)
  return false unless blankish?(cur)
  obj.public_send(:"#{attr}=", value)
  true
end

admin_role =
  Role.where("lower(name) = ?", "administrator").first ||
  Role.where("lower(name) = ?", "superadmin").first ||
  Role.first

raise "no role found in Role table" unless admin_role

user =
  User.find_by(email: new_email) ||
  User.where("lower(email) = ?", new_email).first ||
  User.find_by(email: default_admin_email) ||
  User.where("lower(email) = ?", default_admin_email).first

changed = false

if user
  if user.respond_to?(:name=) && user.name != new_name
    user.name = new_name
    changed = true
  end

  if user.email.to_s.downcase != new_email
    user.email = new_email
    changed = true
  end

  changed ||= ensure_attr!(user, :provider, "greenlight")
  changed ||= ensure_attr!(user, :language, "en")

  if user.respond_to?(:role=) && user.respond_to?(:role_id)
    if user.role_id != admin_role.id
      user.role = admin_role
      changed = true
    end
  end

  user.password = new_pw
  user.password_confirmation = new_pw if user.respond_to?(:password_confirmation=)
  changed = true
else
  attrs = {
    email: new_email,
    password: new_pw,
    provider: "greenlight",
    language: "en",
    role: admin_role,
  }
  attrs[:name] = new_name if User.new.respond_to?(:name=)

  user = User.create!(attrs)
  changed = true
end

user.save!

puts(changed ? "CHANGED id=#{user.id} email=#{user.email}" : "NOOP id=#{user.id} email=#{user.email}")
