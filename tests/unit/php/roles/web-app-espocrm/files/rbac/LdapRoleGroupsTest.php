<?php

declare(strict_types=1);

namespace Laminas\Ldap\Exception {
    class LdapException extends \Exception
    {
    }
}

namespace Espo\Core\Api {
    interface Request
    {
    }
}

namespace Espo\Core\Authentication {
    use Espo\Entities\User;

    class AuthenticationData
    {
        public function __construct(private ?string $method)
        {
        }

        public function getMethod(): ?string
        {
            return $this->method;
        }
    }

    class Result
    {
        public function __construct(private ?User $user)
        {
        }

        public function getUser(): ?User
        {
            return $this->user;
        }
    }
}

namespace Espo\Core\Authentication\Hook {
    use Espo\Core\Api\Request;
    use Espo\Core\Authentication\AuthenticationData;
    use Espo\Core\Authentication\Result;

    interface OnResult
    {
        public function process(Result $result, AuthenticationData $data, Request $request): void;
    }
}

namespace Espo\Core\Authentication\Util {
    class MethodProvider
    {
        public function __construct(private string $method)
        {
        }

        public function get(): string
        {
            return $this->method;
        }
    }
}

namespace Espo\Core\Authentication\Ldap {
    use Espo\Core\Utils\Config;
    use Laminas\Ldap\Exception\LdapException;

    class LdapLogin
    {
        public const NAME = 'LDAP';
    }

    class Utils
    {
        public function __construct(private Config $config)
        {
        }

        public function getOptions(): array
        {
            return [
                'userNameAttribute' => $this->config->get('ldapUserNameAttribute'),
                'userObjectClass' => $this->config->get('ldapUserObjectClass'),
            ];
        }

        public function getLdapClientOptions(): array
        {
            return ['host' => $this->config->get('ldapHost')];
        }
    }

    class Client
    {
        public const SEARCH_SCOPE_SUB = 1;

        public bool $bound = false;
        public array $searches = [];

        public function __construct(private array $entries, private ?LdapException $failure)
        {
        }

        public function bind(): void
        {
            if ($this->failure !== null) {
                throw $this->failure;
            }

            $this->bound = true;
        }

        public function searchEntries(string $filter, ?string $baseDn, int $scope, array $attributes): array
        {
            $this->searches[] = [$filter, $baseDn, $scope, $attributes];

            return $this->entries;
        }
    }

    class ClientFactory
    {
        public array $options = [];

        public function __construct(private Client $client)
        {
        }

        public function create(array $options): Client
        {
            $this->options[] = $options;

            return $this->client;
        }
    }
}

namespace Espo\Core\ORM {
    use Espo\Entities\User;

    class EntityManager
    {
        public array $saved = [];

        public function saveEntity(User $user): void
        {
            $this->saved[] = [$user->userName, $user->get('type'), $user->get('teamsIds')];
        }
    }
}

namespace {

    use Espo\Core\Acl\Cache\Clearer;
    use Espo\Core\Api\Request;
    use Espo\Core\Authentication\AuthenticationData;
    use Espo\Core\Authentication\Ldap\Client;
    use Espo\Core\Authentication\Ldap\ClientFactory;
    use Espo\Core\Authentication\Result;
    use Espo\Core\Authentication\Util\MethodProvider;
    use Espo\Core\ORM\EntityManager;
    use Espo\Core\Utils\Config;
    use Espo\Core\Utils\Log;
    use Espo\Entities\User;
    use Espo\Modules\InfinitoRbac\Classes\Authentication\LdapRoleGroups;
    use Laminas\Ldap\Exception\LdapException;
    use PHPUnit\Framework\TestCase;

    require_once __DIR__ . '/espo_stubs.php';
    require_once dirname(__DIR__, 7) . '/roles/web-app-espocrm/files/php/rbac/ldap_role_groups.php';

    final class LdapRoleGroupsTest extends TestCase
    {
        private const ADMIN_DN = 'cn=web-app-espocrm-administrator,ou=roles,dc=example,dc=org';
        private const MANAGER_DN = 'cn=web-app-espocrm-manager,ou=roles,dc=example,dc=org';
        private const USER_DN = 'cn=web-app-espocrm-user,ou=roles,dc=example,dc=org';

        private const CONFIG = [
            'infinitoLdapMemberOfAttribute' => 'memberOf',
            'infinitoLdapAdministratorGroups' => [self::ADMIN_DN],
            'infinitoOidcProtectedUsers' => ['platformadmin'],
            'ldapUserNameAttribute' => 'uid',
            'ldapUserObjectClass' => 'inetOrgPerson',
            'ldapHost' => 'openldap',
        ];

        private Client $client;
        private ClientFactory $clientFactory;
        private EntityManager $entityManager;
        private Clearer $clearer;
        private Log $log;

        /**
         * Build the hook against a directory that answers the account search with the given entries.
         *
         * @param list<array<string, mixed>> $entries what the account search returns
         * @param array<string, mixed> $config EspoCRM config entries that replace those the RBAC hook writes
         * @param string $method configured authentication method
         * @param ?LdapException $failure what binding to the directory throws
         */
        private function hook(array $entries, array $config, string $method, ?LdapException $failure): LdapRoleGroups
        {
            $this->client = new Client($entries, $failure);
            $this->clientFactory = new ClientFactory($this->client);
            $this->entityManager = new EntityManager();
            $this->clearer = new Clearer();
            $this->log = new Log();

            return new LdapRoleGroups(
                new MethodProvider($method),
                $this->clientFactory,
                $this->entityManager,
                new Config($config + self::CONFIG + [
                    'infinitoLdapTeamGroups' => (object) ['team-managers' => self::MANAGER_DN, 'team-users' => self::USER_DN],
                ]),
                $this->clearer,
                $this->log,
            );
        }

        /**
         * @param list<string> $groups DNs the directory lists in the account's memberOf
         * @return list<array<string, mixed>>
         */
        private static function entry(array $groups): array
        {
            return [['dn' => 'uid=biber,ou=users,dc=example,dc=org', 'memberof' => $groups]];
        }

        private static function signIn(LdapRoleGroups $hook, ?User $user, ?string $method): void
        {
            $hook->process(new Result($user), new AuthenticationData($method), new class implements Request {});
        }

        public function testANewAccountGetsTheTeamOfItsRoleGroupAtSignIn(): void
        {
            $biber = new User('biber', User::TYPE_REGULAR);
            $hook = $this->hook(self::entry([strtoupper(self::USER_DN)]), [], 'LDAP', null);

            self::signIn($hook, $biber, null);

            self::assertSame(['team-users'], $biber->get('teamsIds'));
            self::assertSame(User::TYPE_REGULAR, $biber->get('type'));
            self::assertSame([['biber', User::TYPE_REGULAR, ['team-users']]], $this->entityManager->saved);
            self::assertSame(['biber'], $this->clearer->cleared);
            self::assertTrue($this->client->bound);
            self::assertSame([['host' => 'openldap']], $this->clientFactory->options);
            self::assertSame(
                [['(&(objectClass=inetOrgPerson)(uid=biber))', null, Client::SEARCH_SCOPE_SUB, ['memberOf']]],
                $this->client->searches
            );
        }

        public function testTheAdministratorGroupPromotesAtSignIn(): void
        {
            $biber = (new User('Biber', User::TYPE_REGULAR))->inTeams(['team-users']);
            $hook = $this->hook(self::entry([self::ADMIN_DN, self::USER_DN]), [], 'LDAP', null);

            self::signIn($hook, $biber, null);

            self::assertSame(User::TYPE_ADMIN, $biber->get('type'));
            self::assertSame([['Biber', User::TYPE_ADMIN, ['team-users']]], $this->entityManager->saved);
            self::assertSame(['Biber'], $this->clearer->cleared);
        }

        public function testLeavingTheRoleGroupsDemotesAndDropsOnlyTheManagedTeams(): void
        {
            $former = (new User('former', User::TYPE_ADMIN))->inTeams(['team-managers', 'sales']);
            $hook = $this->hook(self::entry(['cn=other,ou=groups,dc=example,dc=org']), [], 'LDAP', null);

            self::signIn($hook, $former, null);

            self::assertSame(User::TYPE_REGULAR, $former->get('type'));
            self::assertSame(['sales'], $former->get('teamsIds'));
        }

        public function testAnAccountMissingFromTheDirectoryHoldsNoRoleGroup(): void
        {
            $former = (new User('former', User::TYPE_ADMIN))->inTeams(['team-users']);
            $hook = $this->hook([], [], 'LDAP', null);

            self::signIn($hook, $former, null);

            self::assertSame(User::TYPE_REGULAR, $former->get('type'));
            self::assertSame([], $former->get('teamsIds'));
        }

        public function testAnAlignedAccountIsNotSaved(): void
        {
            $bob = (new User('bob', User::TYPE_REGULAR))->inTeams(['sales', 'team-managers']);
            $hook = $this->hook(self::entry([self::MANAGER_DN]), [], 'LDAP', null);

            self::signIn($hook, $bob, null);

            self::assertSame([], $this->entityManager->saved);
            self::assertSame([], $this->clearer->cleared);
            self::assertSame([], $this->log->messages);
        }

        public function testTheProtectedAdministratorIsNeverLookedUp(): void
        {
            $admin = new User('PlatformAdmin', User::TYPE_ADMIN);
            $hook = $this->hook(self::entry([]), [], 'LDAP', null);

            self::signIn($hook, $admin, null);

            self::assertSame(User::TYPE_ADMIN, $admin->get('type'));
            self::assertSame([], $this->clientFactory->options);
            self::assertSame([], $this->entityManager->saved);
        }

        public function testAPortalUserIsLeftAlone(): void
        {
            $portal = new User('customer', User::TYPE_PORTAL);
            $hook = $this->hook(self::entry([self::ADMIN_DN]), [], 'LDAP', null);

            self::signIn($hook, $portal, null);

            self::assertSame(User::TYPE_PORTAL, $portal->get('type'));
            self::assertSame([], $this->clientFactory->options);
        }

        public function testASignInByAnotherMethodIsLeftAlone(): void
        {
            $biber = new User('biber', User::TYPE_ADMIN);
            $hook = $this->hook(self::entry([]), [], 'Oidc', null);

            self::signIn($hook, $biber, null);
            self::signIn($hook, $biber, 'ApiKey');

            self::assertSame(User::TYPE_ADMIN, $biber->get('type'));
            self::assertSame([], $this->clientFactory->options);
        }

        public function testAFailedSignInIsLeftAlone(): void
        {
            $hook = $this->hook(self::entry([self::ADMIN_DN]), [], 'LDAP', null);

            self::signIn($hook, null, null);

            self::assertSame([], $this->clientFactory->options);
        }

        public function testAnUnreachableDirectoryKeepsTheAccountAndLogsTheError(): void
        {
            $biber = (new User('biber', User::TYPE_ADMIN))->inTeams(['team-managers']);
            $failure = new LdapException('connect failed');
            $hook = $this->hook(self::entry([]), [], 'LDAP', $failure);

            self::signIn($hook, $biber, null);

            self::assertSame(User::TYPE_ADMIN, $biber->get('type'));
            self::assertSame([], $this->entityManager->saved);
            self::assertCount(1, $this->log->errors);
            self::assertSame(['exception' => $failure], $this->log->errors[0][1]);
        }

        public function testTheUsernameIsEscapedInTheSearchFilter(): void
        {
            $hook = $this->hook([], [], 'LDAP', null);

            self::signIn($hook, new User('a*b(c)\\d', User::TYPE_REGULAR), null);

            self::assertSame('(&(objectClass=inetOrgPerson)(uid=a\\2ab\\28c\\29\\5cd))', $this->client->searches[0][0]);
        }

        public function testAMissingTeamMapFailsLoudly(): void
        {
            $hook = $this->hook(self::entry([]), ['infinitoLdapTeamGroups' => null], 'LDAP', null);

            $this->expectException(RuntimeException::class);
            $this->expectExceptionMessage('InfinitoRbac: config infinitoLdapTeamGroups is not set.');

            self::signIn($hook, new User('biber', User::TYPE_REGULAR), null);
        }

        public function testAMissingMemberOfAttributeFailsLoudly(): void
        {
            $hook = $this->hook(self::entry([]), ['infinitoLdapMemberOfAttribute' => ''], 'LDAP', null);

            $this->expectException(RuntimeException::class);
            $this->expectExceptionMessage('InfinitoRbac: config infinitoLdapMemberOfAttribute is not set.');

            self::signIn($hook, new User('biber', User::TYPE_REGULAR), null);
        }
    }
}
