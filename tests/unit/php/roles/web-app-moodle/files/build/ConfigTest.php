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
        file_put_contents($this->root . '/lib/setup.php', "<?php\n\$forcedAtSetup = \$CFG->forced_plugin_settings ?? null;\n");
    }

    protected function tearDown(): void
    {
        unlink($this->root . '/lib/setup.php');
        unlink($this->root . '/config.php');
        rmdir($this->root . '/lib');
        rmdir($this->root);
    }

    /**
     * @param string $code PHP run after config.php returned; $forcedAtSetup holds what lib/setup.php saw
     * @param array<string, string> $env entries that replace the defaults of ENV
     * @return string what the code printed
     */
    private function boot(string $code, array $env): string
    {
        $process = proc_open(
            [PHP_BINARY, '-r', 'require $argv[1]; ' . $code, $this->root . '/config.php'],
            [1 => ['pipe', 'w'], 2 => ['redirect', 1]],
            $pipes,
            null,
            $env + self::ENV + ['PATH' => (string) getenv('PATH')]
        );
        $output = (string) stream_get_contents($pipes[1]);
        fclose($pipes[1]);

        $this->assertSame(0, proc_close($process), $output);

        return $output;
    }

    public function testEveryReplicaReadsSessionsFromTheSharedDatabase(): void
    {
        $this->assertSame('\core\session\database', $this->boot('echo $CFG->session_handler_class ?? "";', []));
    }

    public function testThePluginSettingsAreForcedBeforeMoodleBootsAndKeepObjectfs(): void
    {
        $forced = ['auth_oidc' => ['clientid' => 'moodle', 'forceredirect' => true, 'loginflow' => 1, 'icon' => false]];

        $output = $this->boot('echo json_encode($forcedAtSetup);', [
            'MOODLE_OBJECTFS_ENABLED' => 'true',
            'MOODLE_OBJECTFS_READY_FILE' => $this->root . '/config.php',
            'MOODLE_OBJECTFS_S3_BASE_URL' => 'https://s3.example.test',
            'MOODLE_OBJECTFS_S3_BUCKET' => 'moodle',
            'MOODLE_OBJECTFS_S3_KEY' => 'SYNTH-S3-KEY',
            'MOODLE_OBJECTFS_S3_REGION' => 'eu-central-1',
            'MOODLE_OBJECTFS_S3_SECRET' => 'SYNTH-S3-SECRET',
            'MOODLE_FORCED_PLUGIN_SETTINGS' => base64_encode((string) json_encode($forced)),
        ]);
        $settings = json_decode($output, true, flags: JSON_THROW_ON_ERROR);

        $this->assertSame(['tool_objectfs', 'tool_task', 'auth_oidc'], array_keys($settings));
        $this->assertSame(['clientid' => 'moodle', 'forceredirect' => '1', 'loginflow' => '1', 'icon' => ''], $settings['auth_oidc']);
        $this->assertSame('\tool_objectfs\s3_file_system', $settings['tool_objectfs']['filesystem']);
        $this->assertSame('moodle', $settings['tool_objectfs']['s3_bucket']);
    }
}
