<?php

declare(strict_types=1);

use PHPUnit\Framework\TestCase;

final class LoginRbacServiceProviderTest extends TestCase
{
    private const DRIVER = <<<'PHP'
        <?php
        namespace Illuminate\Support {
            abstract class ServiceProvider
            {
                public function __construct(protected $app)
                {
                }
            }
        }

        namespace {
            $events = new class () {
                public array $listened = [];

                public function listen(string $event, string $listener): void
                {
                    $this->listened[] = [$event, $listener];
                }
            };
            $app = new class ($events) {
                public array $made = [];

                public function __construct(private object $events)
                {
                }

                public function make(string $abstract): object
                {
                    $this->made[] = $abstract;
                    return $this->events;
                }
            };
            require getenv('PROVIDER');
            (new Infinito\SnipeItLoginRbac\LoginRbacServiceProvider($app))->boot();
            echo json_encode(['made' => $app->made, 'listened' => $events->listened]);
        }
        PHP;

    private static function packageDir(): string
    {
        return dirname(__DIR__, 8) . '/roles/web-app-snipe-it/files/php/login_rbac';
    }

    public function testBootListensToEverySignIn(): void
    {
        $driver = tempnam(sys_get_temp_dir(), 'snipeitloginrbacprovider');
        file_put_contents($driver, self::DRIVER);
        try {
            $process = proc_open(
                [PHP_BINARY, $driver],
                [1 => ['pipe', 'w'], 2 => ['pipe', 'w']],
                $pipes,
                null,
                ['PROVIDER' => self::packageDir() . '/src/login_rbac_service_provider.php']
            );
            $stdout = (string) stream_get_contents($pipes[1]);
            $stderr = (string) stream_get_contents($pipes[2]);
            fclose($pipes[1]);
            fclose($pipes[2]);
            $code = proc_close($process);
        } finally {
            unlink($driver);
        }

        $this->assertSame(0, $code, $stderr);
        $this->assertSame(
            [
                'made' => ['events'],
                'listened' => [['Illuminate\Auth\Events\Login', 'Infinito\SnipeItLoginRbac\SyncRolesOnLogin']],
            ],
            json_decode($stdout, true)
        );
    }

    public function testPackageDiscoveryFindsTheProviderAndTheAutoloaderItsClasses(): void
    {
        $composer = json_decode((string) file_get_contents(self::packageDir() . '/composer.json'), true);

        $this->assertSame(['Infinito\SnipeItLoginRbac\LoginRbacServiceProvider'], $composer['extra']['laravel']['providers']);
        $this->assertSame(['src/'], $composer['autoload']['classmap']);
        foreach (['login_rbac_service_provider.php' => 'LoginRbacServiceProvider', 'sync_roles_on_login.php' => 'SyncRolesOnLogin'] as $file => $class) {
            $this->assertMatchesRegularExpression(
                '/^namespace Infinito\\\\SnipeItLoginRbac;$.*^final class ' . $class . '\b/ms',
                (string) file_get_contents(self::packageDir() . '/src/' . $file)
            );
        }
    }
}
