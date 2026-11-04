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
        $GLOBALS['moved_sites'] = [];
        $GLOBALS['written'] = [];
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
        function get_network()
        {
            return (object) $GLOBALS['state']['network'];
        }
        function remove_all_filters($hook)
        {
            unset($GLOBALS['state']['filters'][$hook]);
            return true;
        }
        function get_blog_id_from_url($domain, $path)
        {
            return $GLOBALS['state']['sites'][$domain . $path] ?? 0;
        }
        function get_blog_option($id, $option)
        {
            $value = $GLOBALS['state']['options'][$id][$option] ?? false;
            return is_string($value) ? ($GLOBALS['state']['filters']['option_' . $option][$value] ?? $value) : $value;
        }
        function update_blog_option($id, $option, $value)
        {
            if (get_blog_option($id, $option) === $value) {
                return false;
            }
            $GLOBALS['state']['options'][$id][$option] = $value;
            $GLOBALS['written'][] = ['id' => $id, 'option' => $option, 'value' => $value];
            return true;
        }
        function wp_update_site($id, $data)
        {
            if (($GLOBALS['state']['refuse'] ?? '') === $data['domain']) {
                return new WP_Error('Sorry, that site already exists!');
            }
            $GLOBALS['state']['sites'] = array_filter($GLOBALS['state']['sites'], static fn ($site) => $site !== $id);
            $GLOBALS['state']['sites'][$data['domain'] . $data['path']] = $id;
            $GLOBALS['moved_sites'][] = ['id' => $id] + $data;
            return $id;
        }
        function wp_insert_site($data)
        {
            if (($GLOBALS['state']['refuse'] ?? '') === $data['domain']) {
                return new WP_Error('Sorry, that site already exists!');
            }
            $GLOBALS['inserted'][] = $data;
            $id = 40 + count($GLOBALS['inserted']);
            $GLOBALS['state']['sites'][$data['domain'] . $data['path']] = $id;
            $GLOBALS['state']['options'][$id] = $data['options'];
            return $id;
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
        echo json_encode([
            'inserted' => $GLOBALS['inserted'],
            'moved' => $GLOBALS['moved_sites'],
            'written' => $GLOBALS['written'],
            'log' => $GLOBALS['log'],
            'error' => $error,
            'sites' => (object) $GLOBALS['state']['sites'],
            'options' => (object) $GLOBALS['state']['options'],
        ]);
        PHP;

    /**
     * Run the script in a fresh PHP process against stubbed WordPress state.
     *
     * @param array<string, mixed> $state  admin_email, network (domain, path), sites (domain.path => blog id),
     *                                     options (blog id => option => stored value), filters (hook => stored value => filtered value)
     *                                     and an optional refused domain
     * @param string|null $urls            WP_MS_SITE_URLS, null to leave it unset
     * @return array{inserted: list<array<string, mixed>>, moved: list<array<string, mixed>>, written: list<array<string, mixed>>,
     *               log: list<string>, error: string|null, sites: array<string, int>, options: array<int, array<string, string>>}
     */
    private function runScript(array $state, ?string $urls): array
    {
        $harness = tempnam(sys_get_temp_dir(), 'wpms');
        file_put_contents($harness, self::HARNESS);
        $env = [
            'STUB_STATE' => (string) json_encode($state + [
                'network' => ['domain' => 'blog.main.test', 'path' => '/'],
                'sites' => (object) [],
                'options' => (object) [],
                'filters' => (object) [],
            ]),
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
            [
                'admin_email' => 'admin@main.test',
                'sites' => ['biberblog.main.test/' => 2, 'biber.blog.main.test/' => 3],
                'options' => [
                    2 => ['home' => 'https://biberblog.main.test', 'siteurl' => 'https://biberblog.main.test/'],
                    3 => ['home' => 'https://biber.blog.main.test', 'siteurl' => 'https://biber.blog.main.test'],
                ],
            ],
            'https://biberblog.main.test/,https://biber.blog.main.test'
        );

        self::assertNull($result['error']);
        self::assertSame([], $result['inserted']);
        self::assertSame([], $result['moved']);
        self::assertSame([], $result['written']);
        self::assertSame([], $result['log']);
    }

    public function testAStaleHomeAndSiteurlConvergeOnTheSiteUrl(): void
    {
        $result = $this->runScript(
            [
                'admin_email' => 'admin@main.test',
                'sites' => ['biberblog.main.test/' => 2],
                'options' => [2 => ['home' => 'https://biberblog.main.test.blog.main.test', 'siteurl' => 'http://old.main.test/']],
            ],
            'https://biberblog.main.test'
        );

        self::assertNull($result['error']);
        self::assertSame([], $result['inserted']);
        self::assertSame([], $result['moved']);
        self::assertSame(
            [
                ['id' => 2, 'option' => 'home', 'value' => 'https://biberblog.main.test'],
                ['id' => 2, 'option' => 'siteurl', 'value' => 'https://biberblog.main.test'],
            ],
            $result['written']
        );
        self::assertSame(['CHANGED https://biberblog.main.test'], $result['log']);
    }

    public function testAStaleSchemeTheNetworkOriginsFilterRewritesOnReadStillConverges(): void
    {
        $result = $this->runScript(
            [
                'admin_email' => 'admin@main.test',
                'sites' => ['biberblog.main.test/' => 2],
                'options' => [2 => ['home' => 'http://biberblog.main.test', 'siteurl' => 'http://biberblog.main.test']],
                'filters' => [
                    'option_home' => ['http://biberblog.main.test' => 'https://biberblog.main.test'],
                    'option_siteurl' => ['http://biberblog.main.test' => 'https://biberblog.main.test'],
                ],
            ],
            'https://biberblog.main.test'
        );

        self::assertNull($result['error']);
        self::assertSame(['home' => 'https://biberblog.main.test', 'siteurl' => 'https://biberblog.main.test'], $result['options'][2]);
        self::assertSame(['CHANGED https://biberblog.main.test'], $result['log']);
    }

    public function testALegacySlugSiteMovesOntoItsSiblingDomain(): void
    {
        $result = $this->runScript(
            [
                'admin_email' => 'admin@main.test',
                'sites' => ['biberblog.main.test.blog.main.test/' => 5],
                'options' => [5 => ['home' => 'http://biberblog.main.test.blog.main.test', 'siteurl' => 'http://biberblog.main.test.blog.main.test']],
            ],
            'https://biberblog.main.test'
        );

        self::assertNull($result['error']);
        self::assertSame([], $result['inserted']);
        self::assertSame([['id' => 5, 'domain' => 'biberblog.main.test', 'path' => '/']], $result['moved']);
        self::assertSame(['biberblog.main.test/' => 5], $result['sites']);
        self::assertSame(['home' => 'https://biberblog.main.test', 'siteurl' => 'https://biberblog.main.test'], $result['options'][5]);
        self::assertSame(['CHANGED https://biberblog.main.test'], $result['log']);
    }

    public function testALegacySlugSiteBelowAWwwNetworkDomainMovesOntoItsSiblingDomain(): void
    {
        $result = $this->runScript(
            [
                'admin_email' => 'admin@main.test',
                'network' => ['domain' => 'www.blog.main.test', 'path' => '/'],
                'sites' => ['biberblog.main.test.blog.main.test/' => 5],
            ],
            'https://biberblog.main.test'
        );

        self::assertNull($result['error']);
        self::assertSame([['id' => 5, 'domain' => 'biberblog.main.test', 'path' => '/']], $result['moved']);
    }

    public function testARunAfterCreatingMovingAndConvergingChangesNothing(): void
    {
        $urls = 'https://biberblog.main.test,https://biber.blog.main.test,https://biber.main.test';
        $first = $this->runScript(
            [
                'admin_email' => 'admin@main.test',
                'sites' => ['biberblog.main.test.blog.main.test/' => 5, 'biber.blog.main.test/' => 3],
                'options' => [
                    5 => ['home' => 'http://biberblog.main.test.blog.main.test', 'siteurl' => 'http://biberblog.main.test.blog.main.test'],
                    3 => ['home' => 'http://biber.blog.main.test', 'siteurl' => 'http://biber.blog.main.test'],
                ],
            ],
            $urls
        );
        $second = $this->runScript(['admin_email' => 'admin@main.test', 'sites' => $first['sites'], 'options' => $first['options']], $urls);

        self::assertNull($first['error']);
        self::assertSame(
            ['CHANGED https://biberblog.main.test', 'CHANGED https://biber.blog.main.test', 'CHANGED https://biber.main.test'],
            $first['log']
        );
        self::assertNull($second['error']);
        self::assertSame([], $second['inserted']);
        self::assertSame([], $second['moved']);
        self::assertSame([], $second['written']);
        self::assertSame([], $second['log']);
    }

    public function testSitesOffTheExactLegacySlugDomainAndPathAreLeftAlone(): void
    {
        $unrelated = [
            'shop.main.test/' => 8,
            'biberblog.blog.main.test/' => 9,
            'biberblog.main.test.other.test/' => 10,
            'biberblog.main.test.blog.main.test/blog/' => 11,
        ];
        $result = $this->runScript(['admin_email' => 'admin@main.test', 'sites' => $unrelated], 'https://biberblog.main.test');

        self::assertNull($result['error']);
        self::assertSame([], $result['moved']);
        self::assertSame([], $result['written']);
        self::assertSame(['biberblog.main.test'], array_column($result['inserted'], 'domain'));
        self::assertSame($unrelated + ['biberblog.main.test/' => 41], $result['sites']);
    }

    public function testALegacySlugSiteNextToASiteOnItsDomainHalts(): void
    {
        $sites = ['biberblog.main.test/' => 2, 'biberblog.main.test.blog.main.test/' => 5];
        $result = $this->runScript(['admin_email' => 'admin@main.test', 'sites' => $sites], 'https://biberblog.main.test');

        self::assertStringContainsString('site 2', (string) $result['error']);
        self::assertStringContainsString('biberblog.main.test.blog.main.test', (string) $result['error']);
        self::assertSame([], $result['moved']);
        self::assertSame([], $result['written']);
        self::assertSame($sites, $result['sites']);
    }

    public function testALegacySlugDomainThatIsItselfAListedSiteHalts(): void
    {
        $sites = ['biberblog.main.test.blog.main.test/' => 5];
        $result = $this->runScript(
            ['admin_email' => 'admin@main.test', 'sites' => $sites],
            'https://biberblog.main.test,https://biberblog.main.test.blog.main.test'
        );

        self::assertStringContainsString('biberblog.main.test.blog.main.test', (string) $result['error']);
        self::assertSame([], $result['inserted']);
        self::assertSame([], $result['moved']);
        self::assertSame($sites, $result['sites']);
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
