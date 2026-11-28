<?php

declare(strict_types=1);

use PHPUnit\Framework\TestCase;

final class InfinitoOidcRbacMapperTest extends TestCase
{
    private const PLUGIN = '/roles/web-app-wordpress/files/mu-plugins/infinito-oidc-rbac-mapper.php';

    private const LOCKED = ['first_name', 'last_name', 'display_name', 'email', 'website', 'language'];

    private const SUBMITTED_POST = ['first_name' => 'X', 'last_name' => 'Y', 'display_name' => 'Z', 'email' => 'x@example.org', 'url' => 'https://x.example', 'locale' => 'fr_FR', 'description' => 'kept'];

    private const SUBMITTED_DATA = ['user_email' => 'x@example.org', 'user_url' => 'https://x.example', 'display_name' => 'Z', 'user_nicename' => 'kept'];

    private const SUBMITTED_META = ['first_name' => 'X', 'last_name' => 'Y', 'locale' => 'fr_FR', 'nickname' => 'kept'];

    private const HARNESS = <<<'PHP'
        <?php
        define('ABSPATH', '/');
        function add_action($hook, $callback, $priority = 10, $acceptedArgs = 1)
        {
            return true;
        }
        function add_filter($hook, $callback, $priority = 10, $acceptedArgs = 1)
        {
            return true;
        }
        function apply_filters($hook, $value)
        {
            return $value;
        }
        function wp_slash($value)
        {
            return $value;
        }
        class WP_User
        {
            public $ID = 7;
            public $user_email = 'biber@example.org';
            public $user_url = 'https://biber.example';
            public $display_name = 'Biber';
            public $first_name = 'Bi';
            public $last_name = 'Ber';
            public $locale = 'de_DE';
        }
        function get_userdata($id)
        {
            return new WP_User();
        }
        function get_user_meta($id, $key, $single = false)
        {
            $meta = ['openid-connect-generic-subject-identity' => (string) getenv('STUB_SUBJECT'), 'first_name' => 'Bi', 'last_name' => 'Ber', 'locale' => 'de_DE'];
            return $meta[$key] ?? '';
        }
        require getenv('STUB_PLUGIN');
        $submitted = json_decode((string) getenv('STUB_SUBMITTED'), true);
        try {
            if (getenv('STUB_CASE') === 'fields') {
                echo json_encode(['fields' => infinito_oidc_locked_fields()]);
                exit;
            }
            $_POST = $submitted['post'];
            infinito_oidc_keep_managed_profile_fields(7);
            echo json_encode([
                'post' => $_POST,
                'data' => infinito_oidc_keep_managed_user_data($submitted['data'], true, 7),
                'meta' => infinito_oidc_keep_managed_user_meta($submitted['meta'], new WP_User(), true),
                'mail' => infinito_oidc_mail_email_change(true, ['ID' => 7]),
            ]);
        } catch (Throwable $error) {
            echo json_encode(['error' => $error->getMessage()]);
        }
        PHP;

    /**
     * @param ?string $locked the WORDPRESS_OIDC_PROFILE_LOCKED value, null to leave it unset
     * @param bool $managed   whether the account carries an OIDC subject
     * @param string $case    `guards` runs every guard on the submitted values in a fresh PHP process against a
     *                        stubbed WordPress, `fields` returns the resolved fields
     * @return array<string, mixed> the guarded values, the resolved fields or the raised message
     */
    private function mapper(?string $locked, bool $managed, string $case): array
    {
        $harness = tempnam(sys_get_temp_dir(), 'wpom');
        file_put_contents($harness, self::HARNESS);
        $env = [
            'STUB_CASE' => $case,
            'STUB_PLUGIN' => dirname(__DIR__, 7) . self::PLUGIN,
            'STUB_SUBJECT' => $managed ? 'sub-biber' : '',
            'STUB_SUBMITTED' => (string) json_encode(['post' => self::SUBMITTED_POST, 'data' => self::SUBMITTED_DATA, 'meta' => self::SUBMITTED_META]),
        ];
        if ($locked !== null) {
            $env['WORDPRESS_OIDC_PROFILE_LOCKED'] = $locked;
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

    /**
     * @param list<string> $removed keys dropped from today's locked keys
     * @return string the WORDPRESS_OIDC_PROFILE_LOCKED value of the remaining keys
     */
    private static function lockedWithout(array $removed): string
    {
        return (string) json_encode(array_values(array_diff(self::LOCKED, $removed)));
    }

    public function testEveryLockedKeyResolvesToItsStoredFieldAndInput(): void
    {
        self::assertSame(
            [
                'first_name' => ['meta' => 'first_name', 'input' => 'first_name', 'submit' => 'restore'],
                'last_name' => ['meta' => 'last_name', 'input' => 'last_name', 'submit' => 'restore'],
                'display_name' => ['column' => 'display_name', 'input' => 'display_name', 'submit' => 'drop'],
                'email' => ['column' => 'user_email', 'input' => 'email', 'submit' => 'restore'],
                'website' => ['column' => 'user_url', 'input' => 'url', 'submit' => 'restore'],
                'language' => ['meta' => 'locale', 'input' => 'locale', 'submit' => 'drop'],
            ],
            $this->mapper((string) json_encode(self::LOCKED), true, 'fields')['fields']
        );
    }

    public function testTheConfiguredKeysKeepEveryStoredProfileFieldOfAnOidcAccount(): void
    {
        self::assertSame(
            [
                'post' => ['first_name' => 'Bi', 'last_name' => 'Ber', 'email' => 'biber@example.org', 'url' => 'https://biber.example', 'description' => 'kept'],
                'data' => ['user_email' => 'biber@example.org', 'user_url' => 'https://biber.example', 'display_name' => 'Biber', 'user_nicename' => 'kept'],
                'meta' => ['first_name' => 'Bi', 'last_name' => 'Ber', 'locale' => 'de_DE', 'nickname' => 'kept'],
                'mail' => false,
            ],
            $this->mapper((string) json_encode(self::LOCKED), true, 'guards')
        );
    }

    public function testARemovedKeyUnlocksItsFieldOnEveryWrite(): void
    {
        self::assertSame(
            [
                'post' => ['first_name' => 'Bi', 'last_name' => 'Ber', 'email' => 'x@example.org', 'url' => 'https://x.example', 'locale' => 'fr_FR', 'description' => 'kept'],
                'data' => ['user_email' => 'x@example.org', 'user_url' => 'https://x.example', 'display_name' => 'Biber', 'user_nicename' => 'kept'],
                'meta' => ['first_name' => 'Bi', 'last_name' => 'Ber', 'locale' => 'fr_FR', 'nickname' => 'kept'],
                'mail' => true,
            ],
            $this->mapper(self::lockedWithout(['email', 'website', 'language']), true, 'guards')
        );
    }

    public function testAnAccountOutsideOidcKeepsEverySubmittedValueWithoutReadingTheList(): void
    {
        self::assertSame(
            ['post' => self::SUBMITTED_POST, 'data' => self::SUBMITTED_DATA, 'meta' => self::SUBMITTED_META, 'mail' => true],
            $this->mapper(null, false, 'guards')
        );
    }

    public function testAnUnknownKeyRaisesAndNamesIt(): void
    {
        self::assertStringContainsString('nickname', $this->mapper((string) json_encode(['first_name', 'nickname']), true, 'guards')['error']);
    }

    public function testAnEmptyLockedListRaises(): void
    {
        self::assertStringContainsString('WORDPRESS_OIDC_PROFILE_LOCKED', $this->mapper('[]', true, 'guards')['error']);
    }

    public function testALockedObjectInsteadOfAListRaises(): void
    {
        self::assertStringContainsString('WORDPRESS_OIDC_PROFILE_LOCKED', $this->mapper('{"email":"#email"}', true, 'guards')['error']);
    }

    public function testALockedListThatIsNoJsonRaises(): void
    {
        self::assertStringContainsString('WORDPRESS_OIDC_PROFILE_LOCKED', $this->mapper('email,website', true, 'guards')['error']);
    }

    public function testAMissingLockedListRaisesForAnOidcAccount(): void
    {
        self::assertStringContainsString('WORDPRESS_OIDC_PROFILE_LOCKED', $this->mapper(null, true, 'guards')['error']);
    }
}
