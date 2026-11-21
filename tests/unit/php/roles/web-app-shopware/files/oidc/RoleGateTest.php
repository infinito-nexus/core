<?php

declare(strict_types=1);

namespace Heptacom\AdminOpenAuth\Contract {
    final class RoleAssignment
    {
        public bool $isAdministrator = false;

        public array $roleIds = [];
    }

    final class User
    {
        public function __construct(private ?object $roleAssignment, private ?object $oidcData)
        {
        }

        public function getExtensionOfType(string $name, string $type): ?object
        {
            $extension = match ($name) {
                'roleAssignment' => $this->roleAssignment,
                'oidcData' => $this->oidcData,
                default => null,
            };

            return $extension instanceof $type ? $extension : null;
        }
    }
}

namespace Heptacom\AdminOpenAuth\Http\Route\Support {
    use Heptacom\AdminOpenAuth\Contract\User;

    final class UserRedirectReceivedEvent
    {
        public function __construct(public readonly User $user)
        {
        }
    }
}

namespace Shopware\Core\Framework\Struct {
    final class ArrayStruct
    {
        public function __construct(private array $data)
        {
        }

        public function get(string $key): mixed
        {
            return $this->data[$key] ?? null;
        }
    }
}

namespace Symfony\Component\HttpKernel\Exception {
    class AccessDeniedHttpException extends \RuntimeException
    {
    }
}

namespace {

    use App\InfinitoRbac\AdminOpenAuthRoleGate;
    use Heptacom\AdminOpenAuth\Contract\RoleAssignment;
    use Heptacom\AdminOpenAuth\Contract\User;
    use Heptacom\AdminOpenAuth\Http\Route\Support\UserRedirectReceivedEvent;
    use PHPUnit\Framework\TestCase;
    use Shopware\Core\Framework\Struct\ArrayStruct;
    use Symfony\Component\HttpKernel\Exception\AccessDeniedHttpException;

    require_once dirname(__DIR__, 7) . '/roles/web-app-shopware/files/php/oidc/role_gate.php';

    final class RoleGateTest extends TestCase
    {
        private const VERIFIED = ['sub' => 'f3b1c2d4', 'email' => 'biber@example.test', 'email_verified' => true];

        private static function event(?RoleAssignment $assignment, ?array $idTokenPayload = self::VERIFIED): UserRedirectReceivedEvent
        {
            $oidcData = $idTokenPayload === null ? null : new ArrayStruct(['idTokenPayload' => $idTokenPayload]);

            return new UserRedirectReceivedEvent(new User($assignment, $oidcData));
        }

        private static function assignment(bool $isAdministrator, array $roleIds): RoleAssignment
        {
            $assignment = new RoleAssignment();
            $assignment->isAdministrator = $isAdministrator;
            $assignment->roleIds = $roleIds;

            return $assignment;
        }

        public function testTheAdministratorRuleAdmitsTheSignIn(): void
        {
            (new AdminOpenAuthRoleGate())(self::event(self::assignment(true, [])));

            $this->addToAssertionCount(1);
        }

        public function testAnAclRoleAdmitsTheSignIn(): void
        {
            (new AdminOpenAuthRoleGate())(self::event(self::assignment(false, ['0190f4c5a6a07a1f8d0c3b1e2f3a4b5c'])));

            $this->addToAssertionCount(1);
        }

        public function testASignInWithoutAnyGrantIsRefused(): void
        {
            $this->expectException(AccessDeniedHttpException::class);

            (new AdminOpenAuthRoleGate())(self::event(self::assignment(false, [])));
        }

        public function testASignInWithoutARoleAssignmentIsRefused(): void
        {
            $this->expectException(AccessDeniedHttpException::class);

            (new AdminOpenAuthRoleGate())(self::event(null));
        }

        public function testAnUnverifiedEmailIsRefusedEvenForTheAdministratorGroup(): void
        {
            $this->expectException(AccessDeniedHttpException::class);

            (new AdminOpenAuthRoleGate())(self::event(self::assignment(true, []), ['email_verified' => false] + self::VERIFIED));
        }

        public function testAMissingEmailVerifiedClaimIsRefused(): void
        {
            $payload = self::VERIFIED;
            unset($payload['email_verified']);
            $this->expectException(AccessDeniedHttpException::class);

            (new AdminOpenAuthRoleGate())(self::event(self::assignment(true, []), $payload));
        }

        public function testAStringTrueIsNotAVerifiedEmail(): void
        {
            $this->expectException(AccessDeniedHttpException::class);

            (new AdminOpenAuthRoleGate())(self::event(self::assignment(true, []), ['email_verified' => 'true'] + self::VERIFIED));
        }

        public function testASignInWithoutIdTokenDataIsRefused(): void
        {
            $this->expectException(AccessDeniedHttpException::class);

            (new AdminOpenAuthRoleGate())(self::event(self::assignment(true, []), null));
        }
    }
}
