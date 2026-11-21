<?php

/**
 * Refuse an AdminOpenAuth sign-in whose ID token holds no verified email, or
 * that no role-assignment rule granted anything.
 *
 * Registered in templates/adminopenauth.yaml.j2 as a listener of
 * UserRedirectReceivedEvent with a priority below the rule execution of
 * AdminOpenAuth, so it reads the RoleAssignment the rules produced before the
 * Shopware user is created or updated. AdminOpenAuth resolves that user by
 * email first, so an unverified address must never reach the resolver.
 */

declare(strict_types=1);

namespace App\InfinitoRbac;

use Heptacom\AdminOpenAuth\Contract\RoleAssignment;
use Heptacom\AdminOpenAuth\Http\Route\Support\UserRedirectReceivedEvent;
use Shopware\Core\Framework\Struct\ArrayStruct;
use Symfony\Component\HttpKernel\Exception\AccessDeniedHttpException;

final class AdminOpenAuthRoleGate
{
    public function __invoke(UserRedirectReceivedEvent $event): void
    {
        $claims = $event->user->getExtensionOfType('oidcData', ArrayStruct::class)?->get('idTokenPayload');

        if (!\is_array($claims) || ($claims['email_verified'] ?? null) !== true) {
            throw new AccessDeniedHttpException('This account has no verified email address.');
        }

        $assignment = $event->user->getExtensionOfType('roleAssignment', RoleAssignment::class);

        if ($assignment instanceof RoleAssignment && ($assignment->isAdministrator || $assignment->roleIds !== [])) {
            return;
        }

        throw new AccessDeniedHttpException('This account holds no Shopware role group.');
    }
}
