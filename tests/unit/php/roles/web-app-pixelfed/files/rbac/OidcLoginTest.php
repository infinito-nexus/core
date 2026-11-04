<?php

declare(strict_types=1);

use App\Listeners\InfinitoRbacOidcLogin;
use App\Services\InfinitoRbacUserinfoClient;
use App\Services\UserOidcService;
use Illuminate\Auth\Events\Login;
use Illuminate\Routing\Events\RouteMatched;
use Illuminate\Support\Facades\Log;
use PHPUnit\Framework\TestCase;

require_once __DIR__ . '/pixelfed_stubs.php';
require_once dirname(__DIR__, 7) . '/roles/web-app-pixelfed/files/php/rbac/userinfo_client.php';
require_once dirname(__DIR__, 7) . '/roles/web-app-pixelfed/files/php/rbac/oidc_login.php';

final class OidcLoginTest extends TestCase
{
    private const CALLBACK = 'App\Http\Controllers\RemoteOidcController@handleCallback';
    private const PROFILE_URL = 'https://auth.example.org/realms/main/protocol/openid-connect/userinfo';
    private const ADMIN_GROUP = '/roles/web-app-pixelfed/administrator';

    private const ENV = [
        'PF_INFINITO_RBAC_CLAIM' => 'groups',
        'PF_INFINITO_RBAC_ADMIN_GROUP' => self::ADMIN_GROUP,
        'PF_INFINITO_RBAC_KEPT_USERNAME' => 'Administrator',
    ];

    protected function setUp(): void
    {
        PixelfedStubContainer::$current = new PixelfedStubContainer();
        PixelfedStubContainer::$config = ['remote-auth.oidc.profileURL' => self::PROFILE_URL];
        Log::$messages = [];

        foreach (self::ENV as $key => $value) {
            putenv("{$key}={$value}");
        }
    }

    protected function tearDown(): void
    {
        foreach (array_keys(self::ENV) as $key) {
            putenv($key);
        }
    }

    /**
     * Build a Pixelfed account as the Login event carries it.
     *
     * @param string $username Pixelfed username
     * @param bool $isAdmin the stored admin flag
     */
    private static function account(string $username, bool $isAdmin): object
    {
        return new class ($username, $isAdmin) {
            public int $saves = 0;

            public function __construct(public string $username, public bool $is_admin)
            {
            }

            public function save(): void
            {
                ++$this->saves;
            }
        };
    }

    private static function route(string $action): object
    {
        return new class ($action) {
            public function __construct(private string $action)
            {
            }

            public function getActionName(): string
            {
                return $this->action;
            }
        };
    }

    /**
     * Run an OIDC callback: match its route, let the controller resolve the provider and fetch userinfo, then log in.
     *
     * @param array<string, mixed> $claims the userinfo response of the identity provider
     * @param object $account the account the callback logs in
     */
    private function signInThroughOidc(array $claims, object $account): UserOidcService
    {
        $listener = new InfinitoRbacOidcLogin();
        $listener->handleRouteMatched(new RouteMatched(self::route(self::CALLBACK), null));

        $provider = PixelfedStubContainer::$current->resolve(
            UserOidcService::class,
            new UserOidcService(new PixelfedStubHttpClient([self::PROFILE_URL => json_encode($claims)]))
        );
        $provider->getHttpClient()->send(new PixelfedStubRequest('GET', self::PROFILE_URL), []);

        $listener->handleLogin(new Login('web', $account, false));

        return $provider;
    }

    public function testTheAdministratorGroupPromotesAtSignIn(): void
    {
        $biber = self::account('biber', false);

        $provider = $this->signInThroughOidc(['groups' => ['/roles/web-app-pixelfed/user', self::ADMIN_GROUP]], $biber);

        self::assertTrue($biber->is_admin);
        self::assertSame(1, $biber->saves);
        self::assertInstanceOf(InfinitoRbacUserinfoClient::class, $provider->getHttpClient());
        self::assertSame(['InfinitoRbac: the OIDC sign-in of biber set its admin flag to true'], Log::$messages);
    }

    public function testLeavingTheAdministratorGroupDemotesAtSignIn(): void
    {
        $former = self::account('former', true);

        $this->signInThroughOidc(['groups' => ['/roles/web-app-pixelfed/user']], $former);

        self::assertFalse($former->is_admin);
        self::assertSame(1, $former->saves);
    }

    public function testASignInWithoutAGroupsClaimDemotes(): void
    {
        $former = self::account('former', true);

        $this->signInThroughOidc(['preferred_username' => 'former'], $former);

        self::assertFalse($former->is_admin);
    }

    public function testAnAlignedAccountIsNotSaved(): void
    {
        $biber = self::account('biber', true);

        $this->signInThroughOidc(['groups' => [self::ADMIN_GROUP]], $biber);

        self::assertSame(0, $biber->saves);
        self::assertSame([], Log::$messages);
    }

    public function testTheKeptAdministratorKeepsItsFlagWithoutTheGroup(): void
    {
        $administrator = self::account('administrator', true);

        $this->signInThroughOidc(['groups' => []], $administrator);

        self::assertTrue($administrator->is_admin);
        self::assertSame(0, $administrator->saves);
    }

    public function testAnotherRouteLeavesTheProviderAndAPasswordLoginAlone(): void
    {
        $listener = new InfinitoRbacOidcLogin();
        $listener->handleRouteMatched(new RouteMatched(self::route('App\Http\Controllers\Auth\LoginController@login'), null));
        $biber = self::account('biber', true);

        $listener->handleLogin(new Login('web', $biber, false));

        self::assertSame([], PixelfedStubContainer::$current->extenders);
        self::assertTrue($biber->is_admin);
        self::assertSame(0, $biber->saves);
    }

    public function testACallbackThatRelayedNoUserinfoFailsLoudly(): void
    {
        $listener = new InfinitoRbacOidcLogin();
        $listener->handleRouteMatched(new RouteMatched(self::route(self::CALLBACK), null));
        PixelfedStubContainer::$current->resolve(
            UserOidcService::class,
            new UserOidcService(new PixelfedStubHttpClient([]))
        );

        $this->expectException(RuntimeException::class);
        $this->expectExceptionMessage('InfinitoRbac: the OIDC sign-in relayed no JSON userinfo response from ' . self::PROFILE_URL);

        $listener->handleLogin(new Login('web', self::account('biber', false), false));
    }

    public function testAMissingEnvironmentValueFailsLoudly(): void
    {
        putenv('PF_INFINITO_RBAC_ADMIN_GROUP');

        $this->expectException(RuntimeException::class);
        $this->expectExceptionMessage('InfinitoRbac: PF_INFINITO_RBAC_ADMIN_GROUP is empty');

        $this->signInThroughOidc(['groups' => [self::ADMIN_GROUP]], self::account('biber', false));
    }
}
