<?php

declare(strict_types=1);

namespace Doctrine\DBAL {
    if (!class_exists(Connection::class)) {
        class Connection
        {
            public array $statements = [];

            public function executeStatement(string $sql, array $params = []): int
            {
                $this->statements[] = [$sql, $params];

                return 1;
            }
        }
    }
}

namespace Symfony\Component\Security\Core\User {
    if (!interface_exists(UserInterface::class)) {
        interface UserInterface
        {
        }
    }
}

namespace Symfony\Component\Ldap {
    if (!interface_exists(LdapInterface::class)) {
        interface LdapInterface
        {
        }
    }

    if (!class_exists(Entry::class)) {
        class Entry
        {
            public function __construct(private string $dn, private array $attributes)
            {
            }

            public function getAttribute(string $name, bool $caseSensitive = true): ?array
            {
                foreach ($this->attributes as $key => $values) {
                    if ($key === $name || (!$caseSensitive && strtolower($key) === strtolower($name))) {
                        return $values;
                    }
                }

                return null;
            }
        }
    }
}

namespace Symfony\Component\Ldap\Security {
    use Symfony\Component\Ldap\Entry;
    use Symfony\Component\Security\Core\User\UserInterface;

    if (!class_exists(LdapUser::class)) {
        class LdapUser implements UserInterface
        {
            public function __construct(
                public Entry $entry,
                public string $identifier,
                public ?string $password,
                public array $roles,
                public array $extraFields,
            ) {
            }
        }
    }

    if (!class_exists(LdapUserProvider::class)) {
        class LdapUserProvider
        {
            public array $arguments;

            public function __construct(mixed ...$arguments)
            {
                $this->arguments = $arguments;
            }

            public function loadFromEntry(string $identifier, Entry $entry): UserInterface
            {
                return $this->loadUser($identifier, $entry);
            }

            protected function loadUser(string $identifier, Entry $entry): UserInterface
            {
                throw new \LogicException('the provider under test must override loadUser');
            }
        }
    }
}

namespace {

    use App\Extension\Iam\backend\Security\ProfileLdapUserProvider;
    use Doctrine\DBAL\Connection;
    use PHPUnit\Framework\TestCase;
    use Symfony\Component\Ldap\Entry;
    use Symfony\Component\Ldap\LdapInterface;

    require_once dirname(__DIR__, 7) . '/roles/web-app-suitecrm/files/php/iam/profile_ldap_user_provider.php';

    final class ProfileLdapUserProviderTest extends TestCase
    {
        private const FIELD_MAP = [
            'mail' => 'email1',
            'givenName' => 'first_name',
            'telephoneNumber' => 'phone_work',
            'title' => 'title',
            'postalCode' => 'address_postalcode',
        ];

        private const PROFILE_COLUMNS = [
            'givenName' => ['column' => 'first_name', 'length' => 255],
            'telephoneNumber' => ['column' => 'phone_work', 'length' => 50],
            'title' => ['column' => 'title', 'length' => 7],
        ];

        private Connection $connection;

        private function provider(array $profileColumns = self::PROFILE_COLUMNS): ProfileLdapUserProvider
        {
            $this->connection = new Connection();

            return new ProfileLdapUserProvider(
                $this->connection,
                new class () implements LdapInterface {
                },
                'ou=users,dc=example,dc=org',
                'cn=administrator,dc=example,dc=org',
                'secret',
                ['ROLE_USER'],
                'uid',
                '(uid={username})',
                self::FIELD_MAP,
                $profileColumns,
            );
        }

        private static function biber(array $attributes): Entry
        {
            return new Entry('uid=biber,ou=users,dc=example,dc=org', $attributes);
        }

        public function testAnAbsentExtraFieldIsSkippedInsteadOfRefusingTheAccount(): void
        {
            $user = $this->provider()->loadFromEntry('biber', self::biber([
                'mail' => ['biber@example.org'],
                'givenName' => ['Biber'],
                'title' => ['Account Manager'],
            ]));

            self::assertSame('biber', $user->identifier);
            self::assertSame(['ROLE_USER'], $user->roles);
            self::assertNull($user->password);
            self::assertSame(
                ['mail' => ['biber@example.org'], 'givenName' => ['Biber'], 'title' => ['Account Manager']],
                $user->extraFields,
            );
        }

        public function testTheAttributeNameMatchesWithoutRegardToCase(): void
        {
            $user = $this->provider([])->loadFromEntry('biber', self::biber(['postalcode' => ['10115']]));

            self::assertSame(['postalCode' => ['10115']], $user->extraFields);
        }

        public function testTheLookupWritesThePresentProfileColumnsCutToTheirLength(): void
        {
            $this->provider()->loadFromEntry('Biber', self::biber([
                'givenName' => ['Biber'],
                'title' => ['Account Manager'],
            ]));

            self::assertSame([[
                'UPDATE users SET first_name = ?, title = ? WHERE deleted = 0 AND LOWER(user_name) = ?',
                ['Biber', 'Account', 'biber'],
            ]], $this->connection->statements);
        }

        public function testAnEntryWithoutProfileAttributesWritesNothing(): void
        {
            $this->provider()->loadFromEntry('biber', self::biber(['mail' => ['biber@example.org']]));

            self::assertSame([], $this->connection->statements);
        }

        public function testAProfileColumnOutsideTheIdentifierShapeIsRejected(): void
        {
            $this->expectException(InvalidArgumentException::class);

            $this->provider(['title' => ['column' => 'title = title, is_admin', 'length' => 50]]);
        }

        public function testTheParentSearchFetchesEveryAttributeBecauseItHoldsNoExtraField(): void
        {
            $provider = $this->provider();

            self::assertSame([], $provider->arguments[8]);
            self::assertNull($provider->arguments[7]);
            self::assertSame('(uid={username})', $provider->arguments[6]);
        }
    }
}
