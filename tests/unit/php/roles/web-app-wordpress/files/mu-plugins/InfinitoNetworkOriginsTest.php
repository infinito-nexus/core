<?php

declare(strict_types=1);

use PHPUnit\Framework\TestCase;

final class InfinitoNetworkOriginsTest extends TestCase
{
    private const PLUGIN = '/roles/web-app-wordpress/files/mu-plugins/infinito-network-origins.php';

    private const ONION = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.onion';

    private const HARNESS = <<<'PHP'
        <?php
        define('ABSPATH', '/');
        $GLOBALS['hooks'] = [];
        function add_filter($hook, $callback, $priority = 10, $acceptedArgs = 1)
        {
            $GLOBALS['hooks'][$hook][] = $callback;
            return true;
        }
        function apply_hook($hook, $value)
        {
            foreach ($GLOBALS['hooks'][$hook] ?? [] as $callback) {
                $value = $callback($value);
            }
            return $value;
        }
        function is_multisite()
        {
            return getenv('STUB_MULTISITE') === '1';
        }
        function is_subdomain_install()
        {
            return true;
        }
        function get_site_by_path($domain, $path, $segments = null)
        {
            foreach ($GLOBALS['hooks']['pre_get_site_by_path'] ?? [] as $callback) {
                $site = $callback(null, $domain, $path, $segments);
                if ($site !== null) {
                    return $site;
                }
            }
            return 'site:' . $domain;
        }
        if (getenv('STUB_NETWORK_DOMAIN') !== false) {
            define('DOMAIN_CURRENT_SITE', getenv('STUB_NETWORK_DOMAIN'));
        }
        $_SERVER['HTTP_HOST'] = (string) getenv('STUB_HOST');
        require getenv('STUB_PLUGIN');
        require getenv('STUB_PLUGIN');
        $urls = json_decode((string) getenv('STUB_URLS'), true);
        echo json_encode([
            'hooks' => array_map('count', $GLOBALS['hooks']),
            'home' => array_map(static fn ($url) => apply_hook('option_home', $url), $urls),
            'content' => array_map(static fn ($url) => apply_hook('content_url', $url), $urls),
            'uploads' => apply_hook('upload_dir', ['path' => '/var/www/html/wp-content/uploads', 'baseurl' => $urls[0], 'error' => false]),
            'site' => get_site_by_path((string) getenv('STUB_HOST'), '/', 1),
            'cookie_domain' => defined('COOKIE_DOMAIN') ? COOKIE_DOMAIN : null,
        ]);
        PHP;

    /**
     * Load the plugin twice in a fresh PHP process, as multisite does through sunrise and mu-plugins.
     *
     * @param string $host       the request's Host header
     * @param bool $multisite    whether the stubbed WordPress runs a network
     * @param list<string> $urls stored URLs the filters are applied to
     * @return array<string, mixed> registered hooks, filtered URLs, resolved site and cookie domain
     */
    private function load(string $host, bool $multisite, array $urls): array
    {
        $harness = tempnam(sys_get_temp_dir(), 'wpno');
        file_put_contents($harness, self::HARNESS);
        $env = [
            'INFINITO_NETWORK_BASE_URLS' => 'https://blog.main.test,http://blog.' . self::ONION . '/'
                . ';https://biberblog.main.test/,http://biberblog.' . self::ONION
                . ';https://biber.blog.main.test,http://biber.blog.' . self::ONION,
            'STUB_HOST' => $host,
            'STUB_MULTISITE' => $multisite ? '1' : '0',
            'STUB_NETWORK_DOMAIN' => 'blog.main.test',
            'STUB_PLUGIN' => dirname(__DIR__, 7) . self::PLUGIN,
            'STUB_URLS' => (string) json_encode($urls),
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

    public function testASingleSiteServesTheOnionSiblingFromItsOwnOrigin(): void
    {
        $result = $this->load('blog.' . self::ONION, false, ['https://blog.main.test', 'https://blog.main.test/wp-content/themes/a.css']);

        self::assertSame(['http://blog.' . self::ONION, 'http://blog.' . self::ONION . '/wp-content/themes/a.css'], $result['home']);
        self::assertSame($result['home'], $result['content']);
        self::assertArrayNotHasKey('pre_get_site_by_path', $result['hooks']);
        self::assertNull($result['cookie_domain']);
    }

    public function testTheCanonicalHostKeepsItsStoredUrls(): void
    {
        $result = $this->load('blog.main.test', true, ['https://blog.main.test', 'https://biberblog.main.test']);

        self::assertSame(['https://blog.main.test', 'https://biberblog.main.test'], $result['home']);
        self::assertSame('site:blog.main.test', $result['site']);
        self::assertArrayNotHasKey('pre_get_site_by_path', $result['hooks']);
        self::assertSame('.blog.main.test', $result['cookie_domain']);
    }

    public function testAChildOnItsOwnClearnetDomainKeepsItsCookieOnThatHost(): void
    {
        $result = $this->load('biberblog.main.test', true, ['https://biberblog.main.test']);

        self::assertSame('site:biberblog.main.test', $result['site']);
        self::assertSame(['https://biberblog.main.test'], $result['home']);
        self::assertSame('', $result['cookie_domain']);
    }

    public function testAChildBelowTheNetworkDomainSharesTheNetworkCookieOnTheOnion(): void
    {
        $result = $this->load('biber.blog.' . self::ONION, true, ['https://biber.blog.main.test']);

        self::assertSame('site:biber.blog.main.test', $result['site']);
        self::assertSame(['http://biber.blog.' . self::ONION], $result['home']);
        self::assertSame('.blog.' . self::ONION, $result['cookie_domain']);
    }

    public function testAHostOutsideTheNetworkRegistersNothing(): void
    {
        $result = $this->load('', true, ['https://blog.main.test']);

        self::assertSame([], $result['hooks']);
        self::assertSame(['https://blog.main.test'], $result['home']);
    }

    public function testAMultisiteSiblingResolvesToItsOwnSite(): void
    {
        $result = $this->load('biberblog.' . self::ONION, true, ['https://biberblog.main.test', 'https://blog.main.test/wp-admin/']);

        self::assertSame('site:biberblog.main.test', $result['site']);
        self::assertSame(['http://biberblog.' . self::ONION, 'http://blog.' . self::ONION . '/wp-admin/'], $result['home']);
        self::assertSame('', $result['cookie_domain']);
    }

    public function testTheMainSiteSiblingSharesTheNetworkCookieOnTheOnion(): void
    {
        $result = $this->load('blog.' . self::ONION, true, ['https://blog.main.test']);

        self::assertSame('site:blog.main.test', $result['site']);
        self::assertSame(['http://blog.' . self::ONION], $result['home']);
        self::assertSame('.blog.' . self::ONION, $result['cookie_domain']);
    }

    public function testLoadingTwiceRegistersEveryFilterOnce(): void
    {
        $result = $this->load('blog.' . self::ONION, true, ['https://blog.main.test']);

        self::assertNotSame([], $result['hooks']);
        self::assertSame(array_fill_keys(array_keys($result['hooks']), 1), $result['hooks']);
    }

    public function testOnlyUrlsOfASiteMoveIntoTheRequestNetwork(): void
    {
        $result = $this->load('blog.' . self::ONION, true, ['https://cdn.main.test/a.css']);

        self::assertSame(['https://cdn.main.test/a.css'], $result['home']);
        self::assertSame(
            ['path' => '/var/www/html/wp-content/uploads', 'baseurl' => 'https://cdn.main.test/a.css', 'error' => false],
            $result['uploads']
        );
    }
}
