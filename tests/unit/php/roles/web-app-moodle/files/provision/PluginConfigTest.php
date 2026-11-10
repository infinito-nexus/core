<?php

declare(strict_types=1);

use PHPUnit\Framework\TestCase;

final class PluginConfigTest extends TestCase
{
    private const SECRET = 'p$`"\\w\'d';

    private const MOODLE = <<<'PHP'
        <?php
        $CFG = new stdClass();
        $CFG->forced_plugin_settings = json_decode((string) getenv('STUB_FORCED'), true);

        function stub_state(): array {
            $file = getenv('STUB_STATE');
            return is_file($file)
                ? json_decode(file_get_contents($file), true)
                : ['config' => [], 'log' => []];
        }

        function stub_store(array $state): void {
            file_put_contents(getenv('STUB_STATE'), json_encode($state));
        }

        function get_config($plugin, $name = null) {
            return stub_state()['config'][$plugin][$name] ?? false;
        }

        function set_config($name, $value, $plugin = null) {
            $state = stub_state();
            $state['config'][$plugin][$name] = $value;
            stub_store($state);
            return true;
        }

        function add_to_config_log($name, $oldvalue, $value, $plugin) {
            $state = stub_state();
            $state['log'][] = [$plugin, $name, $oldvalue, $value];
            stub_store($state);
        }
        PHP;

    private string $config;

    private string $state;

    protected function setUp(): void
    {
        $this->config = (string) tempnam(sys_get_temp_dir(), 'mdlcfg');
        $this->state = (string) tempnam(sys_get_temp_dir(), 'mdlplg');
        file_put_contents($this->config, self::MOODLE);
        unlink($this->state);
    }

    protected function tearDown(): void
    {
        unlink($this->config);
        if (is_file($this->state)) {
            unlink($this->state);
        }
    }

    /**
     * Store plugin settings the way an earlier run or an administrator left them.
     *
     * @param array<string, array<string, string>> $config stored values by plugin and name
     */
    private function seed(array $config): void
    {
        file_put_contents($this->state, json_encode(['config' => $config, 'log' => []]));
    }

    /**
     * Encode the stdin payload the Ansible task sends.
     *
     * @param array<mixed> $settings setting values by name
     * @param string       $component plugin the settings belong to
     */
    private static function payload(array $settings, string $component = 'auth_ldap'): string
    {
        return json_encode(['component' => $component, 'settings' => $settings]) . "\n";
    }

    /**
     * Run the script against the stubbed Moodle.
     *
     * @param string                               $stdin  payload piped to the script
     * @param array<string, array<string, string>> $forced $CFG->forced_plugin_settings
     *
     * @return array{0: string, 1: string, 2: int, 3: array<string, mixed>|null}
     *         stdout, stderr, exit code and the stub state, null when nothing was written
     */
    private function runScript(string $stdin, array $forced = []): array
    {
        $script = dirname(__DIR__, 7) . '/roles/web-app-moodle/files/php/provision/plugin_config.php';
        $process = proc_open(
            [PHP_BINARY, $script],
            [0 => ['pipe', 'r'], 1 => ['pipe', 'w'], 2 => ['pipe', 'w']],
            $pipes,
            null,
            [
                'MOODLE_CONFIG' => $this->config,
                'STUB_STATE' => $this->state,
                'STUB_FORCED' => json_encode((object) $forced),
                'PATH' => (string) getenv('PATH'),
            ]
        );
        fwrite($pipes[0], $stdin);
        fclose($pipes[0]);
        $stdout = (string) stream_get_contents($pipes[1]);
        fclose($pipes[1]);
        $stderr = (string) stream_get_contents($pipes[2]);
        fclose($pipes[2]);
        $code = proc_close($process);

        $state = is_file($this->state)
            ? json_decode((string) file_get_contents($this->state), true)
            : null;

        return [$stdout, $stderr, $code, $state];
    }

    public function testAFreshPluginGetsEverySettingStoredVerbatimAsAString(): void
    {
        [$stdout, , $code, $state] = $this->runScript(self::payload([
            'host_url' => 'ldap://ldap:389',
            'ldap_version' => 3,
            'bind_pw' => self::SECRET,
        ]));

        $this->assertSame(0, $code);
        $this->assertSame("CHANGED 3\n", $stdout);
        $this->assertSame(
            ['auth_ldap' => ['host_url' => 'ldap://ldap:389', 'ldap_version' => '3', 'bind_pw' => self::SECRET]],
            $state['config']
        );
    }

    public function testEveryWriteIsLoggedWithTheValueItReplaced(): void
    {
        $this->seed(['auth_ldap' => ['ldap_version' => '2']]);

        [, , , $state] = $this->runScript(self::payload(['ldap_version' => 3, 'start_tls' => 0]));

        $this->assertSame(
            [['auth_ldap', 'ldap_version', '2', '3'], ['auth_ldap', 'start_tls', false, '0']],
            $state['log']
        );
    }

    public function testOnlyTheSettingsThatDifferAreWritten(): void
    {
        $this->seed([
            'auth_ldap' => ['host_url' => 'ldap://ldap:389', 'ldap_version' => '2', 'removecontexts' => '1'],
            'auth_oidc' => ['clientid' => 'moodle'],
        ]);

        [$stdout, , $code, $state] = $this->runScript(self::payload([
            'host_url' => 'ldap://ldap:389',
            'ldap_version' => 3,
        ]));

        $this->assertSame(0, $code);
        $this->assertSame("CHANGED 1\n", $stdout);
        $this->assertSame(
            [
                'auth_ldap' => ['host_url' => 'ldap://ldap:389', 'ldap_version' => '3', 'removecontexts' => '1'],
                'auth_oidc' => ['clientid' => 'moodle'],
            ],
            $state['config']
        );
    }

    public function testASecondRunChangesNothing(): void
    {
        $payload = self::payload(['host_url' => 'ldap://ldap:389', 'search_sub' => 1, 'bind_pw' => self::SECRET]);
        [, , , $first] = $this->runScript($payload);
        [$stdout, , $code, $second] = $this->runScript($payload);

        $this->assertSame(0, $code);
        $this->assertSame("CHANGED 0\n", $stdout);
        $this->assertSame($first, $second);
    }

    public function testNoValueReachesTheOutput(): void
    {
        [$stdout, $stderr] = $this->runScript(self::payload(['bind_pw' => self::SECRET]));

        $this->assertStringNotContainsString(self::SECRET, $stdout . $stderr);
    }

    public function testASettingForcedInConfigPhpAbortsBeforeAnyWrite(): void
    {
        [, $stderr, $code, $state] = $this->runScript(
            self::payload(['host_url' => 'ldap://ldap:389', 'bind_pw' => self::SECRET]),
            ['auth_ldap' => ['bind_pw' => 'from-config-php']]
        );

        $this->assertSame(4, $code);
        $this->assertStringContainsString('bind_pw', $stderr);
        $this->assertNull($state);
    }

    public function testAValueThatIsNeitherStringNorIntegerAbortsBeforeAnyWrite(): void
    {
        [, $stderr, $code, $state] = $this->runScript(
            self::payload(['host_url' => 'ldap://ldap:389', 'search_sub' => true])
        );

        $this->assertSame(2, $code);
        $this->assertStringContainsString('auth_ldap/search_sub', $stderr);
        $this->assertNull($state);
    }

    public function testCoreIsRefusedBecauseSetConfigWouldFileItAsAPlugin(): void
    {
        [, , $code, $state] = $this->runScript(self::payload(['debug' => '0'], 'core'));

        $this->assertSame(2, $code);
        $this->assertNull($state);
    }

    public function testASettingsListIsRefused(): void
    {
        [, , $code, $state] = $this->runScript(self::payload(['ldap://ldap:389', 3]));

        $this->assertSame(2, $code);
        $this->assertNull($state);
    }
}
