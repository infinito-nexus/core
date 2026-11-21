<?php

declare(strict_types=1);

use PHPUnit\Framework\TestCase;

final class ProbeTest extends TestCase
{
    private const CLEARNET = 'https://next.cloud.example';

    private const ONION = 'http://next.cloud.k6ef7vnaclqi3scmtehdah5szh3y52564zbsinpgmfsg7ytvfla4mcyd.onion';

    private const BASE_ENDPOINT = 'https://next.cloud.example/push';

    private const STUB_BASE = <<<'PHP'
        <?php
        namespace OCP {
            interface IConfig {}
            interface IURLGenerator {}
            final class Server {
                public static function get(string $id): object {
                    return \StubContainer::get($id);
                }
            }
        }
        namespace OCP\App {
            interface IAppManager {}
        }
        namespace OCP\Capabilities {
            interface ICapability {}
        }
        namespace {
            final class OC {
                public static bool $CLI = true;
            }
            final class StubConfig implements \OCP\IConfig {
                public function getAppValue($app, $key) {
                    return [$app, $key] === ['notify_push', 'base_endpoint'] ? (string) getenv('STUB_BASE_ENDPOINT') : '';
                }
            }
            final class StubUrlGenerator implements \OCP\IURLGenerator {
                public function linkToRoute($route) {
                    return '/apps/notify_push/pre_auth';
                }
                public function getAbsoluteURL($url) {
                    if (\OC::$CLI) {
                        return rtrim((string) getenv('STUB_CLI_URL'), '/') . '/' . ltrim($url, '/');
                    }
                    $scheme = !empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off' ? 'https' : 'http';
                    return $scheme . '://' . $_SERVER['HTTP_HOST'] . (str_starts_with($url, '/') ? '' : '/') . $url;
                }
            }
            final class StubContainer {
                public static function get(string $id): object {
                    return match ($id) {
                        \OCP\App\IAppManager::class => new class implements \OCP\App\IAppManager {
                            public function loadApp(string $app): void {
                                require_once (string) getenv('STUB_CAPABILITIES');
                            }
                        },
                        \OCA\NotifyPush\Capabilities::class => new \OCA\NotifyPush\Capabilities(new StubConfig(), new StubUrlGenerator()),
                    };
                }
            }
        }
        PHP;

    private string $root;

    private string $capabilities;

    protected function setUp(): void
    {
        $this->root = sys_get_temp_dir() . '/nextcloud-notify-push-probe-' . bin2hex(random_bytes(6));
        mkdir($this->root . '/lib', 0700, true);
        file_put_contents($this->root . '/lib/base.php', self::STUB_BASE);
        $this->capabilities = $this->root . '/Capabilities.php';
        copy(__DIR__ . '/fixtures/Capabilities.v1.4.2.php.txt', $this->capabilities);
    }

    protected function tearDown(): void
    {
        foreach ([$this->capabilities, $this->root . '/lib/base.php'] as $file) {
            if (is_file($file)) {
                unlink($file);
            }
        }
        rmdir($this->root . '/lib');
        rmdir($this->root);
    }

    /**
     * Feed a role program on stdin, as the addon tasks do.
     *
     * @param string $program file name under files/php/addons/notify_push/
     * @param list<string> $args program arguments after the --
     * @param string $baseEndpoint base_endpoint the stub config holds
     * @return array{0: string, 1: string, 2: int} stdout, stderr and exit code
     */
    private function runProgram(string $program, array $args, string $baseEndpoint): array
    {
        $script = dirname(__DIR__, 9) . '/roles/web-app-nextcloud/files/php/addons/notify_push/websocket/' . $program;
        $process = proc_open(
            array_merge([PHP_BINARY, '--'], $args),
            [0 => ['pipe', 'r'], 1 => ['pipe', 'w'], 2 => ['pipe', 'w']],
            $pipes,
            null,
            [
                'STUB_CAPABILITIES' => $this->capabilities,
                'STUB_BASE_ENDPOINT' => $baseEndpoint,
                'STUB_CLI_URL' => self::CLEARNET,
                'PATH' => (string) getenv('PATH'),
            ]
        );
        fwrite($pipes[0], (string) file_get_contents($script));
        fclose($pipes[0]);
        $stdout = (string) stream_get_contents($pipes[1]);
        $stderr = (string) stream_get_contents($pipes[2]);
        fclose($pipes[1]);
        fclose($pipes[2]);

        return [$stdout, $stderr, proc_close($process)];
    }

    /**
     * Probe one origin against the stub Nextcloud root.
     *
     * @param string $origin scheme and host the probe poses as
     * @param string $baseEndpoint base_endpoint the stub config holds
     * @return array{0: string, 1: string, 2: int} stdout, stderr and exit code
     */
    private function probe(string $origin, string $baseEndpoint): array
    {
        return $this->runProgram('probe.php', [$this->root, $origin, '/push/'], $baseEndpoint);
    }

    public function testPatchedCapabilitiesPassTheProbeOfEveryNetwork(): void
    {
        [, $stderr, $code] = $this->runProgram('patch.php', [$this->capabilities], self::BASE_ENDPOINT);
        $this->assertSame(0, $code, $stderr);

        $this->assertSame(["OK wss://next.cloud.example/push/ws\n", '', 0], $this->probe(self::CLEARNET, self::BASE_ENDPOINT));
        $this->assertSame(
            ["OK ws://next.cloud.k6ef7vnaclqi3scmtehdah5szh3y52564zbsinpgmfsg7ytvfla4mcyd.onion/push/ws\n", '', 0],
            $this->probe(self::ONION, self::BASE_ENDPOINT)
        );
    }

    public function testNegativeControlUpstreamFailsOnlyTheOnionProbe(): void
    {
        $this->assertSame(0, $this->probe(self::CLEARNET, self::BASE_ENDPOINT)[2]);

        [$stdout, $stderr, $code] = $this->probe(self::ONION, self::BASE_ENDPOINT);

        $this->assertSame(1, $code);
        $this->assertSame('', $stdout);
        $this->assertStringContainsString("announces the push websocket 'wss://next.cloud.example/push/ws' instead of ws://", $stderr);
    }

    public function testCapabilitiesWithoutAStoredEndpointFailTheProbe(): void
    {
        [$stdout, $stderr, $code] = $this->probe(self::CLEARNET, '');

        $this->assertSame(1, $code);
        $this->assertSame('', $stdout);
        $this->assertStringContainsString("announces the push websocket '' instead of wss://next.cloud.example/push/ws", $stderr);
    }
}
