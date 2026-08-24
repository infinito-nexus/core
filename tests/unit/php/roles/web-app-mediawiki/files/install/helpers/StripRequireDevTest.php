<?php

declare(strict_types=1);

use PHPUnit\Framework\TestCase;

final class StripRequireDevTest extends TestCase
{
    /**
     * Run the script against a throwaway composer.json.
     *
     * @param string|null $contents fixture content, null to omit the file
     * @param bool $withPath        false to invoke the script without an argument
     * @return array{0: string, 1: string, 2: int, 3: string|null}
     *         stdout, stderr, exit code and the file content afterwards
     */
    private function runScript(?string $contents, bool $withPath = true): array
    {
        $file = (string) tempnam(sys_get_temp_dir(), 'cmpsr');
        if ($contents === null) {
            unlink($file);
        } else {
            file_put_contents($file, $contents);
        }

        $script = dirname(__DIR__, 8) . '/roles/web-app-mediawiki/files/install/helpers/strip_require_dev.php';
        $command = $withPath ? [PHP_BINARY, $script, $file] : [PHP_BINARY, $script];
        $process = proc_open(
            $command,
            [1 => ['pipe', 'w'], 2 => ['pipe', 'w']],
            $pipes,
            null,
            ['PATH' => (string) getenv('PATH')]
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

    private const MANIFEST = <<<'JSON'
        {
            "name": "acme/ext",
            "require": {"php": ">=8.1"},
            "require-dev": {"phpunit/phpunit": "^10"},
            "autoload": {"psr-4": {"Acme\\": "src/"}}
        }
        JSON;

    public function testRequireDevIsRemovedFromTheManifest(): void
    {
        [$stdout, , $code, $after] = $this->runScript(self::MANIFEST);

        $this->assertSame(0, $code);
        $this->assertSame("STRIP_REQUIRE_DEV_REMOVED\n", $stdout);
        $this->assertArrayNotHasKey('require-dev', (array) json_decode((string) $after, true));
    }

    public function testTheRemainingKeysKeepTheirValuesAndOrder(): void
    {
        [, , , $after] = $this->runScript(self::MANIFEST);

        $decoded = (array) json_decode((string) $after, true);
        $this->assertSame(['name', 'require', 'autoload'], array_keys($decoded));
        $this->assertSame('acme/ext', $decoded['name']);
        $this->assertSame(['php' => '>=8.1'], $decoded['require']);
        $this->assertSame(['psr-4' => ['Acme\\' => 'src/']], $decoded['autoload']);
    }

    public function testAnEmptyObjectIsNotRewrittenAsAnArray(): void
    {
        [, , , $after] = $this->runScript('{"extra":{},"require-dev":{"a/b":"^1"}}');

        $this->assertStringContainsString('"extra": {}', (string) $after);
        $this->assertStringNotContainsString('[]', (string) $after);
    }

    public function testSlashesAndUnicodeStayUnescaped(): void
    {
        [, , , $after] = $this->runScript('{"homepage":"https://acme.test/x","description":"Grüße","require-dev":{}}');

        $this->assertStringContainsString('https://acme.test/x', (string) $after);
        $this->assertStringContainsString('Grüße', (string) $after);
    }

    public function testTheRewrittenFileEndsWithANewline(): void
    {
        [, , , $after] = $this->runScript(self::MANIFEST);

        $this->assertStringEndsWith("}\n", (string) $after);
    }

    public function testAManifestWithoutRequireDevIsLeftByteForByte(): void
    {
        $original = '{"name":"acme/ext",   "require":{"php":">=8.1"}}';
        [$stdout, , $code, $after] = $this->runScript($original);

        $this->assertSame(0, $code);
        $this->assertSame("STRIP_REQUIRE_DEV_ABSENT\n", $stdout);
        $this->assertSame($original, $after);
    }

    public function testMalformedJsonFailsWithoutWritingAnything(): void
    {
        $original = '{"name": "acme/ext", "require-dev"';
        [, $stderr, $code, $after] = $this->runScript($original);

        $this->assertSame(1, $code);
        $this->assertStringContainsString('is not a JSON object', $stderr);
        $this->assertSame($original, $after);
    }

    public function testATopLevelJsonArrayIsRejected(): void
    {
        $original = '[{"require-dev": {}}]';
        [, $stderr, $code, $after] = $this->runScript($original);

        $this->assertSame(1, $code);
        $this->assertStringContainsString('is not a JSON object', $stderr);
        $this->assertSame($original, $after);
    }

    public function testAMissingManifestFails(): void
    {
        [, $stderr, $code] = $this->runScript(null);

        $this->assertSame(1, $code);
        $this->assertStringContainsString('cannot read', $stderr);
    }

    public function testAMissingArgumentIsAUsageError(): void
    {
        [, $stderr, $code] = $this->runScript(null, false);

        $this->assertSame(2, $code);
        $this->assertStringContainsString('usage: strip_require_dev.php', $stderr);
    }
}
