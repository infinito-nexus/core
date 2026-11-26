<?php

declare(strict_types=1);

use PHPUnit\Framework\TestCase;

final class ManagedOptionsTest extends TestCase
{
    private const SCRIPT = '/roles/web-app-wordpress/files/php/managed_options.php';

    private const PATH = 'probe://wp-content/infinito-managed-options.php';

    private const STAGED = self::PATH . '.new';

    private const MANAGED = [
        'option' => ['blogname' => 'Managed Blog'],
        'site_option' => ['registration' => 'user'],
        'merge' => [
            'mwai_options' => [
                'keys' => ['ai_default_env' => 'infinito-litellm'],
                'records' => ['ai_envs' => ['id' => 'infinito-litellm', 'apikey' => 'SYNTH-AI-KEY-1']],
            ],
        ],
    ];

    private const HARNESS = <<<'PHP'
        <?php
        final class ProbeStream
        {
            public $context;

            private string $path = '';

            private int $position = 0;

            public function stream_open($path, $mode, $options, &$openedPath)
            {
                $this->path = $path;
                if (str_contains($mode, 'r')) {
                    return isset($GLOBALS['probe']['files'][$path]);
                }
                $created = 0666 & ~umask();
                $GLOBALS['probe']['files'][$path] = ['content' => '', 'mode' => $created];
                $GLOBALS['probe']['log'][] = ['open', $path, $created];
                return true;
            }

            public function stream_write($data)
            {
                $GLOBALS['probe']['files'][$this->path]['content'] .= $data;
                return strlen($data);
            }

            public function stream_read($count)
            {
                $chunk = substr($GLOBALS['probe']['files'][$this->path]['content'], $this->position, $count);
                $this->position += strlen($chunk);
                return $chunk;
            }

            public function stream_eof()
            {
                return $this->position >= strlen($GLOBALS['probe']['files'][$this->path]['content']);
            }

            public function stream_flush()
            {
                return true;
            }

            public function stream_close()
            {
            }

            public function stream_set_option($option, $arg1, $arg2)
            {
                return false;
            }

            public function stream_stat()
            {
                return $this->url_stat($this->path, 0);
            }

            public function url_stat($path, $flags)
            {
                if (!isset($GLOBALS['probe']['files'][$path])) {
                    return false;
                }
                $file = $GLOBALS['probe']['files'][$path];
                return ['mode' => 0100000 | $file['mode'], 'size' => strlen($file['content'])];
            }

            public function stream_metadata($path, $option, $value)
            {
                if ($option !== STREAM_META_ACCESS || !isset($GLOBALS['probe']['files'][$path])) {
                    return false;
                }
                $GLOBALS['probe']['files'][$path]['mode'] = $value;
                $GLOBALS['probe']['log'][] = ['chmod', $path, $value];
                return true;
            }

            public function rename($from, $to)
            {
                $GLOBALS['probe']['files'][$to] = $GLOBALS['probe']['files'][$from];
                unset($GLOBALS['probe']['files'][$from]);
                $GLOBALS['probe']['log'][] = ['rename', $from, $to];
                return true;
            }
        }
        umask(0022);
        stream_wrapper_register('probe', ProbeStream::class);
        $GLOBALS['probe'] = ['files' => json_decode((string) getenv('STUB_FILES'), true), 'log' => []];
        ob_start();
        register_shutdown_function(static function () {
            $stdout = ob_get_clean();
            echo json_encode(['stdout' => $stdout, 'files' => (object) $GLOBALS['probe']['files'], 'log' => $GLOBALS['probe']['log']]);
        });
        require getenv('STUB_SCRIPT');
        PHP;

    /**
     * Run the script in a fresh PHP process whose values file lives on a stream that records every step.
     *
     * @param array<string, array{content: string, mode: int}> $files files on the stream before the run, by URL
     * @return array{stdout: string, files: array<string, array{content: string, mode: int}>, log: list<list<int|string>>}
     *         what the script printed, the files on the stream and every open for writing, chmod and rename in order
     */
    private function persist(array $files): array
    {
        $harness = tempnam(sys_get_temp_dir(), 'wpmw');
        file_put_contents($harness, self::HARNESS);
        $env = [
            'INFINITO_MANAGED_OPTIONS' => base64_encode((string) json_encode(self::MANAGED)),
            'STUB_FILES' => (string) json_encode((object) $files),
            'STUB_SCRIPT' => dirname(__DIR__, 6) . self::SCRIPT,
        ];
        $process = proc_open([PHP_BINARY, $harness, self::PATH], [1 => ['pipe', 'w'], 2 => ['pipe', 'w']], $pipes, null, $env);
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
     * @param string $content the values file the script wrote
     * @return mixed what the mu-plugin gets when it includes that file
     */
    private static function included(string $content): mixed
    {
        $file = tempnam(sys_get_temp_dir(), 'wpmv');
        file_put_contents($file, $content);
        $values = include $file;
        unlink($file);

        return $values;
    }

    public function testTheValuesFileIsPrivateFromItsFirstByteAndMovedIntoPlaceWhole(): void
    {
        $run = $this->persist([]);

        self::assertSame("changed\n", $run['stdout']);
        self::assertSame(
            [['open', self::STAGED, 0600], ['chmod', self::STAGED, 0600], ['rename', self::STAGED, self::PATH]],
            $run['log']
        );
        self::assertSame([self::PATH], array_keys($run['files']));
        self::assertSame(0600, $run['files'][self::PATH]['mode']);
        self::assertSame(self::MANAGED, self::included($run['files'][self::PATH]['content']));
    }

    public function testAWorldReadableFileWithTheSameValuesIsWrittenAgainPrivate(): void
    {
        $content = $this->persist([])['files'][self::PATH]['content'];

        $run = $this->persist([self::PATH => ['content' => $content, 'mode' => 0644]]);

        self::assertSame("changed\n", $run['stdout']);
        self::assertSame(['open', self::STAGED, 0600], $run['log'][0]);
        self::assertSame(0600, $run['files'][self::PATH]['mode']);
        self::assertSame($content, $run['files'][self::PATH]['content']);
    }

    public function testAPrivateFileWithTheSameValuesIsLeftAlone(): void
    {
        $content = $this->persist([])['files'][self::PATH]['content'];

        $run = $this->persist([self::PATH => ['content' => $content, 'mode' => 0600]]);

        self::assertSame("unchanged\n", $run['stdout']);
        self::assertSame([], $run['log']);
    }
}
