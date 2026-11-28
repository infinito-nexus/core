<?php

declare(strict_types=1);

namespace Joomla\CMS\Plugin {
    if (!class_exists(CMSPlugin::class, false)) {
        abstract class CMSPlugin
        {
        }
    }
}

namespace Joomla\Event {
    if (!interface_exists(SubscriberInterface::class, false)) {
        interface SubscriberInterface
        {
            public static function getSubscribedEvents(): array;
        }
    }

    if (!class_exists(Priority::class, false)) {
        final class Priority
        {
            public const MIN = -3;
            public const NORMAL = 0;
        }
    }
}

namespace {
    use Joomla\Event\Priority;
    use Joomla\Plugin\System\Keycloak\Extension\Keycloak;
    use PHPUnit\Framework\TestCase;

    final class KeycloakTest extends TestCase
    {
        private const PLUGIN = '/roles/web-app-joomla/files/joomla-oidc-plugin/plg_system_keycloak/src/Extension/Keycloak.php';

        private const TRIMMED = [
            'JOOMLA_OIDC_GROUP_MAP',
            'JOOMLA_OIDC_PROFILE_CLAIMS',
            'JOOMLA_OIDC_PROFILE_ADDRESS_FIELDS',
            'JOOMLA_OIDC_PROFILE_LOCKED',
            'JOOMLA_OIDC_ISSUER_URL',
            'JOOMLA_ADMIN_USERNAME',
        ];

        private const LOCKED = ['name', 'username', 'email', 'language', 'timezone', 'phone', 'website', 'address'];

        private const SCALAR_CLAIMS = ['phone' => 'phone_number', 'website' => 'website'];

        private const ADDRESS_FIELDS = [
            'address1' => 'street_address',
            'city' => 'locality',
            'region' => 'region',
            'postal_code' => 'postal_code',
            'country' => 'country',
        ];

        public static function setUpBeforeClass(): void
        {
            if (!defined('_JEXEC')) {
                define('_JEXEC', 1);
            }
            require_once dirname(__DIR__, 10) . self::PLUGIN;
        }

        protected function tearDown(): void
        {
            foreach (self::TRIMMED as $name) {
                putenv($name);
            }
        }

        private function call(string $method, mixed ...$arguments): mixed
        {
            $plugin = (new ReflectionClass(Keycloak::class))->newInstanceWithoutConstructor();
            $reflection = new ReflectionMethod(Keycloak::class, $method);

            return $reflection->invoke($plugin, ...$arguments);
        }

        private static function locked(array $keys): array
        {
            return Keycloak::lockTargets($keys, self::SCALAR_CLAIMS, self::ADDRESS_FIELDS);
        }

        public function testAMissingVariableRaisesAndNamesIt(): void
        {
            putenv('JOOMLA_OIDC_ISSUER_URL');

            $this->expectException(RuntimeException::class);
            $this->expectExceptionMessage('JOOMLA_OIDC_ISSUER_URL');

            $this->call('requireEnv', 'JOOMLA_OIDC_ISSUER_URL');
        }

        public function testAnEmptyVariableRaisesInsteadOfFallingBack(): void
        {
            putenv('JOOMLA_OIDC_ISSUER_URL=');

            $this->expectException(RuntimeException::class);

            $this->call('requireEnv', 'JOOMLA_OIDC_ISSUER_URL');
        }

        public function testASetVariableIsReturnedVerbatim(): void
        {
            putenv('JOOMLA_OIDC_ISSUER_URL=https://auth.example/realms/main');

            self::assertSame('https://auth.example/realms/main', $this->call('requireEnv', 'JOOMLA_OIDC_ISSUER_URL'));
        }

        public function testAGroupMapThatIsNoObjectRaises(): void
        {
            putenv('JOOMLA_OIDC_GROUP_MAP=[]');

            $this->expectException(RuntimeException::class);
            $this->expectExceptionMessage('JOOMLA_OIDC_GROUP_MAP');

            $this->call('mapGroupsToJoomla', ['/roles/web-app-joomla/editor']);
        }

        public function testGroupPathsMapWithOrWithoutTheirLeadingSlashOnce(): void
        {
            putenv('JOOMLA_OIDC_GROUP_MAP=' . json_encode(['/roles/web-app-joomla/editor' => 4, '/roles/web-app-joomla/manager' => 6]));

            self::assertSame(
                [4, 6],
                $this->call('mapGroupsToJoomla', ['/roles/web-app-joomla/editor', 'roles/web-app-joomla/editor', '/roles/web-app-joomla/manager', '/unrelated'])
            );
        }

        public function testTheBootstrapAdministratorKeepsSuperUsersWithoutTheAdministratorGroup(): void
        {
            putenv('JOOMLA_OIDC_GROUP_MAP=' . json_encode(['/roles/web-app-joomla/editor' => 4, '/roles/web-app-joomla/administrator' => 8]));
            putenv('JOOMLA_ADMIN_USERNAME=platformadmin');

            self::assertSame([4, 8], $this->call('groupsForLogin', 'platformadmin', ['/roles/web-app-joomla/editor']));
        }

        public function testAnotherAccountWithoutTheAdministratorGroupGetsNoSuperUsers(): void
        {
            putenv('JOOMLA_OIDC_GROUP_MAP=' . json_encode(['/roles/web-app-joomla/editor' => 4, '/roles/web-app-joomla/administrator' => 8]));
            putenv('JOOMLA_ADMIN_USERNAME=platformadmin');

            self::assertSame([4], $this->call('groupsForLogin', 'biber', ['/roles/web-app-joomla/editor']));
        }

        public function testTheBootstrapAdministratorInTheAdministratorGroupHoldsSuperUsersOnce(): void
        {
            putenv('JOOMLA_OIDC_GROUP_MAP=' . json_encode(['/roles/web-app-joomla/administrator' => 8]));
            putenv('JOOMLA_ADMIN_USERNAME=platformadmin');

            self::assertSame([8], $this->call('groupsForLogin', 'platformadmin', ['/roles/web-app-joomla/administrator']));
        }

        public function testAnEmptyProfileClaimMapRaises(): void
        {
            putenv('JOOMLA_OIDC_PROFILE_CLAIMS={}');

            $this->expectException(RuntimeException::class);
            $this->expectExceptionMessage('JOOMLA_OIDC_PROFILE_CLAIMS');

            $this->call('jsonEnv', 'JOOMLA_OIDC_PROFILE_CLAIMS');
        }

        public function testPhoneWebsiteAndAddressClaimsFillTheirProfileKeys(): void
        {
            $claims = [
                'phone_number' => ' +49 40 1234 ',
                'website' => 'https://biber.example',
                'address' => [
                    'street_address' => 'Dammweg 1',
                    'locality' => 'Hamburg',
                    'region' => 'HH',
                    'postal_code' => '20095',
                    'country' => 'DE',
                ],
            ];

            self::assertSame(
                [
                    'phone' => '+49 40 1234',
                    'website' => 'https://biber.example',
                    'address1' => 'Dammweg 1',
                    'city' => 'Hamburg',
                    'region' => 'HH',
                    'postal_code' => '20095',
                    'country' => 'DE',
                ],
                Keycloak::profileFromClaims($claims, self::SCALAR_CLAIMS, 'address', self::ADDRESS_FIELDS)
            );
        }

        public function testAbsentClaimsClearTheirProfileKeys(): void
        {
            $profile = Keycloak::profileFromClaims(
                ['website' => ['not', 'a', 'string'], 'address' => 'not an object'],
                self::SCALAR_CLAIMS,
                'address',
                self::ADDRESS_FIELDS
            );

            self::assertSame(array_fill_keys(['phone', 'website', 'address1', 'city', 'region', 'postal_code', 'country'], ''), $profile);
        }

        public function testTheConfiguredKeysLockTheColumnsParamsAndEverySyncedProfileField(): void
        {
            self::assertSame(
                [
                    'fields' => [
                        ['name', null],
                        ['username', null],
                        ['email1', null],
                        ['language', 'params'],
                        ['timezone', 'params'],
                        ['phone', 'profile'],
                        ['website', 'profile'],
                        ['address1', 'profile'],
                        ['city', 'profile'],
                        ['region', 'profile'],
                        ['postal_code', 'profile'],
                        ['country', 'profile'],
                    ],
                    'columns' => ['name' => 'name', 'username' => 'username', 'email1' => 'email'],
                    'params' => ['language', 'timezone'],
                    'profile' => ['phone', 'website', 'address1', 'city', 'region', 'postal_code', 'country'],
                ],
                self::locked(self::LOCKED)
            );
        }

        public function testTheLockedKeysAreReadFromTheEnvironment(): void
        {
            putenv('JOOMLA_OIDC_PROFILE_CLAIMS=' . json_encode(self::SCALAR_CLAIMS));
            putenv('JOOMLA_OIDC_PROFILE_ADDRESS_FIELDS=' . json_encode(self::ADDRESS_FIELDS));
            putenv('JOOMLA_OIDC_PROFILE_LOCKED=' . json_encode(['email', 'website']));

            self::assertSame(self::locked(['email', 'website']), $this->call('lockedTargets'));
        }

        public function testARemovedKeyUnlocksItsField(): void
        {
            $locked = self::locked(array_values(array_diff(self::LOCKED, ['email', 'timezone', 'phone'])));

            self::assertNotContains(['email1', null], $locked['fields']);
            self::assertNotContains(['timezone', 'params'], $locked['fields']);
            self::assertNotContains(['phone', 'profile'], $locked['fields']);
            self::assertArrayNotHasKey('email1', $locked['columns']);
            self::assertNotContains('timezone', $locked['params']);
            self::assertNotContains('phone', $locked['profile']);
        }

        public function testRemovingTheAddressUnlocksEveryAddressField(): void
        {
            $locked = self::locked(array_values(array_diff(self::LOCKED, ['address'])));

            self::assertSame(['phone', 'website'], $locked['profile']);
            foreach (array_keys(self::ADDRESS_FIELDS) as $key) {
                self::assertNotContains([$key, 'profile'], $locked['fields']);
            }
        }

        public function testAnUnknownKeyRaisesAndNamesIt(): void
        {
            $this->expectException(RuntimeException::class);
            $this->expectExceptionMessage('nickname');

            self::locked(['name', 'nickname']);
        }

        public function testAProfileKeyTheClaimMapsDoNotSyncRaises(): void
        {
            $this->expectException(RuntimeException::class);
            $this->expectExceptionMessage('website');

            Keycloak::lockTargets(['website'], ['phone' => 'phone_number'], self::ADDRESS_FIELDS);
        }

        public function testAnEmptyLockedListRaises(): void
        {
            putenv('JOOMLA_OIDC_PROFILE_LOCKED=[]');

            $this->expectException(RuntimeException::class);
            $this->expectExceptionMessage('JOOMLA_OIDC_PROFILE_LOCKED');

            $this->call('lockedKeys');
        }

        public function testALockedObjectInsteadOfAListRaises(): void
        {
            putenv('JOOMLA_OIDC_PROFILE_LOCKED=' . json_encode(['name' => '#jform_name']));

            $this->expectException(RuntimeException::class);
            $this->expectExceptionMessage('JOOMLA_OIDC_PROFILE_LOCKED');

            $this->call('lockedKeys');
        }

        public function testALockedListThatIsNoJsonRaises(): void
        {
            putenv('JOOMLA_OIDC_PROFILE_LOCKED=name,email');

            $this->expectException(RuntimeException::class);
            $this->expectExceptionMessage('JOOMLA_OIDC_PROFILE_LOCKED');

            $this->call('lockedKeys');
        }

        public function testALockedEntryThatIsNoNameRaises(): void
        {
            putenv('JOOMLA_OIDC_PROFILE_LOCKED=' . json_encode(['name', 3]));

            $this->expectException(RuntimeException::class);
            $this->expectExceptionMessage('JOOMLA_OIDC_PROFILE_LOCKED');

            $this->call('lockedKeys');
        }

        public function testAMissingLockedListRaises(): void
        {
            putenv('JOOMLA_OIDC_PROFILE_LOCKED');

            $this->expectException(RuntimeException::class);
            $this->expectExceptionMessage('JOOMLA_OIDC_PROFILE_LOCKED');

            $this->call('lockedKeys');
        }

        public function testTheProfileFormIsLockedAfterEveryOtherListener(): void
        {
            $events = Keycloak::getSubscribedEvents();

            self::assertSame(['onContentPrepareForm', Priority::MIN], $events['onContentPrepareForm']);
            self::assertSame('onAfterRoute', $events['onAfterRoute']);
            self::assertSame('onContentNormaliseRequestData', $events['onContentNormaliseRequestData']);
            self::assertSame('onUserBeforeSave', $events['onUserBeforeSave']);
        }

        public function testEveryLocalLoginIsCheckedForAnSsoAccount(): void
        {
            self::assertSame('onUserAfterLogin', Keycloak::getSubscribedEvents()['onUserAfterLogin']);
        }

        public function testAnUnchangedSsoAccountHasNoChangedManagedField(): void
        {
            $stored = ['name' => 'Biber', 'username' => 'biber', 'email' => 'biber@example.org', 'params' => '{"language":"en-GB","timezone":"UTC","keycloak_managed":1,"editor":"tinymce"}'];
            $next   = ['params' => '{"language":"en-GB","timezone":"UTC","keycloak_managed":1,"editor":"none"}', 'profile' => ['phone' => '+49 40 1234', 'aboutme' => 'edited']] + $stored;

            self::assertSame([], Keycloak::changedManagedFields($stored, $next, ['phone' => '+49 40 1234', 'aboutme' => 'old'], self::locked(self::LOCKED)));
        }

        public function testEveryManagedColumnAndParamIsReportedWhenItChanges(): void
        {
            $stored = ['name' => 'Biber', 'username' => 'biber', 'email' => 'biber@example.org', 'params' => '{"language":"en-GB","timezone":"UTC","keycloak_managed":1}'];
            $next   = ['name' => 'Other', 'username' => 'renamed', 'email' => 'other@example.org', 'params' => '{"language":"de-DE","timezone":"Europe/Berlin"}'];

            self::assertSame(
                ['name', 'username', 'email', 'params.language', 'params.timezone', 'params.keycloak_managed'],
                Keycloak::changedManagedFields($stored, $next, [], self::locked(self::LOCKED))
            );
        }

        public function testAChangeOfAnUnlockedFieldPassesWhileTheMarkerStaysGuarded(): void
        {
            $stored = ['name' => 'Biber', 'username' => 'biber', 'email' => 'biber@example.org', 'params' => '{"language":"en-GB","timezone":"UTC","keycloak_managed":1}'];
            $next   = ['name' => 'Other', 'username' => 'renamed', 'email' => 'other@example.org', 'params' => '{"language":"de-DE","timezone":"Europe/Berlin"}', 'profile' => ['phone' => '+49 40 9999']];

            self::assertSame(
                ['username', 'params.keycloak_managed'],
                Keycloak::changedManagedFields($stored, $next, ['phone' => '+49 40 1234'], self::locked(['username', 'website']))
            );
        }

        public function testAChangedManagedProfileFieldIsReported(): void
        {
            $stored = ['name' => 'Biber', 'username' => 'biber', 'email' => 'biber@example.org', 'params' => '{"keycloak_managed":1}'];
            $next   = ['profile' => ['phone' => '+49 40 9999', 'city' => 'Hamburg', 'website' => 'https://tampered.example']] + $stored;

            self::assertSame(
                ['profile.phone', 'profile.website'],
                Keycloak::changedManagedFields($stored, $next, ['phone' => '+49 40 1234', 'city' => 'Hamburg'], self::locked(self::LOCKED))
            );
        }

        public function testASaveWithoutProfileFieldsKeepsTheStoredProfile(): void
        {
            $stored = ['name' => 'Biber', 'username' => 'biber', 'email' => 'biber@example.org', 'params' => '{"keycloak_managed":1}'];

            self::assertSame([], Keycloak::changedManagedFields($stored, $stored, ['phone' => '+49 40 1234'], self::locked(self::LOCKED)));
        }

        public function testOnlyAnAccountCarryingTheMarkerIsManaged(): void
        {
            self::assertTrue(Keycloak::isManagedRecord('{"keycloak_managed":1}'));
            self::assertTrue(Keycloak::isManagedRecord(['keycloak_managed' => '1']));
            self::assertFalse(Keycloak::isManagedRecord('{"language":"en-GB"}'));
            self::assertFalse(Keycloak::isManagedRecord(''));
        }

        public function testTheRedirectUriFollowsTheSiblingTheRequestReached(): void
        {
            $siblings = [
                'https://joomla.example.org/index.php?option=keycloak&task=callback',
                'http://joomla.' . str_repeat('a', 56) . '.onion/index.php?option=keycloak&task=callback',
            ];

            self::assertSame($siblings[1], Keycloak::redirectUriForHost('JOOMLA.' . str_repeat('a', 56) . '.onion', $siblings, $siblings[0]));
            self::assertSame($siblings[0], Keycloak::redirectUriForHost('joomla.example.org', $siblings, $siblings[0]));
        }

        public function testAHostOutsideTheSiblingsKeepsTheConfiguredRedirectUri(): void
        {
            $siblings = ['https://joomla.example.org/index.php?option=keycloak&task=callback'];

            self::assertSame($siblings[0], Keycloak::redirectUriForHost('intruder.' . str_repeat('b', 56) . '.onion', $siblings, $siblings[0]));
            self::assertSame($siblings[0], Keycloak::redirectUriForHost('', $siblings, $siblings[0]));
        }

        public function testAPortIsPartOfTheSiblingAuthority(): void
        {
            $siblings = ['https://joomla.example.org:8443/index.php?option=keycloak&task=callback'];

            self::assertSame($siblings[0], Keycloak::redirectUriForHost('joomla.example.org:8443', $siblings, 'configured'));
            self::assertSame('configured', Keycloak::redirectUriForHost('joomla.example.org', $siblings, 'configured'));
        }
    }
}
