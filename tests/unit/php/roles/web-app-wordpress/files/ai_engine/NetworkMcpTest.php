<?php

declare(strict_types=1);

use PHPUnit\Framework\TestCase;

final class NetworkMcpTest extends TestCase
{
    private const SCRIPT = '/roles/web-app-wordpress/files/php/ai_engine/network_mcp.php';

    private const GUARD = '/roles/web-app-wordpress/files/mu-plugins/infinito-ai-engine-network.php';

    private const EXPOSED = ['module_mcp' => true, 'mcp_bearer_token' => 'SYNTH-MCP-TOKEN', 'module_suggestions' => true];

    private const HARNESS = <<<'PHP'
        <?php
        define('ABSPATH', '/');
        final class WP_CLI
        {
            public static function log($message)
            {
                $GLOBALS['log'][] = $message;
            }
        }
        $GLOBALS['state'] = json_decode((string) getenv('STUB_STATE'), true);
        $GLOBALS['blog'] = $GLOBALS['state']['main'];
        $GLOBALS['hooks'] = [];
        $GLOBALS['log'] = [];
        $GLOBALS['written'] = [];
        function add_filter($hook, $callback, $priority = 10, $acceptedArgs = 1)
        {
            $GLOBALS['hooks'][$hook][] = $callback;
            return true;
        }
        function remove_all_filters($hook)
        {
            unset($GLOBALS['hooks'][$hook]);
            return true;
        }
        function is_multisite()
        {
            return true;
        }
        function is_main_site($siteId = null)
        {
            return (int) ($siteId ?? $GLOBALS['blog']) === $GLOBALS['state']['main'];
        }
        function get_sites($args)
        {
            return $GLOBALS['state']['sites'];
        }
        function switch_to_blog($blogId)
        {
            $GLOBALS['blog'] = $blogId;
            return true;
        }
        function restore_current_blog()
        {
            $GLOBALS['blog'] = $GLOBALS['state']['main'];
            return true;
        }
        function get_option($option)
        {
            $value = $GLOBALS['state']['options'][$GLOBALS['blog']][$option] ?? false;
            foreach ($GLOBALS['hooks']['option_' . $option] ?? [] as $callback) {
                $value = $callback($value);
            }
            return $value;
        }
        function update_option($option, $value, $autoload = null)
        {
            $GLOBALS['state']['options'][$GLOBALS['blog']][$option] = $value;
            $GLOBALS['written'][] = ['blog' => $GLOBALS['blog'], 'option' => $option, 'value' => $value, 'autoload' => $autoload];
            return true;
        }
        require getenv('STUB_GUARD');
        require getenv('STUB_SCRIPT');
        echo json_encode([
            'written' => $GLOBALS['written'],
            'log' => $GLOBALS['log'],
            'options' => (object) $GLOBALS['state']['options'],
            'blog' => $GLOBALS['blog'],
        ]);
        PHP;

    /**
     * Run the sweep through a fresh PHP process with the AI Engine network guard loaded, as `wp eval-file` does.
     *
     * @param array<int, array<string, mixed>> $options stored options per blog id, blog 1 is the main site
     * @return array{written: list<array<string, mixed>>, log: list<string>, options: array<int, array<string, mixed>>, blog: int}
     *         the option writes, the WP-CLI log, the stored options and the current blog after the run
     */
    private function sweep(array $options): array
    {
        $harness = tempnam(sys_get_temp_dir(), 'wpmcp');
        file_put_contents($harness, self::HARNESS);
        $root = dirname(__DIR__, 7);
        $env = [
            'STUB_GUARD' => $root . self::GUARD,
            'STUB_SCRIPT' => $root . self::SCRIPT,
            'STUB_STATE' => (string) json_encode(['main' => 1, 'sites' => array_keys($options), 'options' => (object) $options]),
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

    public function testTheStoredRowBelowTheMainSiteIsReadPastTheGuardAndCleared(): void
    {
        $swept = $this->sweep([
            1 => ['mwai_options' => self::EXPOSED],
            2 => ['mwai_options' => self::EXPOSED],
            3 => ['mwai_options' => ['module_mcp' => false, 'mcp_bearer_token' => 'SYNTH-MCP-TOKEN-3']],
            4 => ['mwai_options' => ['module_mcp' => false]],
            5 => ['blogname' => 'No AI Engine'],
        ]);

        self::assertSame(
            [
                ['blog' => 2, 'option' => 'mwai_options', 'value' => ['module_mcp' => false, 'module_suggestions' => true], 'autoload' => false],
                ['blog' => 3, 'option' => 'mwai_options', 'value' => ['module_mcp' => false], 'autoload' => false],
            ],
            $swept['written']
        );
        self::assertSame(['CHANGED 2', 'CHANGED 3'], $swept['log']);
        self::assertSame(1, $swept['blog']);
    }

    public function testTheMainSiteKeepsItsMcpModuleAndToken(): void
    {
        $swept = $this->sweep([1 => ['mwai_options' => self::EXPOSED]]);

        self::assertSame([], $swept['written']);
        self::assertSame([], $swept['log']);
        self::assertSame(self::EXPOSED, $swept['options'][1]['mwai_options']);
    }

    public function testASecondRunChangesNothing(): void
    {
        $first = $this->sweep([1 => ['mwai_options' => self::EXPOSED], 2 => ['mwai_options' => self::EXPOSED]]);
        $second = $this->sweep($first['options']);

        self::assertSame(['CHANGED 2'], $first['log']);
        self::assertSame([], $second['written']);
        self::assertSame([], $second['log']);
    }
}
