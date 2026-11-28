<?php

declare(strict_types=1);

namespace Infinito\Tests\Roles\WebAppEspocrm\Seed;

use PHPUnit\Framework\TestCase;

final class ConfigTest extends TestCase
{
    private const SCRIPT = '/roles/web-app-espocrm/files/php/seed/config.php';

    private const BOOTSTRAP_REQUIRE = 'require "/var/www/html/bootstrap.php";';

    private const STORED = ['maintenanceMode' => false, 'useCache' => false, 'passwordSalt' => 'stored-salt'];

    private const SEED = [
        'ESPOCRM_SEED_MAINTENANCE_MODE' => 'true',
        'ESPOCRM_SEED_USE_CACHE' => 'false',
        'ESPOCRM_SEED_PASSWORD_SALT' => 'seeded-salt',
        'ESPOCRM_SEEDER_FORM_FIELDS' => 'maintenance_mode,use_cache',
    ];

    private const BOOTSTRAP = <<<'PHP'
        <?php
        namespace {
            final class EspoStub
            {
                public static array $state = [];

                public static function load(): void
                {
                    self::$state = json_decode((string) file_get_contents((string) getenv('STUB_STATE')), true);
                }

                public static function save(): void
                {
                    file_put_contents((string) getenv('STUB_STATE'), json_encode(self::$state));
                }
            }

            EspoStub::load();
            register_shutdown_function([EspoStub::class, 'save']);
        }

        namespace Espo\Core {
            final class StubConfig
            {
                public function get(string $key): mixed
                {
                    return \EspoStub::$state['config'][$key] ?? null;
                }
            }

            final class StubConfigWriter
            {
                public function set(string $key, mixed $value): void
                {
                    \EspoStub::$state['set'][$key] = $value;
                }

                public function save(): void
                {
                    \EspoStub::$state['saves']++;
                }
            }

            final class StubFactory
            {
                public function create(string $className): object
                {
                    return match ($className) {
                        '\Espo\Core\Utils\Config\ConfigWriter' => new StubConfigWriter(),
                    };
                }
            }

            final class StubContainer
            {
                public function get(string $name): object
                {
                    return match ($name) {
                        'config' => new StubConfig(),
                        'injectableFactory' => new StubFactory(),
                    };
                }
            }

            final class Application
            {
                public function getContainer(): StubContainer
                {
                    return new StubContainer();
                }
            }
        }
        PHP;

    private string $root;

    protected function setUp(): void
    {
        $this->root = sys_get_temp_dir() . '/espocrm-seed-config-' . bin2hex(random_bytes(8));
        mkdir($this->root, 0700, true);
        file_put_contents($this->root . '/bootstrap.php', self::BOOTSTRAP);
    }

    protected function tearDown(): void
    {
        foreach (['bootstrap.php', 'state.json'] as $file) {
            if (is_file($this->root . '/' . $file)) {
                unlink($this->root . '/' . $file);
            }
        }
        rmdir($this->root);
    }

    /**
     * Pipe the seeder into php against the stubbed EspoCRM, as the role runs it in the container.
     *
     * @param array<string, string> $env ESPOCRM_SEED_* values, the form fields and the seeder mode
     * @return array{0: string, 1: string, 2: int, 3: array{config: array<string, mixed>, set: array<string, mixed>, saves: int}}
     *         stdout, stderr, exit code and the stub state afterwards
     */
    private function seed(array $env): array
    {
        $state = $this->root . '/state.json';
        file_put_contents($state, json_encode(['config' => self::STORED, 'set' => new \stdClass(), 'saves' => 0]));

        $source = str_replace(
            self::BOOTSTRAP_REQUIRE,
            'require ' . var_export($this->root . '/bootstrap.php', true) . ';',
            (string) file_get_contents(dirname(__DIR__, 7) . self::SCRIPT),
            $replaced
        );
        $this->assertSame(1, $replaced, 'the seeder MUST require the EspoCRM bootstrap exactly once');

        $process = proc_open(
            [PHP_BINARY, '-d', 'variables_order=EGPCS'],
            [0 => ['pipe', 'r'], 1 => ['pipe', 'w'], 2 => ['pipe', 'w']],
            $pipes,
            null,
            $env + ['STUB_STATE' => $state, 'PATH' => (string) getenv('PATH')]
        );
        fwrite($pipes[0], $source);
        fclose($pipes[0]);
        $stdout = (string) stream_get_contents($pipes[1]);
        $stderr = (string) stream_get_contents($pipes[2]);
        fclose($pipes[1]);
        fclose($pipes[2]);
        $code = proc_close($process);

        return [$stdout, $stderr, $code, json_decode((string) file_get_contents($state), true)];
    }

    public function testTheReadReportsTheDriftOfTheFormFieldsAndWritesNothing(): void
    {
        [$stdout, $stderr, $code, $after] = $this->seed(self::SEED + ['ESPOCRM_SEEDER_MODE' => 'read']);

        $this->assertSame(0, $code, $stderr);
        $this->assertSame("{\"settings\":{\"maintenance_mode\":false},\"hidden\":1}\n", $stdout);
        $this->assertSame([], $after['set']);
        $this->assertSame(0, $after['saves']);
    }

    public function testTheWriteSetsAndSavesEveryDifferingSetting(): void
    {
        [$stdout, $stderr, $code, $after] = $this->seed(self::SEED);
        $set = $after['set'];
        ksort($set);

        $this->assertSame(0, $code, $stderr);
        $this->assertSame("CHANGED\n", $stdout);
        $this->assertSame(['maintenanceMode' => true, 'passwordSalt' => 'seeded-salt'], $set);
        $this->assertSame(1, $after['saves']);
    }
}
