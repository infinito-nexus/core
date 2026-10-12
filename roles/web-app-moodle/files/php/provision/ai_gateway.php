<?php
define('CLI_SCRIPT', true);

require(getenv('MOODLE_CONFIG'));

$class = \aiprovider_openai\provider::class;
$name = (string) getenv('AI_PROVIDER_NAME');
$textactions = [
    \core_ai\aiactions\generate_text::class,
    \core_ai\aiactions\summarise_text::class,
    \core_ai\aiactions\explain_text::class,
];
$imageaction = \core_ai\aiactions\generate_image::class;

$manager = \core\di::get(\core_ai\manager::class);
$instances = $manager->get_provider_instances(['provider' => $class, 'name' => $name]);
$provider = $instances
    ? reset($instances)
    : $manager->create_provider_instance(classname: $class, name: $name);

$actionconfig = $provider->actionconfig;
foreach ($textactions as $action) {
    $actionconfig[$action]['enabled'] = true;
    $actionconfig[$action]['settings']['endpoint'] = (string) getenv('AI_CHAT_ENDPOINT');
    $actionconfig[$action]['settings']['model'] = (string) getenv('AI_CHAT_MODEL');
}
$actionconfig[$imageaction]['enabled'] = false;
$actionconfig[$imageaction]['settings']['endpoint'] = (string) getenv('AI_IMAGE_ENDPOINT');

$provider = $manager->update_provider_instance(
    provider: $provider,
    config: array_merge($provider->config, ['apikey' => (string) getenv('AI_API_KEY')]),
    actionconfig: $actionconfig,
);
$manager->enable_provider_instance($provider);

$stored = $manager->get_provider_instances(['id' => $provider->id]);
echo json_encode([
    'id' => (int) $provider->id,
    'endpoints' => array_map(
        fn(array $action): string => (string) ($action['settings']['endpoint'] ?? ''),
        reset($stored)->actionconfig,
    ),
]), PHP_EOL;
