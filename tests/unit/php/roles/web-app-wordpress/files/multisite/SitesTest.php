<?php

declare(strict_types=1);

use PHPUnit\Framework\TestCase;

final class SitesTest extends TestCase
{
    private const SCRIPT = '/roles/web-app-wordpress/files/php/multisite/sites.php';

    private const HARNESS = <<<'PHP'
        <?php
        final class WpCliHalt extends RuntimeException
        {
        }
        final class WP_CLI
        {
            public static function error($message)
            {
                throw new WpCliHalt($message);
            }
            public static function log($message)
            {
                $GLOBALS['log'][] = $message;
            }
        }
        final class WP_Error
        {
            public function __construct(private string $message)
            {
            }
            public function get_error_message()
            {
                return $this->message;
            }
        }
        $GLOBALS['state'] = json_decode((string) getenv('STUB_STATE'), true);
        $GLOBALS['log'] = [];
        $GLOBALS['inserted'] = [];
        function untrailingslashit($value)
        {
            return rtrim($value, '/\\');
        }
        function trailingslashit($value)
        {
            return untrailingslashit($value) . '/';
        }
        function get_user_by($field, $value)
        {
            return $value === $GLOBALS['state']['admin_email'] ? (object) ['ID' => 7] : false;
        }
        function get_blog_id_from_url($domain, $path)
        {
            return $GLOBALS['state']['sites'][$domain . $path] ?? 0;
        }
        function wp_insert_site($data)
        {
            if (($GLOBALS['state']['refuse'] ?? '') === $data['domain']) {
                return new WP_Error('Sorry, that site already exists!');
            }
            $GLOBALS['inserted'][] = $data;
            return 40 + count($GLOBALS['inserted']);
        }
        function is_wp_error($value)
        {
            return $value instanceof WP_Error;
        }
        $error = null;
        try {
            require getenv('STUB_SCRIPT');
        } catch (WpCliHalt $halt) {
            $error = $halt->getMessage();
        }
        echo json_encode(['inserted' => $GLOBALS['inserted'], 'log' => $GLOBALS['log'], 'error' => $error]);
        PHP;

    /**
     * Run the script in a fresh PHP process against stubbed WordPress state.
     *
     * @param array<string, mixed> $state  admin_email, sites (domain.path => blog id) and an optional refused domain
     * @param string|null $urls            WP_MS_SITE_URLS, null to leave it unset
     * @return array{inserted: list<array<string, mixed>>, log: list<string>, error: string|null}
     */
    private function runScript(array $state, ?string $urls): array
    {
        $harness = tempnam(sys_get_temp_dir(), 'wpms');
        file_put_contents($harness, self::HARNESS);
        $env = [
            'STUB_STATE' => (string) json_encode($state + ['sites' => (object) []]),
            'STUB_SCRIPT' => dirname(__DIR__, 7) . self::SCRIPT,
            'WP_MS_ADMIN_EMAIL' => 'admin@main.test',
        ];
        if ($urls !== null) {
            $env['WP_MS_SITE_URLS'] = $urls;
        }
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

    public function testAMissingChildIsCreatedOnItsOwnDomain(): void
    {
        $result = $this->runScript(['admin_email' => 'admin@main.test'], 'https://biberblog.main.test/,https://biber.blog.main.test');

        self::assertNull($result['error']);
        self::assertSame(
            [
                [
                    'domain' => 'biberblog.main.test',
                    'path' => '/',
                    'title' => 'biberblog.main.test',
                    'user_id' => 7,
                    'options' => ['home' => 'https://biberblog.main.test', 'siteurl' => 'https://biberblog.main.test'],
                ],
                [
                    'domain' => 'biber.blog.main.test',
                    'path' => '/',
                    'title' => 'biber.blog.main.test',
                    'user_id' => 7,
                    'options' => ['home' => 'https://biber.blog.main.test', 'siteurl' => 'https://biber.blog.main.test'],
                ],
            ],
            $result['inserted']
        );
        self::assertSame(['CHANGED https://biberblog.main.test', 'CHANGED https://biber.blog.main.test'], $result['log']);
    }

    public function testASecondRunChangesNothing(): void
    {
        $result = $this->runScript(
            ['admin_email' => 'admin@main.test', 'sites' => ['biberblog.main.test/' => 2, 'biber.blog.main.test/' => 3]],
            'https://biberblog.main.test/,https://biber.blog.main.test'
        );

        self::assertNull($result['error']);
        self::assertSame([], $result['inserted']);
        self::assertSame([], $result['log']);
    }

    public function testASiteWordPressRefusesHaltsWithItsDomain(): void
    {
        $result = $this->runScript(['admin_email' => 'admin@main.test', 'refuse' => 'biberblog.main.test'], 'https://biberblog.main.test');

        self::assertStringContainsString('biberblog.main.test', (string) $result['error']);
    }

    public function testAnUnknownAdministratorHalts(): void
    {
        $result = $this->runScript(['admin_email' => 'someone-else@main.test'], 'https://biberblog.main.test');

        self::assertSame([], $result['inserted']);
        self::assertNotNull($result['error']);
    }

    public function testAnAbsentSiteListHalts(): void
    {
        $result = $this->runScript(['admin_email' => 'admin@main.test'], null);

        self::assertSame([], $result['inserted']);
        self::assertNotNull($result['error']);
    }
}
