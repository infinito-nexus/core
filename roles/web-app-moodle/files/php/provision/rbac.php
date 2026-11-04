<?php
/**
 * Converge Moodle's system roles and site administrators on the members of the RBAC groups.
 *
 * Env:
 *   MOODLE_CONFIG             path of the site's config.php
 *   MOODLE_RBAC_ACCOUNT_AUTH  auth plugin of the account a member gets when it has none yet
 *   MOODLE_RBAC_BOOTSTRAP     username that stays the first site administrator
 *   MOODLE_RBAC_PROTECTED     JSON list of usernames whose system role assignments stay untouched
 *   MOODLE_RBAC_SITEADMINS    JSON list of {username, email, name} that hold site administration
 *   MOODLE_RBAC_SYSTEM_ROLES  JSON list of the system role shortnames whose RBAC group of the same name is converged
 *   MOODLE_RBAC_MEMBERS       JSON object of RBAC role to its {username, email, name} list
 *
 * Output: one CHANGED line per change or UNCHANGED on stdout; [FAIL] lines on stderr and exit 1 when a member could not be converged.
 */
define('CLI_SCRIPT', true);

require(getenv('MOODLE_CONFIG'));
require_once($CFG->libdir . '/authlib.php');
require_once($CFG->dirroot . '/user/lib.php');

function rbac_env(string $name): string
{
    $value = getenv($name);
    if ($value === false || $value === '') {
        fwrite(STDERR, "[FAIL] $name is empty\n");
        exit(1);
    }
    return $value;
}

function rbac_json(string $name): array
{
    $value = json_decode(rbac_env($name), true);
    if (!is_array($value)) {
        fwrite(STDERR, "[FAIL] $name is neither a JSON list nor a JSON object\n");
        exit(1);
    }
    return $value;
}

function rbac_find(string $username): ?stdClass
{
    global $CFG, $DB;
    $user = $DB->get_record('user', [
        'username' => $username,
        'mnethostid' => $CFG->mnet_localhost_id,
        'deleted' => 0,
    ]);
    return $user ?: null;
}

function rbac_account(array $member, string $auth, array &$failures, bool &$changed): ?stdClass
{
    global $CFG, $DB;
    $username = (string) $member['username'];
    $user = rbac_find($username);
    if ($user) {
        return $user;
    }
    try {
        $id = user_create_user((object) [
            'username' => $username,
            'email' => (string) $member['email'],
            'auth' => $auth,
            'confirmed' => 1,
            'mnethostid' => $CFG->mnet_localhost_id,
            'password' => AUTH_PASSWORD_NOT_CACHED,
        ], false, true);
    } catch (Throwable $error) {
        $failures[] = "cannot create the account of $username: " . $error->getMessage();
        return null;
    }
    echo "CHANGED $username created with auth $auth\n";
    $changed = true;
    return $DB->get_record('user', ['id' => $id], '*', MUST_EXIST);
}

$auth = rbac_env('MOODLE_RBAC_ACCOUNT_AUTH');
$protected = array_flip(rbac_json('MOODLE_RBAC_PROTECTED'));
$groups = rbac_json('MOODLE_RBAC_MEMBERS');
$failures = [];
$changed = false;
$systemcontext = context_system::instance();

foreach (rbac_json('MOODLE_RBAC_SYSTEM_ROLES') as $shortname) {
    if (!array_key_exists($shortname, $groups)) {
        $failures[] = "no members were passed for the role $shortname";
        continue;
    }
    $roleid = (int) $DB->get_field('role', 'id', ['shortname' => $shortname]);
    if (!$roleid) {
        $failures[] = "no Moodle role has the shortname $shortname";
        continue;
    }

    $wanted = [];
    foreach ($groups[$shortname] as $member) {
        $user = rbac_account($member, $auth, $failures, $changed);
        if ($user && !isset($protected[$user->username])) {
            $wanted[(int) $user->id] = $user->username;
        }
    }

    $held = [];
    $assignments = $DB->get_records('role_assignments', [
        'roleid' => $roleid,
        'contextid' => $systemcontext->id,
    ]);
    foreach ($assignments as $assignment) {
        $userid = (int) $assignment->userid;
        $username = (string) $DB->get_field('user', 'username', ['id' => $userid]);
        if (isset($protected[$username])) {
            continue;
        }
        if (isset($wanted[$userid])) {
            $held[$userid] = true;
            continue;
        }
        role_unassign($roleid, $userid, $systemcontext->id, $assignment->component, (int) $assignment->itemid);
        echo "CHANGED $username unassigned $shortname\n";
        $changed = true;
    }

    foreach ($wanted as $userid => $username) {
        if (isset($held[$userid])) {
            continue;
        }
        role_assign($roleid, $userid, $systemcontext->id);
        echo "CHANGED $username assigned $shortname\n";
        $changed = true;
    }
}

$bootstrapname = rbac_env('MOODLE_RBAC_BOOTSTRAP');
$bootstrap = rbac_find($bootstrapname);
if (!$bootstrap) {
    $failures[] = "the bootstrap administrator $bootstrapname has no account";
} else {
    $admins = [(int) $bootstrap->id];
    foreach (rbac_json('MOODLE_RBAC_SITEADMINS') as $member) {
        $user = rbac_account($member, $auth, $failures, $changed);
        if ($user) {
            $admins[] = (int) $user->id;
        }
    }
    $admins = array_values(array_unique($admins));
    $current = array_values(array_filter(array_map('intval', explode(',', (string) $CFG->siteadmins))));
    if ($current !== $admins) {
        set_config('siteadmins', implode(',', $admins));
        echo 'CHANGED siteadmins ' . implode(',', $admins) . "\n";
        $changed = true;
    }
}

if (!$changed && !$failures) {
    echo "UNCHANGED\n";
}
foreach ($failures as $failure) {
    fwrite(STDERR, "[FAIL] $failure\n");
}
exit($failures ? 1 : 0);
