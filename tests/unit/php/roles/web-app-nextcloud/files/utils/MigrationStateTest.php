<?php

declare(strict_types=1);

use PHPUnit\Framework\TestCase;

final class MigrationStateTest extends TestCase
{
    private const SCRIPT = '/roles/web-app-nextcloud/files/php/utils/migration_state.php';

    private const STUB_BASE = <<<'PHP'
        <?php
        namespace OC\DB {
            final class Connection {}
            final class MigrationService {
                private array $versions;
                public function __construct(string $appName, Connection $connection) {
                    $this->versions = json_decode((string) getenv('STUB_VERSIONS'), true)[$appName];
                }
                public function getMigratedVersions(): array {
                    return $this->versions['migrated'];
                }
                public function getAvailableVersions(): array {
                    return $this->versions['available'];
                }
            }
        }
        namespace OCP {
            final class Server {
                public static function get(string $id): object {
                    return match ($id) {
                        \OC\DB\Connection::class => new \OC\DB\Connection(),
                    };
                }
            }
        }
        namespace {
            if (!defined('OC_CONSOLE')) {
                throw new \LogicException('Nextcloud booted outside its console');
            }
        }
        PHP;

    private string $root;

    protected function setUp(): void
    {
        $this->root = sys_get_temp_dir() . '/nextcloud-migration-state-' . bin2hex(random_bytes(6));
        mkdir($this->root . '/lib', 0700, true);
        file_put_contents($this->root . '/lib/base.php', self::STUB_BASE);
    }

    protected function tearDown(): void
    {
        unlink($this->root . '/lib/base.php');
        rmdir($this->root . '/lib');
        rmdir($this->root);
    }

    /**
     * @param int $count how many migration steps to name
     * @return list<string> Nextcloud migration versions as the installer records them
     */
    private static function versions(int $count): array
    {
        return array_map(static fn (int $step): string => sprintf('%09dDate20260129094821', $step), range(1, $count));
    }

    /**
     * Feed the probe on stdin, as the install gate does.
     *
     * @param string $appId the app the gate asks about
     * @param array<string, array{migrated: list<string>, available: list<string>}> $versions schema state per app
     * @return array{0: string, 1: string, 2: int} stdout, stderr and exit code
     */
    private function probe(string $appId, array $versions): array
    {
        $process = proc_open(
            [PHP_BINARY, '--', $this->root, $appId],
            [0 => ['pipe', 'r'], 1 => ['pipe', 'w'], 2 => ['pipe', 'w']],
            $pipes,
            null,
            ['STUB_VERSIONS' => (string) json_encode($versions), 'PATH' => (string) getenv('PATH')]
        );
        fwrite($pipes[0], (string) file_get_contents(dirname(__DIR__, 7) . self::SCRIPT));
        fclose($pipes[0]);
        $stdout = (string) stream_get_contents($pipes[1]);
        $stderr = (string) stream_get_contents($pipes[2]);
        fclose($pipes[1]);
        fclose($pipes[2]);

        return [$stdout, $stderr, proc_close($process)];
    }

    public function testTheProbePrintsTheSchemaStateOfTheAppTheGateNames(): void
    {
        $recognize = ['migrated' => self::versions(3), 'available' => self::versions(8)];

        [$stdout, $stderr, $code] = $this->probe('recognize', [
            'recognize' => $recognize,
            'calendar' => ['migrated' => self::versions(2), 'available' => self::versions(2)],
        ]);

        $this->assertSame(0, $code, $stderr);
        $this->assertSame(1, preg_match('/\AMIGRATION_STATE (\{.*\})\n\z/', $stdout, $line), $stdout);
        $this->assertSame($recognize, json_decode($line[1], true, flags: JSON_THROW_ON_ERROR));
    }

    public function testAnAppliedSchemaReportsEveryAvailableVersionAsMigrated(): void
    {
        $settled = ['migrated' => self::versions(8), 'available' => self::versions(8)];

        [$stdout, $stderr, $code] = $this->probe('recognize', ['recognize' => $settled]);

        $this->assertSame(0, $code, $stderr);
        $this->assertSame('MIGRATION_STATE ' . json_encode($settled) . "\n", $stdout);
    }
}
