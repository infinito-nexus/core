<?php

declare(strict_types=1);

namespace Espo\Core\Authentication\Oidc\UserProvider {
    use Espo\Entities\User;

    class UserInfo
    {
        public function __construct(private array $claims)
        {
        }

        public function get(string $name): mixed
        {
            return $this->claims[$name] ?? null;
        }
    }

    class DefaultUserProvider
    {
        public int $calls = 0;

        public function __construct(public ?User $user)
        {
        }

        public function get(UserInfo $userInfo): ?User
        {
            ++$this->calls;

            return $this->user;
        }
    }

    class UserRepository
    {
        public array $saved = [];

        public function __construct(public array $users)
        {
        }

        public function findByUsername(string $username): ?User
        {
            return $this->users[$username] ?? null;
        }

        public function save(User $user): void
        {
            $this->saved[] = $user->userName;
        }
    }

    class Sync
    {
        public function normalizeUsername(string $username): string
        {
            return strtolower($username);
        }
    }
}

namespace Espo\Core\Authentication\Oidc {
    use Espo\Core\Authentication\Oidc\UserProvider\UserInfo;
    use Espo\Entities\User;

    interface UserProvider
    {
        public function get(UserInfo $userInfo): ?User;
    }
}

namespace {

    use Espo\Core\Acl\Cache\Clearer;
    use Espo\Core\Authentication\Oidc\UserProvider\DefaultUserProvider;
    use Espo\Core\Authentication\Oidc\UserProvider\Sync;
    use Espo\Core\Authentication\Oidc\UserProvider\UserInfo;
    use Espo\Core\Authentication\Oidc\UserProvider\UserRepository;
    use Espo\Core\Utils\Config;
    use Espo\Core\Utils\Log;
    use Espo\Entities\User;
    use Espo\Modules\InfinitoRbac\Classes\Oidc\GroupUserProvider;
    use PHPUnit\Framework\TestCase;

    require_once __DIR__ . '/espo_stubs.php';
    require_once dirname(__DIR__, 7) . '/roles/web-app-espocrm/files/php/rbac/group_user_provider.php';

    final class GroupUserProviderTest extends TestCase
    {
        private const ADMIN_GROUP = '/roles/web-app-espocrm/administrator';
        private const USER_GROUP = '/roles/web-app-espocrm/user';

        private DefaultUserProvider $defaultUserProvider;
        private UserRepository $userRepository;
        private Clearer $clearer;

        private function provider(?User $created, array $existing = [], ?array $config = null): GroupUserProvider
        {
            $this->defaultUserProvider = new DefaultUserProvider($created);
            $this->userRepository = new UserRepository($existing);
            $this->clearer = new Clearer();

            return new GroupUserProvider(
                $this->defaultUserProvider,
                $this->userRepository,
                new Sync(),
                new Config($config ?? [
                    'oidcGroupClaim' => 'groups',
                    'oidcUsernameClaim' => 'preferred_username',
                    'infinitoOidcAllowedGroups' => [self::ADMIN_GROUP, self::USER_GROUP],
                    'infinitoOidcAdministratorGroups' => [self::ADMIN_GROUP],
                    'infinitoOidcProtectedUsers' => ['platformadmin'],
                ]),
                $this->clearer,
                new Log(),
            );
        }

        private static function claims(string $username, array $groups): UserInfo
        {
            return new UserInfo(['preferred_username' => $username, 'groups' => $groups]);
        }

        public function testAMemberOfTheUserGroupSignsInAsARegularUser(): void
        {
            $biber = new User('biber', User::TYPE_REGULAR);

            $user = $this->provider($biber)->get(self::claims('biber', [self::USER_GROUP]));

            self::assertSame($biber, $user);
            self::assertSame(User::TYPE_REGULAR, $user->get('type'));
            self::assertSame([], $this->userRepository->saved);
        }

        public function testAUserOutsideEveryRoleGroupIsRefusedBeforeAnAccountIsCreated(): void
        {
            $user = $this->provider(new User('biber', User::TYPE_REGULAR))->get(self::claims('biber', ['/roles/web-app-other/user']));

            self::assertNull($user);
            self::assertSame(0, $this->defaultUserProvider->calls);
        }

        public function testARefusedAdministratorAccountIsDemoted(): void
        {
            $former = new User('former', User::TYPE_ADMIN);

            $user = $this->provider(null, ['former' => $former])->get(self::claims('Former', []));

            self::assertNull($user);
            self::assertSame(User::TYPE_REGULAR, $former->get('type'));
            self::assertSame(['former'], $this->userRepository->saved);
            self::assertSame(['former'], $this->clearer->cleared);
        }

        public function testTheAdministratorGroupPromotesAtSignIn(): void
        {
            $biber = new User('biber', User::TYPE_REGULAR);

            $user = $this->provider($biber)->get(self::claims('biber', [self::ADMIN_GROUP]));

            self::assertSame(User::TYPE_ADMIN, $user->get('type'));
            self::assertSame(['biber'], $this->userRepository->saved);
            self::assertSame(['biber'], $this->clearer->cleared);
        }

        public function testLeavingTheAdministratorGroupDemotesAtSignIn(): void
        {
            $biber = new User('biber', User::TYPE_ADMIN);

            $user = $this->provider($biber)->get(self::claims('biber', [self::USER_GROUP]));

            self::assertSame(User::TYPE_REGULAR, $user->get('type'));
            self::assertSame(['biber'], $this->userRepository->saved);
        }

        public function testTheProtectedAdministratorSignsInWithoutAGroupAndKeepsItsType(): void
        {
            $admin = new User('platformadmin', User::TYPE_ADMIN);

            $user = $this->provider($admin)->get(self::claims('platformadmin', []));

            self::assertSame($admin, $user);
            self::assertSame(User::TYPE_ADMIN, $user->get('type'));
            self::assertSame([], $this->userRepository->saved);
        }

        public function testAPortalUserKeepsItsType(): void
        {
            $portal = new User('customer', User::TYPE_PORTAL);

            $user = $this->provider($portal)->get(self::claims('customer', [self::ADMIN_GROUP]));

            self::assertSame(User::TYPE_PORTAL, $user->get('type'));
            self::assertSame([], $this->userRepository->saved);
        }

        public function testAMissingGroupListRefusesEveryUnprotectedUser(): void
        {
            $user = $this->provider(new User('biber', User::TYPE_REGULAR), [], [
                'oidcGroupClaim' => 'groups',
                'oidcUsernameClaim' => 'preferred_username',
            ])->get(self::claims('biber', [self::USER_GROUP]));

            self::assertNull($user);
            self::assertSame(0, $this->defaultUserProvider->calls);
        }
    }
}
