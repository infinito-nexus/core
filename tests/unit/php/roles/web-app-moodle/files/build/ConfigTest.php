<?php

declare(strict_types=1);

use PHPUnit\Framework\TestCase;

final class ConfigTest extends TestCase
{
    private const ENV = [
        'MOODLE_DB_TYPE' => 'mariadb',
        'MOODLE_DB_HOST' => 'mariadb',
        'MOODLE_DB_NAME' => 'moodle',
        'MOODLE_DB_USER' => 'moodle',
        'MOODLE_DB_PASS' => 'secret',
        'MOODLE_DB_PREFIX' => 'mdl_',
        'MOODLE_DB_PORT' => '3306',
        'MOODLE_WWWROOT' => 'https://academy.example.test',
        'MOODLE_DATAROOT' => '/var/www/moodledata',
        'MOODLE_LOCALCACHEDIR' => '/var/cache/moodle',
        'MOODLE_REVERSEPROXY' => 'false',
        'MOODLE_SSLPROXY' => 'true',
        'MOODLE_EGRESS_BLOCKED_HOSTS' => '10.0.0.0/8',
        'MOODLE_EGRESS_ALLOWED_PORTS' => '443',
        'MOODLE_INTERNAL_HOST' => 'moodle',
        'MOODLE_OBJECTFS_ENABLED' => 'false',
        'MOODLE_FORCED_PLUGIN_SETTINGS' => 'e30=',
    ];

    private string $root;

    protected function setUp(): void
    {
        $this->root = sys_get_temp_dir() . '/mdlconfig' . bin2hex(random_bytes(6));
        mkdir($this->root . '/lib', 0700, true);
        copy(dirname(__DIR__, 7) . '/roles/web-app-moodle/files/build/config.php', $this->root . '/config.php');
        file_put_contents($this->root . '/lib/setup.php', "<?php\n");
    }

    protected function tearDown(): void
    {
        unlink($this->root . '/lib/setup.php');
        unlink($this->root . '/config.php');
        rmdir($this->root . '/lib');
        rmdir($this->root);
    }

    public function testEveryReplicaReadsSessionsFromTheSharedDatabase(): void
    {
        $process = proc_open(
            [PHP_BINARY, '-r', 'require $argv[1]; echo $CFG->session_handler_class ?? "";', $this->root . '/config.php'],
            [1 => ['pipe', 'w'], 2 => ['redirect', 1]],
            $pipes,
            null,
            self::ENV + ['PATH' => (string) getenv('PATH')]
        );
        $output = (string) stream_get_contents($pipes[1]);
        fclose($pipes[1]);

        $this->assertSame(0, proc_close($process), $output);
        $this->assertSame('\core\session\database', $output);
    }
}
