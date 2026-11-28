<?php

declare(strict_types=1);

use Symfony\Component\DependencyInjection\ContainerBuilder;
use Symfony\Component\DependencyInjection\Loader\Configurator\ContainerConfigurator;

/*
 * Exception: plugin:install writes every config.xml default with override, and Shopware refuses a
 * static key whose value differs, so a plugin's static keys go live only once the plugin is active.
 */
return static function (ContainerConfigurator $configurator, ContainerBuilder $container): void {
    $active = array_column($container->getParameter('kernel.active_plugins'), 'name');
    $pattern = $container->getParameter('kernel.project_dir') . '/config/infinito/static_system_config/*.yaml';

    foreach (glob($pattern) ?: [] as $file) {
        if (\in_array(basename($file, '.yaml'), $active, true)) {
            $configurator->import($file);
        }
    }
};
