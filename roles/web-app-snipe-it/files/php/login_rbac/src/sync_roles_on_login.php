<?php
/**
 * Applies the role groups of the account that signs in: `superuser` for the administrator role
 * group, the permission group for both role groups, neither for anyone else.
 *
 * Env (templates/env.j2):
 *   SNIPE_IT_LOGIN_RBAC_PROTECTED            comma-separated usernames a sign-in never changes
 *   SNIPE_IT_LOGIN_RBAC_PERMISSION_GROUP     name of the permission group every member joins
 *   SNIPE_IT_LOGIN_RBAC_ADMINISTRATOR_GROUP  path of the administrator role group in the groups claim
 *   SNIPE_IT_LOGIN_RBAC_USER_GROUP           path of the user role group in the groups claim
 *   SNIPE_IT_LOGIN_RBAC_ADMINISTRATOR_DN     DN of the administrator role group in the directory
 *   SNIPE_IT_LOGIN_RBAC_USER_DN              DN of the user role group in the directory
 *   SNIPE_IT_LOGIN_RBAC_MEMBER_OF            directory attribute that lists the groups of an entry
 *   SNIPE_IT_LOGIN_RBAC_GROUPS_VARIABLE      server variable Apache fills from the groups claim of a proxied request
 *   SNIPE_IT_LOGIN_RBAC_LDAP                 "true" when the directory holds the accounts, else "false"
 */

namespace Infinito\SnipeItLoginRbac;

use App\Models\Group;
use App\Models\Ldap;
use App\Models\Setting;
use App\Models\User;
use Illuminate\Auth\Events\Login;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Log;
use RuntimeException;

final class SyncRolesOnLogin
{
    public function __construct(private readonly Request $request)
    {
    }

    public function handle(Login $event): void
    {
        $user = $event->user;
        $config = self::config();
        if (!$user instanceof User || in_array($user->username, $config['protected'], true)) {
            return;
        }

        $claimed = $this->claimedGroups($user, $config['groups_variable']);
        if ($claimed === null && !($config['ldap'] && (string) $user->ldap_import === '1')) {
            return;
        }
        $group = Group::where('name', $config['permission_group'])->first();
        if ($group === null) {
            throw new RuntimeException("the permission group '{$config['permission_group']}' does not exist yet");
        }
        $entry = $config['ldap'] ? $this->directoryEntry($user, $config['member_of']) : null;

        if ($claimed !== null) {
            $administrator = self::holds($claimed, $config['administrator_group'], '/');
            $member = $administrator || self::holds($claimed, $config['user_group'], '/');
        } else {
            $dns = $entry === null ? [] : array_values(array_filter(
                (array) ($entry[strtolower($config['member_of'])] ?? []),
                static fn ($key): bool => $key !== 'count',
                ARRAY_FILTER_USE_KEY
            ));
            $administrator = self::holds($dns, $config['administrator_dn'], '');
            $member = $administrator || self::holds($dns, $config['user_dn'], '');
        }

        if ($entry !== null) {
            Ldap::applyLdapAttributesToUser($user, Ldap::parseAndMapLdapAttributes($entry));
        }
        $this->converge($user, $group, $administrator, $member);
    }

    /**
     * @param User $user the account that signs in
     * @param string $variable server variable that holds the groups claim
     * @return list<string>|null the role groups of a proxied SSO sign-in of that account, else null
     */
    private function claimedGroups(User $user, string $variable): ?array
    {
        $settings = Setting::getSettings();
        if ((string) $settings->login_remote_user_enabled !== '1') {
            return null;
        }
        $signedIn = $this->serverVariable((string) $settings->login_remote_user_header_name);
        if ($signedIn === null || $signedIn !== (string) $user->username) {
            return null;
        }
        $groups = $this->serverVariable($variable);
        if ($groups === null) {
            throw new RuntimeException("the SSO sign-in of {$user->username} carries no groups claim");
        }
        return array_map('trim', explode(',', $groups));
    }

    /**
     * @param string $name server variable Apache sets, also read with the REDIRECT_ prefix mod_rewrite adds
     * @return string|null its non-empty value
     */
    private function serverVariable(string $name): ?string
    {
        $value = $this->request->server($name) ?? $this->request->server('REDIRECT_' . $name);
        return is_string($value) && $value !== '' ? $value : null;
    }

    /**
     * @param User $user the account that signs in
     * @param string $memberOf directory attribute that lists the groups of an entry
     * @return array<string, mixed>|null its directory entry as ldap_get_entries returns it, else null
     */
    private function directoryEntry(User $user, string $memberOf): ?array
    {
        $field = (string) Setting::getSettings()->ldap_username_field;
        $filter = sprintf('(%s=%s)', $field, ldap_escape((string) $user->username, '', LDAP_ESCAPE_FILTER));
        $results = Ldap::findLdapUsers(null, 1, $filter, ['*', $memberOf]);
        if (!is_array($results)) {
            throw new RuntimeException("the directory search for {$user->username} failed");
        }
        return $results['count'] > 0 ? $results[0] : null;
    }

    /**
     * @param User $user the account that signs in
     * @param Group $group the permission group every member joins
     * @param bool $administrator whether it holds the administrator role group
     * @param bool $member whether it holds one of the two role groups
     */
    private function converge(User $user, Group $group, bool $administrator, bool $member): void
    {
        $decoded = json_decode((string) $user->permissions, true);
        $before = is_array($decoded) ? $decoded : [];
        $permissions = $before;
        if ($administrator) {
            $permissions['superuser'] = '1';
        } else {
            unset($permissions['superuser'], $permissions['admin']);
        }
        if ($permissions !== $before) {
            $user->permissions = json_encode((object) $permissions);
            Log::info(($administrator ? 'login rbac: promoted ' : 'login rbac: demoted ') . $user->username);
        }
        if ($user->isDirty()) {
            $user->saveQuietly();
        }

        $inGroup = $user->groups()->where('group_id', $group->id)->exists();
        if ($member && !$inGroup) {
            $user->groups()->attach($group->id);
            Log::info("login rbac: joined {$user->username}");
        } elseif (!$member && $inGroup) {
            $user->groups()->detach($group->id);
            Log::info("login rbac: left {$user->username}");
        }
    }

    /**
     * @param list<string> $groups group paths or DNs the sign-in carries
     * @param string $wanted the role group to look for
     * @param string $trim characters that do not tell two groups apart at the edges
     * @return bool whether the sign-in carries that role group
     */
    private static function holds(array $groups, string $wanted, string $trim): bool
    {
        $normalize = static fn (string $group): string => strtolower(trim($group, $trim));
        return in_array($normalize($wanted), array_map($normalize, $groups), true);
    }

    /**
     * @return array{protected: list<string>, permission_group: string, administrator_group: string,
     *     user_group: string, administrator_dn: string, user_dn: string, member_of: string,
     *     groups_variable: string, ldap: bool} the settings from the environment
     */
    private static function config(): array
    {
        $ldap = self::env('SNIPE_IT_LOGIN_RBAC_LDAP');
        if ($ldap !== 'true' && $ldap !== 'false') {
            throw new RuntimeException('SNIPE_IT_LOGIN_RBAC_LDAP is neither true nor false');
        }
        return [
            'protected' => explode(',', self::env('SNIPE_IT_LOGIN_RBAC_PROTECTED')),
            'permission_group' => self::env('SNIPE_IT_LOGIN_RBAC_PERMISSION_GROUP'),
            'administrator_group' => self::env('SNIPE_IT_LOGIN_RBAC_ADMINISTRATOR_GROUP'),
            'user_group' => self::env('SNIPE_IT_LOGIN_RBAC_USER_GROUP'),
            'administrator_dn' => self::env('SNIPE_IT_LOGIN_RBAC_ADMINISTRATOR_DN'),
            'user_dn' => self::env('SNIPE_IT_LOGIN_RBAC_USER_DN'),
            'member_of' => self::env('SNIPE_IT_LOGIN_RBAC_MEMBER_OF'),
            'groups_variable' => self::env('SNIPE_IT_LOGIN_RBAC_GROUPS_VARIABLE'),
            'ldap' => $ldap === 'true',
        ];
    }

    /**
     * @param string $name environment variable
     * @return string its non-empty value
     */
    private static function env(string $name): string
    {
        $value = getenv($name);
        if (!is_string($value) || $value === '') {
            throw new RuntimeException("$name is not set");
        }
        return $value;
    }
}
