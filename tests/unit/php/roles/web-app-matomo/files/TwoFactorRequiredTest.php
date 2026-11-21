<?php

declare(strict_types=1);

use Infinito\Matomo\TwoFactor\Settings;
use PHPUnit\Framework\TestCase;

use function Infinito\Matomo\TwoFactor\converge;

require_once dirname(__DIR__, 6) . '/roles/web-app-matomo/files/php/two_factor_required.php';

final class MatomoFakeTwoFactorSettings implements Settings
{
    public int $writes = 0;

    public function __construct(public bool $isRequired, public bool $isOwned)
    {
    }

    public function required(): bool
    {
        return $this->isRequired;
    }

    public function setRequired(bool $required): void
    {
        $this->writes++;
        $this->isRequired = $required;
    }

    public function owned(): bool
    {
        return $this->isOwned;
    }

    public function setOwned(bool $owned): void
    {
        $this->writes++;
        $this->isOwned = $owned;
    }
}

final class TwoFactorRequiredTest extends TestCase
{
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
        fwrite($pipes[0], (string) file_get_contents(dirname(__DIR__, 6) . '/roles/web-app-matomo/files/php/two_factor_required.php'));
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
        self::assertStringContainsString("[FAIL] MATOMO_CONFIG is empty\n", $stderr);
    }

    public function testEnforcingRequiresTheSecondFactorAndMarksItAsTheDeploys(): void
    {
        $settings = new MatomoFakeTwoFactorSettings(false, false);

        [$code, $line] = converge($settings, 'enforced');

        self::assertSame(0, $code);
        self::assertStringStartsWith('[CHANGED]', $line);
        self::assertTrue($settings->isRequired);
        self::assertTrue($settings->isOwned);
    }

    public function testASecondEnforcingRunChangesNothing(): void
    {
        $settings = new MatomoFakeTwoFactorSettings(false, false);
        converge($settings, 'enforced');
        $settings->writes = 0;

        [$code, $line] = converge($settings, 'enforced');

        self::assertSame(0, $code);
        self::assertStringStartsWith('[UNCHANGED]', $line);
        self::assertSame(0, $settings->writes);
    }

    public function testEnforcingOverAnAdminsRequirementLeavesItUnmarked(): void
    {
        $settings = new MatomoFakeTwoFactorSettings(true, false);

        [, $line] = converge($settings, 'enforced');

        self::assertStringStartsWith('[UNCHANGED]', $line);
        self::assertFalse($settings->isOwned);
        self::assertSame(0, $settings->writes);
    }

    public function testOfferingLiftsTheRequirementTheDeploySet(): void
    {
        $settings = new MatomoFakeTwoFactorSettings(false, false);
        converge($settings, 'enforced');

        [$code, $line] = converge($settings, 'offered');

        self::assertSame(0, $code);
        self::assertStringStartsWith('[CHANGED]', $line);
        self::assertFalse($settings->isRequired);
        self::assertFalse($settings->isOwned);
    }

    public function testOfferingKeepsARequirementAnAdminSet(): void
    {
        $settings = new MatomoFakeTwoFactorSettings(true, false);

        [, $line] = converge($settings, 'offered');

        self::assertStringStartsWith('[UNCHANGED]', $line);
        self::assertTrue($settings->isRequired);
        self::assertSame(0, $settings->writes);
    }

    public function testTurningTheSecondFactorOffLiftsAnyRequirement(): void
    {
        $settings = new MatomoFakeTwoFactorSettings(true, false);

        [$code, $line] = converge($settings, 'off');

        self::assertSame(0, $code);
        self::assertStringStartsWith('[CHANGED]', $line);
        self::assertFalse($settings->isRequired);
    }

    public function testAMarkerWithoutItsRequirementIsReleased(): void
    {
        foreach (['offered', 'off'] as $mode) {
            $settings = new MatomoFakeTwoFactorSettings(false, true);

            [, $line] = converge($settings, $mode);

            self::assertStringStartsWith('[CHANGED]', $line, $mode);
            self::assertFalse($settings->isOwned, $mode);
        }
    }

    public function testAnUnknownModeFailsBeforeAnyWrite(): void
    {
        $settings = new MatomoFakeTwoFactorSettings(true, true);

        [$code, $line] = converge($settings, 'required');

        self::assertSame(1, $code);
        self::assertStringStartsWith('[FAIL]', $line);
        self::assertSame(0, $settings->writes);
    }
}
