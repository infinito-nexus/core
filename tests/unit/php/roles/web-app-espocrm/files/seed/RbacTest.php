<?php

declare(strict_types=1);

namespace Infinito\Tests\Roles\WebAppEspocrm\Seed;

use PHPUnit\Framework\TestCase;

final class RbacTest extends TestCase
{
    private const SCRIPT = '/roles/web-app-espocrm/files/php/seed/rbac.php';

    private const ADMIN_GROUP = '/roles/web-app-espocrm/administrator';

    private const ADMIN_DN = 'cn=web-app-espocrm-administrator,ou=roles,dc=example,dc=org';

    private const TIERS = [
        'manager' => [
            'team' => 'Managers',
            'role' => 'Manager',
            'access' => 'manage',
            'path' => '/roles/web-app-espocrm/manager',
            'dn' => 'cn=web-app-espocrm-manager,ou=roles,dc=example,dc=org',
        ],
        'user' => [
            'team' => 'Users',
            'role' => 'User',
            'access' => 'use',
            'path' => '/roles/web-app-espocrm/user',
            'dn' => 'cn=web-app-espocrm-user,ou=roles,dc=example,dc=org',
        ],
    ];

    private const SCOPES = [
        'Account' => ['acl' => true],
        'EmailTemplate' => ['acl' => 'boolean'],
        'Note' => ['entity' => true],
        'Team' => ['acl' => true],
    ];

    private const SETTINGS = [
        'aclStrictMode',
        'oidcGroupClaim',
        'oidcSyncTeams',
        'oidcTeamsIds',
        'oidcTeamsColumns',
        'infinitoOidcAllowedGroups',
        'infinitoOidcAdministratorGroups',
        'infinitoOidcProtectedUsers',
        'infinitoLdapMemberOfAttribute',
        'infinitoLdapTeamGroups',
        'infinitoLdapAdministratorGroups',
    ];

    private const BOOTSTRAP = <<<'PHP'
        <?php
        namespace {
            final class EspoStub
            {
                public static array $state = [];

                public static function load(): void
                {
                    self::$state = unserialize((string) file_get_contents((string) getenv('STUB_STATE')));
                }

                public static function save(): void
                {
                    file_put_contents((string) getenv('STUB_STATE'), serialize(self::$state));
                }
            }

            EspoStub::load();
            register_shutdown_function([EspoStub::class, 'save']);
        }

        namespace Espo\Entities {
            class User
            {
                public const TYPE_ADMIN = 'admin';
                public const TYPE_REGULAR = 'regular';
            }
        }

        namespace Espo\ORM {
            final class StubEntity
            {
                private array $values;
                private array $fetched;
                private array $links = [];

                public function __construct(private string $entityType, array $values, private bool $new)
                {
                    foreach ($values as $key => $value) {
                        if (str_ends_with($key, 'Ids')) {
                            $this->links[substr($key, 0, -3)] = $value;
                            unset($values[$key]);
                        }
                    }
                    $this->values = $values;
                    $this->fetched = $values;
                }

                public function entityType(): string
                {
                    return $this->entityType;
                }

                public function isNew(): bool
                {
                    return $this->new;
                }

                public function getId(): ?string
                {
                    return $this->values['id'] ?? null;
                }

                public function getUserName(): string
                {
                    return $this->values['userName'];
                }

                public function get(string $key): mixed
                {
                    return $this->values[$key] ?? null;
                }

                public function set(string|array $key, mixed $value = null): void
                {
                    foreach (is_array($key) ? $key : [$key => $value] as $name => $item) {
                        $this->values[$name] = $item;
                    }
                }

                public function loadLinkMultipleField(string $link): void
                {
                    $this->values[$link . 'Ids'] = $this->links[$link];
                    $this->fetched[$link . 'Ids'] = $this->links[$link];
                }

                public function getLinkMultipleIdList(string $link): array
                {
                    if (!array_key_exists($link . 'Ids', $this->values)) {
                        throw new \LogicException("$link read before it was loaded");
                    }

                    return $this->values[$link . 'Ids'];
                }

                public function isAttributeChanged(string $name): bool
                {
                    return json_encode($this->values[$name] ?? null) !== json_encode($this->fetched[$name] ?? null);
                }

                public function persist(string $id): array
                {
                    $this->values['id'] = $id;
                    $this->new = false;
                    $record = $this->values;
                    foreach ($this->links as $link => $ids) {
                        if (!array_key_exists($link . 'Ids', $record)) {
                            $record[$link . 'Ids'] = $ids;
                        }
                    }

                    return $record;
                }
            }

            final class StubQuery
            {
                public function __construct(private string $entityType, private array $where)
                {
                }

                public function find(): array
                {
                    $rows = [];
                    foreach (\EspoStub::$state[$this->entityType] as $record) {
                        foreach ($this->where as $field => $expected) {
                            $value = $record[$field];
                            if (is_array($expected) ? !in_array($value, $expected, true) : $value !== $expected) {
                                continue 2;
                            }
                        }
                        $rows[] = new StubEntity($this->entityType, $record, false);
                    }

                    return $rows;
                }

                public function findOne(): ?StubEntity
                {
                    return $this->find()[0] ?? null;
                }
            }

            final class StubRepository
            {
                public function __construct(private string $entityType)
                {
                }

                public function where(array $where): StubQuery
                {
                    return new StubQuery($this->entityType, $where);
                }
            }

            class EntityManager
            {
                public function getRDBRepository(string $entityType): StubRepository
                {
                    return new StubRepository($entityType);
                }

                public function getNewEntity(string $entityType): StubEntity
                {
                    return new StubEntity($entityType, [], true);
                }

                public function saveEntity(StubEntity $entity): void
                {
                    $type = $entity->entityType();
                    $id = $entity->getId() ?? strtolower($type) . '-' . (count(\EspoStub::$state[$type]) + 1);
                    \EspoStub::$state[$type][$id] = $entity->persist($id);
                    \EspoStub::$state['saved'][] = "$type:$id";
                }
            }
        }

        namespace Espo\Core\ORM {
            class EntityManager extends \Espo\ORM\EntityManager
            {
            }
        }

        namespace Espo\Core {
            final class StubConfig
            {
                public function get(string $key): mixed
                {
                    return \EspoStub::$state['config'][$key] ?? null;
                }
            }

            final class StubConfigWriter
            {
                private array $pending = [];

                public function set(string $key, mixed $value): void
                {
                    $this->pending[$key] = $value;
                }

                public function save(): void
                {
                    \EspoStub::$state['config'] = $this->pending + \EspoStub::$state['config'];
                    \EspoStub::$state['configSaves'][] = array_keys($this->pending);
                }
            }

            final class StubClearer
            {
                public function clearForUser(\Espo\ORM\StubEntity $user): void
                {
                    \EspoStub::$state['cleared'][] = $user->getUserName();
                }
            }

            final class StubFactory
            {
                public function create(string $className): object
                {
                    return match ($className) {
                        '\Espo\Core\Utils\Config\ConfigWriter' => new StubConfigWriter(),
                        '\Espo\Core\Acl\Cache\Clearer' => new StubClearer(),
                    };
                }
            }

            final class StubMetadata
            {
                public function get(array $path): mixed
                {
                    return $path === ['scopes'] ? \EspoStub::$state['scopes'] : null;
                }
            }

            final class StubContainer
            {
                public function getByClass(string $className): object
                {
                    if ($className !== ORM\EntityManager::class) {
                        throw new \LogicException("unexpected class $className");
                    }

                    return new ORM\EntityManager();
                }

                public function get(string $name): object
                {
                    return match ($name) {
                        'config' => new StubConfig(),
                        'injectableFactory' => new StubFactory(),
                        'metadata' => new StubMetadata(),
                    };
                }
            }

            final class Application
            {
                public function setupSystemUser(): void
                {
                    \EspoStub::$state['systemUser'] = true;
                }

                public function getContainer(): StubContainer
                {
                    return new StubContainer();
                }
            }
        }
        PHP;

    private string $root;

    protected function setUp(): void
    {
        $this->root = sys_get_temp_dir() . '/espocrm-rbac-' . bin2hex(random_bytes(8));
        mkdir($this->root, 0700, true);
        file_put_contents($this->root . '/bootstrap.php', self::BOOTSTRAP);
    }

    protected function tearDown(): void
    {
        foreach (['bootstrap.php', 'state.ser'] as $file) {
            if (is_file($this->root . '/' . $file)) {
                unlink($this->root . '/' . $file);
            }
        }
        rmdir($this->root);
    }

    /**
     * Build one account row of the stubbed user table.
     *
     * @param string $userName EspoCRM username
     * @param string $type EspoCRM user type
     * @param list<string> $teams ids of the teams the account belongs to
     * @return array<string, mixed>
     */
    private static function user(string $userName, string $type, array $teams): array
    {
        return ['id' => "id-$userName", 'userName' => $userName, 'type' => $type, 'teamsIds' => $teams];
    }

    /**
     * Build one entry of a role group member list.
     *
     * @param string $username directory login of the member
     * @return array{username: string, email: string, name: string}
     */
    private static function member(string $username): array
    {
        return ['username' => $username, 'email' => "$username@example.org", 'name' => $username];
    }

    /**
     * Build a site that no RBAC run has touched yet.
     *
     * @param list<array<string, mixed>> $users account rows
     * @return array<string, mixed> the stub state
     */
    private static function site(array $users): array
    {
        $rows = [];
        foreach ($users as $user) {
            $rows[$user['id']] = $user;
        }

        return [
            'Role' => [],
            'Team' => [],
            'User' => $rows,
            'config' => [],
            'scopes' => self::SCOPES,
            'saved' => [],
            'cleared' => [],
            'configSaves' => [],
        ];
    }

    /**
     * Pipe the script into php against the stubbed EspoCRM.
     *
     * @param array<string, mixed> $site the stub state the run starts from
     * @param array<string, list<array{username: string, email: string, name: string}>> $members members per RBAC role
     * @param array<string, string> $override environment entries that replace the defaults of the hook
     * @return array{0: string, 1: string, 2: int, 3: array<string, mixed>} stdout, stderr, exit code and the stub state afterwards
     */
    private function runScript(array $site, array $members, array $override): array
    {
        $state = $this->root . '/state.ser';
        file_put_contents($state, serialize($site));

        $env = $override + [
            'ESPOCRM_RBAC_ROOT' => $this->root,
            'ESPOCRM_RBAC_TIERS' => json_encode(self::TIERS),
            'ESPOCRM_RBAC_ADMINS' => json_encode(array_column($members['administrator'], 'username')),
            'ESPOCRM_RBAC_MEMBERS' => json_encode($members),
            'ESPOCRM_RBAC_ADMIN_GROUP' => self::ADMIN_GROUP,
            'ESPOCRM_RBAC_ADMIN_DN' => self::ADMIN_DN,
            'ESPOCRM_RBAC_MEMBER_OF' => 'memberOf',
            'ESPOCRM_RBAC_PROTECTED' => json_encode(['PlatformAdmin']),
            'ESPOCRM_RBAC_CLAIM' => 'groups',
            'STUB_STATE' => $state,
            'PATH' => (string) getenv('PATH'),
        ];

        $process = proc_open([PHP_BINARY], [0 => ['pipe', 'r'], 1 => ['pipe', 'w'], 2 => ['pipe', 'w']], $pipes, null, $env);
        fwrite($pipes[0], (string) file_get_contents(dirname(__DIR__, 7) . self::SCRIPT));
        fclose($pipes[0]);
        $stdout = (string) stream_get_contents($pipes[1]);
        $stderr = (string) stream_get_contents($pipes[2]);
        fclose($pipes[1]);
        fclose($pipes[2]);
        $code = proc_close($process);

        return [$stdout, $stderr, $code, unserialize((string) file_get_contents($state))];
    }

    /**
     * @param list<string> $users lines for the accounts the run changed
     * @return string the output of a first run on a fresh site
     */
    private static function firstRun(array $users): string
    {
        $lines = [
            'CHANGED role Manager',
            'CHANGED team Managers',
            'CHANGED role User',
            'CHANGED team Users',
            ...array_map(static fn (string $key): string => "CHANGED config $key", self::SETTINGS),
            ...$users,
        ];

        return implode("\n", $lines) . "\n";
    }

    public function testAFreshSiteGetsItsRolesTeamsSettingsAndTheTypeAndTeamsOfEveryMember(): void
    {
        $site = self::site([
            self::user('platformadmin', 'admin', []),
            self::user('alice', 'regular', []),
            self::user('bob', 'regular', []),
            self::user('mallory', 'admin', []),
            self::user('api-bot', 'api', []),
        ]);

        [$stdout, $stderr, $code, $after] = $this->runScript($site, [
            'administrator' => [self::member('Alice')],
            'manager' => [self::member('Bob')],
            'user' => [self::member('alice')],
        ], []);

        $this->assertSame(0, $code, $stderr);
        $this->assertSame(self::firstRun([
            'CHANGED alice type=admin +Users',
            'CHANGED bob +Managers',
            'CHANGED mallory type=regular',
        ]), $stdout);
        $this->assertTrue($after['systemUser']);
        $this->assertSame(['alice', 'bob', 'mallory'], $after['cleared']);
        $this->assertSame('admin', $after['User']['id-alice']['type']);
        $this->assertSame(['team-2'], $after['User']['id-alice']['teamsIds']);
        $this->assertSame(['team-1'], $after['User']['id-bob']['teamsIds']);
        $this->assertSame('regular', $after['User']['id-mallory']['type']);
        $this->assertSame(['role-1'], $after['Team']['team-1']['rolesIds']);
        $this->assertSame(['team-1', 'team-2'], $after['config']['oidcTeamsIds']);
        $this->assertSame(
            [self::ADMIN_GROUP, self::TIERS['manager']['path'], self::TIERS['user']['path']],
            $after['config']['infinitoOidcAllowedGroups']
        );
        $this->assertSame(['platformadmin'], $after['config']['infinitoOidcProtectedUsers']);
        $this->assertSame('memberOf', $after['config']['infinitoLdapMemberOfAttribute']);
        $this->assertSame(
            ['team-1' => self::TIERS['manager']['dn'], 'team-2' => self::TIERS['user']['dn']],
            (array) $after['config']['infinitoLdapTeamGroups']
        );
        $this->assertSame([self::ADMIN_DN], $after['config']['infinitoLdapAdministratorGroups']);
        $this->assertSame([self::SETTINGS], $after['configSaves']);
    }

    public function testTheRolesGrantRecordAccessByTierAndReadOnlyUsersAndTeams(): void
    {
        [, $stderr, $code, $after] = $this->runScript(self::site([]), ['administrator' => [], 'manager' => [], 'user' => []], []);

        $this->assertSame(0, $code, $stderr);
        $manager = (array) $after['Role']['role-1']['data'];
        $user = (array) $after['Role']['role-2']['data'];
        $this->assertSame(['Account', 'EmailTemplate', 'Team'], array_keys($manager));
        $this->assertSame(['create' => 'yes', 'read' => 'all', 'edit' => 'all', 'delete' => 'all', 'stream' => 'all'], $manager['Account']);
        $this->assertSame(['create' => 'yes', 'read' => 'team', 'edit' => 'own', 'delete' => 'no', 'stream' => 'team'], $user['Account']);
        $this->assertSame(['create' => 'no', 'read' => 'all', 'edit' => 'no', 'delete' => 'no'], $user['Team']);
        $this->assertTrue($user['EmailTemplate']);
        $this->assertSame('all', $after['Role']['role-1']['userPermission']);
        $this->assertSame('team', $after['Role']['role-2']['userPermission']);
    }

    public function testASecondRunChangesNothing(): void
    {
        $members = ['administrator' => [self::member('alice')], 'manager' => [self::member('bob')], 'user' => []];
        [, , , $converged] = $this->runScript(self::site([
            self::user('alice', 'regular', []),
            self::user('bob', 'regular', ['sales']),
        ]), $members, []);
        $converged['saved'] = [];
        $converged['cleared'] = [];

        [$stdout, $stderr, $code, $after] = $this->runScript($converged, $members, []);

        $this->assertSame(0, $code, $stderr);
        $this->assertSame("UNCHANGED\n", $stdout);
        $this->assertSame([], $after['saved']);
        $this->assertSame([], $after['cleared']);
    }

    public function testAFormerMemberLosesTheManagedTeamAndKeepsItsOwnTeams(): void
    {
        [, , , $converged] = $this->runScript(
            self::site([self::user('bob', 'regular', ['sales'])]),
            ['administrator' => [], 'manager' => [self::member('bob')], 'user' => []],
            []
        );
        $this->assertSame(['sales', 'team-1'], $converged['User']['id-bob']['teamsIds']);

        [$stdout, $stderr, $code, $after] = $this->runScript(
            $converged,
            ['administrator' => [], 'manager' => [], 'user' => []],
            []
        );

        $this->assertSame(0, $code, $stderr);
        $this->assertSame("CHANGED bob -Managers\n", $stdout);
        $this->assertSame(['sales'], $after['User']['id-bob']['teamsIds']);
    }

    public function testTheProtectedAdministratorAndNonHumanAccountsAreNeverChanged(): void
    {
        $site = self::site([
            self::user('platformadmin', 'admin', ['sales']),
            self::user('system', 'system', []),
            self::user('api-bot', 'api', []),
        ]);

        [$stdout, $stderr, $code, $after] = $this->runScript($site, ['administrator' => [], 'manager' => [], 'user' => []], []);

        $this->assertSame(0, $code, $stderr);
        $this->assertSame(self::firstRun([]), $stdout);
        $this->assertSame($site['User'], $after['User']);
        $this->assertSame([], $after['cleared']);
    }

    public function testATierWithoutMembersFailsBeforeTouchingTheSite(): void
    {
        $site = self::site([self::user('bob', 'regular', [])]);

        [$stdout, $stderr, $code, $after] = $this->runScript($site, ['administrator' => [], 'manager' => []], []);

        $this->assertSame(1, $code);
        $this->assertSame('', $stdout);
        $this->assertSame("[FAIL] ESPOCRM_RBAC_MEMBERS has no entry for the tier user\n", $stderr);
        $this->assertSame($site, $after);
    }

    public function testAnEmptyGroupsClaimFailsBeforeTouchingTheSite(): void
    {
        $site = self::site([]);

        [$stdout, $stderr, $code, $after] = $this->runScript(
            $site,
            ['administrator' => [], 'manager' => [], 'user' => []],
            ['ESPOCRM_RBAC_CLAIM' => '']
        );

        $this->assertSame(1, $code);
        $this->assertSame('', $stdout);
        $this->assertSame("[FAIL] ESPOCRM_RBAC_CLAIM is empty\n", $stderr);
        $this->assertSame($site, $after);
    }

    public function testAnEmptyMemberOfAttributeFailsBeforeTouchingTheSite(): void
    {
        $site = self::site([]);

        [$stdout, $stderr, $code, $after] = $this->runScript(
            $site,
            ['administrator' => [], 'manager' => [], 'user' => []],
            ['ESPOCRM_RBAC_MEMBER_OF' => '']
        );

        $this->assertSame(1, $code);
        $this->assertSame('', $stdout);
        $this->assertSame("[FAIL] ESPOCRM_RBAC_MEMBER_OF is empty\n", $stderr);
        $this->assertSame($site, $after);
    }
}
