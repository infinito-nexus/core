<?php

declare(strict_types=1);

use PHPUnit\Framework\TestCase;

final class AiGatewayTest extends TestCase
{
    private const NAME = 'LiteLLM gateway';

    private const CHAT = 'http://litellm:4000/v1/chat/completions';

    private const IMAGE = 'http://litellm:4000/v1/images/generations';

    private const MODEL = 'gateway-chat';

    private const OPENAI = 'aiprovider_openai\\provider';

    private const TEXT_ACTIONS = [
        'core_ai\\aiactions\\generate_text',
        'core_ai\\aiactions\\summarise_text',
        'core_ai\\aiactions\\explain_text',
    ];

    private const IMAGE_ACTION = 'core_ai\\aiactions\\generate_image';

    private const MOODLE = <<<'PHP'
        <?php
        namespace core_ai\aiactions {
            class generate_text {}
            class summarise_text {}
            class explain_text {}
            class generate_image {}
        }

        namespace core_ai {
            abstract class provider {
                public function __construct(
                    public bool $enabled,
                    public string $name,
                    public array $config,
                    public array $actionconfig,
                    public ?int $id = null,
                ) {
                }

                public function with(...$values): static {
                    $copy = clone $this;
                    foreach ($values as $property => $value) {
                        $copy->$property = $value;
                    }
                    return $copy;
                }
            }

            class manager {
                private function rows(): array {
                    $file = getenv('STUB_STATE');
                    return is_file($file) ? json_decode(file_get_contents($file), true) : [];
                }

                private function store(provider $provider): provider {
                    $rows = $this->rows();
                    $rows[$provider->id] = [
                        'id' => $provider->id,
                        'provider' => get_class($provider),
                        'name' => $provider->name,
                        'enabled' => $provider->enabled,
                        'config' => $provider->config,
                        'actionconfig' => $provider->actionconfig,
                    ];
                    file_put_contents(getenv('STUB_STATE'), json_encode($rows));
                    return $provider;
                }

                public function get_provider_instances(?array $filter = null): array {
                    $found = [];
                    foreach ($this->rows() as $row) {
                        foreach ($filter ?? [] as $column => $value) {
                            if ($row[$column] != $value) {
                                continue 2;
                            }
                        }
                        $found[$row['id']] = new $row['provider'](
                            enabled: $row['enabled'],
                            name: $row['name'],
                            config: $row['config'],
                            actionconfig: $row['actionconfig'],
                            id: $row['id'],
                        );
                    }
                    return $found;
                }

                public function create_provider_instance(
                    string $classname,
                    string $name,
                    bool $enabled = false,
                    ?array $config = null,
                    ?array $actionconfig = null,
                ): provider {
                    return $this->store(new $classname(
                        enabled: $enabled,
                        name: $name,
                        config: $config ?? [],
                        actionconfig: $actionconfig ?? $classname::initialise_action_settings(),
                        id: count($this->rows()) + 1,
                    ));
                }

                public function update_provider_instance(
                    provider $provider,
                    ?array $config = null,
                    ?array $actionconfig = null,
                ): provider {
                    return $this->store($provider->with(
                        config: $config ?? $provider->config,
                        actionconfig: $actionconfig ?? $provider->actionconfig,
                    ));
                }

                public function enable_provider_instance(provider $provider): provider {
                    return $provider->enabled ? $provider : $this->store($provider->with(enabled: true));
                }
            }
        }

        namespace aiprovider_openai {
            class provider extends \core_ai\provider {
                public static function initialise_action_settings(): array {
                    $text = [
                        'enabled' => true,
                        'settings' => [
                            'endpoint' => 'https://api.openai.com/v1/chat/completions',
                            'model' => 'gpt-4o',
                            'systeminstruction' => 'upstream default',
                        ],
                    ];
                    return [
                        \core_ai\aiactions\generate_text::class => $text,
                        \core_ai\aiactions\generate_image::class => [
                            'enabled' => true,
                            'settings' => [
                                'endpoint' => 'https://api.openai.com/v1/images/generations',
                                'model' => 'dall-e-3',
                            ],
                        ],
                        \core_ai\aiactions\summarise_text::class => $text,
                        \core_ai\aiactions\explain_text::class => $text,
                    ];
                }
            }
        }

        namespace core {
            class di {
                public static function get(string $class): object {
                    return new $class();
                }
            }
        }
        PHP;

    private string $config;

    private string $state;

    protected function setUp(): void
    {
        $this->config = (string) tempnam(sys_get_temp_dir(), 'mdlcfg');
        $this->state = (string) tempnam(sys_get_temp_dir(), 'mdlai');
        file_put_contents($this->config, self::MOODLE);
        unlink($this->state);
    }

    protected function tearDown(): void
    {
        unlink($this->config);
        if (is_file($this->state)) {
            unlink($this->state);
        }
    }

    /**
     * Store provider instances the way an earlier run or an administrator left them.
     *
     * @param list<array<string, mixed>> $rows instances, each with its id
     */
    private function seed(array $rows): void
    {
        file_put_contents($this->state, json_encode(array_column($rows, null, 'id')));
    }

    /**
     * Run the script against the stubbed Moodle.
     *
     * @return array{0: array<string, mixed>, 1: int, 2: array<int, array<string, mixed>>}
     *         decoded last output line, exit code and the stored instances by id
     */
    private function runScript(): array
    {
        $script = dirname(__DIR__, 7) . '/roles/web-app-moodle/files/php/provision/ai_gateway.php';
        $process = proc_open(
            [PHP_BINARY, $script],
            [1 => ['pipe', 'w'], 2 => ['pipe', 'w']],
            $pipes,
            null,
            [
                'MOODLE_CONFIG' => $this->config,
                'STUB_STATE' => $this->state,
                'AI_PROVIDER_NAME' => self::NAME,
                'AI_API_KEY' => 'sk-gateway',
                'AI_CHAT_ENDPOINT' => self::CHAT,
                'AI_CHAT_MODEL' => self::MODEL,
                'AI_IMAGE_ENDPOINT' => self::IMAGE,
                'PATH' => (string) getenv('PATH'),
            ]
        );
        $stdout = trim((string) stream_get_contents($pipes[1]));
        fclose($pipes[1]);
        fclose($pipes[2]);
        $code = proc_close($process);

        $lines = explode("\n", $stdout);
        $stored = is_file($this->state)
            ? json_decode((string) file_get_contents($this->state), true)
            : [];

        return [(array) json_decode((string) end($lines), true), $code, $stored];
    }

    public function testAFreshMoodleGetsOneEnabledInstanceWithTheGatewayKey(): void
    {
        [, $code, $stored] = $this->runScript();

        $this->assertSame(0, $code);
        $this->assertCount(1, $stored);
        $instance = reset($stored);
        $this->assertSame(self::OPENAI, $instance['provider']);
        $this->assertSame(self::NAME, $instance['name']);
        $this->assertTrue($instance['enabled']);
        $this->assertSame('sk-gateway', $instance['config']['apikey']);
    }

    public function testEveryTextActionIsEnabledAndAnswersThroughTheGateway(): void
    {
        [, , $stored] = $this->runScript();

        $actions = reset($stored)['actionconfig'];
        foreach (self::TEXT_ACTIONS as $action) {
            $this->assertTrue($actions[$action]['enabled'], $action);
            $this->assertSame(self::CHAT, $actions[$action]['settings']['endpoint'], $action);
            $this->assertSame(self::MODEL, $actions[$action]['settings']['model'], $action);
            $this->assertSame(
                'upstream default',
                $actions[$action]['settings']['systeminstruction'],
                $action
            );
        }
    }

    public function testImageGenerationIsSwitchedOffAndStillPointsAtTheGateway(): void
    {
        [, , $stored] = $this->runScript();

        $image = reset($stored)['actionconfig'][self::IMAGE_ACTION];
        $this->assertFalse($image['enabled']);
        $this->assertSame(self::IMAGE, $image['settings']['endpoint']);
    }

    public function testTheOutputNamesTheInstanceAndTheStoredEndpointOfEveryAction(): void
    {
        [$output, , $stored] = $this->runScript();

        $this->assertSame(array_key_first($stored), $output['id']);
        $this->assertSame(
            [
                self::TEXT_ACTIONS[0] => self::CHAT,
                self::IMAGE_ACTION => self::IMAGE,
                self::TEXT_ACTIONS[1] => self::CHAT,
                self::TEXT_ACTIONS[2] => self::CHAT,
            ],
            $output['endpoints']
        );
    }

    public function testAnInstanceOfThatNameIsReusedAndKeepsWhatTheScriptDoesNotSet(): void
    {
        $this->seed([[
            'id' => 7,
            'provider' => self::OPENAI,
            'name' => self::NAME,
            'enabled' => false,
            'config' => ['apikey' => 'sk-stale', 'orgid' => 'org-1'],
            'actionconfig' => [
                self::TEXT_ACTIONS[0] => [
                    'enabled' => false,
                    'settings' => [
                        'endpoint' => 'https://api.openai.com/v1/chat/completions',
                        'model' => 'gpt-4o',
                        'systeminstruction' => 'answer briefly',
                    ],
                ],
            ],
        ]]);

        [$output, , $stored] = $this->runScript();

        $this->assertSame([7], array_keys($stored));
        $this->assertSame(7, $output['id']);
        $this->assertTrue($stored[7]['enabled']);
        $this->assertSame(['apikey' => 'sk-gateway', 'orgid' => 'org-1'], $stored[7]['config']);
        $settings = $stored[7]['actionconfig'][self::TEXT_ACTIONS[0]]['settings'];
        $this->assertSame(self::CHAT, $settings['endpoint']);
        $this->assertSame('answer briefly', $settings['systeminstruction']);
    }

    public function testAnInstanceAnAdministratorAddedIsLeftAlone(): void
    {
        $own = [
            'id' => 1,
            'provider' => self::OPENAI,
            'name' => 'Our own OpenAI account',
            'enabled' => true,
            'config' => ['apikey' => 'sk-own'],
            'actionconfig' => [],
        ];
        $this->seed([$own]);

        [$output, , $stored] = $this->runScript();

        $this->assertSame([1, 2], array_keys($stored));
        $this->assertSame($own, $stored[1]);
        $this->assertSame(2, $output['id']);
        $this->assertSame(self::NAME, $stored[2]['name']);
    }

    public function testASecondRunChangesNothing(): void
    {
        [, , $first] = $this->runScript();
        [, $code, $second] = $this->runScript();

        $this->assertSame(0, $code);
        $this->assertSame($first, $second);
    }
}
