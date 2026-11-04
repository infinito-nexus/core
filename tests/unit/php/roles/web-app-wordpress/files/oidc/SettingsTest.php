<?php

declare(strict_types=1);

final class WpOidcState
{
    public static bool $multisite = false;

    public static array $sites = [];

    public static ?int $currentBlog = null;

    public static array $options = [];

    public static array $switches = [];

    public static array $restores = [];

    public static array $log = [];

    public static function reset(): void
    {
        self::$multisite = false;
        self::$sites = [];
        self::$currentBlog = null;
        self::$options = [];
        self::$switches = [];
        self::$restores = [];
        self::$log = [];
    }

    public static function blog(): int
    {
        return self::$currentBlog ?? 1;
    }
}

final class WP_CLI
{
    public static function log(string $message): void
    {
        WpOidcState::$log[] = $message;
    }
}

function is_multisite(): bool
{
    return WpOidcState::$multisite;
}

function get_sites(array $args = []): array
{
    return WpOidcState::$sites;
}

function get_current_blog_id(): int
{
    return WpOidcState::blog();
}

function switch_to_blog(int $blogId): void
{
    WpOidcState::$currentBlog = $blogId;
    WpOidcState::$switches[] = $blogId;
}

function restore_current_blog(): void
{
    WpOidcState::$restores[] = WpOidcState::blog();
    WpOidcState::$currentBlog = null;
}

function delete_option(string $key): bool
{
    $blog = WpOidcState::blog();
    if (!array_key_exists($key, WpOidcState::$options[$blog] ?? [])) {
        return false;
    }
    unset(WpOidcState::$options[$blog][$key]);

    return true;
}

use PHPUnit\Framework\TestCase;

final class SettingsTest extends TestCase
{
    private const SCRIPT = '/roles/web-app-wordpress/files/php/oidc/settings.php';

    private const OPTION = 'openid_connect_generic_settings';

    private const STORED = ['client_id' => 'wp', 'client_secret' => 's3cret'];

    protected function setUp(): void
    {
        WpOidcState::reset();
    }

    private function run_script(): void
    {
        include dirname(__DIR__, 7) . self::SCRIPT;
    }

    public function testASingleSiteLosesItsStoredCopyWithoutSwitchingBlogs(): void
    {
        WpOidcState::$options[1] = [self::OPTION => self::STORED, 'blogname' => 'blog'];

        $this->run_script();

        self::assertSame(['blogname' => 'blog'], WpOidcState::$options[1]);
        self::assertSame([], WpOidcState::$switches);
        self::assertSame(['CHANGED 1'], WpOidcState::$log);
    }

    public function testEverySiteOfANetworkLosesItsStoredCopy(): void
    {
        WpOidcState::$multisite = true;
        WpOidcState::$sites = [1, 7, 9];
        foreach ([1, 7, 9] as $blog) {
            WpOidcState::$options[$blog] = [self::OPTION => self::STORED];
        }

        $this->run_script();

        self::assertSame([1, 7, 9], WpOidcState::$switches);
        self::assertSame([1, 7, 9], WpOidcState::$restores);
        foreach ([1, 7, 9] as $blog) {
            self::assertArrayNotHasKey(self::OPTION, WpOidcState::$options[$blog]);
        }
        self::assertSame(['CHANGED 1', 'CHANGED 7', 'CHANGED 9'], WpOidcState::$log);
    }

    public function testOnlyASiteThatStillStoresTheSettingsReportsAChange(): void
    {
        WpOidcState::$multisite = true;
        WpOidcState::$sites = [1, 7, 9];
        WpOidcState::$options[7] = [self::OPTION => self::STORED];

        $this->run_script();

        self::assertSame(['CHANGED 7'], WpOidcState::$log);
    }

    public function testASecondRunChangesNothing(): void
    {
        WpOidcState::$multisite = true;
        WpOidcState::$sites = [1, 7];
        WpOidcState::$options[1] = [self::OPTION => self::STORED];

        $this->run_script();
        WpOidcState::$log = [];
        $this->run_script();

        self::assertSame([], WpOidcState::$log);
    }
}
