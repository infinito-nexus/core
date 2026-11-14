<?php

declare(strict_types=1);

use PHPUnit\Framework\TestCase;

final class InfinitoOidcRbacMapperMultisiteTest extends TestCase
{
    private const PLUGIN = '/roles/web-app-wordpress/files/mu-plugins/infinito-oidc-rbac-mapper.php';

    private const GROUPS = '/roles/web-app-wordpress';

    private const SITE_ROLES = ['administrator', 'editor', 'author', 'contributor', 'subscriber'];

    private const TENANTS = ['blog.main.test', 'biberblog.main.test', 'biber.blog.main.test'];

    private const OWN_DOMAIN = 'biber.user.blog.main.test';

    private const OTHER_OWN_DOMAIN = 'mapache.user.blog.main.test';

    private const SUBJECT_META = 'infinito_site_owner_subject';

    private const HARNESS = <<<'PHP'
        <?php
        define('ABSPATH', '/');
        function add_action($hook, $callback, $priority = 10, $acceptedArgs = 1)
        {
            return true;
        }
        function add_filter($hook, $callback, $priority = 10, $acceptedArgs = 1)
        {
            return true;
        }
        final class WP_Error
        {
            public function __construct(private string $message)
            {
            }
            public function get_error_message()
            {
                return $this->message;
            }
        }
        function is_wp_error($value)
        {
            return $value instanceof WP_Error;
        }
        $GLOBALS['state'] = json_decode((string) getenv('STUB_STATE'), true);
        $GLOBALS['blog'] = 1;
        $GLOBALS['switched'] = [];
        class WP_User
        {
            public $ID;
            public $user_login;
            public $roles;
            public function __construct($id)
            {
                $this->ID = (int) $id;
                $this->user_login = $GLOBALS['state']['login'];
                $this->roles = $GLOBALS['state']['members'][$GLOBALS['blog']][$this->ID] ?? [];
            }
            public function set_role($role)
            {
                $GLOBALS['state']['members'][$GLOBALS['blog']][$this->ID] = [$role];
                $this->roles = [$role];
            }
        }
        function is_multisite()
        {
            return true;
        }
        function get_sites($args)
        {
            $sites = [];
            foreach ($GLOBALS['state']['sites'] as $id => $site) {
                if (isset($args['domain']) && $site['domain'] !== $args['domain']) {
                    continue;
                }
                $sites[] = (object) ['blog_id' => (string) $id, 'domain' => $site['domain'], 'path' => '/', 'archived' => $site['archived'] ? '1' : '0'];
            }
            return $sites;
        }
        function is_user_member_of_blog($userId, $blogId)
        {
            return isset($GLOBALS['state']['members'][(int) $blogId][(int) $userId]);
        }
        function add_user_to_blog($blogId, $userId, $role)
        {
            $GLOBALS['state']['members'][(int) $blogId][(int) $userId] = [$role];
            return true;
        }
        function remove_user_from_blog($userId, $blogId)
        {
            unset($GLOBALS['state']['members'][(int) $blogId][(int) $userId]);
            return true;
        }
        function switch_to_blog($blogId)
        {
            $GLOBALS['switched'][] = $GLOBALS['blog'];
            $GLOBALS['blog'] = (int) $blogId;
            return true;
        }
        function restore_current_blog()
        {
            $GLOBALS['blog'] = array_pop($GLOBALS['switched']);
            return true;
        }
        function get_user_meta($userId, $key, $single = false)
        {
            return $GLOBALS['state']['user_meta'][$key] ?? '';
        }
        function update_user_meta($userId, $key, $value)
        {
            $GLOBALS['state']['user_meta'][$key] = $value;
            return true;
        }
        function get_site_meta($blogId, $key, $single = false)
        {
            return $GLOBALS['state']['site_meta'][(int) $blogId][$key] ?? '';
        }
        function wp_update_site($blogId, $data)
        {
            if ($GLOBALS['state']['refuse_site_updates']) {
                return new WP_Error('the sites table refuses the update');
            }
            $GLOBALS['state']['sites'][(int) $blogId] = $data + $GLOBALS['state']['sites'][(int) $blogId];
            return (int) $blogId;
        }
        function wp_insert_site($data)
        {
            $id = max(array_keys($GLOBALS['state']['sites'])) + 1;
            $GLOBALS['state']['sites'][$id] = ['domain' => $data['domain'], 'archived' => 0];
            $GLOBALS['state']['site_meta'][$id] = $data['meta'];
            $GLOBALS['state']['members'][$id][(int) $data['user_id']] = ['administrator'];
            return $id;
        }
        require getenv('STUB_PLUGIN');
        infinito_oidc_map_rbac_role(new WP_User(7), json_decode((string) getenv('STUB_CLAIMS'), true));
        $roles = [];
        foreach ($GLOBALS['state']['sites'] as $id => $site) {
            $roles[$site['domain']] = $GLOBALS['state']['members'][$id][7] ?? [];
        }
        echo json_encode([
            'roles' => $roles,
            'owned' => $GLOBALS['state']['user_meta']['_infinito_oidc_added_blog_ids'] ?? [],
            'state' => $GLOBALS['state'],
        ]);
        PHP;

    /**
     * @param array<string, mixed> $state      sites (blog id => domain, archived), members (blog id => user id => roles),
     *                                         site_meta (blog id => key => value), user_meta of biber (user id 7) and
     *                                         refuse_site_updates
     * @param list<string> $groups             the groups claim of the sign-in
     * @param bool $siteOwners                 WORDPRESS_SITE_OWNER_ENABLED
     * @return array{roles: array<string, list<string>>, owned: list<int>, state: array<string, mixed>} biber's roles per
     *                                         site domain, the memberships the mapper owns and the state after the sign-in
     */
    private function signIn(array $state, array $groups, bool $siteOwners): array
    {
        $harness = tempnam(sys_get_temp_dir(), 'wpmm');
        file_put_contents($harness, self::HARNESS);
        $env = [
            'STUB_STATE' => (string) json_encode($state + ['login' => 'biber', 'site_meta' => (object) [], 'user_meta' => (object) [], 'refuse_site_updates' => false]),
            'STUB_PLUGIN' => dirname(__DIR__, 7) . self::PLUGIN,
            'STUB_CLAIMS' => (string) json_encode(['groups' => $groups, 'sub' => 'sub-biber', 'preferred_username' => 'biber']),
            'WORDPRESS_OIDC_CLAIM_GROUPS' => 'groups',
            'WORDPRESS_OIDC_CLAIM_USERNAME' => 'preferred_username',
            'WORDPRESS_RBAC_GROUP_MAP' => self::groupMap(),
            'WORDPRESS_SITE_OWNER_ENABLED' => $siteOwners ? 'true' : 'false',
            'WORDPRESS_SITE_OWNER_BASE_URL' => 'https://user.blog.main.test',
        ];
        $process = proc_open([PHP_BINARY, $harness], [1 => ['pipe', 'w'], 2 => ['pipe', 'w']], $pipes, null, $env);
        $stdout = (string) stream_get_contents($pipes[1]);
        $stderr = (string) stream_get_contents($pipes[2]);
        fclose($pipes[1]);
        fclose($pipes[2]);
        $code = proc_close($process);
        unlink($harness);
        self::assertSame(0, $code, $stderr);

        return json_decode($stdout, true, flags: JSON_THROW_ON_ERROR);
    }

    /**
     * @return string WORDPRESS_RBAC_GROUP_MAP of a network with three tenants, the global site roles, the network
     *                administrators and the site owners
     */
    private static function groupMap(): string
    {
        $map = [];
        foreach (self::TENANTS as $tenant) {
            foreach (self::SITE_ROLES as $role) {
                $map[self::GROUPS . '/' . $tenant . '/' . $role] = ['role' => $role, 'tenant' => $tenant];
            }
        }
        foreach (self::SITE_ROLES as $role) {
            $map[self::GROUPS . '/global-' . $role] = ['role' => $role];
        }
        $map[self::GROUPS . '/network-administrator'] = ['network' => true];
        $map[self::GROUPS . '/site-owner'] = ['site_owner' => true];

        return (string) json_encode($map);
    }

    /**
     * @param array<int, string> $extra blog id => domain of the sites beyond the three tenants, ids from 4
     * @return array<int, array{domain: string, archived: int}> the sites of the network
     */
    private static function sites(array $extra): array
    {
        $sites = [];
        foreach (array_values(self::TENANTS) as $index => $domain) {
            $sites[$index + 1] = ['domain' => $domain, 'archived' => 0];
        }
        foreach ($extra as $id => $domain) {
            $sites[$id] = ['domain' => $domain, 'archived' => 0];
        }

        return $sites;
    }

    public function testAGlobalRoleAppliesOnEverySiteOfTheNetwork(): void
    {
        $result = $this->signIn(
            ['sites' => self::sites([4 => self::OTHER_OWN_DOMAIN]), 'members' => [1 => [7 => ['subscriber']], 4 => [11 => ['administrator']]]],
            [self::GROUPS . '/global-editor'],
            false
        );

        self::assertSame(
            ['blog.main.test' => ['editor'], 'biberblog.main.test' => ['editor'], 'biber.blog.main.test' => ['editor'], self::OTHER_OWN_DOMAIN => ['editor']],
            $result['roles']
        );
        self::assertSame([2, 3, 4], $result['owned']);
    }

    public function testNoSignInLowersARoleTheGroupsGrantOnAnySite(): void
    {
        $result = $this->signIn(
            [
                'sites' => self::sites([4 => self::OTHER_OWN_DOMAIN]),
                'members' => [1 => [7 => ['editor']], 2 => [7 => ['editor']]],
                'user_meta' => ['_infinito_oidc_added_blog_ids' => [2]],
            ],
            [self::GROUPS . '/global-editor', self::GROUPS . '/biberblog.main.test/administrator', self::GROUPS . '/biber.blog.main.test/author'],
            false
        );

        self::assertSame(
            ['blog.main.test' => ['editor'], 'biberblog.main.test' => ['administrator'], 'biber.blog.main.test' => ['editor'], self::OTHER_OWN_DOMAIN => ['editor']],
            $result['roles']
        );
        self::assertSame([2, 3, 4], $result['owned']);
    }

    public function testAPerSiteRoleStaysOnItsOwnSite(): void
    {
        $result = $this->signIn(
            ['sites' => self::sites([4 => self::OTHER_OWN_DOMAIN]), 'members' => [1 => [7 => ['subscriber']]]],
            [self::GROUPS . '/biberblog.main.test/editor'],
            false
        );

        self::assertSame(
            ['blog.main.test' => ['subscriber'], 'biberblog.main.test' => ['editor'], 'biber.blog.main.test' => [], self::OTHER_OWN_DOMAIN => []],
            $result['roles']
        );
        self::assertSame([2], $result['owned']);
    }

    public function testLeavingTheGlobalGroupRemovesTheMembershipsTheMapperAddedAndDemotesTheRest(): void
    {
        $result = $this->signIn(
            [
                'sites' => self::sites([4 => self::OTHER_OWN_DOMAIN]),
                'members' => [1 => [7 => ['editor']], 2 => [7 => ['editor']], 3 => [7 => ['editor']], 4 => [7 => ['editor']]],
                'user_meta' => ['_infinito_oidc_added_blog_ids' => [2, 3, 4]],
            ],
            [],
            false
        );

        self::assertSame(
            ['blog.main.test' => ['subscriber'], 'biberblog.main.test' => [], 'biber.blog.main.test' => [], self::OTHER_OWN_DOMAIN => []],
            $result['roles']
        );
        self::assertSame([], $result['owned']);
    }

    public function testAGlobalRoleLeavesTheOwnSiteToItsOwner(): void
    {
        $result = $this->signIn(
            [
                'sites' => self::sites([5 => self::OWN_DOMAIN]),
                'members' => [1 => [7 => ['subscriber']], 5 => [7 => ['administrator']]],
                'site_meta' => [5 => [self::SUBJECT_META => 'sub-biber']],
            ],
            [self::GROUPS . '/site-owner', self::GROUPS . '/global-editor'],
            true
        );

        self::assertSame(['administrator'], $result['roles'][self::OWN_DOMAIN]);
        self::assertSame(['editor'], $result['roles']['biberblog.main.test']);
    }

    public function testAFailedOwnSiteStepKeepsTheOwnerAdministratorOfTheOwnSite(): void
    {
        $result = $this->signIn(
            [
                'sites' => [5 => ['domain' => self::OWN_DOMAIN, 'archived' => 1]] + self::sites([]),
                'members' => [1 => [7 => ['subscriber']], 5 => [7 => ['administrator']]],
                'site_meta' => [5 => [self::SUBJECT_META => 'sub-biber']],
                'refuse_site_updates' => true,
            ],
            [self::GROUPS . '/site-owner'],
            true
        );

        self::assertSame(['administrator'], $result['roles'][self::OWN_DOMAIN]);
        self::assertSame(['subscriber'], $result['roles']['blog.main.test']);
    }

    public function testAFailedOwnSiteStepKeepsAGlobalRoleOffTheOwnSite(): void
    {
        $result = $this->signIn(
            [
                'sites' => [5 => ['domain' => self::OWN_DOMAIN, 'archived' => 1]] + self::sites([]),
                'members' => [1 => [7 => ['subscriber']], 5 => [7 => ['administrator']]],
                'site_meta' => [5 => [self::SUBJECT_META => 'sub-biber']],
                'refuse_site_updates' => true,
            ],
            [self::GROUPS . '/site-owner', self::GROUPS . '/global-editor'],
            true
        );

        self::assertSame(['administrator'], $result['roles'][self::OWN_DOMAIN]);
        self::assertSame(['editor'], $result['roles']['biber.blog.main.test']);
    }

    public function testAFailedArchiveDemotesTheFormerOwnerOnTheOwnSite(): void
    {
        $result = $this->signIn(
            [
                'sites' => [5 => ['domain' => self::OWN_DOMAIN, 'archived' => 0]] + self::sites([]),
                'members' => [5 => [7 => ['administrator']]],
                'site_meta' => [5 => [self::SUBJECT_META => 'sub-biber']],
                'refuse_site_updates' => true,
            ],
            [],
            true
        );

        self::assertSame(['subscriber'], $result['roles'][self::OWN_DOMAIN]);
    }

    public function testAForeignSiteOnTheOwnDomainGetsNoOwnerProtection(): void
    {
        $result = $this->signIn(
            [
                'sites' => [5 => ['domain' => self::OWN_DOMAIN, 'archived' => 0]] + self::sites([]),
                'members' => [5 => [7 => ['administrator']]],
                'site_meta' => [5 => [self::SUBJECT_META => 'sub-mapache']],
            ],
            [self::GROUPS . '/site-owner'],
            true
        );

        self::assertSame(['subscriber'], $result['roles'][self::OWN_DOMAIN]);
    }

    public function testTheFirstSignInOfASiteOwnerCreatesTheOwnSiteAndALaterOneCreatesNothing(): void
    {
        $first = $this->signIn(['sites' => self::sites([]), 'members' => [1 => [7 => ['subscriber']]]], [self::GROUPS . '/site-owner'], true);
        $second = $this->signIn($first['state'], [self::GROUPS . '/site-owner'], true);

        self::assertSame(['administrator'], $first['roles'][self::OWN_DOMAIN]);
        self::assertSame('sub-biber', $first['state']['site_meta'][4][self::SUBJECT_META]);
        self::assertSame($first['state']['sites'], $second['state']['sites']);
        self::assertSame(['administrator'], $second['roles'][self::OWN_DOMAIN]);
    }
}
