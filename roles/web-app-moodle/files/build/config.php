<?php
// nocheck: mirrored-unit-test - env-driven Moodle configuration; the file assigns globals and calls Moodle's setup.php, it exposes no unit
// Env-driven Moodle config. Single source of truth for defaults is
// env.j2 (rendered by Ansible into .env/env). All MOODLE_* env vars
// MUST be set; missing values fail fast.
// See docs/requirements/015-moodle-self-built.md.

function moodle_env(string $name): string {
    $v = getenv($name);
    if ($v === false || $v === '') {
        throw new RuntimeException("Required env var {$name} is not set");
    }
    return $v;
}

function moodle_env_bool(string $name): bool {
    return filter_var(moodle_env($name), FILTER_VALIDATE_BOOLEAN);
}

unset($CFG);
global $CFG;
$CFG = new stdClass();

$CFG->dbtype    = moodle_env('MOODLE_DB_TYPE');
$CFG->dblibrary = 'native';
$CFG->dbhost    = moodle_env('MOODLE_DB_HOST');
$CFG->dbname    = moodle_env('MOODLE_DB_NAME');
$CFG->dbuser    = moodle_env('MOODLE_DB_USER');
$CFG->dbpass    = moodle_env('MOODLE_DB_PASS');
$CFG->prefix    = moodle_env('MOODLE_DB_PREFIX');
$CFG->dboptions = array(
    'dbpersist'   => 0,
    'dbport'      => moodle_env('MOODLE_DB_PORT'),
    'dbsocket'    => '',
    'dbcollation' => 'utf8mb4_unicode_ci',
);

$CFG->wwwroot              = moodle_env('MOODLE_WWWROOT');
$CFG->dataroot             = moodle_env('MOODLE_DATAROOT');
$CFG->localcachedir        = moodle_env('MOODLE_LOCALCACHEDIR');
$CFG->admin                = 'admin';
$CFG->directorypermissions = 02770;
$CFG->routerconfigured     = true;

$CFG->reverseproxy = moodle_env_bool('MOODLE_REVERSEPROXY');
$CFG->sslproxy     = moodle_env_bool('MOODLE_SSLPROXY');

$_moodle_internal_host = moodle_env('MOODLE_INTERNAL_HOST');
if (explode(':', $_SERVER['HTTP_HOST'] ?? '', 2)[0] === $_moodle_internal_host) {
    $_SERVER['HTTP_HOST']   = parse_url($CFG->wwwroot, PHP_URL_HOST);
    $_SERVER['SERVER_NAME'] = $_SERVER['HTTP_HOST'];
}

$_moodle_debug     = moodle_env_bool('MOODLE_DEBUG');
$CFG->debug        = $_moodle_debug ? 32767 : 0;
$CFG->debugdisplay = $_moodle_debug;

if (moodle_env_bool('MOODLE_OBJECTFS_ENABLED')
        && is_file(moodle_env('MOODLE_OBJECTFS_READY_FILE'))) {
    $CFG->alternative_file_system_class = '\\tool_objectfs\\s3_file_system';
    $CFG->pathtophp = PHP_BINDIR . '/php';
    $CFG->forced_plugin_settings = array(
        'tool_objectfs' => array(
            'enabletasks'   => 1,
            'filesystem'    => '\\tool_objectfs\\s3_file_system',
            'minimumage'    => 0,
            'sizethreshold' => 0,
            's3_base_url'   => moodle_env('MOODLE_OBJECTFS_S3_BASE_URL'),
            's3_bucket'     => moodle_env('MOODLE_OBJECTFS_S3_BUCKET'),
            's3_key'        => moodle_env('MOODLE_OBJECTFS_S3_KEY'),
            's3_region'     => moodle_env('MOODLE_OBJECTFS_S3_REGION'),
            's3_secret'     => moodle_env('MOODLE_OBJECTFS_S3_SECRET'),
        ),
        'tool_task' => array(
            'enablerunnow' => 1,
        ),
    );
}

require_once(__DIR__ . '/lib/setup.php');
