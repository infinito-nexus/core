<?php

namespace Espo\Modules\InfinitoRbac\Classes\Authentication;

use Espo\Core\Acl\Cache\Clearer as AclCacheClearer;
use Espo\Core\Api\Request;
use Espo\Core\Authentication\AuthenticationData;
use Espo\Core\Authentication\Hook\OnResult;
use Espo\Core\Authentication\Ldap\Client;
use Espo\Core\Authentication\Ldap\ClientFactory;
use Espo\Core\Authentication\Ldap\LdapLogin;
use Espo\Core\Authentication\Ldap\Utils as LdapUtils;
use Espo\Core\Authentication\Result;
use Espo\Core\Authentication\Util\MethodProvider;
use Espo\Core\ORM\EntityManager;
use Espo\Core\Utils\Config;
use Espo\Core\Utils\Log;
use Espo\Entities\User;
use Laminas\Ldap\Exception\LdapException;
use RuntimeException;

/**
 * Sign-in hook that sets the teams and type of an LDAP account from its role groups in the directory.
 *
 * Config (written by files/php/seed/rbac.php):
 *   infinitoLdapMemberOfAttribute    attribute of a directory account that lists the DNs of its groups
 *   infinitoLdapTeamGroups           {team id: role group DN} of the teams the role groups grant
 *   infinitoLdapAdministratorGroups  role group DNs whose members are EspoCRM administrators
 *   infinitoOidcProtectedUsers       usernames whose type and teams stay untouched
 *   ldap*                            EspoCRM's own LDAP settings, for the connection and the account search
 */
class LdapRoleGroups implements OnResult
{
    private const FILTER_ESCAPES = [
        '\\' => '\\5c',
        '*' => '\\2a',
        '(' => '\\28',
        ')' => '\\29',
        "\x00" => '\\00',
    ];

    public function __construct(
        private MethodProvider $methodProvider,
        private ClientFactory $clientFactory,
        private EntityManager $entityManager,
        private Config $config,
        private AclCacheClearer $aclCacheClearer,
        private Log $log,
    ) {}

    public function process(Result $result, AuthenticationData $data, Request $request): void
    {
        $user = $result->getUser();

        if ($user === null || ($data->getMethod() ?? $this->methodProvider->get()) !== LdapLogin::NAME) {
            return;
        }

        if (!in_array($user->get('type'), [User::TYPE_ADMIN, User::TYPE_REGULAR], true)) {
            return;
        }

        $username = strtolower((string) $user->getUserName());

        if (in_array($username, $this->configList('infinitoOidcProtectedUsers'), true)) {
            return;
        }

        $teamGroups = $this->teamGroups();
        $administratorGroups = $this->configList('infinitoLdapAdministratorGroups');
        $memberOf = $this->memberOf($username);

        if ($memberOf === null) {
            return;
        }

        $type = array_intersect($administratorGroups, $memberOf) !== [] ? User::TYPE_ADMIN : User::TYPE_REGULAR;
        $managed = array_map('strval', array_keys($teamGroups));
        $granted = array_map('strval', array_keys(array_intersect($teamGroups, $memberOf)));

        $user->loadLinkMultipleField('teams');
        $current = $user->getLinkMultipleIdList('teams');
        $wanted = array_values(array_unique(array_merge(array_diff($current, $managed), $granted)));
        sort($current);
        sort($wanted);

        if ($user->get('type') === $type && $current === $wanted) {
            return;
        }

        $user->set('type', $type);

        if ($current !== $wanted) {
            $user->set('teamsIds', $wanted);
        }

        $this->entityManager->saveEntity($user);
        $this->aclCacheClearer->clearForUser($user);
        $this->log->info("InfinitoRbac: the sign-in of `{$username}` applied type `{$type}` and the teams of its role groups.");
    }

    /**
     * @return ?string[] lowercased DNs of the account's groups, null when the directory could not be read
     */
    private function memberOf(string $username): ?array
    {
        $utils = new LdapUtils($this->config);
        $options = $utils->getOptions();
        $attribute = $this->configString('infinitoLdapMemberOfAttribute');
        $filter = sprintf(
            '(&(objectClass=%s)(%s=%s))',
            $this->option($options, 'userObjectClass'),
            $this->option($options, 'userNameAttribute'),
            strtr($username, self::FILTER_ESCAPES)
        );

        try {
            $client = $this->clientFactory->create($utils->getLdapClientOptions());
            $client->bind();
            $entries = $client->searchEntries($filter, null, Client::SEARCH_SCOPE_SUB, [$attribute]);
        } catch (LdapException $exception) {
            $this->log->error(
                "InfinitoRbac: the role groups of `{$username}` could not be read from the directory; " .
                "its teams and type stay until the next RBAC run.",
                ['exception' => $exception]
            );

            return null;
        }

        return array_map('strtolower', $entries[0][strtolower($attribute)] ?? []);
    }

    /**
     * @return array<string, string> lowercased role group DN per team id
     */
    private function teamGroups(): array
    {
        $value = $this->config->get('infinitoLdapTeamGroups');
        $groups = is_object($value) ? get_object_vars($value) : $value;

        if (!is_array($groups) || $groups === []) {
            throw new RuntimeException('InfinitoRbac: config infinitoLdapTeamGroups is not set.');
        }

        return array_map(static fn ($dn): string => strtolower((string) $dn), $groups);
    }

    /**
     * @return string[] lowercased entries of a list config key
     */
    private function configList(string $key): array
    {
        $value = $this->config->get($key);

        if (!is_array($value)) {
            throw new RuntimeException("InfinitoRbac: config {$key} is not set.");
        }

        return array_map(static fn ($item): string => strtolower((string) $item), array_values($value));
    }

    private function configString(string $key): string
    {
        $value = $this->config->get($key);

        if (!is_string($value) || $value === '') {
            throw new RuntimeException("InfinitoRbac: config {$key} is not set.");
        }

        return $value;
    }

    /**
     * @param array<string, mixed> $options EspoCRM's LDAP options
     */
    private function option(array $options, string $name): string
    {
        $value = $options[$name] ?? null;

        if (!is_string($value) || $value === '') {
            throw new RuntimeException("InfinitoRbac: LDAP option {$name} is not set.");
        }

        return $value;
    }
}
