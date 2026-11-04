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

namespace Symfony\Component\EventDispatcher {
    if (!interface_exists(EventSubscriberInterface::class)) {
        interface EventSubscriberInterface
        {
            public static function getSubscribedEvents(): array;
        }
    }
}

namespace Symfony\Component\Security\Core\Exception {
    if (!class_exists(CustomUserMessageAuthenticationException::class)) {
        class CustomUserMessageAuthenticationException extends \RuntimeException
        {
        }
    }
}

namespace Symfony\Component\Security\Http\Authenticator\Passport\Badge {
    if (!class_exists(UserBadge::class)) {
        class UserBadge
        {
            public function __construct(private string $identifier)
            {
            }

            public function getUserIdentifier(): string
            {
                return $this->identifier;
            }
        }
    }
}

namespace Nbgrp\OneloginSamlBundle\Security\Http\Authenticator\Passport\Badge {
    if (!class_exists(SamlAttributesBadge::class)) {
        class SamlAttributesBadge
        {
            public function __construct(private array $attributes)
            {
            }

            public function getAttributes(): array
            {
                return $this->attributes;
            }
        }
    }
}

namespace Symfony\Component\Security\Http\Authenticator\Passport {
    if (!class_exists(Passport::class)) {
        class Passport
        {
            public function __construct(private array $badges)
            {
            }

            public function getBadge(string $badgeFqcn): ?object
            {
                foreach ($this->badges as $badge) {
                    if ($badge instanceof $badgeFqcn) {
                        return $badge;
                    }
                }

                return null;
            }
        }
    }
}

namespace Symfony\Component\Security\Http\Event {
    use Symfony\Component\Security\Http\Authenticator\Passport\Passport;

    if (!class_exists(CheckPassportEvent::class)) {
        class CheckPassportEvent
        {
            public function __construct(private Passport $passport)
            {
            }

            public function getPassport(): Passport
            {
                return $this->passport;
            }
        }
    }

    if (!class_exists(LoginSuccessEvent::class)) {
        class LoginSuccessEvent
        {
            public function __construct(private Passport $passport)
            {
            }

            public function getPassport(): Passport
            {
                return $this->passport;
            }
        }
    }
}

namespace {

    use App\Extension\Iam\backend\Security\SamlDirectorySync;
    use Doctrine\DBAL\Connection;
    use Nbgrp\OneloginSamlBundle\Security\Http\Authenticator\Passport\Badge\SamlAttributesBadge;
    use PHPUnit\Framework\TestCase;
    use Symfony\Component\Security\Core\Exception\CustomUserMessageAuthenticationException;
    use Symfony\Component\Security\Http\Authenticator\Passport\Badge\UserBadge;
    use Symfony\Component\Security\Http\Authenticator\Passport\Passport;
    use Symfony\Component\Security\Http\Event\CheckPassportEvent;
    use Symfony\Component\Security\Http\Event\LoginSuccessEvent;

    require_once dirname(__DIR__, 7) . '/roles/web-app-suitecrm/files/php/iam/saml_directory_sync.php';

    final class SamlDirectorySyncTest extends TestCase
    {
        private const ADMIN_GROUP = '/roles/web-app-suitecrm/administrator';
        private const USER_GROUP = '/roles/web-app-suitecrm/user';

        private Connection $connection;

        private function sync(array $profileColumns = []): SamlDirectorySync
        {
            $this->connection = new Connection();

            return new SamlDirectorySync(
                $this->connection,
                'groups',
                [self::ADMIN_GROUP, self::USER_GROUP],
                [self::ADMIN_GROUP],
                ['PlatformAdmin'],
                $profileColumns,
            );
        }

        private static function saml(string $username, array $attributes): Passport
        {
            return new Passport([new UserBadge($username), new SamlAttributesBadge($attributes)]);
        }

        public function testAUserGroupMemberPassesTheGateWithoutAWrite(): void
        {
            $this->sync()->onCheckPassport(new CheckPassportEvent(self::saml('biber', ['groups' => [self::USER_GROUP]])));

            self::assertSame([], $this->connection->statements);
        }

        public function testAUserOutsideEveryRoleGroupIsRefusedAndLosesTheAdminFlag(): void
        {
            $sync = $this->sync();

            try {
                $sync->onCheckPassport(new CheckPassportEvent(self::saml('Biber', ['groups' => ['/roles/web-app-other/user']])));
                self::fail('a user outside every role group must be refused');
            } catch (CustomUserMessageAuthenticationException) {
            }

            self::assertSame([[
                'UPDATE users SET is_admin = ? WHERE deleted = 0 AND is_admin <> ? AND LOWER(user_name) = ?',
                [0, 0, 'biber'],
            ]], $this->connection->statements);
        }

        public function testAnAssertionWithoutTheGroupAttributeIsRefused(): void
        {
            $this->expectException(CustomUserMessageAuthenticationException::class);

            $this->sync()->onCheckPassport(new CheckPassportEvent(self::saml('biber', ['firstName' => ['Biber']])));
        }

        public function testTheProtectedAdministratorPassesWithoutAGroup(): void
        {
            $this->sync()->onCheckPassport(new CheckPassportEvent(self::saml('platformadmin', [])));

            self::assertSame([], $this->connection->statements);
        }

        public function testAPassportWithoutSamlAttributesIsLeftAlone(): void
        {
            $sync = $this->sync();
            $passport = new Passport([new UserBadge('biber')]);

            $sync->onCheckPassport(new CheckPassportEvent($passport));
            $sync->onLoginSuccess(new LoginSuccessEvent($passport));

            self::assertSame([], $this->connection->statements);
        }

        public function testTheAdministratorGroupGrantsTheAdminFlagAtSignIn(): void
        {
            $this->sync()->onLoginSuccess(new LoginSuccessEvent(self::saml('biber', ['groups' => [self::USER_GROUP, self::ADMIN_GROUP]])));

            self::assertSame([[
                'UPDATE users SET is_admin = ? WHERE deleted = 0 AND is_admin <> ? AND LOWER(user_name) = ?',
                [1, 1, 'biber'],
            ]], $this->connection->statements);
        }

        public function testTheProtectedAdministratorKeepsItsFlagAndGetsItsProfile(): void
        {
            $this->sync(['firstName' => ['column' => 'first_name', 'length' => 255]])
                ->onLoginSuccess(new LoginSuccessEvent(self::saml('PlatformAdmin', ['firstName' => ['Platform']])));

            self::assertSame([[
                'UPDATE users SET first_name = ? WHERE deleted = 0 AND LOWER(user_name) = ?',
                ['Platform', 'platformadmin'],
            ]], $this->connection->statements);
        }

        public function testTheProfileColumnsTakeThePresentAttributesCutToTheColumnLength(): void
        {
            $this->sync([
                'telephoneNumber' => ['column' => 'phone_work', 'length' => 50],
                'title' => ['column' => 'title', 'length' => 5],
                'ou' => ['column' => 'department', 'length' => 50],
            ])->onLoginSuccess(new LoginSuccessEvent(self::saml('biber', [
                'groups' => [self::USER_GROUP],
                'telephoneNumber' => ['+49 30 1234567'],
                'title' => ['Account Manager'],
            ])));

            self::assertSame([
                [
                    'UPDATE users SET phone_work = ?, title = ? WHERE deleted = 0 AND LOWER(user_name) = ?',
                    ['+49 30 1234567', 'Accou', 'biber'],
                ],
                [
                    'UPDATE users SET is_admin = ? WHERE deleted = 0 AND is_admin <> ? AND LOWER(user_name) = ?',
                    [0, 0, 'biber'],
                ],
            ], $this->connection->statements);
        }

        public function testAProfileColumnOutsideTheIdentifierShapeIsRejected(): void
        {
            $this->expectException(InvalidArgumentException::class);

            $this->sync(['title' => ['column' => 'title; DROP TABLE users', 'length' => 50]]);
        }

        public function testAnEmptyLoginGroupListIsRejected(): void
        {
            $this->expectException(InvalidArgumentException::class);

            new SamlDirectorySync(new Connection(), 'groups', [], [], ['platformadmin'], []);
        }

        public function testTheGateRunsBeforeTheUserIsLoaded(): void
        {
            $events = SamlDirectorySync::getSubscribedEvents();

            self::assertGreaterThan(256, $events[CheckPassportEvent::class][1]);
            self::assertGreaterThan(0, $events[LoginSuccessEvent::class][1]);
        }
    }
}
