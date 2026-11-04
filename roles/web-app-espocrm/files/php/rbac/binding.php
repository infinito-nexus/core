<?php
// nocheck: mirrored-unit-test - only registers one container binding that EspoCRM's
// binding loader reads; the provider it binds is tested by GroupUserProviderTest.php

namespace Espo\Modules\InfinitoRbac;

use Espo\Core\Binding\Binder;
use Espo\Core\Binding\BindingProcessor;

class Binding implements BindingProcessor
{
    public function process(Binder $binder): void
    {
        $binder
            ->for('Espo\\Core\\Authentication\\Oidc\\Login')
            ->bindImplementation(
                'Espo\\Core\\Authentication\\Oidc\\UserProvider',
                'Espo\\Modules\\InfinitoRbac\\Classes\\Oidc\\GroupUserProvider'
            );
    }
}
