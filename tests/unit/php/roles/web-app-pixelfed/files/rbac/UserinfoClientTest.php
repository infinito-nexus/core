<?php

declare(strict_types=1);

use App\Services\InfinitoRbacUserinfoClient;
use PHPUnit\Framework\TestCase;

require_once __DIR__ . '/pixelfed_stubs.php';
require_once dirname(__DIR__, 7) . '/roles/web-app-pixelfed/files/php/rbac/userinfo_client.php';

final class UserinfoClientTest extends TestCase
{
    private const TOKEN_URL = 'https://auth.example.org/realms/main/protocol/openid-connect/token';
    private const PROFILE_URL = 'https://auth.example.org/realms/main/protocol/openid-connect/userinfo';

    private const CLAIMS = [
        'preferred_username' => 'biber',
        'groups' => ['/roles/web-app-pixelfed/administrator'],
    ];

    private PixelfedStubHttpClient $inner;

    private function client(string $profileUrl): InfinitoRbacUserinfoClient
    {
        $this->inner = new PixelfedStubHttpClient([
            self::TOKEN_URL => json_encode(['access_token' => 'token-value', 'token_type' => 'Bearer']),
            self::PROFILE_URL => json_encode(self::CLAIMS),
        ]);

        return new InfinitoRbacUserinfoClient($this->inner, $profileUrl);
    }

    public function testTheUserinfoResponseIsRelayedAndItsClaimsKept(): void
    {
        $client = $this->client(self::PROFILE_URL);

        $token = $client->send(new PixelfedStubRequest('POST', self::TOKEN_URL), ['timeout' => 5]);
        $userinfo = $client->send(new PixelfedStubRequest('GET', self::PROFILE_URL), []);

        self::assertSame(json_encode(['access_token' => 'token-value', 'token_type' => 'Bearer']), (string) $token->getBody());
        self::assertSame(json_encode(self::CLAIMS), (string) $userinfo->getBody());
        self::assertSame(self::CLAIMS, $client->claims());
        self::assertSame(
            [['send', 'POST', self::TOKEN_URL, ['timeout' => 5]], ['send', 'GET', self::PROFILE_URL, []]],
            $this->inner->calls
        );
    }

    public function testTheProfileUrlMatchesInItsNormalisedForm(): void
    {
        $client = $this->client('https://auth.example.org:443/realms/main/protocol/openid-connect/userinfo');

        $client->send(new PixelfedStubRequest('GET', self::PROFILE_URL), []);

        self::assertSame(self::CLAIMS, $client->claims());
    }

    public function testNoUserinfoResponseFailsLoudly(): void
    {
        $client = $this->client(self::PROFILE_URL);
        $client->send(new PixelfedStubRequest('POST', self::TOKEN_URL), []);

        $this->expectException(RuntimeException::class);
        $this->expectExceptionMessage('InfinitoRbac: the OIDC sign-in relayed no JSON userinfo response from ' . self::PROFILE_URL);

        $client->claims();
    }

    public function testAUserinfoResponseThatIsNoJsonObjectIsNotKept(): void
    {
        $this->inner = new PixelfedStubHttpClient([self::PROFILE_URL => 'eyJhbGciOiJSUzI1NiJ9.signed.userinfo']);
        $client = new InfinitoRbacUserinfoClient($this->inner, self::PROFILE_URL);
        $client->send(new PixelfedStubRequest('GET', self::PROFILE_URL), []);

        $this->expectException(RuntimeException::class);

        $client->claims();
    }

    public function testEveryOtherCallIsDelegated(): void
    {
        $client = $this->client(self::PROFILE_URL);

        $client->sendAsync(new PixelfedStubRequest('GET', self::TOKEN_URL), ['a' => 1]);
        $client->request('GET', self::TOKEN_URL, ['b' => 2]);
        $client->requestAsync('GET', self::TOKEN_URL, ['c' => 3]);

        self::assertSame(['config', 'timeout'], $client->getConfig('timeout'));
        self::assertSame(
            [
                ['sendAsync', 'GET', self::TOKEN_URL, ['a' => 1]],
                ['request', 'GET', self::TOKEN_URL, ['b' => 2]],
                ['requestAsync', 'GET', self::TOKEN_URL, ['c' => 3]],
            ],
            $this->inner->calls
        );
    }
}
