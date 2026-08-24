<?php

declare(strict_types=1);

use PHPUnit\Framework\TestCase;

final class ConfigureDbTest extends TestCase
{
    /**
     * Run the script against a throwaway configuration.php.
     *
     * @param array<string, string> $env  extra environment for the child
     * @param string|null $contents       fixture content, null to omit the file
     * @return array{0: string, 1: int, 2: string|null}
     *         stdout, exit code and the file content afterwards
     */
    private function runScript(array $env, ?string $contents): array
    {
        $file = tempnam(sys_get_temp_dir(), 'jcfg');
        if ($contents === null) {
            unlink($file);
        } else {
            file_put_contents($file, $contents);
        }

        $script = dirname(__DIR__, 6) . '/roles/web-app-joomla/files/php/configure_db.php';
        $process = proc_open(
            [PHP_BINARY, $script],
            [1 => ['pipe', 'w'], 2 => ['pipe', 'w']],
            $pipes,
            null,
            $env + ['J_CONFIG_FILE' => $file, 'PATH' => (string) getenv('PATH')]
        );
        $stdout = (string) stream_get_contents($pipes[1]);
        fclose($pipes[1]);
        fclose($pipes[2]);
        $code = proc_close($process);

        $after = is_file($file) ? (string) file_get_contents($file) : null;
        if (is_file($file)) {
            unlink($file);
        }

        return [$stdout, $code, $after];
    }

    private const CONFIG = <<<'PHP'
        <?php
        class JConfig {
        	public $dbtype = 'mysqli';
        	public $host = 'old-host';
        	public $user = 'joomla';
        	public $password = 'old-secret';
        	public $db = 'joomla';
        }
        PHP;

    /** @return array<string, string> */
    private function env(string $host, string $password): array
    {
        return [
            'J_DBTYPE' => 'mysqli',
            'J_DBHOST' => $host,
            'J_DBUSER' => 'joomla',
            'J_DBPASS' => $password,
            'J_DBNAME' => 'joomla',
        ];
    }

    public function testOnlyDifferingValuesAreRewritten(): void
    {
        [$stdout, $code, $after] = $this->runScript(
            $this->env('new-host', 'old-secret'),
            self::CONFIG
        );

        $this->assertSame(0, $code);
        $this->assertSame('changed', $stdout);
        $this->assertStringContainsString("public \$host = 'new-host';", (string) $after);
        $this->assertStringContainsString("public \$user = 'joomla';", (string) $after);
    }

    public function testMatchingConfigIsReportedAsOkAndLeftAlone(): void
    {
        [$stdout, , $after] = $this->runScript(
            $this->env('old-host', 'old-secret'),
            self::CONFIG
        );

        $this->assertSame('ok', $stdout);
        $this->assertSame(self::CONFIG, $after);
    }

    public function testPasswordWithApostropheIsEscaped(): void
    {
        [, , $after] = $this->runScript(
            $this->env('old-host', "pa'ss"),
            self::CONFIG
        );

        $this->assertStringContainsString("public \$password = 'pa\\'ss';", (string) $after);
    }

    public function testAbsentKeyIsNotAdded(): void
    {
        [, , $after] = $this->runScript(
            $this->env('new-host', 'old-secret'),
            "<?php\nclass JConfig {\n\tpublic \$host = 'old-host';\n}\n"
        );

        $this->assertStringNotContainsString('$dbtype', (string) $after);
    }

    public function testMissingConfigFileIsAcceptedSilently(): void
    {
        [$stdout, $code] = $this->runScript($this->env('new-host', 'x'), null);

        $this->assertSame(0, $code);
        $this->assertSame('', $stdout);
    }
}
