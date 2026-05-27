# Security Guidelines 🛡️

Infinito.Nexus is designed with security in mind. However, while following our guidelines can greatly improve your system's security, no IT system can be 100% secure. Please report any vulnerabilities as soon as possible.

In addition to the user security guidelines, administrators have additional responsibilities to secure the entire system:

- **Deploy on an Encrypted Server**
  You SHOULD install Infinito.Nexus on an encrypted server to prevent hosting providers from accessing end-user data. For a practical guide on setting up an encrypted server, refer to the [Hetzner Arch LUKS repository](https://github.com/kevinveenbirkenbach/hetzner-arch-luks) 🔐. (Learn more about [disk encryption](https://en.wikipedia.org/wiki/Disk_encryption) on Wikipedia.)

- **Centralized User Management & SSO**
  For robust authentication and central user management, you SHOULD set up Infinito.Nexus using Keycloak and LDAP.
  This configuration enables centralized [Single Sign-On (SSO)](https://en.wikipedia.org/wiki/Single_sign-on), simplifying user management and boosting security.

- **Enforce 2FA and Use a Password Manager**
  Administrators MUST enforce [2FA](https://en.wikipedia.org/wiki/Multi-factor_authentication) and SHOULD use a password manager with auto-generated passwords. We recommend [KeePass](https://en.wikipedia.org/wiki/KeePass). The KeePass database can be stored securely in your Nextcloud instance and synchronized between devices.

- **Avoid Root Logins & Plaintext Passwords**
  Infinito.Nexus MUST NOT allow logging in via the root user or using simple passwords. Instead, an SSH key MUST be generated and transferred during system initialization. When executing commands as root, always use `sudo` (or, if necessary, `sudo su`, but only if you understand the risks). (More information on [SSH](https://en.wikipedia.org/wiki/Secure_Shell) and [sudo](https://en.wikipedia.org/wiki/Sudo) is available on Wikipedia.)

- **Manage Inventories Securely**
  Your inventories for running Infinito.Nexus MUST be managed in a separate repository and secured with tools such as [Ansible Vault](https://en.wikipedia.org/wiki/Encryption) 🔒. Sensitive credentials MUST NEVER be stored in plaintext; use a password file to secure these details.

- **Reporting Vulnerabilities**
  If you discover a security vulnerability in Infinito.Nexus, you MUST report it immediately through [SECURITY.md](../../SECURITY.md) and MUST NOT open a public issue. We encourage proactive vulnerability reporting so that issues can be addressed as quickly as possible.

By following these guidelines, both end users and administrators can achieve a high degree of security. Stay vigilant, keep your systems updated, and report any suspicious activity. While we strive for maximum security, no system is completely infallible.
