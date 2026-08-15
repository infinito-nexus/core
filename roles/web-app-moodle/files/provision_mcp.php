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

require_once($CFG->dirroot . '/user/lib.php');

$username = (string) getenv('MCP_ACCOUNT_USERNAME');
$capabilities = array_filter(array_map('trim', explode(',', (string) getenv('MCP_ROLE_CAPABILITIES'))));
$systemcontext = context_system::instance();

$account = $DB->get_record('user', [
    'username' => $username,
    'mnethostid' => $CFG->mnet_localhost_id,
]);
if (!$account) {
    $new = new stdClass();
    $new->username = $username;
    $new->email = (string) getenv('MCP_ACCOUNT_EMAIL');
    $new->password = (string) getenv('MCP_ACCOUNT_PASSWORD');
    $new->firstname = 'Infinito';
    $new->lastname = 'MCP';
    $new->auth = 'manual';
    $new->confirmed = 1;
    $new->mnethostid = $CFG->mnet_localhost_id;
    $accountid = user_create_user($new, true, false);
    $account = $DB->get_record('user', ['id' => $accountid], '*', MUST_EXIST);
}

$roleshortname = (string) getenv('MCP_ROLE_SHORTNAME');
$roleid = $DB->get_field('role', 'id', ['shortname' => $roleshortname]);
if (!$roleid) {
    $roleid = create_role((string) getenv('MCP_ROLE_NAME'), $roleshortname, '', 'user');
    set_role_contextlevels($roleid, [CONTEXT_SYSTEM]);
}
foreach ($capabilities as $capability) {
    assign_capability($capability, CAP_ALLOW, $roleid, $systemcontext->id, true);
}
role_assign($roleid, $account->id, $systemcontext->id);

$token = $DB->get_field('external_tokens', 'token', [
    'externalserviceid' => $service->id,
    'userid' => $account->id,
    'tokentype' => EXTERNAL_TOKEN_PERMANENT,
], IGNORE_MULTIPLE);

if (!$token) {
    $token = external_generate_token(
        EXTERNAL_TOKEN_PERMANENT,
        $service->id,
        $account->id,
        $systemcontext
    );
}

echo $token . PHP_EOL;
