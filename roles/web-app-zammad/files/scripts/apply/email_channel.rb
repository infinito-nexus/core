UserInfo.current_user_id = 1

group = Group.find_or_create_by!(name: ENV.fetch("MAIL_GROUP_NAME")) do |g|
  g.active = true
end

smtp_port      = Integer(ENV.fetch("SMTP_PORT"))
smtp_use_ssl   = smtp_port == 465
smtp_start_tls = !smtp_use_ssl

channel = Channel.find_or_initialize_by(area: "Email::Account", group_id: group.id)
channel.options = {
  inbound: {
    adapter: "imap",
    options: {
      host:           ENV.fetch("IMAP_HOST"),
      port:           Integer(ENV.fetch("IMAP_PORT")),
      ssl:            "starttls",
      user:           ENV.fetch("IMAP_USER"),
      password:       ENV.fetch("IMAP_PASS"),
      folder:         "INBOX",
      keep_on_server: false,
    },
  },
  outbound: {
    adapter: "smtp",
    options: {
      host:      ENV.fetch("SMTP_HOST"),
      port:      smtp_port,
      ssl:       smtp_use_ssl,
      start_tls: smtp_start_tls,
      user:      ENV.fetch("SMTP_USER"),
      password:  ENV.fetch("SMTP_PASS"),
    },
  },
}
channel.active = true
channel.save!

addr = EmailAddress.find_or_initialize_by(email: ENV.fetch("MAIL_FROM_ADDRESS"))
addr.name       = ENV.fetch("MAIL_FROM_NAME")
addr.channel_id = channel.id
addr.active     = true
addr.save!
