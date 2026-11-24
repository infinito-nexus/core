<?php

declare(strict_types=1);

use PHPUnit\Framework\TestCase;

final class ShowcaseTest extends TestCase
{
    private const DAL = '/roles/web-app-shopware/files/php/dal.php';

    private const SCRIPT = '/roles/web-app-shopware/files/php/design/showcase.php';

    private const FINGERPRINT = 'infinito_showcase_fingerprint';

    private const KERNEL_SECRET = 'kernel-secret';

    private const STUB = <<<'PHP'
        <?php
        function container(): object
        {
            return new class () {
                public function getParameter(string $name): string
                {
                    return $name === 'kernel.secret' ? (string) getenv('STUB_KERNEL_SECRET') : '';
                }
            };
        }

        function dal(string $operation, string $entity, array $argument): array
        {
            $GLOBALS['STUB']['calls'][] = [$operation, $entity, $argument];

            return $operation === 'search' ? (array_shift($GLOBALS['STUB']['responses']) ?? []) : [];
        }

        $GLOBALS['STUB'] = [
            'calls' => [],
            'responses' => json_decode((string) getenv('STUB_RESPONSES'), true),
        ];
        register_shutdown_function(static function (): void {
            file_put_contents((string) getenv('STUB_LOG'), json_encode($GLOBALS['STUB']['calls']));
        });
        PHP;

    /**
     * @return array<string, string> the environment the seed task hands the script
     */
    private static function environment(): array
    {
        return [
            'SHOWCASE' => (string) json_encode([
                'manufacturer' => 'd0000000000000000000000000000001',
                'customer' => 'd0000000000000000000000000000002',
                'address' => 'd0000000000000000000000000000003',
                'customerEmail' => 'design-showcase@shop.example',
                'products' => [
                    ['id' => 'd0000000000000000000000000000011', 'number' => 'DESIGN-1', 'name' => 'Design showcase lamp', 'gross' => 119],
                    ['id' => 'd0000000000000000000000000000012', 'number' => 'DESIGN-2', 'name' => 'Design showcase chair', 'gross' => 238],
                ],
            ]),
            'SHOWCASE_DOMAIN' => 'shop.example',
            'STUB_KERNEL_SECRET' => self::KERNEL_SECRET,
        ];
    }

    /**
     * @param string $secret the kernel secret
     * @return string the password the script derives from it
     */
    private static function password(string $secret): string
    {
        return hash_hmac('sha256', 'web-app-shopware:showcase-customer', $secret);
    }

    /**
     * @param array<string, list<array<string, mixed>>> $stored the stored row per product and customer id
     * @return list<list<array<string, mixed>>> the rows each successive DAL search returns
     */
    private static function responses(array $stored): array
    {
        $ids = ['d0000000000000000000000000000011', 'd0000000000000000000000000000012', 'd0000000000000000000000000000002'];

        return array_merge(
            [
                [['url' => 'https://other.example', 'salesChannelId' => 'headless'], ['url' => 'https://shop.example', 'salesChannelId' => 'storefront']],
                [[
                    'id' => 'storefront',
                    'currencyId' => 'eur',
                    'navigationCategoryId' => 'root',
                    'customerGroupId' => 'group',
                    'languageId' => 'language',
                    'countryId' => 'country',
                ]],
                [['id' => 'reduced', 'taxRate' => 7, 'position' => 2], ['id' => 'standard', 'taxRate' => 19, 'position' => 1]],
                [['id' => 'salutation']],
                [['id' => 'theme', 'configValues' => ['sw-color-brand-primary' => ['value' => '#123456']]]],
            ],
            array_map(static fn (string $id): array => $stored[$id] ?? [], $ids)
        );
    }

    /**
     * @param array<string, string> $environment the script's environment
     * @param list<list<array<string, mixed>>> $responses the rows each successive DAL search returns
     * @return array{0: string, 1: string, 2: int, 3: list<array{0: string, 1: string, 2: array<string, mixed>}>}
     *         stdout, stderr, exit code and the recorded DAL calls
     */
    private function runScript(array $environment, array $responses): array
    {
        $root = sys_get_temp_dir() . '/shopware-showcase-' . bin2hex(random_bytes(8));
        mkdir($root);
        file_put_contents("$root/stub.php", self::STUB);

        $head = rtrim((string) file_get_contents(dirname(__DIR__, 7) . self::DAL));
        foreach (['dal', 'container'] as $function) {
            $head = str_replace("function {$function}(", "function unused_{$function}(", $head, $replaced);
            $this->assertSame(1, $replaced, "dal.php MUST reach Shopware through exactly one {$function}() function");
        }
        $source = $head . "\n" . (string) file_get_contents(dirname(__DIR__, 7) . self::SCRIPT);

        $process = proc_open(
            [PHP_BINARY, '-d', "auto_prepend_file=$root/stub.php"],
            [0 => ['pipe', 'r'], 1 => ['pipe', 'w'], 2 => ['pipe', 'w']],
            $pipes,
            null,
            $environment + [
                'STUB_RESPONSES' => json_encode($responses),
                'STUB_LOG' => "$root/log.json",
                'PATH' => (string) getenv('PATH'),
            ]
        );
        fwrite($pipes[0], $source);
        fclose($pipes[0]);
        $stdout = (string) stream_get_contents($pipes[1]);
        $stderr = (string) stream_get_contents($pipes[2]);
        fclose($pipes[1]);
        fclose($pipes[2]);
        $code = proc_close($process);

        $calls = json_decode((string) file_get_contents("$root/log.json"), true);
        unlink("$root/log.json");
        unlink("$root/stub.php");
        rmdir($root);

        return [$stdout, $stderr, $code, $calls];
    }

    /**
     * @param list<array{0: string, 1: string, 2: array<string, mixed>}> $calls the recorded DAL calls
     * @return array<string, array<string, mixed>> the written payload per "<operation> <entity> <id>"
     */
    private static function upserts(array $calls): array
    {
        $upserts = [];
        foreach ($calls as [$operation, $entity, $argument]) {
            if ($operation !== 'search') {
                $upserts["{$operation} {$entity} {$argument['id']}"] = $argument;
            }
        }

        return $upserts;
    }

    /**
     * @param array<string, array<string, mixed>> $upserts the upserted payload per "upsert <entity> <id>"
     * @return array<string, list<array<string, mixed>>> each row as the DAL search returns it after the upsert
     */
    private static function stored(array $upserts): array
    {
        $stored = [];
        foreach ($upserts as $payload) {
            $stored[$payload['id']] = [['id' => $payload['id'], 'customFields' => $payload['customFields']]];
        }

        return $stored;
    }

    /**
     * @param string $stdout the script's output
     * @return array<string, mixed> its closing JSON line
     */
    private static function result(string $stdout): array
    {
        $lines = explode("\n", trim($stdout));

        return json_decode((string) end($lines), true, 512, JSON_THROW_ON_ERROR);
    }

    public function testTheFirstRunSeedsEveryProductAndTheCustomerAndReportsTheSeededIds(): void
    {
        [$stdout, $stderr, $code, $calls] = $this->runScript(self::environment(), self::responses([]));

        $this->assertSame(0, $code, $stderr);
        $upserts = self::upserts($calls);
        $this->assertSame(
            [
                'upsert product d0000000000000000000000000000011',
                'upsert product d0000000000000000000000000000012',
                'upsert customer d0000000000000000000000000000002',
            ],
            array_keys($upserts)
        );
        $lamp = $upserts['upsert product d0000000000000000000000000000011'];
        $this->assertSame('standard', $lamp['taxId']);
        $this->assertSame([['currencyId' => 'eur', 'gross' => 119, 'net' => 100.0, 'linked' => true]], $lamp['price']);
        $this->assertSame([['id' => 'd0000000000000000000000000000011', 'salesChannelId' => 'storefront', 'visibility' => 30]], $lamp['visibilities']);
        $customer = $upserts['upsert customer d0000000000000000000000000000002'];
        $password = self::password(self::KERNEL_SECRET);
        $this->assertSame($password, $customer['password']);
        $this->assertSame('storefront', $customer['salesChannelId']);
        $this->assertSame(
            [
                'changed' => true,
                'channelId' => 'storefront',
                'themeId' => 'theme',
                'themeConfig' => ['sw-color-brand-primary' => '#123456'],
                'customerPassword' => $password,
            ],
            self::result($stdout)
        );
        $this->assertStringNotContainsString(self::KERNEL_SECRET, $stdout . $stderr);
        $this->assertStringNotContainsString($password, json_encode($customer['customFields']) . $stderr);
    }

    public function testNegativeControlASecondRunOverTheSeededRowsWritesNothing(): void
    {
        [, , , $first] = $this->runScript(self::environment(), self::responses([]));

        [$stdout, $stderr, $code, $calls] = $this->runScript(self::environment(), self::responses(self::stored(self::upserts($first))));

        $this->assertSame(0, $code, $stderr);
        $this->assertSame([], self::upserts($calls));
        $this->assertFalse(self::result($stdout)['changed']);
    }

    public function testADriftedProductOrARotatedKernelSecretRewritesOnlyThatRow(): void
    {
        [, , , $first] = $this->runScript(self::environment(), self::responses([]));
        $stored = self::stored(self::upserts($first));
        $stored['d0000000000000000000000000000012'][0]['customFields'][self::FINGERPRINT] = 'stale';
        $environment = ['STUB_KERNEL_SECRET' => 'rotated-kernel-secret'] + self::environment();

        [$stdout, $stderr, $code, $calls] = $this->runScript($environment, self::responses($stored));

        $this->assertSame(0, $code, $stderr);
        $upserts = self::upserts($calls);
        $this->assertSame(
            ['upsert product d0000000000000000000000000000012', 'upsert customer d0000000000000000000000000000002'],
            array_keys($upserts)
        );
        $this->assertSame(self::password('rotated-kernel-secret'), $upserts['upsert customer d0000000000000000000000000000002']['password']);
        $this->assertTrue(self::result($stdout)['changed']);
    }

    public function testNegativeControlADomainNoSalesChannelServesFailsBeforeAnyWrite(): void
    {
        $environment = ['SHOWCASE_DOMAIN' => 'unserved.example'] + self::environment();

        [, $stderr, $code, $calls] = $this->runScript($environment, self::responses([]));

        $this->assertSame(1, $code);
        $this->assertStringContainsString('no storefront sales channel serves unserved.example', $stderr);
        $this->assertSame([['search', 'sales_channel_domain', []]], $calls);
    }

    public function testTheScriptRefusesAnEmptyKernelSecretOnItsOwnWithoutRelyingOnSymfonysCheck(): void
    {
        [, $stderr, $code, $calls] = $this->runScript(['STUB_KERNEL_SECRET' => ''] + self::environment(), self::responses([]));

        $this->assertSame(1, $code);
        $this->assertStringContainsString('kernel.secret is empty', $stderr);
        $this->assertSame([], $calls);
    }

    public function testTheScriptHoldsNoApiCredentialAndNoHttpClient(): void
    {
        $source = (string) file_get_contents(dirname(__DIR__, 7) . self::SCRIPT);

        foreach (['INTEGRATION_', 'oauth/token', 'grant_type', 'curl_', 'ADMIN_PASSWORD', '_action/sync'] as $needle) {
            $this->assertStringNotContainsString($needle, $source, $needle);
        }
    }
}
