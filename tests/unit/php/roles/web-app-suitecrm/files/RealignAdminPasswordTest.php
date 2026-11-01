<?php

declare(strict_types=1);

namespace Infinito\Tests\SuiteCrm;

use Infinito\SuiteCrm\Administrator\Users;
use PHPUnit\Framework\TestCase;

use function Infinito\SuiteCrm\Administrator\ensure;

require_once dirname(__DIR__, 6) . '/roles/web-app-suitecrm/files/php/realign_admin_password.php';

final class FakeUsers implements Users
{
    public array $inserted = [];

    public array $updated = [];

    /**
     * @param list<array{login: string, hash: string, emails: list<string>, admin: bool}> $rows undeleted users, id = list index
     */
    public function __construct(public array $rows)
    {
    }

    public function find(string $login): array
    {
        $found = [];
        foreach ($this->rows as $id => $row) {
            if ($row['login'] === $login) {
                $found[] = ['id' => (string) $id, 'hash' => $row['hash'], 'admin' => $row['admin']];
            }
        }

        return $found;
    }

    public function administrators(): int
    {
        return count(array_filter($this->rows, static fn (array $row): bool => $row['admin']));
    }

    public function holdersOf(string $email, string $login): array
    {
        $holders = [];
        foreach ($this->rows as $row) {
            if ($row['login'] !== $login && in_array(strtoupper($email), array_map('strtoupper', $row['emails']), true)) {
                $holders[] = $row['login'];
            }
        }

        return $holders;
    }

    public function insertAdministrator(string $login, string $hash, string $email): void
    {
        $this->inserted[] = ['login' => $login, 'email' => $email];
        $this->rows[] = ['login' => $login, 'hash' => $hash, 'emails' => [$email], 'admin' => true];
    }

    public function emailsOf(string $id): array
    {
        return $this->rows[(int) $id]['emails'];
    }

    public function updateHash(string $id, string $hash): void
    {
        $this->updated[] = $this->rows[(int) $id]['login'];
        $this->rows[(int) $id]['hash'] = $hash;
    }

    /**
     * @return array{login: string, hash: string, emails: list<string>, admin: bool}|null
     */
    public function row(string $login): ?array
    {
        foreach ($this->rows as $row) {
            if ($row['login'] === $login) {
                return $row;
            }
        }

        return null;
    }
}

final class RealignAdminPasswordTest extends TestCase
{
    private const LOGIN = 'platformadmin';

    private const PASSWORD = 'the-declared-password';

    private const EMAIL = 'platformadmin@example.org';

    /**
     * @param list<string> $emails addresses linked to the user
     * @return array{login: string, hash: string, emails: list<string>, admin: bool}
     */
    private static function row(string $login, string $password, array $emails, bool $admin): array
    {
        return ['login' => $login, 'hash' => password_hash(strtolower(md5($password)), PASSWORD_DEFAULT), 'emails' => $emails, 'admin' => $admin];
    }

    /**
     * @return array{login: string, hash: string, emails: list<string>, admin: bool}
     */
    private static function legacyAdministrator(): array
    {
        return self::row('administrator', 'host-password', ['administrator@example.org'], true);
    }

    private static function accepts(string $hash): bool
    {
        return password_verify(strtolower(md5(self::PASSWORD)), $hash);
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
        fwrite($pipes[0], (string) file_get_contents(dirname(__DIR__, 6) . '/roles/web-app-suitecrm/files/php/realign_admin_password.php'));
        fclose($pipes[0]);
        $stdout = (string) stream_get_contents($pipes[1]);
        $stderr = (string) stream_get_contents($pipes[2]);
        fclose($pipes[1]);
        fclose($pipes[2]);

        return [proc_close($process), $stdout, $stderr];
    }

    public function testTheScriptPipedIntoPhpLikeTheRoleReportsAnEmptyEnvironmentAsFail(): void
    {
        [$code, $stdout, $stderr] = self::pipeIntoPhp();

        self::assertSame(1, $code, $stdout . $stderr);
        self::assertSame('', $stdout);
        self::assertStringContainsString("[FAIL] SUITECRM_DB_HOST is empty\n", $stderr);
        self::assertStringNotContainsString('Undefined constant', $stderr);
    }

    public function testAnAbsentLoginIsCreatedAsAdministratorNextToTheExistingOne(): void
    {
        $users = new FakeUsers([self::legacyAdministrator()]);

        [$code, $line] = ensure($users, self::LOGIN, self::PASSWORD, self::EMAIL);

        self::assertSame(0, $code);
        self::assertStringStartsWith('[CHANGED]', $line);
        self::assertSame([['login' => self::LOGIN, 'email' => self::EMAIL]], $users->inserted);
        self::assertTrue(self::accepts($users->row(self::LOGIN)['hash']));
        self::assertSame(self::legacyAdministrator()['emails'], $users->row('administrator')['emails']);
        self::assertTrue($users->row('administrator')['admin']);
    }

    public function testASecondRunAfterTheCreateChangesNothing(): void
    {
        $users = new FakeUsers([self::legacyAdministrator()]);
        ensure($users, self::LOGIN, self::PASSWORD, self::EMAIL);

        [$code, $line] = ensure($users, self::LOGIN, self::PASSWORD, self::EMAIL);

        self::assertSame(0, $code);
        self::assertStringStartsWith('[UNCHANGED]', $line);
        self::assertCount(1, $users->inserted);
        self::assertSame([], $users->updated);
    }

    public function testAPresentAdministratorWithTheDeclaredPasswordIsLeftAlone(): void
    {
        $users = new FakeUsers([self::row(self::LOGIN, self::PASSWORD, [self::EMAIL], true)]);

        [$code, $line] = ensure($users, self::LOGIN, self::PASSWORD, self::EMAIL);

        self::assertSame(0, $code);
        self::assertStringStartsWith('[UNCHANGED]', $line);
        self::assertSame([], $users->inserted);
        self::assertSame([], $users->updated);
    }

    public function testALegacyMd5HashOfTheDeclaredPasswordIsLeftAlone(): void
    {
        $users = new FakeUsers([['login' => self::LOGIN, 'hash' => strtolower(md5(self::PASSWORD)), 'emails' => [self::EMAIL], 'admin' => true]]);

        [$code, $line] = ensure($users, self::LOGIN, self::PASSWORD, self::EMAIL);

        self::assertSame(0, $code);
        self::assertStringStartsWith('[UNCHANGED]', $line);
    }

    public function testAPresentAdministratorWithAStalePasswordIsRealigned(): void
    {
        $users = new FakeUsers([self::row(self::LOGIN, 'stale', [self::EMAIL], true)]);

        [$code, $line] = ensure($users, self::LOGIN, self::PASSWORD, self::EMAIL);

        self::assertSame(0, $code);
        self::assertStringStartsWith('[CHANGED]', $line);
        self::assertSame([self::LOGIN], $users->updated);
        self::assertTrue(self::accepts($users->row(self::LOGIN)['hash']));
    }

    public function testAnInstallWithoutAnyAdministratorFailsInsteadOfCreating(): void
    {
        $users = new FakeUsers([self::row('sales', 'x', ['sales@example.org'], false)]);

        [$code, $line] = ensure($users, self::LOGIN, self::PASSWORD, self::EMAIL);

        self::assertSame(1, $code);
        self::assertStringStartsWith('[FAIL]', $line);
        self::assertStringContainsString('no administrator', $line);
        self::assertSame([], $users->inserted);
    }

    public function testAnEmailHeldByAnotherUserFailsNamingTheHolder(): void
    {
        $users = new FakeUsers([
            self::legacyAdministrator(),
            self::row('sales', 'x', ['PlatformAdmin@Example.org'], false),
        ]);

        [$code, $line] = ensure($users, self::LOGIN, self::PASSWORD, self::EMAIL);

        self::assertSame(1, $code);
        self::assertStringStartsWith('[FAIL]', $line);
        self::assertStringContainsString('sales', $line);
        self::assertSame([], $users->inserted);
    }

    public function testTwoUndeletedUsersWithTheLoginFailWithoutTouchingEither(): void
    {
        $users = new FakeUsers([
            self::legacyAdministrator(),
            self::row(self::LOGIN, 'stale', [self::EMAIL], true),
            self::row(self::LOGIN, 'other', ['other@example.org'], false),
        ]);

        [$code, $line] = ensure($users, self::LOGIN, self::PASSWORD, self::EMAIL);

        self::assertSame(1, $code);
        self::assertStringStartsWith('[FAIL] 2 undeleted SuiteCRM users carry the login', $line);
        self::assertSame([], $users->updated);
        self::assertSame([], $users->inserted);
    }

    public function testANonAdministratorWithTheDeclaredEmailIsStillNotPromoted(): void
    {
        $users = new FakeUsers([self::legacyAdministrator(), self::row(self::LOGIN, 'stale', ['PlatformAdmin@Example.org'], false)]);

        [$code, $line] = ensure($users, self::LOGIN, self::PASSWORD, self::EMAIL);

        self::assertSame(1, $code);
        self::assertStringStartsWith('[FAIL]', $line);
        self::assertStringContainsString('not promoted', $line);
        self::assertStringContainsString('a matching email proves nothing', $line);
        self::assertFalse($users->row(self::LOGIN)['admin']);
        self::assertSame([], $users->updated);
    }

    public function testANonAdministratorWithAnotherEmailNamesTheMismatch(): void
    {
        $users = new FakeUsers([self::legacyAdministrator(), self::row(self::LOGIN, 'stale', ['someone@example.org'], false)]);

        [$code, $line] = ensure($users, self::LOGIN, self::PASSWORD, self::EMAIL);

        self::assertSame(1, $code);
        self::assertStringContainsString("its email someone@example.org differs from 'platformadmin@example.org'", $line);
        self::assertFalse($users->row(self::LOGIN)['admin']);
    }

    public function testAnLdapCreatedNonAdministratorWithoutEmailSaysSo(): void
    {
        $users = new FakeUsers([self::legacyAdministrator(), self::row(self::LOGIN, 'stale', [], false)]);

        [$code, $line] = ensure($users, self::LOGIN, self::PASSWORD, self::EMAIL);

        self::assertSame(1, $code);
        self::assertStringContainsString('it carries no email address', $line);
        self::assertStringNotContainsString('differs', $line);
        self::assertFalse($users->row(self::LOGIN)['admin']);
        self::assertSame([], $users->updated);
    }
}
