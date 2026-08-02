<?php
define('CLI_SCRIPT', true);

require(getenv('MOODLE_CONFIG'));
require_once($CFG->libdir . '/externallib.php');
require_once($CFG->dirroot . '/webservice/lib.php');

$shortname = (string) getenv('MCP_SERVICE_SHORTNAME');
$servicename = (string) getenv('MCP_SERVICE_NAME');
$functions = array_filter(array_map('trim', explode(',', (string) getenv('MCP_SERVICE_FUNCTIONS'))));

set_config('enablewebservices', 1);

$protocols = array_filter(array_map('trim', explode(',', (string) get_config('core', 'webserviceprotocols'))));
if (!in_array('mcp', $protocols, true)) {
    $protocols[] = 'mcp';
    set_config('webserviceprotocols', implode(',', $protocols));
}

$webservice = new webservice();
$service = $webservice->get_external_service_by_shortname($shortname);
if (!$service) {
    $webservice->add_external_service((object) [
        'name' => $servicename,
        'shortname' => $shortname,
        'enabled' => 1,
        'restrictedusers' => 0,
        'downloadfiles' => 0,
        'uploadfiles' => 0,
    ]);
    $service = $webservice->get_external_service_by_shortname($shortname, MUST_EXIST);
}

foreach ($functions as $function) {
    if (!$DB->record_exists('external_functions', ['name' => $function])) {
        continue;
    }
    if (!$webservice->service_function_exists($function, $service->id)) {
        $webservice->add_external_function_to_service($function, $service->id);
    }
}

$admin = get_admin();
$token = $DB->get_field('external_tokens', 'token', [
    'externalserviceid' => $service->id,
    'userid' => $admin->id,
    'tokentype' => EXTERNAL_TOKEN_PERMANENT,
], IGNORE_MULTIPLE);

if (!$token) {
    $token = external_generate_token(
        EXTERNAL_TOKEN_PERMANENT,
        $service->id,
        $admin->id,
        context_system::instance()
    );
}

echo $token . PHP_EOL;
