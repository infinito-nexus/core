<?php

declare(strict_types=1);

use PHPUnit\Framework\TestCase;

final class ToggleDebugTest extends TestCase
{
    /**
     * Run the script against a throwaway configuration.php.
     *
     * @param array<string, string> $env  extra environment for the child
     * @param string|null $contents       fixture content, null to omit the file
     * @return array{0: string, 1: string, 2: int, 3: string|null}
     *         stdout, stderr, exit code and the file content afterwards
     */
    private function runScript(array $env, ?string $contents): array
    {
        $file = tempnam(sys_get_temp_dir(), 'jcfg');
        if ($contents === null) {
            unlink($file);
        } else {
            file_put_contents($file, $contents);
        }

        $script = dirname(__DIR__, 6) . '/roles/web-app-joomla/files/php/toggle_debug.php';
        $process = proc_open(
            [PHP_BINARY, $script],
            [1 => ['pipe', 'w'], 2 => ['pipe', 'w']],
            $pipes,
            null,
            $env + ['J_CONFIG_FILE' => $file, 'PATH' => (string) getenv('PATH')]
        );
        $stdout = (string) stream_get_contents($pipes[1]);
        $stderr = (string) stream_get_contents($pipes[2]);
        fclose($pipes[1]);
        fclose($pipes[2]);
        $code = proc_close($process);

        $after = is_file($file) ? (string) file_get_contents($file) : null;
        if (is_file($file)) {
            unlink($file);
        }

        return [$stdout, $stderr, $code, $after];
    }

    private const CONFIG = <<<'PHP'
        <?php
        class JConfig {
        	public $debug = true;
        	public $error_reporting = "none";
        	public $sitename = 'Infinito';
        }
        PHP;

    public function testExistingDebugFlagIsFlippedOff(): void
    {
        [$stdout, , $code, $after] = $this->runScript(
            ['J_MODE_DEBUG' => '0', 'J_ERR_LEVEL' => 'default'],
            self::CONFIG
        );

        $this->assertSame(0, $code);
        $this->assertSame('changed', $stdout);
        $this->assertStringContainsString('public $debug = false;', (string) $after);
        $this->assertStringNotContainsString('public $debug = true;', (string) $after);
    }

    public function testDebugFlagIsAppendedWhenAbsent(): void
    {
        [, , , $after] = $this->runScript(
            ['J_MODE_DEBUG' => '1', 'J_ERR_LEVEL' => 'default'],
            "<?php\nclass JConfig {\n\tpublic \$sitename = 'Infinito';\n}\n"
        );

        $this->assertStringContainsString('public $debug = true;', (string) $after);
        $this->assertStringContainsString("public \$error_reporting = 'default';", (string) $after);
    }

    public function testUnrelatedSettingsSurvive(): void
    {
        [, , , $after] = $this->runScript(
            ['J_MODE_DEBUG' => '0', 'J_ERR_LEVEL' => 'maximum'],
            self::CONFIG
        );

        $this->assertStringContainsString("public \$sitename = 'Infinito';", (string) $after);
    }

    public function testErrorLevelWithApostropheIsEscaped(): void
    {
        [, , , $after] = $this->runScript(
            ['J_MODE_DEBUG' => '0', 'J_ERR_LEVEL' => "it's"],
            self::CONFIG
        );

        $this->assertStringContainsString("public \$error_reporting = 'it\\'s';", (string) $after);
    }

    public function testMalformedPublicLinesAreDropped(): void
    {
        [, , , $after] = $this->runScript(
            ['J_MODE_DEBUG' => '0', 'J_ERR_LEVEL' => 'default'],
            "<?php\nclass JConfig {\n\tpublic 1 = broken;\n\tpublic = maximum;\n\tpublic \$debug = true;\n}\n"
        );

        $this->assertStringNotContainsString('public 1 =', (string) $after);
        $this->assertStringNotContainsString('public = maximum;', (string) $after);
    }

    public function testMissingConfigFileFailsLoudly(): void
    {
        [, $stderr, $code] = $this->runScript(
            ['J_MODE_DEBUG' => '0', 'J_ERR_LEVEL' => 'default'],
            null
        );

        $this->assertSame(1, $code);
        $this->assertStringContainsString('configuration.php missing', $stderr);
    }

    public function testRewriteIsStableOnASecondRun(): void
    {
        [, , , $once] = $this->runScript(
            ['J_MODE_DEBUG' => '0', 'J_ERR_LEVEL' => 'maximum'],
            self::CONFIG
        );
        [, , , $twice] = $this->runScript(
            ['J_MODE_DEBUG' => '0', 'J_ERR_LEVEL' => 'maximum'],
            (string) $once
        );

        $this->assertSame($once, $twice);
    }
}
