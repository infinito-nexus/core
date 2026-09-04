<?php

declare(strict_types=1);

namespace App\Models\Auth {
    final class User
    {
        public static ?User $found = null;

        public static ?string $queriedEmail = null;

        public string $password = '';

        public int $saves = 0;

        public static function where(string $column, $value): self
        {
            self::$queriedEmail = $column === 'email' ? (string) $value : null;

            return new self();
        }

        public function first(): ?User
        {
            return self::$found;
        }

        public function save(): void
        {
            ++$this->saves;
        }
    }
}

namespace Illuminate\Support\Facades {
    final class Hash
    {
        public static function check(string $plain, string $stored): bool
        {
            return $stored === 'bcrypt:' . $plain;
        }
    }
}

namespace {

    use App\Models\Auth\User;
    use PHPUnit\Framework\TestCase;

    final class RealignAdminPasswordTest extends TestCase
    {
        private const SNIPPET = '/roles/web-app-akaunting/files/php/realign_admin_password.php';

        /**
         * Evaluate the tinker snippet against the stubs above.
         *
         * @return string everything the snippet printed
         */
        private function runSnippet(?string $email, ?string $password): string
        {
            putenv($email === null ? 'ADMIN_EMAIL' : 'ADMIN_EMAIL=' . $email);
            putenv($password === null ? 'ADMIN_PASSWORD' : 'ADMIN_PASSWORD=' . $password);

            $code = file_get_contents(dirname(__DIR__, 6) . self::SNIPPET);
            ob_start();
            eval($code); // nocheck: eval - the snippet is repo-owned and only runs under artisan tinker
            return (string) ob_get_clean();
        }

        protected function setUp(): void
        {
            User::$found = null;
            User::$queriedEmail = null;
        }

        public function testItFailsWhenNoUserCarriesTheEmail(): void
        {
            $out = $this->runSnippet('admin@example.org', 'declared');

            self::assertStringContainsString('FAILED', $out);
            self::assertSame('admin@example.org', User::$queriedEmail);
        }

        public function testItFailsWhenTheEmailIsMissing(): void
        {
            $out = $this->runSnippet(null, 'declared');

            self::assertStringContainsString('FAILED', $out);
        }

        public function testItLeavesAMatchingPasswordAlone(): void
        {
            $user = new User();
            $user->password = 'bcrypt:declared';
            User::$found = $user;

            $out = $this->runSnippet('admin@example.org', 'declared');

            self::assertSame("UNCHANGED\n", $out);
            self::assertSame(0, $user->saves);
        }

        public function testItStoresTheDeclaredPasswordInClearTextSoTheModelHashesIt(): void
        {
            $user = new User();
            $user->password = 'bcrypt:stale';
            User::$found = $user;

            $out = $this->runSnippet('admin@example.org', 'declared');

            self::assertSame("CHANGED\n", $out);
            self::assertSame(1, $user->saves);
            self::assertSame('declared', $user->password);
        }
    }
}
