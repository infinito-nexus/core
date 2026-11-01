<?php

declare(strict_types=1);

use Infinito\Matomo\Superuser\Users;
use PHPUnit\Framework\TestCase;

use function Infinito\Matomo\Superuser\ensure;

require_once dirname(__DIR__, 6) . '/roles/web-app-matomo/files/php/converge_superuser_password.php';

final class MatomoFakeUsers implements Users
{
    public array $inserted = [];

    public array $updated = [];

    /**
     * @param array<string, array{password: string, email: string, superuser: bool}> $rows user table keyed by login
     */
    public function __construct(public array $rows)
    {
    }

    public function find(string $login): ?array
    {
        $row = $this->rows[$login] ?? null;

        return $row === null ? null : ['password' => $row['password'], 'superuser' => $row['superuser']];
    }

    public function superusers(): int
    {
        return count(array_filter($this->rows, static fn (array $row): bool => $row['superuser']));
    }

    public function holdersOf(string $email, string $login): array
    {
        $holders = [];
        foreach ($this->rows as $holder => $row) {
            if ($holder !== $login && strtolower($row['email']) === strtolower($email)) {
                $holders[] = $holder;
            }
        }

        return $holders;
    }

    public function insertSuperuser(string $login, string $hash, string $email): void
    {
        $this->inserted[] = ['login' => $login, 'email' => $email];
        $this->rows[$login] = ['password' => $hash, 'email' => $email, 'superuser' => true];
    }

    public function updatePassword(string $login, string $hash): void
    {
        $this->updated[] = $login;
        $this->rows[$login]['password'] = $hash;
    }
}

final class ConvergeSuperuserPasswordTest extends TestCase
{
    private const LOGIN = 'platformadmin';

    private const PASSWORD = 'the-declared-password';

    private const EMAIL = 'platformadmin@example.org';

    /**
     * @return array{password: string, email: string, superuser: bool}
     */
    private static function row(string $password, string $email, bool $superuser): array
    {
        return ['password' => password_hash(md5($password), PASSWORD_DEFAULT), 'email' => $email, 'superuser' => $superuser];
    }

    /**
     * @return array{0: int, 1: string, 2: string} exit code, stdout and stderr of `php` fed the script on stdin
     */
    private static function pipeIntoPhp(): array
    {
        $process = proc_open(
            [PHP_BINARY],
            [0 => ['pipe', 'r'], 1 => ['pipe', 'w'], 2 => ['pipe', 'w']],
            $pipes,
            null,
            []
        );
        fwrite($pipes[0], (string) file_get_contents(dirname(__DIR__, 6) . '/roles/web-app-matomo/files/php/converge_superuser_password.php'));
        fclose($pipes[0]);
        $stdout = (string) stream_get_contents($pipes[1]);
        $stderr = (string) stream_get_contents($pipes[2]);
        fclose($pipes[1]);
        fclose($pipes[2]);

        return [proc_close($process), $stdout, $stderr];
    }

    private static function legacyAdministrator(): array
    {
        return self::row('host-password', 'administrator@example.org', true);
    }

    public function testTheScriptPipedIntoPhpLikeTheRoleReportsAnEmptyEnvironmentAsFail(): void
    {
        [$code, $stdout, $stderr] = self::pipeIntoPhp();

        self::assertSame(1, $code, $stdout . $stderr);
        self::assertSame('', $stdout);
        self::assertStringContainsString("[FAIL] MATOMO_CONFIG is empty\n", $stderr);
        self::assertStringNotContainsString('Undefined constant', $stderr);
    }

    public function testAnAbsentLoginIsCreatedAsSuperuserNextToTheExistingOne(): void
    {
        $users = new MatomoFakeUsers(['administrator' => self::legacyAdministrator()]);
        $administrator = $users->rows['administrator'];

        [$code, $line] = ensure($users, self::LOGIN, self::PASSWORD, self::EMAIL);

        self::assertSame(0, $code);
        self::assertStringStartsWith('[CHANGED]', $line);
        self::assertSame([['login' => self::LOGIN, 'email' => self::EMAIL]], $users->inserted);
        self::assertTrue(password_verify(md5(self::PASSWORD), $users->rows[self::LOGIN]['password']));
        self::assertSame($administrator, $users->rows['administrator']);
    }

    public function testASecondRunAfterTheCreateChangesNothing(): void
    {
        $users = new MatomoFakeUsers(['administrator' => self::legacyAdministrator()]);
        ensure($users, self::LOGIN, self::PASSWORD, self::EMAIL);

        [$code, $line] = ensure($users, self::LOGIN, self::PASSWORD, self::EMAIL);

        self::assertSame(0, $code);
        self::assertStringStartsWith('[UNCHANGED]', $line);
        self::assertCount(1, $users->inserted);
        self::assertSame([], $users->updated);
    }

    public function testAPresentSuperuserWithTheDeclaredPasswordIsLeftAlone(): void
    {
        $users = new MatomoFakeUsers([self::LOGIN => self::row(self::PASSWORD, self::EMAIL, true)]);

        [$code, $line] = ensure($users, self::LOGIN, self::PASSWORD, self::EMAIL);

        self::assertSame(0, $code);
        self::assertStringStartsWith('[UNCHANGED]', $line);
        self::assertSame([], $users->inserted);
        self::assertSame([], $users->updated);
    }

    public function testAPresentSuperuserWithAStalePasswordIsRealigned(): void
    {
        $users = new MatomoFakeUsers([self::LOGIN => self::row('stale', self::EMAIL, true)]);

        [$code, $line] = ensure($users, self::LOGIN, self::PASSWORD, self::EMAIL);

        self::assertSame(0, $code);
        self::assertStringStartsWith('[CHANGED]', $line);
        self::assertSame([self::LOGIN], $users->updated);
        self::assertTrue(password_verify(md5(self::PASSWORD), $users->rows[self::LOGIN]['password']));
    }

    public function testAnInstallWithoutAnySuperuserFailsInsteadOfCreating(): void
    {
        $users = new MatomoFakeUsers(['viewer' => self::row('x', 'viewer@example.org', false)]);

        [$code, $line] = ensure($users, self::LOGIN, self::PASSWORD, self::EMAIL);

        self::assertSame(1, $code);
        self::assertStringStartsWith('[FAIL]', $line);
        self::assertStringContainsString('no superuser', $line);
        self::assertSame([], $users->inserted);
    }

    public function testAnEmailHeldByAnotherAccountFailsNamingTheHolder(): void
    {
        $users = new MatomoFakeUsers([
            'administrator' => self::legacyAdministrator(),
            'someone' => self::row('x', 'PlatformAdmin@Example.org', false),
        ]);

        [$code, $line] = ensure($users, self::LOGIN, self::PASSWORD, self::EMAIL);

        self::assertSame(1, $code);
        self::assertStringStartsWith('[FAIL]', $line);
        self::assertStringContainsString('someone', $line);
        self::assertSame([], $users->inserted);
    }

    public function testANonSuperuserHoldingTheLoginIsNotPromoted(): void
    {
        $users = new MatomoFakeUsers([
            'administrator' => self::legacyAdministrator(),
            self::LOGIN => self::row('stale', self::EMAIL, false),
        ]);

        [$code, $line] = ensure($users, self::LOGIN, self::PASSWORD, self::EMAIL);

        self::assertSame(1, $code);
        self::assertStringStartsWith('[FAIL]', $line);
        self::assertStringContainsString('not promoted', $line);
        self::assertFalse($users->rows[self::LOGIN]['superuser']);
        self::assertSame([], $users->inserted);
        self::assertSame([], $users->updated);
    }
}
