<?php

namespace App\Listeners;

use App\Http\Controllers\RemoteOidcController;
use App\Services\InfinitoRbacUserinfoClient;
use App\Services\UserOidcService;
use Illuminate\Auth\Events\Login;
use Illuminate\Routing\Events\RouteMatched;
use Illuminate\Support\Facades\Log;
use RuntimeException;

/**
 * Sets the admin flag of an account at its OIDC sign-in from the administrator role group in the groups claim.
 *
 * Env:
 *   PF_INFINITO_RBAC_CLAIM          name of the groups claim
 *   PF_INFINITO_RBAC_ADMIN_GROUP    groups claim value of the administrator role
 *   PF_INFINITO_RBAC_KEPT_USERNAME  username whose admin flag a sign-in never changes
 */
class InfinitoRbacOidcLogin
{
    public function handleRouteMatched(RouteMatched $event): void
    {
        if ($event->route->getActionName() !== RemoteOidcController::class.'@handleCallback') {
            return;
        }

        app()->extend(UserOidcService::class, static function (UserOidcService $provider): UserOidcService {
            $client = new InfinitoRbacUserinfoClient($provider->getHttpClient(), (string) config('remote-auth.oidc.profileURL'));
            app()->instance(InfinitoRbacUserinfoClient::class, $client);

            return $provider->setHttpClient($client);
        });
    }

    public function handleLogin(Login $event): void
    {
        if (! app()->bound(InfinitoRbacUserinfoClient::class)) {
            return;
        }

        $groups = (array) (app(InfinitoRbacUserinfoClient::class)->claims()[self::env('PF_INFINITO_RBAC_CLAIM')] ?? []);
        $user = $event->user;

        if (strtolower($user->username) === strtolower(self::env('PF_INFINITO_RBAC_KEPT_USERNAME'))) {
            return;
        }

        $isAdmin = in_array(self::env('PF_INFINITO_RBAC_ADMIN_GROUP'), $groups, true);

        if ((bool) $user->is_admin === $isAdmin) {
            return;
        }

        $user->is_admin = $isAdmin;
        $user->save();
        Log::info('InfinitoRbac: the OIDC sign-in of '.$user->username.' set its admin flag to '.($isAdmin ? 'true' : 'false'));
    }

    private static function env(string $key): string
    {
        $value = getenv($key);

        if ($value === false || $value === '') {
            throw new RuntimeException("InfinitoRbac: {$key} is empty");
        }

        return $value;
    }
}
