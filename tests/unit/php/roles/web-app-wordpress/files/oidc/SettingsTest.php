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

    public static array $blogsWhoseWriteNeverPersists = [];

    public static function reset(): void
    {
        self::$multisite = false;
        self::$sites = [];
        self::$currentBlog = null;
        self::$options = [];
        self::$switches = [];
        self::$restores = [];
        self::$blogsWhoseWriteNeverPersists = [];
    }

    public static function blog(): int
    {
        return self::$currentBlog ?? 0;
    }
}

final class WpCliHalt extends RuntimeException
{
}

final class WP_CLI
{
    public static function error(string $message): void
    {
        throw new WpCliHalt($message);
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

function update_option(string $key, $value): bool
{
    $blog = WpOidcState::blog();
    if (in_array($blog, WpOidcState::$blogsWhoseWriteNeverPersists, true)) {
        return false;
    }
    WpOidcState::$options[$blog][$key] = $value;

    return true;
}

function get_option(string $key, $default = false)
{
    return WpOidcState::$options[WpOidcState::blog()][$key] ?? $default;
}

use PHPUnit\Framework\TestCase;

final class SettingsTest extends TestCase
{
    private const SCRIPT = '/roles/web-app-wordpress/files/php/oidc/settings.php';

    private const OPTION = 'openid_connect_generic_settings';

    private const SETTINGS = ['client_id' => 'wp', 'client_secret' => 's3cret'];

    protected function setUp(): void
    {
        WpOidcState::reset();
    }

    private function runPayload(?string $payload): void
    {
        putenv($payload === null ? 'WP_OIDC_SETTINGS' : 'WP_OIDC_SETTINGS=' . $payload);
        include dirname(__DIR__, 7) . self::SCRIPT;
    }

    private function encoded(): string
    {
        return base64_encode((string) json_encode(self::SETTINGS));
    }

    public function testASingleSiteIsWrittenWithoutSwitchingBlogs(): void
    {
        $this->runPayload($this->encoded());

        self::assertSame(self::SETTINGS, WpOidcState::$options[0][self::OPTION]);
        self::assertSame([], WpOidcState::$switches);
    }

    public function testEverySiteOfANetworkReceivesTheSettings(): void
    {
        WpOidcState::$multisite = true;
        WpOidcState::$sites = [1, 7, 9];

        $this->runPayload($this->encoded());

        self::assertSame([1, 7, 9], WpOidcState::$switches);
        self::assertSame([1, 7, 9], WpOidcState::$restores);
        foreach ([1, 7, 9] as $blog) {
            self::assertSame(self::SETTINGS, WpOidcState::$options[$blog][self::OPTION]);
        }
    }

    public function testASiteWhoseWriteDoesNotPersistIsNamed(): void
    {
        WpOidcState::$multisite = true;
        WpOidcState::$sites = [1, 7, 9];
        WpOidcState::$blogsWhoseWriteNeverPersists = [7];

        $this->expectException(WpCliHalt::class);
        $this->expectExceptionMessageMatches('/\b7\b/');

        $this->runPayload($this->encoded());
    }

    public function testEverySiteIsVisitedBeforeTheFailureIsReported(): void
    {
        WpOidcState::$multisite = true;
        WpOidcState::$sites = [1, 7, 9];
        WpOidcState::$blogsWhoseWriteNeverPersists = [1];

        try {
            $this->runPayload($this->encoded());
            self::fail('a blocked write must halt the run');
        } catch (WpCliHalt $halt) {
            self::assertSame([1, 7, 9], WpOidcState::$switches);
        }
    }

    public function testAPayloadThatIsNotAMapHalts(): void
    {
        $this->expectException(WpCliHalt::class);

        $this->runPayload(base64_encode('"a string"'));
    }

    public function testAnAbsentPayloadHalts(): void
    {
        $this->expectException(WpCliHalt::class);

        $this->runPayload(null);
    }
}
