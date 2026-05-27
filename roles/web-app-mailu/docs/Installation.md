# Installation ⚙️

## Fetchmail Issues 📨

Fetchmail might not work properly with large amounts of data. For more information, refer to this [issue](https://github.com/Mailu/Mailu/issues/1719).

## Deactivating Fetchmail ❌

Before uninstalling Fetchmail, ensure you remove all fetched accounts from the administration panel.

## Fetchmail Security Concerns 🔐

There are known security concerns with Fetchmail as stated in the [German Wikipedia](https://de.wikipedia.org/wiki/Fetchmail). If you require Fetchmail functions in the future, consider creating a Docker container for [Getmail](https://en.wikipedia.org/wiki/Getmail) as it is considered more secure.

## Fetchmail Workaround 🔄

If you need to receive emails from another account, follow these steps:

1. Redirect your emails to your new email account.
2. Export all data from your original account.
3. Import all data to your new account.

## Port Management 🌐

Check for any port conflicts and manually change the conflicting ports if necessary. Use the following command to verify:

```bash
netstat -tulpn
```

## Admin Account Creation 👤

To use Mailu, create the primary administrator user account, `admin@{{hostname}}`, using the command below. Replace `PASSWORD` with your preferred password:

```bash
compose -p mailu exec admin flask mailu admin {{admin}} {{hostname}} PASSWORD
```

## CLI User Management 🛠️

For managing users, follow the instructions in the official [Mailu CLI documentation](https://mailu.io/master/cli.html).

## Starting the Server ▶️

To start the server, use the following command:

```bash
compose -p mailu up -d
```

## OIDC Support 🔐

This role now supports OpenID Connect (OIDC) authentication with [Mailu-OIDC](https://github.com/heviat/Mailu-OIDC)! 🎉

To enable OIDC authentication, simply set the following variable:

```yaml
oidc:
  enabled: true
```

For more details, check out the [Mailu-OIDC repository](https://github.com/heviat/Mailu-OIDC/tree/2024.06).
