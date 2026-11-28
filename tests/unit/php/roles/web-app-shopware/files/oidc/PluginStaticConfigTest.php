<?php

declare(strict_types=1);

namespace Symfony\Component\DependencyInjection {
    final class ContainerBuilder
    {
        public function __construct(private array $parameters)
        {
        }

        public function getParameter(string $name): mixed
        {
            return $this->parameters[$name];
        }
    }
}

namespace Symfony\Component\DependencyInjection\Loader\Configurator {
    final class ContainerConfigurator
    {
        public array $imports = [];

        public function import(string $resource): void
        {
            $this->imports[] = $resource;
        }
    }
}

namespace {

    use PHPUnit\Framework\TestCase;
    use Symfony\Component\DependencyInjection\ContainerBuilder;
    use Symfony\Component\DependencyInjection\Loader\Configurator\ContainerConfigurator;

    final class PluginStaticConfigTest extends TestCase
    {
        private const PLUGIN = 'KskHeptacomAdminOpenAuth';

        private string $projectDir;

        private string $staticDir;

        protected function setUp(): void
        {
            $this->projectDir = sys_get_temp_dir() . '/' . uniqid('plugin-static-config-', true);
            $this->staticDir = $this->projectDir . '/config/infinito/static_system_config';
            mkdir($this->staticDir, 0777, true);
            file_put_contents($this->staticDir . '/' . self::PLUGIN . '.yaml', "{}\n");
            file_put_contents($this->staticDir . '/OtherPlugin.yaml', "{}\n");
        }

        protected function tearDown(): void
        {
            array_map('unlink', glob($this->staticDir . '/*') ?: []);
            foreach ([$this->staticDir, dirname($this->staticDir), $this->projectDir . '/config', $this->projectDir] as $dir) {
                if (is_dir($dir)) {
                    rmdir($dir);
                }
            }
        }

        private function imported(array $activePlugins): array
        {
            $config = require dirname(__DIR__, 7) . '/roles/web-app-shopware/files/php/oidc/plugin_static_config.php';
            $active = [];

            foreach ($activePlugins as $name) {
                $active['Vendor\\' . $name] = ['name' => $name, 'path' => '/plugins/' . $name, 'class' => 'Vendor\\' . $name];
            }

            $configurator = new ContainerConfigurator();
            $config($configurator, new ContainerBuilder([
                'kernel.active_plugins' => $active,
                'kernel.project_dir' => $this->projectDir,
            ]));

            return array_map('basename', $configurator->imports);
        }

        public function testTheStaticKeysOfAnActivePluginGoLive(): void
        {
            $this->assertSame([self::PLUGIN . '.yaml'], $this->imported([self::PLUGIN]));
        }

        public function testNegativeControlTheStaticKeysStayOutWhileThePluginIsBeingInstalled(): void
        {
            $this->assertSame([], $this->imported([]));
        }

        public function testOnlyTheFileOfAnActivePluginIsImported(): void
        {
            $this->assertSame([self::PLUGIN . '.yaml'], $this->imported(['UnrelatedPlugin', self::PLUGIN]));
        }

        public function testWithoutStaticFilesNothingIsImported(): void
        {
            array_map('unlink', glob($this->staticDir . '/*') ?: []);
            rmdir($this->staticDir);

            $this->assertSame([], $this->imported([self::PLUGIN]));
        }
    }
}
