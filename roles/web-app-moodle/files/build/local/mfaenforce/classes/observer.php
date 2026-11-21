<?php
namespace local_mfaenforce;

class observer {
    private const EXPIRED_GRACE_START = 1;

    /**
     * @param \core\event\user_loggedin $event the completed sign-in
     */
    public static function user_loggedin(\core\event\user_loggedin $event): void {
        global $DB;

        if (!get_config('local_mfaenforce', 'enabled')) {
            return;
        }
        $grace = ['userid' => $event->objectid, 'factor' => 'grace'];
        if ($DB->record_exists('tool_mfa', $grace)) {
            $DB->set_field('tool_mfa', 'timecreated', self::EXPIRED_GRACE_START, $grace);
            return;
        }
        $DB->insert_record('tool_mfa', $grace + [
            'createdfromip' => getremoteaddr(),
            'timecreated' => self::EXPIRED_GRACE_START,
            'revoked' => 0,
        ]);
    }
}
