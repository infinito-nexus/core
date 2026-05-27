# Identity and Access Management

IAM(Identity and Access Management) is setup via Keycloak and LDAP.

## OpenID Connect (OIDC) Support 🔐

OIDC is supported in this role (for example, via **Keycloak**). OIDC-specific tasks are included when enabled, allowing integration of external authentication providers seamlessly.

### Verify OIDC Configuration

```bash
compose exec -u www-data application /var/www/html/occ config:app:get sociallogin custom_providers
```

## LDAP

More information: <https://docs.nextcloud.com/server/latest/admin_manual/configuration_user/user_auth_ldap.html>

## Get LDAP Configuration

```bash
compose exec -u www-data application php occ ldap:show-config
```

## Get all relevant entries except password

```sql
SELECT * FROM `oc_appconfig` WHERE appid LIKE "%ldap%" and configkey != "s01ldap_agent_password";
```

## Update User with LDAP values

```bash
compose exec -it -u www-data application php occ ldap:check-user --update {{username}}
```

## Update LDAP Sync

```bash
compose exec -u www-data application php occ user:sync-account-data
```

### Update Each User

If you want to update **every LDAP user**, run:

```bash
for user in $(compose exec -u www-data application php occ user:list --output=json | jq -r 'keys[]'); do
    compose exec -u www-data application php occ ldap:check-user --update "$user"
done
```

### Unlink All

```bash
for user in $(compose exec -u www-data application php occ ldap:show-remnants | tail -n +3 | awk -F '|' '{print $2}' | tr -d ' ' | grep -v '^$'); do
    echo "Unlinking user from LDAP: $user"
    echo "y" | compose exec -T -u www-data application php occ ldap:reset-user "$user"
done
```

### Reset LDAP Links for Orphaned Users

Run this **corrected script**:

```bash
for user in $(compose exec -u www-data application php occ ldap:show-remnants | tail -n +3 | awk -F '|' '{print $2}' | tr -d ' ' | grep -v '^$'); do
    echo "Resetting LDAP link for user: $user"
    echo "y" | compose exec -T -u www-data application php occ ldap:reset-user "$user"
done
```

## Federation

If users are just created via Keycloak and not via LDAP, they have a different username. Due to this reaso concider to use LDAP to guaranty that the username is valid.
