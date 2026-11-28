<?php

declare(strict_types=1);

use PHPUnit\Framework\TestCase;

final class LoginMethodsTest extends TestCase
{
    private const FRAMEWORK = <<<'PHP'
        <?php
        namespace Joomla\Database {
            interface DatabaseInterface
            {
            }

            final class ParameterType
            {
                public const INTEGER = 'int';
                public const STRING = 'string';
            }
        }

        namespace Joomla\CMS {
            final class Factory
            {
                public static function getContainer(): object
                {
                    return new class {
                        public function get(string $id): object
                        {
                            return new \StubDatabase();
                        }
                    };
                }
            }
        }

        namespace {
            final class StubQuery
            {
                public array $where = [];
                public array $set = [];
                public array $binds = [];

                public function select($columns): self
                {
                    return $this;
                }

                public function from(string $table): self
                {
                    return $this;
                }

                public function update(string $table): self
                {
                    return $this;
                }

                public function where(string $condition): self
                {
                    $this->where[] = $condition;
                    return $this;
                }

                public function set(string $assignment): self
                {
                    $this->set[] = $assignment;
                    return $this;
                }

                public function bind(string $name, $value, string $type): self
                {
                    $this->binds[$name] = $value;
                    return $this;
                }
            }

            final class StubDatabase
            {
                private StubQuery $query;

                public function getQuery(bool $new = false): StubQuery
                {
                    return new StubQuery();
                }

                public function quoteName($name)
                {
                    return $name;
                }

                public function quote(string $value): string
                {
                    return "'" . $value . "'";
                }

                public function setQuery(StubQuery $query): self
                {
                    $this->query = $query;
                    return $this;
                }

                public function loadObject(): ?object
                {
                    $rows = array_values($this->matching());
                    return $rows === [] ? null : (object) $rows[0];
                }

                public function loadResult(): int
                {
                    return count($this->matching());
                }

                public function execute(): bool
                {
                    $rows = $this->rows();
                    foreach (array_keys($this->matching()) as $index) {
                        foreach ($this->query->set as $assignment) {
                            [$column, $placeholder] = explode(' = ', $assignment, 2);
                            $rows[$index][$column] = $this->query->binds[$placeholder];
                        }
                    }
                    file_put_contents((string) getenv('STUB_STATE'), json_encode($rows));
                    return true;
                }

                private function rows(): array
                {
                    return json_decode((string) file_get_contents((string) getenv('STUB_STATE')), true);
                }

                private function matching(): array
                {
                    return array_filter($this->rows(), function (array $row): bool {
                        foreach ($this->query->where as $condition) {
                            if (preg_match('/^(\w+) = (.+)$/', $condition, $match) !== 1) {
                                throw new \RuntimeException("unparsed condition: {$condition}");
                            }
                            $value = trim($match[2], "'");
                            if ((string) $row[$match[1]] !== (string) ($this->query->binds[$value] ?? $value)) {
                                return false;
                            }
                        }
                        return true;
                    });
                }
            }
        }
        PHP;

    private const BOTH_METHODS_ON = ['multifactorauth/totp' => 1, 'multifactorauth/webauthn' => 1];

    private const BOTH_METHODS_OFF = ['multifactorauth/totp' => 0, 'multifactorauth/webauthn' => 0];

    private string $root;

    private string $state;

    protected function setUp(): void
    {
        $this->root = (string) tempnam(sys_get_temp_dir(), 'jroot');
        unlink($this->root);
        mkdir($this->root . '/includes', 0700, true);
        file_put_contents($this->root . '/includes/defines.php', "<?php\n");
        file_put_contents($this->root . '/includes/framework.php', self::FRAMEWORK);
        $this->state = (string) tempnam(sys_get_temp_dir(), 'jdb');
    }

    protected function tearDown(): void
    {
        unlink($this->root . '/includes/defines.php');
        unlink($this->root . '/includes/framework.php');
        rmdir($this->root . '/includes');
        rmdir($this->root);
        unlink($this->state);
    }

    /**
     * @param list<string> $forced forceMFAUserGroups com_users holds before the run
     */
    private function seed(array $forced): void
    {
        $params = ['allowUserRegistration' => '0', 'forceMFAUserGroups' => $forced];
        file_put_contents($this->state, (string) json_encode([
            ['extension_id' => 1, 'type' => 'plugin', 'folder' => 'multifactorauth', 'element' => 'totp', 'enabled' => 1, 'params' => '{}'],
            ['extension_id' => 2, 'type' => 'plugin', 'folder' => 'multifactorauth', 'element' => 'webauthn', 'enabled' => 1, 'params' => '{}'],
            ['extension_id' => 3, 'type' => 'component', 'folder' => '', 'element' => 'com_users', 'enabled' => 1, 'params' => (string) json_encode($params)],
        ]));
    }

    /**
     * @param array<string, int> $plugins J_LOGIN_PLUGINS
     * @param string $secondFactor        J_LOGIN_2FA
     * @param string $enforced            J_LOGIN_2FA_ENFORCED
     * @return array{0: string, 1: string, 2: int}
     *         stdout, stderr and exit code
     */
    private function runScript(array $plugins, string $secondFactor, string $enforced): array
    {
        $script = dirname(__DIR__, 6) . '/roles/web-app-joomla/files/php/login_methods.php';
        $process = proc_open(
            [PHP_BINARY, $script],
            [1 => ['pipe', 'w'], 2 => ['pipe', 'w']],
            $pipes,
            null,
            [
                'J_ROOT' => $this->root,
                'J_LOGIN_PLUGINS' => (string) json_encode($plugins),
                'J_LOGIN_REGISTRATION' => '0',
                'J_LOGIN_2FA' => $secondFactor,
                'J_LOGIN_2FA_ENFORCED' => $enforced,
                'J_LOGIN_2FA_ROOT_GROUP' => '8',
                'STUB_STATE' => $this->state,
                'PATH' => (string) getenv('PATH'),
            ]
        );
        $stdout = (string) stream_get_contents($pipes[1]);
        fclose($pipes[1]);
        $stderr = (string) stream_get_contents($pipes[2]);
        fclose($pipes[2]);
        $code = proc_close($process);

        return [$stdout, $stderr, $code];
    }

    /**
     * @return list<string> forceMFAUserGroups com_users holds after the run
     */
    private function forcedGroups(): array
    {
        foreach (json_decode((string) file_get_contents($this->state), true) as $row) {
            if ($row['element'] === 'com_users') {
                return json_decode($row['params'], true)['forceMFAUserGroups'];
            }
        }
        $this->fail('com_users left the extensions table');
    }

    public function testAnEnforcedSecondFactorForcesTheRootGroup(): void
    {
        $this->seed([]);

        [$stdout, $stderr, $code] = $this->runScript(self::BOTH_METHODS_ON, '1', '1');

        $this->assertSame(0, $code, $stderr);
        $this->assertSame('changed', $stdout);
        $this->assertSame(['8'], $this->forcedGroups());
    }

    public function testAnOfferedSecondFactorForcesNoGroup(): void
    {
        $this->seed(['8']);

        [$stdout, $stderr, $code] = $this->runScript(self::BOTH_METHODS_ON, '1', '0');

        $this->assertSame(0, $code, $stderr);
        $this->assertSame('changed', $stdout);
        $this->assertSame([], $this->forcedGroups());
    }

    public function testAConvergedListIsLeftAlone(): void
    {
        $this->seed(['8']);

        [$stdout, $stderr, $code] = $this->runScript(self::BOTH_METHODS_ON, '1', '1');

        $this->assertSame(0, $code, $stderr);
        $this->assertSame('ok', $stdout);
        $this->assertSame(['8'], $this->forcedGroups());
    }

    public function testWithoutTheOwnSecondFactorTheListIsKeptWhileAMethodIsLeft(): void
    {
        $this->seed(['8']);

        [$stdout, $stderr, $code] = $this->runScript(['multifactorauth/totp' => 0], '0', '0');

        $this->assertSame(0, $code, $stderr);
        $this->assertSame('changed', $stdout);
        $this->assertSame(['8'], $this->forcedGroups());
    }

    public function testWithoutTheOwnSecondFactorTheListIsClearedOnceNoMethodIsLeft(): void
    {
        $this->seed(['8']);

        [$stdout, $stderr, $code] = $this->runScript(self::BOTH_METHODS_OFF, '0', '0');

        $this->assertSame(0, $code, $stderr);
        $this->assertSame('changed', $stdout);
        $this->assertSame([], $this->forcedGroups());
    }
}
