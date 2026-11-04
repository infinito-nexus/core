<?php
/**
 * Registers SyncRolesOnLogin for every sign-in.
 */

namespace Infinito\SnipeItLoginRbac;

use Illuminate\Auth\Events\Login;
use Illuminate\Support\ServiceProvider;

final class LoginRbacServiceProvider extends ServiceProvider
{
    public function boot(): void
    {
        $this->app->make('events')->listen(Login::class, SyncRolesOnLogin::class);
    }
}
