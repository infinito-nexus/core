<?php

declare(strict_types=1);

use PHPUnit\Framework\TestCase;

final class PatchTest extends TestCase
{
    private const CLEARNET = 'https://next.cloud.example';

    private const ONION = 'http://next.cloud.k6ef7vnaclqi3scmtehdah5szh3y52564zbsinpgmfsg7ytvfla4mcyd.onion';

    private const BASE_ENDPOINT = 'https://next.cloud.example/push';

    private const STORED_LINE = "\$wsEndpoint = str_replace('https://', 'wss://', \$baseEndpoint);";

    private const HARNESS = <<<'PHP'
        <?php
        namespace OCP {
            interface IConfig {}
            interface IURLGenerator {}
        }
        namespace OCP\Capabilities {
            interface ICapability {}
        }
        namespace {
            [, $capabilities, $baseEndpoint, $origin] = $argv;
            require $capabilities;
            $config = new class ($baseEndpoint) implements \OCP\IConfig {
                public function __construct(private string $baseEndpoint) {}
                public function getAppValue($app, $key) {
                    return [$app, $key] === ['notify_push', 'base_endpoint'] ? $this->baseEndpoint : '';
                }
            };
            $urls = new class ($origin) implements \OCP\IURLGenerator {
                public function __construct(private string $origin) {}
                public function linkToRoute($route) {
                    return '/apps/notify_push/pre_auth';
                }
                public function getAbsoluteURL($url) {
                    return $this->origin . (str_starts_with($url, '/') ? '' : '/') . $url;
                }
            };
            echo json_encode((new \OCA\NotifyPush\Capabilities($config, $urls))->getCapabilities());
        }
        PHP;

    private string $root;

    private string $capabilities;

    protected function setUp(): void
    {
        $this->root = sys_get_temp_dir() . '/nextcloud-notify-push-' . bin2hex(random_bytes(6));
        mkdir($this->root, 0700, true);
        $this->capabilities = $this->root . '/Capabilities.php';
        copy(__DIR__ . '/fixtures/Capabilities.v1.4.2.php.txt', $this->capabilities);
        file_put_contents($this->root . '/harness.php', self::HARNESS);
    }

    protected function tearDown(): void
    {
        foreach ([$this->capabilities, $this->root . '/harness.php'] as $file) {
            if (is_file($file)) {
                unlink($file);
            }
        }
        rmdir($this->root);
    }

    /**
     * Feed the patch program on stdin, as the addon task does.
     *
     * @return array{0: string, 1: string, 2: int} stdout, stderr and exit code
     */
    private function patch(): array
    {
        $script = dirname(__DIR__, 9) . '/roles/web-app-nextcloud/files/php/addons/notify_push/websocket/patch.php';
        $process = proc_open(
            [PHP_BINARY, '--', $this->capabilities],
            [0 => ['pipe', 'r'], 1 => ['pipe', 'w'], 2 => ['pipe', 'w']],
            $pipes
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
     * Load the capabilities class and announce it to a client of one origin.
     *
     * @param string $origin scheme and host the client reached Nextcloud on
     * @return string the websocket the capabilities announce
     */
    private function announcedWebsocket(string $origin): string
    {
        $process = proc_open(
            [PHP_BINARY, $this->root . '/harness.php', $this->capabilities, self::BASE_ENDPOINT, $origin],
            [1 => ['pipe', 'w'], 2 => ['pipe', 'w']],
            $pipes
        );
        $stdout = (string) stream_get_contents($pipes[1]);
        $stderr = (string) stream_get_contents($pipes[2]);
        fclose($pipes[1]);
        fclose($pipes[2]);
        $this->assertSame(0, proc_close($process), $stderr);

        return json_decode($stdout, true)['notify_push']['endpoints']['websocket'];
    }

    public function testFixtureIsTheUpstreamReleaseWithItsLicenseHeader(): void
    {
        $fixture = (string) file_get_contents($this->capabilities);

        $this->assertSame('66c62fbfa9d79aa1575890af0694416b2b33e263', sha1('blob ' . strlen($fixture) . "\0" . $fixture));
        $this->assertStringContainsString('SPDX-License-Identifier: AGPL-3.0-or-later', $fixture);
    }

    public function testNegativeControlUpstreamAnnouncesTheClearnetWebsocketToOnionClients(): void
    {
        $this->assertSame('wss://next.cloud.example/push/ws', $this->announcedWebsocket(self::ONION));
    }

    public function testPatchRewritesOnlyTheStoredEndpointLine(): void
    {
        $original = (string) file_get_contents($this->capabilities);

        [$stdout, $stderr, $code] = $this->patch();

        $this->assertSame(0, $code, $stderr);
        $this->assertSame("PATCHED\n", $stdout);
        $patched = (string) file_get_contents($this->capabilities);
        $this->assertStringNotContainsString(self::STORED_LINE, $patched);
        $this->assertSame(
            "\$wsEndpoint = str_replace('https://', 'wss://', "
            . "\$this->urlGenerator->getAbsoluteURL((string) parse_url(\$baseEndpoint, PHP_URL_PATH)));",
            trim(array_values(array_diff(explode("\n", $patched), explode("\n", $original)))[0] ?? '')
        );
        $this->assertCount(count(explode("\n", $original)), explode("\n", $patched));
    }

    public function testPatchedCapabilitiesAnnounceTheWebsocketOfTheNetworkTheClientAsked(): void
    {
        $this->patch();

        $this->assertSame('wss://next.cloud.example/push/ws', $this->announcedWebsocket(self::CLEARNET));
        $this->assertSame(
            'ws://next.cloud.k6ef7vnaclqi3scmtehdah5szh3y52564zbsinpgmfsg7ytvfla4mcyd.onion/push/ws',
            $this->announcedWebsocket(self::ONION)
        );
    }

    public function testSecondRunLeavesThePatchedFileUntouched(): void
    {
        $this->patch();
        $patched = (string) file_get_contents($this->capabilities);

        [$stdout, $stderr, $code] = $this->patch();

        $this->assertSame(0, $code, $stderr);
        $this->assertSame('', $stdout);
        $this->assertSame($patched, (string) file_get_contents($this->capabilities));
    }

    public function testSourceWithoutTheStoredEndpointLineIsLeftAlone(): void
    {
        $rewritten = str_replace(self::STORED_LINE, "\$wsEndpoint = \$this->publicEndpoint();", (string) file_get_contents($this->capabilities));
        file_put_contents($this->capabilities, $rewritten);

        [$stdout, $stderr, $code] = $this->patch();

        $this->assertSame(0, $code, $stderr);
        $this->assertSame('', $stdout);
        $this->assertSame($rewritten, (string) file_get_contents($this->capabilities));
    }
}
