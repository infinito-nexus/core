<?php

declare(strict_types=1);

use PHPUnit\Framework\TestCase;

final class ObserverTest extends TestCase
{
    private const MOODLE = <<<'PHP'
        <?php
        namespace core\event {
            final class user_loggedin
            {
                public function __construct(public int $objectid)
                {
                }
            }
        }

        namespace {
            function get_config($plugin, $name = null)
            {
                return [$plugin, $name] === ['local_mfaenforce', 'enabled'] ? getenv('STUB_ENABLED') : false;
            }

            function getremoteaddr()
            {
                return '192.0.2.7';
            }

            final class stub_database
            {
                public function record_exists($table, array $conditions)
                {
                    return $this->matching($table, $conditions) !== [];
                }

                public function set_field($table, $field, $value, array $conditions)
                {
                    $rows = $this->rows();
                    foreach (array_keys($this->matching($table, $conditions)) as $index) {
                        $rows[$index][$field] = $value;
                    }
                    $this->store($rows);
                    return true;
                }

                public function insert_record($table, $record, $returnid = true)
                {
                    $rows = $this->rows();
                    $rows[] = ['table' => $table] + (array) $record;
                    $this->store($rows);
                    return count($rows);
                }

                private function matching($table, array $conditions)
                {
                    return array_filter($this->rows(), static function (array $row) use ($table, $conditions) {
                        if ($row['table'] !== $table) {
                            return false;
                        }
                        foreach ($conditions as $field => $value) {
                            if (($row[$field] ?? null) != $value) {
                                return false;
                            }
                        }
                        return true;
                    });
                }

                private function rows()
                {
                    return json_decode((string) file_get_contents(getenv('STUB_STATE')), true);
                }

                private function store(array $rows)
                {
                    file_put_contents(getenv('STUB_STATE'), json_encode($rows));
                }
            }

            $DB = new stub_database();
            require getenv('OBSERVER');
            \local_mfaenforce\observer::user_loggedin(new \core\event\user_loggedin((int) getenv('STUB_USER')));
        }
        PHP;

    private const SIGNED_IN = 5;

    private const ADMINISTRATOR = 2;

    private const RECENT_START = 1762900000;

    private string $runner;

    private string $state;

    protected function setUp(): void
    {
        $this->runner = (string) tempnam(sys_get_temp_dir(), 'mdlobs');
        $this->state = (string) tempnam(sys_get_temp_dir(), 'mdlmfa');
        file_put_contents($this->runner, self::MOODLE);
    }

    protected function tearDown(): void
    {
        unlink($this->runner);
        unlink($this->state);
    }

    /**
     * @param int $userid  account the tool_mfa row belongs to
     * @param string $factor factor the row records
     * @param int $start   the row's timecreated
     *
     * @return array<string, int|string>
     */
    private static function row(int $userid, string $factor, int $start): array
    {
        return [
            'table' => 'tool_mfa',
            'userid' => $userid,
            'factor' => $factor,
            'createdfromip' => '198.51.100.4',
            'timecreated' => $start,
            'revoked' => 0,
        ];
    }

    /**
     * @param list<array<string, int|string>> $rows    tool_mfa rows before the sign-in
     * @param string                          $enabled stored local_mfaenforce/enabled
     * @param int                             $userid  account that signs in
     *
     * @return array{0: int, 1: string, 2: list<array<string, int|string>>}
     *         exit code, stderr and the tool_mfa rows after the sign-in
     */
    private function signIn(array $rows, string $enabled, int $userid = self::SIGNED_IN): array
    {
        file_put_contents($this->state, json_encode($rows));
        $observer = dirname(__DIR__, 10) . '/roles/web-app-moodle/files/build/local/mfaenforce/classes/observer.php';
        $process = proc_open(
            [PHP_BINARY, $this->runner],
            [1 => ['pipe', 'w'], 2 => ['pipe', 'w']],
            $pipes,
            null,
            [
                'OBSERVER' => $observer,
                'STUB_STATE' => $this->state,
                'STUB_ENABLED' => $enabled,
                'STUB_USER' => (string) $userid,
                'PATH' => (string) getenv('PATH'),
            ]
        );
        stream_get_contents($pipes[1]);
        fclose($pipes[1]);
        $stderr = (string) stream_get_contents($pipes[2]);
        fclose($pipes[2]);
        $code = proc_close($process);

        return [$code, $stderr, json_decode((string) file_get_contents($this->state), true)];
    }

    public function testAFreshAccountGetsAGraceRowThatHasAlreadyExpired(): void
    {
        [$code, $stderr, $rows] = $this->signIn([], '1');

        $this->assertSame(0, $code, $stderr);
        $this->assertSame(
            [[
                'table' => 'tool_mfa',
                'userid' => self::SIGNED_IN,
                'factor' => 'grace',
                'createdfromip' => '192.0.2.7',
                'timecreated' => 1,
                'revoked' => 0,
            ]],
            $rows
        );
    }

    public function testAnExistingAccountsGracePeriodStartsOverAsExpired(): void
    {
        [$code, $stderr, $rows] = $this->signIn([self::row(self::SIGNED_IN, 'grace', self::RECENT_START)], '1');

        $this->assertSame(0, $code, $stderr);
        $this->assertSame([self::row(self::SIGNED_IN, 'grace', 1)], $rows);
    }

    public function testTheAdministratorIsBackdatedLikeEveryOtherAccount(): void
    {
        [$code, $stderr, $rows] = $this->signIn(
            [self::row(self::ADMINISTRATOR, 'grace', self::RECENT_START)],
            '1',
            self::ADMINISTRATOR
        );

        $this->assertSame(0, $code, $stderr);
        $this->assertSame([self::row(self::ADMINISTRATOR, 'grace', 1)], $rows);
    }

    public function testNothingIsWrittenWhileEnforcementIsOff(): void
    {
        $before = [self::row(self::ADMINISTRATOR, 'grace', self::RECENT_START)];

        [$freshCode, $freshStderr, $fresh] = $this->signIn($before, '0');
        [$existingCode, $existingStderr, $existing] = $this->signIn($before, '0', self::ADMINISTRATOR);

        $this->assertSame(0, $freshCode, $freshStderr);
        $this->assertSame(0, $existingCode, $existingStderr);
        $this->assertSame($before, $fresh);
        $this->assertSame($before, $existing);
    }

    public function testOtherFactorsAndOtherAccountsKeepTheirRows(): void
    {
        $totp = self::row(self::SIGNED_IN, 'totp', self::RECENT_START);
        $otherGrace = self::row(self::ADMINISTRATOR, 'grace', self::RECENT_START);

        [$code, $stderr, $rows] = $this->signIn([$totp, $otherGrace], '1');

        $this->assertSame(0, $code, $stderr);
        $this->assertSame([$totp, $otherGrace], array_slice($rows, 0, 2));
        $this->assertSame(['grace', 1], [$rows[2]['factor'], $rows[2]['timecreated']]);
    }
}
