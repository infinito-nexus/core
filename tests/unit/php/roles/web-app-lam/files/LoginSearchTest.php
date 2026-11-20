<?php

declare(strict_types=1);

use PHPUnit\Framework\TestCase;

final class LoginSearchTest extends TestCase
{
    private const SUFFIX = 'ou=users,dc=example,dc=test';
    private const FILTER = '(&(uid=%USER%)(memberOf=cn=web-app-lam-administrator,ou=roles,dc=example,dc=test))';

    private const PROFILE = <<<'JSON'
        {
          "ServerURL": "ldap://ldap:389",
          "Passwd": "{SSHA}stub stub",
          "loginMethod": "list",
          "typeSettings": {"suffix_user": "dc=my-domain,dc=com"},
          "moduleSettings": {},
          "defaultLanguage": "en_US.utf8"
        }
        JSON;

    /**
     * Run login_search.php against a throwaway served profile and sample profile.
     *
     * @param string|null $served   lam.conf content, null to omit the file
     * @param string|null $sample   unix.sample.conf content, null to omit the file
     * @param int $argCount         how many of the two profile paths to pass
     * @return array{0: string, 1: int, 2: string|null, 3: string|null}
     *         stderr, exit code and both profiles' content afterwards
     */
    private function runScript(?string $served, ?string $sample, int $argCount): array
    {
        $dir = sys_get_temp_dir() . '/lam-login-search-' . bin2hex(random_bytes(6));
        mkdir($dir);
        $servedPath = $dir . '/lam.conf';
        $samplePath = $dir . '/unix.sample.conf';
        if ($served !== null) {
            file_put_contents($servedPath, $served);
        }
        if ($sample !== null) {
            file_put_contents($samplePath, $sample);
        }

        $script = dirname(__DIR__, 6) . '/roles/web-app-lam/files/php/login_search.php';
        $process = proc_open(
            array_merge([PHP_BINARY, $script], array_slice([$servedPath, $samplePath], 0, $argCount)),
            [1 => ['pipe', 'w'], 2 => ['pipe', 'w']],
            $pipes,
            null,
            [
                'LAM_LOGIN_SEARCH_SUFFIX' => self::SUFFIX,
                'LAM_LOGIN_SEARCH_FILTER' => self::FILTER,
                'PATH' => (string) getenv('PATH'),
            ]
        );
        stream_get_contents($pipes[1]);
        $stderr = (string) stream_get_contents($pipes[2]);
        fclose($pipes[1]);
        fclose($pipes[2]);
        $code = proc_close($process);

        $servedAfter = is_file($servedPath) ? (string) file_get_contents($servedPath) : null;
        $sampleAfter = is_file($samplePath) ? (string) file_get_contents($samplePath) : null;
        foreach ([$servedPath, $samplePath] as $path) {
            if (is_file($path)) {
                unlink($path);
            }
        }
        rmdir($dir);

        return [$stderr, $code, $servedAfter, $sampleAfter];
    }

    private function assertSearchLogin(?string $profile): void
    {
        $config = json_decode((string) $profile, true, 512, JSON_THROW_ON_ERROR);
        $this->assertSame('search', $config['loginMethod']);
        $this->assertSame(self::SUFFIX, $config['loginSearchSuffix']);
        $this->assertSame(self::FILTER, $config['loginSearchFilter']);
    }

    public function testTheServedProfileAndTheSampleAreBothPatched(): void
    {
        [$stderr, $code, $served, $sample] = $this->runScript(self::PROFILE, self::PROFILE, 2);

        $this->assertSame(0, $code, $stderr);
        $this->assertSearchLogin($served);
        $this->assertSearchLogin($sample);
    }

    public function testAMissingServedProfileIsSkipped(): void
    {
        [$stderr, $code, $served, $sample] = $this->runScript(null, self::PROFILE, 2);

        $this->assertSame(0, $code, $stderr);
        $this->assertNull($served);
        $this->assertSearchLogin($sample);
    }

    public function testAMissingSampleProfileIsSkipped(): void
    {
        [$stderr, $code, $served, $sample] = $this->runScript(self::PROFILE, null, 2);

        $this->assertSame(0, $code, $stderr);
        $this->assertSearchLogin($served);
        $this->assertNull($sample);
    }

    public function testNeitherProfilePresentFailsLoudly(): void
    {
        [$stderr, $code] = $this->runScript(null, null, 2);

        $this->assertSame(1, $code);
        $this->assertStringContainsString('neither the served profile', $stderr);
    }

    public function testBothProfilePathsAreRequired(): void
    {
        [$stderr, $code, $served] = $this->runScript(self::PROFILE, self::PROFILE, 1);

        $this->assertSame(2, $code);
        $this->assertStringContainsString('usage:', $stderr);
        $this->assertSame(self::PROFILE, $served);
    }

    public function testOutputKeepsTheLineShapeStartShSedRewrites(): void
    {
        [, , $served] = $this->runScript(self::PROFILE, null, 2);
        $lines = explode("\n", (string) $served);

        $this->assertSame('{', $lines[0]);
        $this->assertSame(1, preg_match_all('/^\s*"ServerURL": "[^"]*",$/m', (string) $served));
        $this->assertSame(1, preg_match_all('/^\s*"Passwd": .*,$/m', (string) $served));
        $this->assertSame(1, preg_match_all('/"suffix_user": "[^"]*"/', (string) $served));
        $this->assertSame(1, preg_match_all('/^\s*"defaultLanguage": "[^"]*",$/m', (string) $served));
        $this->assertSame(1, preg_match_all('/^\s*"moduleSettings": \{\},$/m', (string) $served));
    }

    public function testRewriteIsStableOnASecondRun(): void
    {
        [, , $once] = $this->runScript(self::PROFILE, null, 2);
        [, , $twice] = $this->runScript((string) $once, null, 2);

        $this->assertSame($once, $twice);
    }
}
