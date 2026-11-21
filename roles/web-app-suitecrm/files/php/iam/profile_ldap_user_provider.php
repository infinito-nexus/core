<?php

/**
 * LDAP user provider of the auto-create login. Absent extra fields are skipped, where Symfony's
 * provider refuses the whole account with "Missing attribute". The profile columns are written at
 * every lookup, which the LDAP login runs before it checks the password.
 *
 * Env of the container, from templates/env.j2 (AUTH_TYPE=ldap):
 *   LDAP_PROVIDER_BASE_DN, LDAP_PROVIDER_SEARCH_DN, LDAP_PROVIDER_SEARCH_PASSWORD,
 *   LDAP_PROVIDER_DEFAULT_ROLES, LDAP_PROVIDER_UID_KEY, LDAP_PROVIDER_FILTER
 *   SUITECRM_LDAP_PROFILE_COLUMNS   JSON object: directory attribute => {"column": users column, "length": maximum characters}
 *
 * Parameter, from templates/ldap.yaml.j2:
 *   ldap.autocreate.extra_fields_map   directory attribute => SuiteCRM user field of a created account
 */

declare(strict_types=1);

namespace App\Extension\Iam\backend\Security;

use Doctrine\DBAL\Connection;
use InvalidArgumentException;
use Symfony\Component\DependencyInjection\Attribute\AsDecorator;
use Symfony\Component\DependencyInjection\Attribute\Autowire;
use Symfony\Component\DependencyInjection\ContainerInterface;
use Symfony\Component\Ldap\Entry;
use Symfony\Component\Ldap\Ldap;
use Symfony\Component\Ldap\LdapInterface;
use Symfony\Component\Ldap\Security\LdapUser;
use Symfony\Component\Ldap\Security\LdapUserProvider;
use Symfony\Component\Security\Core\User\UserInterface;

#[AsDecorator(decorates: 'security.user.provider.concrete.ldap_users', onInvalid: ContainerInterface::IGNORE_ON_INVALID_REFERENCE)]
final class ProfileLdapUserProvider extends LdapUserProvider
{
    private const COLUMN = '/^[a-z][a-z0-9_]*$/';

    private array $roles;

    private array $fields;

    private array $profileColumns = [];

    public function __construct(
        private readonly Connection $connection,
        #[Autowire(service: Ldap::class)] LdapInterface $ldap,
        #[Autowire(env: 'LDAP_PROVIDER_BASE_DN')] string $baseDn,
        #[Autowire(env: 'LDAP_PROVIDER_SEARCH_DN')] string $searchDn,
        #[Autowire(env: 'LDAP_PROVIDER_SEARCH_PASSWORD')] string $searchPassword,
        #[Autowire(env: 'csv:LDAP_PROVIDER_DEFAULT_ROLES')] array $defaultRoles,
        #[Autowire(env: 'LDAP_PROVIDER_UID_KEY')] string $uidKey,
        #[Autowire(env: 'LDAP_PROVIDER_FILTER')] string $filter,
        #[Autowire('%ldap.autocreate.extra_fields_map%')] array $fieldMap,
        #[Autowire(env: 'json:SUITECRM_LDAP_PROFILE_COLUMNS')] array $profileColumns,
    ) {
        parent::__construct($ldap, $baseDn, $searchDn, $searchPassword, $defaultRoles, $uidKey, $filter, null, []);
        $this->roles = $defaultRoles;
        $this->fields = array_values(array_filter(array_keys($fieldMap), 'is_string'));

        foreach ($profileColumns as $attribute => $target) {
            $column = is_array($target) ? ($target['column'] ?? null) : null;
            $length = is_array($target) ? ($target['length'] ?? null) : null;
            if (!is_string($attribute) || !is_string($column) || preg_match(self::COLUMN, $column) !== 1 || !is_int($length) || $length < 1) {
                throw new InvalidArgumentException("SUITECRM_LDAP_PROFILE_COLUMNS holds an invalid entry for {$attribute}");
            }
            $this->profileColumns[$attribute] = ['column' => $column, 'length' => $length];
        }
    }

    protected function loadUser(string $identifier, Entry $entry): UserInterface
    {
        $extraFields = [];
        foreach ($this->fields as $field) {
            $values = self::values($entry, $field);
            if ($values !== []) {
                $extraFields[$field] = $values;
            }
        }

        $this->writeProfile($identifier, $entry);

        return new LdapUser($entry, $identifier, null, $this->roles, $extraFields);
    }

    private function writeProfile(string $identifier, Entry $entry): void
    {
        $assignments = [];
        $values = [];
        foreach ($this->profileColumns as $attribute => $target) {
            $value = self::values($entry, $attribute)[0] ?? null;
            if ($value === null) {
                continue;
            }
            $assignments[] = $target['column'] . ' = ?';
            $values[] = mb_substr($value, 0, $target['length']);
        }

        if ($identifier === '' || $assignments === []) {
            return;
        }

        $values[] = strtolower($identifier);
        $this->connection->executeStatement(
            'UPDATE users SET ' . implode(', ', $assignments) . ' WHERE deleted = 0 AND LOWER(user_name) = ?',
            $values
        );
    }

    /**
     * @return string[]
     */
    private static function values(Entry $entry, string $attribute): array
    {
        $values = $entry->getAttribute($attribute, false);
        if (!is_array($values)) {
            return [];
        }

        return array_values(array_filter($values, static fn ($value): bool => is_string($value) && $value !== ''));
    }
}
