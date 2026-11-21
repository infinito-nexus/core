<?php

namespace Espo\Modules\InfinitoRbac\Classes\Oidc;

use Espo\Core\Acl\Cache\Clearer as AclCacheClearer;
use Espo\Core\Authentication\Oidc\UserProvider;
use Espo\Core\Authentication\Oidc\UserProvider\DefaultUserProvider;
use Espo\Core\Authentication\Oidc\UserProvider\Sync;
use Espo\Core\Authentication\Oidc\UserProvider\UserInfo;
use Espo\Core\Authentication\Oidc\UserProvider\UserRepository;
use Espo\Core\Utils\Config;
use Espo\Core\Utils\Log;
use Espo\Entities\User;

/**
 * OIDC user provider that admits only members of a declared role group.
 *
 * Config (written by files/php/seed/rbac.php):
 *   oidcGroupClaim                   name of the groups claim
 *   oidcUsernameClaim                name of the username claim
 *   infinitoOidcAllowedGroups        group paths whose members may sign in
 *   infinitoOidcAdministratorGroups  group paths whose members are EspoCRM administrators
 *   infinitoOidcProtectedUsers       usernames that sign in and keep their type regardless of groups
 */
class GroupUserProvider implements UserProvider
{
    public function __construct(
        private DefaultUserProvider $defaultUserProvider,
        private UserRepository $userRepository,
        private Sync $sync,
        private Config $config,
        private AclCacheClearer $aclCacheClearer,
        private Log $log,
    ) {}

    public function get(UserInfo $userInfo): ?User
    {
        $username = $this->username($userInfo);
        $groups = $this->strings($userInfo->get((string) $this->config->get('oidcGroupClaim')));
        $protected = $username !== '' && in_array($username, $this->configList('infinitoOidcProtectedUsers'), true);

        if (!$protected && array_intersect($groups, $this->configList('infinitoOidcAllowedGroups')) === []) {
            $this->log->info("Oidc: user `{$username}` holds no role group of this application, refused.");
            $this->demote($username === '' ? null : $this->userRepository->findByUsername($username));

            return null;
        }

        $user = $this->defaultUserProvider->get($userInfo);

        if ($user !== null && !$protected) {
            $isAdministrator = array_intersect($groups, $this->configList('infinitoOidcAdministratorGroups')) !== [];
            $this->assignType($user, $isAdministrator ? User::TYPE_ADMIN : User::TYPE_REGULAR);
        }

        return $user;
    }

    private function username(UserInfo $userInfo): string
    {
        $raw = $userInfo->get((string) $this->config->get('oidcUsernameClaim'));

        return is_string($raw) && $raw !== '' ? $this->sync->normalizeUsername($raw) : '';
    }

    private function demote(?User $user): void
    {
        if ($user !== null) {
            $this->assignType($user, User::TYPE_REGULAR);
        }
    }

    private function assignType(User $user, string $type): void
    {
        if (!$user->isAdmin() && !$user->isRegular()) {
            return;
        }

        if ($user->get('type') === $type) {
            return;
        }

        $user->set('type', $type);
        $this->userRepository->save($user);
        $this->aclCacheClearer->clearForUser($user);
    }

    /**
     * @return string[]
     */
    private function configList(string $key): array
    {
        return $this->strings($this->config->get($key));
    }

    /**
     * @return string[]
     */
    private function strings(mixed $value): array
    {
        if (is_string($value)) {
            return $value === '' ? [] : [$value];
        }

        if (!is_array($value)) {
            return [];
        }

        return array_values(array_filter($value, static fn ($item): bool => is_string($item) && $item !== ''));
    }
}
