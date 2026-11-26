<?php

declare(strict_types=1);

use PHPUnit\Framework\TestCase;

final class InfinitoManagedOptionsTest extends TestCase
{
    private const PLUGIN = '/roles/web-app-wordpress/files/mu-plugins/infinito-managed-options.php';

    private const RECORD = ['id' => 'infinito-litellm', 'type' => 'custom', 'apikey' => 'SYNTH-AI-KEY-1'];

    private const MANAGED = [
        'option' => ['blogname' => 'Managed Blog', 'permalink_structure' => '/blog/%postname%/'],
        'site_option' => ['registration' => 'user'],
        'merge' => [
            'mwai_options' => [
                'keys' => ['ai_default_env' => 'infinito-litellm', 'ai_default_model' => 'probe-chat'],
                'records' => ['ai_envs' => self::RECORD],
            ],
        ],
    ];

    private const WRITES = [
        'pre_update_option_blogname' => 'Hijacked',
        'pre_update_option_permalink_structure' => '/?p=%post_id%',
        'pre_update_site_option_registration' => 'all',
        'pre_update_option_unmanaged' => 'kept',
        'pre_update_option_mwai_options' => [
            'ai_default_env' => 'openai',
            'module_mcp' => true,
            'ai_envs' => [['id' => 'own', 'name' => 'Own'], ['id' => 'infinito-litellm', 'apikey' => 'stale'], 'garbage'],
        ],
    ];

    private const HARNESS = <<<'PHP'
        <?php
        define('ABSPATH', '/');
        $GLOBALS['hooks'] = [];
        function add_filter($hook, $callback, $priority = 10, $acceptedArgs = 1)
        {
            $GLOBALS['hooks'][$hook][] = ['callback' => $callback, 'priority' => $priority];
            return true;
        }
        function is_main_site()
        {
            return getenv('STUB_MAIN_SITE') === '1';
        }
        $error = null;
        try {
            require getenv('STUB_PLUGIN');
        } catch (RuntimeException $exception) {
            $error = $exception->getMessage();
        }
        $filtered = [];
        foreach (json_decode((string) getenv('STUB_WRITES'), true) as $hook => $value) {
            foreach ($GLOBALS['hooks'][$hook] ?? [] as $filter) {
                $value = $filter['callback']($value);
            }
            $filtered[$hook] = $value;
        }
        echo json_encode([
            'error' => $error,
            'hooks' => array_map(static fn ($filters) => array_column($filters, 'priority'), $GLOBALS['hooks']),
            'filtered' => $filtered,
        ]);
        PHP;

    /**
     * Load the mu-plugin in a fresh PHP process and run the option writes WordPress filters through it.
     *
     * @param string|null $values PHP source of the values file, '' for a path with no file, null to leave
     *                            WORDPRESS_MANAGED_OPTIONS_FILE unset
     * @param bool $mainSite      whether the write happens on the main site of the network
     * @return array{error: string|null, hooks: array<string, list<int>>, filtered: array<string, mixed>}
     *         the refusal of the plugin, the priorities per registered hook and the value each write stores
     */
    private function write(?string $values, bool $mainSite = true): array
    {
        $harness = tempnam(sys_get_temp_dir(), 'wpmo');
        file_put_contents($harness, self::HARNESS);
        $file = tempnam(sys_get_temp_dir(), 'wpmv');
        unlink($file);
        $env = [
            'STUB_MAIN_SITE' => $mainSite ? '1' : '0',
            'STUB_PLUGIN' => dirname(__DIR__, 7) . self::PLUGIN,
            'STUB_WRITES' => (string) json_encode(self::WRITES),
        ];
        if ($values !== null) {
            $env['WORDPRESS_MANAGED_OPTIONS_FILE'] = $file;
            if ($values !== '') {
                file_put_contents($file, $values);
            }
        }
        $process = proc_open([PHP_BINARY, $harness], [1 => ['pipe', 'w'], 2 => ['pipe', 'w']], $pipes, null, $env);
        $stdout = (string) stream_get_contents($pipes[1]);
        $stderr = (string) stream_get_contents($pipes[2]);
        fclose($pipes[1]);
        fclose($pipes[2]);
        $code = proc_close($process);
        unlink($harness);
        if (is_file($file)) {
            unlink($file);
        }
        self::assertSame(0, $code, $stderr);

        return json_decode($stdout, true, flags: JSON_THROW_ON_ERROR);
    }

    /**
     * @param mixed $managed the value the values file returns
     * @return string the values file as managed_options.php writes it
     */
    private static function valuesFile(mixed $managed): string
    {
        return "<?php\nreturn " . var_export($managed, true) . ";\n";
    }

    public function testEveryWriterOfAManagedOptionStoresTheManagedValueOnTheMainSite(): void
    {
        $written = $this->write(self::valuesFile(self::MANAGED));

        self::assertNull($written['error']);
        self::assertSame('Managed Blog', $written['filtered']['pre_update_option_blogname']);
        self::assertSame('/blog/%postname%/', $written['filtered']['pre_update_option_permalink_structure']);
        self::assertSame('user', $written['filtered']['pre_update_site_option_registration']);
        self::assertSame('kept', $written['filtered']['pre_update_option_unmanaged']);
        self::assertSame(
            [
                'pre_update_option_blogname' => [PHP_INT_MAX],
                'pre_update_option_permalink_structure' => [PHP_INT_MAX],
                'pre_update_site_option_registration' => [PHP_INT_MAX],
                'pre_update_option_mwai_options' => [PHP_INT_MAX],
            ],
            $written['hooks']
        );
    }

    public function testASiteBelowTheMainSiteKeepsItsOwnOptionsButNotTheNetworkOption(): void
    {
        $written = $this->write(self::valuesFile(self::MANAGED), false);

        self::assertNull($written['error']);
        self::assertSame('Hijacked', $written['filtered']['pre_update_option_blogname']);
        self::assertSame(self::WRITES['pre_update_option_mwai_options'], $written['filtered']['pre_update_option_mwai_options']);
        self::assertSame('user', $written['filtered']['pre_update_site_option_registration']);
    }

    public function testTheMainSiteMergesOnlyTheManagedKeysAndRecord(): void
    {
        $written = $this->write(self::valuesFile(self::MANAGED));

        self::assertSame(
            [
                'ai_default_env' => 'infinito-litellm',
                'module_mcp' => true,
                'ai_envs' => [['id' => 'own', 'name' => 'Own'], 'garbage', self::RECORD],
                'ai_default_model' => 'probe-chat',
            ],
            $written['filtered']['pre_update_option_mwai_options']
        );
    }

    public function testTheGuardFailsClosedWithoutItsValues(): void
    {
        $broken = [
            'unset variable' => null,
            'missing file' => '',
            'no array' => self::valuesFile('managed'),
            'no merge scope' => self::valuesFile(['option' => self::MANAGED['option'], 'site_option' => []]),
            'scope that is no array' => self::valuesFile(['option' => 'blogname'] + self::MANAGED),
        ];
        foreach ($broken as $case => $values) {
            $written = $this->write($values);

            self::assertNotNull($written['error'], $case);
            self::assertSame([], $written['hooks'], $case);
            self::assertSame('Hijacked', $written['filtered']['pre_update_option_blogname'], $case);
        }
    }
}
