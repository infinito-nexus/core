<?php

declare(strict_types=1);

use PHPUnit\Framework\TestCase;

final class InfinitoAiEngineNetworkTest extends TestCase
{
    private const PLUGIN = '/roles/web-app-wordpress/files/mu-plugins/infinito-ai-engine-network.php';

    private const OPTIONS = ['module_mcp' => true, 'mcp_bearer_token' => 'SYNTH-MCP-TOKEN', 'module_suggestions' => true];

    private const GUARDED = ['module_mcp' => false, 'module_suggestions' => true];

    private const HARNESS = <<<'PHP'
        <?php
        define('ABSPATH', '/');
        $GLOBALS['hooks'] = [];
        function add_filter($hook, $callback, $priority = 10, $acceptedArgs = 1)
        {
            $GLOBALS['hooks'][$hook][] = ['callback' => $callback, 'priority' => $priority];
            return true;
        }
        function apply_hook($hook, $value)
        {
            foreach ($GLOBALS['hooks'][$hook] ?? [] as $filter) {
                $value = $filter['callback']($value);
            }
            return $value;
        }
        function is_multisite()
        {
            return getenv('STUB_MULTISITE') === '1';
        }
        function is_main_site()
        {
            return getenv('STUB_MAIN_SITE') === '1';
        }
        function is_super_admin()
        {
            return getenv('STUB_SUPER_ADMIN') === '1';
        }
        require getenv('STUB_PLUGIN');
        $options = json_decode((string) getenv('STUB_OPTIONS'), true);
        echo json_encode([
            'hooks' => array_map(static fn ($filters) => array_column($filters, 'priority'), $GLOBALS['hooks']),
            'stored' => apply_hook('option_mwai_options', $options),
            'default' => apply_hook('default_option_mwai_options', $options),
            'allow_setup' => apply_hook('mwai_allow_setup', getenv('STUB_ALLOW_SETUP') === '1'),
        ]);
        PHP;

    /**
     * Load the mu-plugin in a fresh PHP process and run the hooks AI Engine fires.
     *
     * @param bool $multisite      whether the stubbed WordPress runs a network
     * @param bool $mainSite       whether the request belongs to the main site of the network
     * @param mixed $options       the mwai_options value the option hooks receive, stored or default
     * @param bool $allowSetup     the setup permission AI Engine hands to mwai_allow_setup
     * @param bool $superAdmin     whether the current user is a network administrator
     * @return array{hooks: array<string, list<int>>, stored: mixed, default: mixed, allow_setup: bool}
     *         priorities per registered hook, the filtered stored and default options and the setup permission
     */
    private function load(bool $multisite, bool $mainSite, mixed $options, bool $allowSetup = true, bool $superAdmin = false): array
    {
        $harness = tempnam(sys_get_temp_dir(), 'wpai');
        file_put_contents($harness, self::HARNESS);
        $env = [
            'STUB_ALLOW_SETUP' => $allowSetup ? '1' : '0',
            'STUB_MAIN_SITE' => $mainSite ? '1' : '0',
            'STUB_MULTISITE' => $multisite ? '1' : '0',
            'STUB_OPTIONS' => (string) json_encode($options),
            'STUB_PLUGIN' => dirname(__DIR__, 7) . self::PLUGIN,
            'STUB_SUPER_ADMIN' => $superAdmin ? '1' : '0',
        ];
        $process = proc_open([PHP_BINARY, $harness], [1 => ['pipe', 'w'], 2 => ['pipe', 'w']], $pipes, null, $env);
        $stdout = (string) stream_get_contents($pipes[1]);
        $stderr = (string) stream_get_contents($pipes[2]);
        fclose($pipes[1]);
        fclose($pipes[2]);
        $code = proc_close($process);
        unlink($harness);
        self::assertSame(0, $code, $stderr);

        return json_decode($stdout, true, flags: JSON_THROW_ON_ERROR);
    }

    public function testASiteBelowTheMainSiteLosesTheMcpModuleAndTokenOfItsStoredAndDefaultOptions(): void
    {
        $loaded = $this->load(true, false, self::OPTIONS);

        self::assertSame(self::GUARDED, $loaded['stored']);
        self::assertSame(self::GUARDED, $loaded['default']);
    }

    public function testTheMainSiteKeepsItsMcpModuleAndToken(): void
    {
        $loaded = $this->load(true, true, self::OPTIONS);

        self::assertSame(self::OPTIONS, $loaded['stored']);
        self::assertSame(self::OPTIONS, $loaded['default']);
    }

    public function testAnOptionValueThatIsNoArrayPassesUnchanged(): void
    {
        $loaded = $this->load(true, false, false);

        self::assertFalse($loaded['stored']);
        self::assertFalse($loaded['default']);
    }

    public function testOnlyANetworkAdministratorMayOpenTheSettings(): void
    {
        self::assertTrue($this->load(true, false, self::OPTIONS, true, true)['allow_setup']);
        self::assertFalse($this->load(true, true, self::OPTIONS, true, false)['allow_setup']);
        self::assertFalse($this->load(true, true, self::OPTIONS, false, true)['allow_setup']);
    }

    public function testANetworkRegistersEveryGuardLastAndASingleSiteNone(): void
    {
        $network = $this->load(true, false, self::OPTIONS);
        $single = $this->load(false, false, self::OPTIONS);

        self::assertSame(
            [
                'mwai_allow_setup' => [PHP_INT_MAX],
                'option_mwai_options' => [PHP_INT_MAX],
                'default_option_mwai_options' => [PHP_INT_MAX],
            ],
            $network['hooks']
        );
        self::assertSame([], $single['hooks']);
        self::assertSame(self::OPTIONS, $single['stored']);
    }
}
