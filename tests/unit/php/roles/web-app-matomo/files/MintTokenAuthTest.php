<?php

declare(strict_types=1);

use Infinito\Matomo\Token\Tokens;
use PHPUnit\Framework\TestCase;

use function Infinito\Matomo\Token\mint;

require_once dirname(__DIR__, 6) . '/roles/web-app-matomo/files/php/mint_token_auth.php';

final class MatomoFakeTokens implements Tokens
{
    public array $inserted = [];

    /**
     * @param list<string> $superusers logins with superuser access
     */
    public function __construct(private array $superusers)
    {
    }

    public function isSuperuser(string $login): bool
    {
        return in_array($login, $this->superusers, true);
    }

    public function insert(string $login, string $hash, string $description): void
    {
        $this->inserted[] = ['login' => $login, 'hash' => $hash, 'description' => $description];
    }
}

final class MintTokenAuthTest extends TestCase
{
    private const LOGIN = 'platformadmin';

    private const DESCRIPTION = 'infinito deploy';

    private const SALT = '0123456789abcdef0123456789abcdef';

    public function testTheScriptPipedIntoPhpLikeTheRoleReportsAnEmptyEnvironmentAsFail(): void
    {
        $process = proc_open(
            [PHP_BINARY],
            [0 => ['pipe', 'r'], 1 => ['pipe', 'w'], 2 => ['pipe', 'w']],
            $pipes,
            null,
            []
        );
        fwrite($pipes[0], (string) file_get_contents(dirname(__DIR__, 6) . '/roles/web-app-matomo/files/php/mint_token_auth.php'));
        fclose($pipes[0]);
        $stdout = (string) stream_get_contents($pipes[1]);
        $stderr = (string) stream_get_contents($pipes[2]);
        fclose($pipes[1]);
        fclose($pipes[2]);

        self::assertSame(1, proc_close($process), $stdout . $stderr);
        self::assertSame('', $stdout);
        self::assertStringContainsString("[FAIL] MATOMO_CONFIG is empty\n", $stderr);
    }

    public function testTheTokenMatchesTheBootstrapFormatAndOnlyItsSaltedHashIsStored(): void
    {
        $tokens = new MatomoFakeTokens([self::LOGIN]);

        [$code, $token] = mint($tokens, self::LOGIN, self::DESCRIPTION, self::SALT);

        self::assertSame(0, $code);
        self::assertMatchesRegularExpression('/^[a-f0-9]{32,64}$/', $token);
        self::assertSame(
            [['login' => self::LOGIN, 'hash' => hash('sha512', $token . self::SALT), 'description' => self::DESCRIPTION]],
            $tokens->inserted
        );
    }

    public function testEveryMintYieldsAFreshToken(): void
    {
        $tokens = new MatomoFakeTokens([self::LOGIN]);

        [, $first] = mint($tokens, self::LOGIN, self::DESCRIPTION, self::SALT);
        [, $second] = mint($tokens, self::LOGIN, self::DESCRIPTION, self::SALT);

        self::assertNotSame($first, $second);
        self::assertCount(2, $tokens->inserted);
    }

    public function testALoginWithoutSuperuserAccessGetsNoToken(): void
    {
        $tokens = new MatomoFakeTokens(['someone-else']);

        [$code, $line] = mint($tokens, self::LOGIN, self::DESCRIPTION, self::SALT);

        self::assertSame(1, $code);
        self::assertStringStartsWith('[FAIL]', $line);
        self::assertStringContainsString(self::LOGIN, $line);
        self::assertSame([], $tokens->inserted);
    }
}
