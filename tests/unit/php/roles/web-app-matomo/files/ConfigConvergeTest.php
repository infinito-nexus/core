<?php

declare(strict_types=1);

use PHPUnit\Framework\TestCase;

final class ConfigConvergeTest extends TestCase
{
    private const SCRIPT = '/roles/web-app-matomo/files/php/config_converge.php';

    private const INCLUDE_PATH = "define('PIWIK_INCLUDE_PATH', '/var/www/html');";

    private const MATOMO = <<<'PHP'
        <?php
        namespace {
            final class MatomoStub
            {
                public static function load(): array
                {
                    return json_decode((string) file_get_contents((string) getenv('STUB_STATE')), true);
                }

                public static function save(array $state): void
                {
                    file_put_contents((string) getenv('STUB_STATE'), json_encode($state));
                }
            }
        }

        namespace Piwik {
            final class Config
            {
                private array $settings;

                public function __construct()
                {
                    $this->settings = \MatomoStub::load()['config'];
                }

                public static function getInstance(): self
                {
                    return new self();
                }

                public function __get(string $name)
                {
                    return array_key_exists($name, $this->settings) ? $this->settings[$name] : [];
                }

                public function __set(string $name, $value): void
                {
                    $this->settings[$name] = $value;
                }

                public function forceSave(): void
                {
                    $state = \MatomoStub::load();
                    \MatomoStub::save(['config' => $this->settings, 'saves' => $state['saves'] + 1]);
                }
            }

            final class FrontController
            {
                public static function getInstance(): self
                {
                    return new self();
                }

                public function init(): void
                {
                }
            }
        }

        namespace Piwik\Application {
            final class Environment
            {
                public function __construct($environment)
                {
                }

                public function init(): void
                {
                }
            }
        }
        PHP;

    /**
     * Feed the script on stdin to php, as the role does, against a stubbed config.ini.php.
     *
     * @param string $sections the MATOMO_CONFIG_SECTIONS value
     * @param string $general the MATOMO_CONFIG_GENERAL value
     * @param array<string, array<string, mixed>> $config the sections the stub starts from
     * @return array{0: string, 1: string, 2: int, 3: array{config: array<string, mixed>, saves: int}}
     *         stdout, stderr, exit code and the stub state afterwards
     */
    private function runScript(string $sections, string $general, array $config): array
    {
        $root = sys_get_temp_dir() . '/matomo-config-' . bin2hex(random_bytes(8));
        mkdir($root);
        file_put_contents("$root/index.php", self::MATOMO);
        file_put_contents("$root/state.json", json_encode(['config' => $config, 'saves' => 0]));

        $source = (string) file_get_contents(dirname(__DIR__, 6) . self::SCRIPT);
        $source = str_replace(
            self::INCLUDE_PATH,
            'define(\'PIWIK_INCLUDE_PATH\', ' . var_export($root, true) . ');',
            $source,
            $replaced
        );
        $this->assertSame(1, $replaced, 'the script MUST define PIWIK_INCLUDE_PATH exactly once');

        $process = proc_open(
            [PHP_BINARY],
            [0 => ['pipe', 'r'], 1 => ['pipe', 'w'], 2 => ['pipe', 'w']],
            $pipes,
            null,
            [
                'MATOMO_CONFIG_SECTIONS' => $sections,
                'MATOMO_CONFIG_GENERAL' => $general,
                'STUB_STATE' => "$root/state.json",
                'PATH' => (string) getenv('PATH'),
            ]
        );
        fwrite($pipes[0], $source);
        fclose($pipes[0]);
        $stdout = (string) stream_get_contents($pipes[1]);
        $stderr = (string) stream_get_contents($pipes[2]);
        fclose($pipes[1]);
        fclose($pipes[2]);
        $code = proc_close($process);

        $after = json_decode((string) file_get_contents("$root/state.json"), true);
        unlink("$root/state.json");
        unlink("$root/index.php");
        rmdir($root);

        return [$stdout, $stderr, $code, $after];
    }

    public function testAReplacedSectionHoldsExactlyTheDesiredKeys(): void
    {
        [$stdout, $stderr, $code, $after] = $this->runScript(
            json_encode(['RebelOIDC' => ['allow_signup' => false, 'scope' => 'openid']]),
            '{}',
            ['General' => ['salt' => 's'], 'RebelOIDC' => ['allow_signup' => '1', 'stale' => 'x']]
        );

        $this->assertSame(0, $code, $stderr);
        $this->assertSame("CHANGED\n", $stdout);
        $this->assertSame(['allow_signup' => '0', 'scope' => 'openid'], $after['config']['RebelOIDC']);
        $this->assertSame(1, $after['saves']);
    }

    public function testAMatchingSectionIsNotSaved(): void
    {
        [$stdout, $stderr, $code, $after] = $this->runScript(
            json_encode(['RebelOIDC' => ['allow_signup' => true]]),
            '{}',
            ['General' => ['salt' => 's'], 'RebelOIDC' => ['allow_signup' => '1']]
        );

        $this->assertSame(0, $code, $stderr);
        $this->assertSame('', $stdout);
        $this->assertSame(0, $after['saves']);
    }

    public function testAnEmptyObjectEmptiesTheSection(): void
    {
        [$stdout, $stderr, $code, $after] = $this->runScript(
            json_encode(['RebelOIDC' => new stdClass()]),
            '{}',
            ['General' => ['salt' => 's'], 'RebelOIDC' => ['scope' => 'openid']]
        );

        $this->assertSame(0, $code, $stderr);
        $this->assertSame("CHANGED\n", $stdout);
        $this->assertSame([], $after['config']['RebelOIDC']);
    }

    public function testAMissingSectionIsCreated(): void
    {
        [$stdout, $stderr, $code, $after] = $this->runScript(
            json_encode(['RebelOIDC' => ['scope' => 'openid']]),
            '{}',
            ['General' => ['salt' => 's']]
        );

        $this->assertSame(0, $code, $stderr);
        $this->assertSame("CHANGED\n", $stdout);
        $this->assertSame(['scope' => 'openid'], $after['config']['RebelOIDC']);
    }

    public function testTheGeneralSectionCannotBeReplaced(): void
    {
        [$stdout, $stderr, $code, $after] = $this->runScript(
            json_encode(['General' => new stdClass()]),
            '{}',
            ['General' => ['salt' => 's']]
        );

        $this->assertSame(1, $code);
        $this->assertStringContainsString('[FAIL] MATOMO_CONFIG_SECTIONS.General is no replaceable section', $stderr);
        $this->assertSame('', $stdout);
        $this->assertSame(0, $after['saves']);
    }

    public function testAGeneralKeyIsSetWhenMissingOrDifferent(): void
    {
        [$stdout, $stderr, $code, $after] = $this->runScript(
            '{}',
            json_encode(['assume_secure_protocol' => true, 'force_ssl' => '1']),
            ['General' => ['salt' => 's', 'assume_secure_protocol' => '0']]
        );

        $this->assertSame(0, $code, $stderr);
        $this->assertSame("CHANGED\n", $stdout);
        $this->assertSame(
            ['salt' => 's', 'assume_secure_protocol' => '1', 'force_ssl' => '1'],
            $after['config']['General']
        );
    }

    public function testAnEmptyStringRemovesAGeneralKey(): void
    {
        [$stdout, $stderr, $code, $after] = $this->runScript(
            '{}',
            json_encode(['force_ssl' => '']),
            ['General' => ['salt' => 's', 'force_ssl' => '1']]
        );

        $this->assertSame(0, $code, $stderr);
        $this->assertSame("CHANGED\n", $stdout);
        $this->assertSame(['salt' => 's'], $after['config']['General']);
    }

    public function testRemovingAnAbsentGeneralKeyChangesNothing(): void
    {
        [$stdout, $stderr, $code, $after] = $this->runScript(
            '{}',
            json_encode(['force_ssl' => '']),
            ['General' => ['salt' => 's']]
        );

        $this->assertSame(0, $code, $stderr);
        $this->assertSame('', $stdout);
        $this->assertSame(0, $after['saves']);
    }

    public function testAListValueIsWrittenAsAListOfStrings(): void
    {
        [$stdout, $stderr, $code, $after] = $this->runScript(
            '{}',
            json_encode(['proxy_scheme_headers' => ['HTTP_X_FORWARDED_PROTO']]),
            ['General' => ['salt' => 's']]
        );

        $this->assertSame(0, $code, $stderr);
        $this->assertSame("CHANGED\n", $stdout);
        $this->assertSame(['HTTP_X_FORWARDED_PROTO'], $after['config']['General']['proxy_scheme_headers']);
    }

    public function testAnEmptyVariableFails(): void
    {
        [, $stderr, $code] = $this->runScript('', '{}', ['General' => ['salt' => 's']]);

        $this->assertSame(1, $code);
        $this->assertStringContainsString('[FAIL] MATOMO_CONFIG_SECTIONS is empty', $stderr);
    }

    public function testAVariableThatIsNoObjectFails(): void
    {
        [, $stderr, $code] = $this->runScript('{}', '"text"', ['General' => ['salt' => 's']]);

        $this->assertSame(1, $code);
        $this->assertStringContainsString('[FAIL] MATOMO_CONFIG_GENERAL is no JSON object', $stderr);
    }
}
