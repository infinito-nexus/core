<?php
namespace Joomla\Plugin\System\Keycloak\Extension;

defined('_JEXEC') or die;

use Joomla\CMS\Access\Access;
use Joomla\CMS\Application\CMSApplicationInterface;
use Joomla\CMS\Component\ComponentHelper;
use Joomla\CMS\Event\Model\NormaliseRequestDataEvent;
use Joomla\CMS\Event\Model\PrepareFormEvent;
use Joomla\CMS\Factory;
use Joomla\CMS\Filter\InputFilter;
use Joomla\CMS\Language\LanguageHelper;
use Joomla\CMS\Log\Log;
use Joomla\CMS\Plugin\CMSPlugin;
use Joomla\CMS\Session\Session;
use Joomla\CMS\String\PunycodeHelper;
use Joomla\CMS\User\User;
use Joomla\CMS\User\UserHelper;
use Joomla\Database\DatabaseInterface;
use Joomla\Database\ParameterType;
use Joomla\Event\Event;
use Joomla\Event\Priority;
use Joomla\Event\SubscriberInterface;
use Jumbojett\OpenIDConnectClient;

class Keycloak extends CMSPlugin implements SubscriberInterface
{
    protected $autoloadLanguage = true;
    protected ?CMSApplicationInterface $app = null;

    private const ENV_ISSUER          = 'JOOMLA_OIDC_ISSUER_URL';
    private const ENV_CLIENT_ID       = 'JOOMLA_OIDC_CLIENT_ID';
    private const ENV_CLIENT_SECRET   = 'JOOMLA_OIDC_CLIENT_SECRET';
    private const ENV_REDIRECT_URI    = 'JOOMLA_OIDC_REDIRECT_URI';
    private const ENV_REDIRECT_URIS   = 'JOOMLA_OIDC_REDIRECT_URIS';
    private const ENV_SOCKS_PROXY     = 'JOOMLA_OIDC_SOCKS_PROXY';
    private const ENV_FALLBACK        = 'JOOMLA_OIDC_FALLBACK_ENABLED';
    private const ENV_GROUP_MAP       = 'JOOMLA_OIDC_GROUP_MAP';
    private const ENV_LOGOUT_URL      = 'JOOMLA_OIDC_END_SESSION_URL';
    private const ENV_CLAIM_USERNAME  = 'JOOMLA_OIDC_CLAIM_USERNAME';
    private const ENV_CLAIM_EMAIL     = 'JOOMLA_OIDC_CLAIM_EMAIL';
    private const ENV_CLAIM_GIVEN     = 'JOOMLA_OIDC_CLAIM_GIVEN_NAME';
    private const ENV_CLAIM_FAMILY    = 'JOOMLA_OIDC_CLAIM_FAMILY_NAME';
    private const ENV_CLAIM_LOCALE    = 'JOOMLA_OIDC_CLAIM_LOCALE';
    private const ENV_CLAIM_ZONEINFO  = 'JOOMLA_OIDC_CLAIM_ZONEINFO';
    private const ENV_CLAIM_GROUPS    = 'JOOMLA_OIDC_CLAIM_GROUPS';
    private const ENV_CLAIM_ADDRESS   = 'JOOMLA_OIDC_CLAIM_ADDRESS';
    private const ENV_PROFILE_CLAIMS  = 'JOOMLA_OIDC_PROFILE_CLAIMS';
    private const ENV_PROFILE_ADDRESS = 'JOOMLA_OIDC_PROFILE_ADDRESS_FIELDS';
    private const ENV_PROFILE_LOCKED  = 'JOOMLA_OIDC_PROFILE_LOCKED';
    private const ENV_BOOTSTRAP_ADMIN = 'JOOMLA_ADMIN_USERNAME';

    private const JOOMLA_GROUP_SUPER = 8;

    private const PROFILE_FORM  = 'com_users.profile';
    private const PROFILE_KEY   = 'profile.';
    private const MANAGED_PARAM = 'keycloak_managed';
    private const SSO_SESSION   = 'keycloak.sso_session';
    private const LOCK_MARKER   = 'data-infinito-sso-locked';
    private const LOCKED_COLUMNS = [
        'name'     => ['field' => 'name', 'column' => 'name'],
        'username' => ['field' => 'username', 'column' => 'username'],
        'email'    => ['field' => 'email1', 'column' => 'email'],
    ];
    private const LOCKED_PARAMS = [
        'language' => 'language',
        'timezone' => 'timezone',
    ];
    private const LOCKED_ADDRESS = 'address';

    private bool $provisioning = false;

    /**
     * Returns:
     *   array: the events this plugin listens to; the profile form is locked after every other plugin, plg_user_profile
     *   included, has added its fields.
     */
    public static function getSubscribedEvents(): array
    {
        return [
            'onAfterInitialise'             => 'onAfterInitialise',
            'onAfterRoute'                  => 'onAfterRoute',
            'onContentPrepareForm'          => ['onContentPrepareForm', Priority::MIN],
            'onContentNormaliseRequestData' => 'onContentNormaliseRequestData',
            'onUserBeforeSave'              => 'onUserBeforeSave',
            'onUserAfterLogin'              => 'onUserAfterLogin',
        ];
    }

    public function setApplication(CMSApplicationInterface $app): void
    {
        $this->app = $app;
    }

    public function onAfterInitialise(Event $event): void
    {
        if ($this->app === null) {
            return;
        }
        try {
            $input = $this->app->getInput();
            $option = (string) $input->getCmd('option', '');
            $task   = (string) $input->getCmd('task', '');
            if ($option === 'keycloak') {
                $this->handleKeycloakRoute($task);
                return;
            }
            if ($this->shouldGuardRoute()) {
                $this->redirectToLogin();
            }
        } catch (\Throwable $ex) {
            Log::add(
                'plg_system_keycloak: ' . $ex->getMessage(),
                Log::ERROR,
                'plg_system_keycloak'
            );
        }
    }

    public function onAfterRoute(Event $event): void
    {
        if ($this->app === null || !$this->app->isClient('site')) {
            return;
        }
        $input = $this->app->getInput();
        if ((string) $input->getCmd('option', '') !== 'com_users' || (string) $input->getCmd('task', '') !== 'user.logout') {
            return;
        }
        $identity = $this->app->getIdentity();
        if ($identity === null || $identity->guest || !Session::checkToken('post')) {
            return;
        }
        $this->handleKeycloakRoute('logout');
    }

    public function onContentPrepareForm(PrepareFormEvent $event): void
    {
        $form = $event->getForm();
        if ($form->getName() !== self::PROFILE_FORM || $this->managedUser() === null) {
            return;
        }
        foreach ($this->lockedTargets()['fields'] as [$field, $group]) {
            $form->setFieldAttribute($field, 'readonly', 'true', $group);
            $form->setFieldAttribute($field, self::LOCK_MARKER, 'true', $group);
        }
    }

    /**
     * Args:
     *   $event: onUserBeforeSave; `subject` is the stored account, `data` the one about to be stored.
     * Raises:
     *   RuntimeException: an API request or a site request outside the break-glass session changes a column,
     *   parameter or plg_user_profile field that JOOMLA_OIDC_PROFILE_LOCKED locks, or the keycloak_managed marker, of
     *   an SSO account; the provisioning write of the callback, the console and the backend pass.
     */
    public function onUserBeforeSave(Event $event): void
    {
        if ($this->provisioning || $event->getArgument('isNew') || !$this->guardsSaves()) {
            return;
        }
        $stored = (array) $event->getArgument('subject');
        if (!self::isManagedRecord($stored['params'] ?? '')) {
            return;
        }
        $next    = (array) $event->getArgument('data');
        $changed = self::changedManagedFields(
            $stored,
            $next,
            is_array($next['profile'] ?? null) ? self::storedProfile((int) ($stored['id'] ?? 0)) : [],
            $this->lockedTargets()
        );
        if ($changed !== []) {
            throw new \RuntimeException('plg_system_keycloak: ' . implode(', ', $changed) . ' of an SSO account come from Keycloak');
        }
    }

    /**
     * Args:
     *   $event: onUserAfterLogin; the Keycloak callback signs in without $app->login(), so every login reported here
     *   is a local one (password, LDAP, passkey, remember-me cookie), and an SSO account other than the bootstrap
     *   administrator is signed out again and sent to Keycloak.
     */
    public function onUserAfterLogin(Event $event): void
    {
        if ($this->app === null || !($this->app->isClient('site') || $this->app->isClient('administrator'))) {
            return;
        }
        Factory::getSession()->clear(self::SSO_SESSION);
        $identity = $this->app->getIdentity();
        if ($identity === null || $identity->guest || (int) $identity->getParam(self::MANAGED_PARAM) !== 1) {
            return;
        }
        if ((string) $identity->username === $this->requireEnv(self::ENV_BOOTSTRAP_ADMIN)) {
            return;
        }
        Log::add('plg_system_keycloak: refused the local sign-in of the SSO account ' . $identity->username, Log::WARNING, 'plg_system_keycloak');
        $this->app->logout();
        $this->app->redirect('index.php?option=keycloak&task=login');
    }

    /**
     * Args:
     *   $stored: the stored account as onUserBeforeSave passes it, params as JSON.
     *   $next: the account about to be stored; `profile` holds the plg_user_profile fields the save writes.
     *   $storedProfile: the stored plg_user_profile fields of the account by key.
     *   $locked: lockTargets() of the locked keys.
     * Returns:
     *   string[]: the locked columns, parameters and profile fields and the keycloak_managed marker whose value
     *   differs.
     */
    public static function changedManagedFields(array $stored, array $next, array $storedProfile, array $locked): array
    {
        $changed = [];
        foreach ($locked['columns'] as $column) {
            if ((string) ($stored[$column] ?? '') !== (string) ($next[$column] ?? '')) {
                $changed[] = $column;
            }
        }
        $before = self::decodedParams($stored['params'] ?? '');
        $after  = self::decodedParams($next['params'] ?? '');
        foreach ([...$locked['params'], self::MANAGED_PARAM] as $param) {
            if ((string) ($before[$param] ?? '') !== (string) ($after[$param] ?? '')) {
                $changed[] = 'params.' . $param;
            }
        }
        $profile = is_array($next['profile'] ?? null) ? $next['profile'] : [];
        foreach ($locked['profile'] as $key) {
            if (array_key_exists($key, $profile) && self::text($storedProfile[$key] ?? '') !== self::text($profile[$key])) {
                $changed[] = self::PROFILE_KEY . $key;
            }
        }
        return $changed;
    }

    private static function text(mixed $value): string
    {
        return is_scalar($value) || $value === null ? (string) $value : (string) json_encode($value);
    }

    /**
     * Args:
     *   $userId: the account whose plg_user_profile fields are read.
     * Returns:
     *   array<string, mixed>: the stored fields by key, decoded as plg_user_profile decodes them.
     */
    private static function storedProfile(int $userId): array
    {
        $db    = Factory::getContainer()->get(DatabaseInterface::class);
        $like  = self::PROFILE_KEY . '%';
        $query = $db->getQuery(true)
            ->select($db->quoteName(['profile_key', 'profile_value']))
            ->from($db->quoteName('#__user_profiles'))
            ->where($db->quoteName('user_id') . ' = :id')
            ->where($db->quoteName('profile_key') . ' LIKE :prefix')
            ->bind(':id', $userId, ParameterType::INTEGER)
            ->bind(':prefix', $like, ParameterType::STRING);
        $profile = [];
        foreach ($db->setQuery($query)->loadRowList() as [$key, $value]) {
            $decoded = json_decode((string) $value, true);
            $profile[substr((string) $key, strlen(self::PROFILE_KEY))] = $decoded ?? $value;
        }
        return $profile;
    }

    /**
     * Args:
     *   $params: user params as JSON, as an array or as a Registry.
     * Returns:
     *   bool: whether the params mark an account Keycloak provisions.
     */
    public static function isManagedRecord(mixed $params): bool
    {
        return (int) (self::decodedParams($params)[self::MANAGED_PARAM] ?? 0) === 1;
    }

    private static function decodedParams(mixed $params): array
    {
        if (is_object($params) && method_exists($params, 'toArray')) {
            return $params->toArray();
        }
        if (is_array($params)) {
            return $params;
        }
        $decoded = json_decode((string) $params, true);
        return is_array($decoded) ? $decoded : [];
    }

    /**
     * Returns:
     *   bool: whether the current site session signed in through Keycloak; the callback runs on the site client, so
     *   a backend session never does.
     */
    private function ssoSession(): bool
    {
        if ($this->app === null || !$this->app->isClient('site')) {
            return false;
        }
        return (bool) Factory::getSession()->get(self::SSO_SESSION, false);
    }

    /**
     * Returns:
     *   bool: whether the signed-in site account edits Keycloak-managed fields as break-glass: a local session of the
     *   bootstrap administrator or of an account holding core.admin.
     */
    private function breakGlassSession(): bool
    {
        $identity = $this->app === null ? null : $this->app->getIdentity();
        if ($identity === null || $identity->guest || $this->ssoSession()) {
            return false;
        }
        return (string) $identity->username === $this->requireEnv(self::ENV_BOOTSTRAP_ADMIN) || $identity->authorise('core.admin');
    }

    /**
     * Returns:
     *   bool: whether a save may not change Keycloak-managed fields: every API request and every site request outside
     *   the break-glass session; the console and the backend may.
     */
    private function guardsSaves(): bool
    {
        if ($this->app === null) {
            return false;
        }
        return $this->app->isClient('api') || ($this->app->isClient('site') && !$this->breakGlassSession());
    }

    public function onContentNormaliseRequestData(NormaliseRequestDataEvent $event): void
    {
        $data = $event->getData();
        $user = $event->getForm()->getName() === self::PROFILE_FORM ? $this->managedUser() : null;
        if ($user === null || !is_object($data)) {
            return;
        }
        $locked = $this->lockedTargets();
        foreach ($locked['columns'] as $field => $column) {
            $data->{$field} = $user->{$column};
        }
        foreach ($locked['fields'] as [$field, $group]) {
            if ($group !== null && isset($data->{$group}) && is_array($data->{$group})) {
                unset($data->{$group}[$field]);
            }
        }
    }

    /**
     * Returns:
     *   ?User: the signed-in account when its profile comes from Keycloak and the session is not the break-glass one,
     *   null otherwise.
     */
    private function managedUser(): ?User
    {
        $identity = $this->app === null ? null : $this->app->getIdentity();
        if ($identity === null || $identity->guest || $this->breakGlassSession()) {
            return null;
        }
        $user = User::getInstance((int) $identity->id);
        return (int) $user->getParam(self::MANAGED_PARAM) === 1 ? $user : null;
    }

    /**
     * Returns:
     *   array: lockTargets() of the keys JOOMLA_OIDC_PROFILE_LOCKED lists, resolved against the profile claim maps.
     */
    private function lockedTargets(): array
    {
        return self::lockTargets(
            $this->lockedKeys(),
            $this->jsonEnv(self::ENV_PROFILE_CLAIMS),
            $this->jsonEnv(self::ENV_PROFILE_ADDRESS)
        );
    }

    /**
     * Returns:
     *   string[]: the sso.<claim> field keys of meta/forms.yml JOOMLA_OIDC_PROFILE_LOCKED lists; anything but a non-empty
     *   JSON list of non-empty strings raises.
     */
    private function lockedKeys(): array
    {
        $keys = json_decode($this->requireEnv(self::ENV_PROFILE_LOCKED), true);
        if (!is_array($keys) || $keys === [] || !array_is_list($keys)) {
            throw new \RuntimeException('plg_system_keycloak: ' . self::ENV_PROFILE_LOCKED . ' is not a non-empty JSON list');
        }
        foreach ($keys as $key) {
            if (!is_string($key) || $key === '') {
                throw new \RuntimeException('plg_system_keycloak: ' . self::ENV_PROFILE_LOCKED . ' lists ' . json_encode($key) . ', which names no field');
            }
        }
        return $keys;
    }

    /**
     * Args:
     *   $keys: sso.<claim> field keys of meta/forms.yml.
     *   $scalarClaims: plg_user_profile key => name of a string claim.
     *   $addressFields: plg_user_profile key => member of the address claim.
     * Returns:
     *   array: what the keys lock: `fields` the [field, group] pairs of the profile form, `columns` form field =>
     *   users column, `params` the user params, `profile` the plg_user_profile keys. `address` locks every key of
     *   $addressFields; a key outside LOCKED_COLUMNS and LOCKED_PARAMS locks the $scalarClaims key of its own name.
     * Raises:
     *   RuntimeException: a key names no column, param or profile field the login syncs.
     */
    public static function lockTargets(array $keys, array $scalarClaims, array $addressFields): array
    {
        $targets = ['fields' => [], 'columns' => [], 'params' => [], 'profile' => []];
        foreach ($keys as $key) {
            if (isset(self::LOCKED_COLUMNS[$key])) {
                ['field' => $field, 'column' => $column] = self::LOCKED_COLUMNS[$key];
                $targets['fields'][]        = [$field, null];
                $targets['columns'][$field] = $column;
                continue;
            }
            if (isset(self::LOCKED_PARAMS[$key])) {
                $targets['fields'][] = [self::LOCKED_PARAMS[$key], 'params'];
                $targets['params'][] = self::LOCKED_PARAMS[$key];
                continue;
            }
            $profileKeys = $key === self::LOCKED_ADDRESS ? array_keys($addressFields) : (array_key_exists($key, $scalarClaims) ? [$key] : []);
            if ($profileKeys === []) {
                throw new \RuntimeException('plg_system_keycloak: ' . self::ENV_PROFILE_LOCKED . ' names ' . $key . ', a field the login does not sync');
            }
            foreach ($profileKeys as $profileKey) {
                $targets['fields'][]  = [(string) $profileKey, 'profile'];
                $targets['profile'][] = (string) $profileKey;
            }
        }
        return $targets;
    }

    /**
     * Args:
     *   $name: environment variable carrying a JSON object.
     * Returns:
     *   array: the decoded, non-empty object; anything else raises.
     */
    private function jsonEnv(string $name): array
    {
        $value = json_decode($this->requireEnv($name), true);
        if (!is_array($value) || $value === []) {
            throw new \RuntimeException('plg_system_keycloak: ' . $name . ' is not a non-empty JSON object');
        }
        return $value;
    }

    /**
     * Args:
     *   $claims: verified ID token claims, nested objects decoded to arrays.
     *   $scalarClaims: plg_user_profile key => name of a string claim.
     *   $addressClaim: name of the structured address claim.
     *   $addressFields: plg_user_profile key => member of the address claim.
     * Returns:
     *   array<string, string>: every mapped profile key with its trimmed claim value, '' where the token carries none.
     */
    public static function profileFromClaims(array $claims, array $scalarClaims, string $addressClaim, array $addressFields): array
    {
        $address = is_array($claims[$addressClaim] ?? null) ? $claims[$addressClaim] : [];
        $profile = [];
        foreach ($scalarClaims as $key => $claim) {
            $profile[(string) $key] = self::scalar($claims[$claim] ?? null);
        }
        foreach ($addressFields as $key => $member) {
            $profile[(string) $key] = self::scalar($address[$member] ?? null);
        }
        return $profile;
    }

    private static function scalar(mixed $value): string
    {
        return is_scalar($value) ? trim((string) $value) : '';
    }

    private const FALLBACK_FLAG = 'keycloak.fallback_until';
    private const FALLBACK_TTL  = 600;

    /**
     * Args:
     *   $name: environment variable the container MUST carry.
     * Returns:
     *   string: its non-empty value; a missing or empty variable raises.
     */
    private function requireEnv(string $name): string
    {
        $value = getenv($name);
        if (!is_string($value) || $value === '') {
            throw new \RuntimeException('plg_system_keycloak: missing required env ' . $name);
        }
        return $value;
    }

    /**
     * Args:
     *   $name: environment variable that is only set in some deployments.
     * Returns:
     *   string: its value, or '' when the deployment does not set it.
     */
    private function optionalEnv(string $name): string
    {
        $value = getenv($name);
        return is_string($value) ? $value : '';
    }

    private function shouldGuardRoute(): bool
    {
        $user = Factory::getUser();
        if (!$user->guest) {
            return false;
        }
        if (strtolower($this->requireEnv(self::ENV_FALLBACK)) !== 'true') {
            return true;
        }
        $input = $this->app->getInput();
        $fallbackRequested = (string) $input->getCmd('fallback', '') === 'local';
        $session = Factory::getSession();
        if ($fallbackRequested) {
            $session->set(self::FALLBACK_FLAG, time() + self::FALLBACK_TTL);
            return false;
        }
        $fallbackUntil = (int) $session->get(self::FALLBACK_FLAG, 0);
        if ($fallbackUntil > time()) {
            return false;
        }
        if ($fallbackUntil) {
            $session->clear(self::FALLBACK_FLAG);
        }
        return true;
    }

    private function redirectToLogin(): void
    {
        $current = (string) $this->app->getInput()->server->getString('REQUEST_URI', '/');
        $session = Factory::getSession();
        $session->set('keycloak.return_to', $current);
        $this->app->redirect('index.php?option=keycloak&task=login');
    }

    private function handleKeycloakRoute(string $task): void
    {
        $this->loadAutoloader();
        try {
            switch ($task) {
                case 'login':
                    $this->buildOidcClient()->authenticate();
                    return;
                case 'callback':
                    $this->handleCallback();
                    return;
                case 'logout':
                    $this->handleLogout();
                    return;
                default:
                    $this->app->redirect('index.php?fallback=local');
            }
        } catch (\Throwable $ex) {
            Log::add(
                'plg_system_keycloak callback error: ' . $ex->getMessage(),
                Log::ERROR,
                'plg_system_keycloak'
            );
            $this->app->enqueueMessage('SSO error: ' . $ex->getMessage(), 'error');
            $this->app->redirect('index.php?fallback=local');
        }
    }

    private function loadAutoloader(): void
    {
        $autoloader = JPATH_PLUGINS . '/system/keycloak/vendor/autoload.php';
        if (file_exists($autoloader)) {
            require_once $autoloader;
        }
    }

    private function buildOidcClient(): OpenIDConnectClient
    {
        $client = new OpenIDConnectClient(
            $this->requireEnv(self::ENV_ISSUER),
            $this->requireEnv(self::ENV_CLIENT_ID),
            $this->requireEnv(self::ENV_CLIENT_SECRET)
        );
        $socksProxy = $this->optionalEnv(self::ENV_SOCKS_PROXY);
        if ($socksProxy !== '') {
            $client->setHttpProxy($socksProxy);
        }
        $client->setRedirectURL($this->redirectUriForRequest($this->requireEnv(self::ENV_REDIRECT_URI)));
        $client->addScope(['openid', 'profile', 'email', 'phone', 'address', $this->requireEnv(self::ENV_CLAIM_GROUPS)]);
        $client->setVerifyHost(true);
        $client->setVerifyPeer(true);
        $caPath = $this->resolveCaBundlePath();
        if ($caPath !== '') {
            $client->setCertPath($caPath);
        }
        return $client;
    }

    /**
     * Args:
     *   $configured: redirect URI of the canonical domain.
     * Returns:
     *   string: the redirect URI of the network sibling the request reached; $configured when it reached none.
     */
    private function redirectUriForRequest(string $configured): string
    {
        $siblings = json_decode($this->requireEnv(self::ENV_REDIRECT_URIS), true);
        if (!is_array($siblings) || $siblings === []) {
            throw new \RuntimeException('plg_system_keycloak: ' . self::ENV_REDIRECT_URIS . ' is not a non-empty JSON list');
        }
        return self::redirectUriForHost(
            (string) $this->app->getInput()->server->getString('HTTP_HOST', ''),
            $siblings,
            $configured
        );
    }

    /**
     * Args:
     *   $host: Host header of the request, with its port when it names one.
     *   $siblings: the redirect URI on every network sibling, each with the scheme of that sibling.
     *   $configured: redirect URI of the canonical domain.
     * Returns:
     *   string: the sibling whose authority is $host; $configured when none is.
     */
    public static function redirectUriForHost(string $host, array $siblings, string $configured): string
    {
        foreach ($siblings as $sibling) {
            $parts     = parse_url((string) $sibling);
            $authority = ($parts['host'] ?? '') . (isset($parts['port']) ? ':' . $parts['port'] : '');
            if ($host !== '' && strcasecmp($authority, $host) === 0) {
                return (string) $sibling;
            }
        }
        return $configured;
    }

    /**
     * Resolve the CA bundle for the server-side OIDC discovery cURL.
     *
     * The sys-svc-compose-ca override reliably bind-mounts the Infinito
     * root CA and exports CURL_CA_BUNDLE/CA_TRUST_CERT/SSL_CERT_FILE to
     * point at it, even when the CA-trust entrypoint wrapper was not
     * applied (e.g. locally-built image absent at inject time). Where
     * none of them is set there is no internal CA to trust, so the
     * caller keeps the client's own default rather than the OS bundle.
     */
    private function resolveCaBundlePath(): string
    {
        foreach (['CURL_CA_BUNDLE', 'CA_TRUST_CERT', 'SSL_CERT_FILE'] as $variable) {
            $candidate = $this->optionalEnv($variable);
            if ($candidate !== '' && is_file($candidate)) {
                return $candidate;
            }
        }
        return '';
    }

    /**
     * Args:
     *   $oidc: client that completed the authorization-code exchange.
     *   $variable: environment variable naming the claim.
     * Returns:
     *   string: the claim value, or '' when the ID token does not carry it.
     */
    private function stringClaim(OpenIDConnectClient $oidc, string $variable): string
    {
        $value = $oidc->getVerifiedClaims($this->requireEnv($variable));
        return is_scalar($value) ? trim((string) $value) : '';
    }

    private function handleCallback(): void
    {
        $oidc = $this->buildOidcClient();
        $oidc->authenticate();

        $username = $this->stringClaim($oidc, self::ENV_CLAIM_USERNAME);
        $email    = $this->stringClaim($oidc, self::ENV_CLAIM_EMAIL);
        $given    = $this->stringClaim($oidc, self::ENV_CLAIM_GIVEN);
        $family   = $this->stringClaim($oidc, self::ENV_CLAIM_FAMILY);
        $groups   = (array) ($oidc->getVerifiedClaims($this->requireEnv(self::ENV_CLAIM_GROUPS)) ?? []);

        if ($username === '') {
            throw new \RuntimeException('Keycloak callback: the ID token carries no ' . $this->requireEnv(self::ENV_CLAIM_USERNAME) . ' claim');
        }
        if ($email === '') {
            $email = $username . '@kc.local';
        }
        $email = PunycodeHelper::emailToPunycode($email);
        $name  = trim((string) (new InputFilter())->clean($given . ' ' . $family, 'string')) ?: $username;

        $mappedGroups = $this->mapGroupsToJoomla($groups);
        if ($username === $this->requireEnv(self::ENV_BOOTSTRAP_ADMIN) && !in_array(self::JOOMLA_GROUP_SUPER, $mappedGroups, true)) {
            $mappedGroups[] = self::JOOMLA_GROUP_SUPER;
        }
        $language = $this->resolveLanguage($this->stringClaim($oidc, self::ENV_CLAIM_LOCALE));
        $timezone = $this->resolveTimezone($this->stringClaim($oidc, self::ENV_CLAIM_ZONEINFO));
        $profile  = self::profileFromClaims(
            json_decode((string) json_encode($oidc->getVerifiedClaims()), true) ?: [],
            $this->jsonEnv(self::ENV_PROFILE_CLAIMS),
            $this->requireEnv(self::ENV_CLAIM_ADDRESS),
            $this->jsonEnv(self::ENV_PROFILE_ADDRESS)
        );

        $user = $this->withProvisioningIdentity(
            function () use ($username, $email, $name, $mappedGroups, $language, $timezone, $profile): User {
                $userId = (int) UserHelper::getUserId($username);
                if ($userId === 0) {
                    $userId = $this->createJoomlaUser($username, $email, $name, $mappedGroups);
                }
                $user = User::getInstance($userId);
                $user->name    = $name;
                $user->email   = $email;
                $user->groups  = $mappedGroups;
                $user->profile = $profile;
                $user->setParam('language', $language);
                $user->setParam('timezone', $timezone);
                $user->setParam(self::MANAGED_PARAM, 1);
                if (!$user->save()) {
                    throw new \RuntimeException('Keycloak: failed to update Joomla user: ' . implode(' ', $user->getErrors()));
                }
                return $user;
            }
        );

        $session = Factory::getSession();
        $session->fork();
        $session->set('user', $user);
        $session->set(self::SSO_SESSION, true);
        $this->app->loadIdentity($user);
        $this->app->checkSession();

        $returnTo = (string) ($session->get('keycloak.return_to', 'index.php'));
        $session->clear('keycloak.return_to');
        $this->app->redirect($returnTo);
    }

    /**
     * Args:
     *   $operation: callable performing the provisioning writes.
     * Returns:
     *   User: the provisioned account returned by the callable.
     */
    private function withProvisioningIdentity(callable $operation): User
    {
        $session          = Factory::getSession();
        $previousUser     = $session->get('user');
        $previousIdentity = $this->app->getIdentity();
        $provisioner      = $this->resolveProvisioningIdentity();

        $session->set('user', $provisioner);
        $this->app->loadIdentity($provisioner);
        $this->provisioning = true;
        try {
            return $operation();
        } finally {
            $this->provisioning = false;
            $session->set('user', $previousUser);
            $this->app->loadIdentity($previousIdentity);
        }
    }

    private function resolveProvisioningIdentity(): User
    {
        foreach (Access::getUsersByGroup(self::JOOMLA_GROUP_SUPER) as $candidateId) {
            $candidateId = (int) $candidateId;
            if ($candidateId > 0 && Access::check($candidateId, 'core.admin')) {
                return User::getInstance($candidateId);
            }
        }
        throw new \RuntimeException('Keycloak: no Super User account available to provision the SSO account');
    }

    private function createJoomlaUser(string $username, string $email, string $name, array $groups): int
    {
        $user = new User();
        $user->set('username',       $username);
        $user->set('email',          $email);
        $user->set('name',           $name);
        $user->set('password_clear', UserHelper::genRandomPassword(32));
        $user->set('block',          0);
        $user->set('groups',         $groups);
        if (!$user->save()) {
            throw new \RuntimeException('Keycloak: failed to create Joomla user: ' . implode(' ', $user->getErrors()));
        }
        return (int) $user->id;
    }

    /**
     * Args:
     *   $kcGroups: group paths of the groups claim.
     * Returns:
     *   int[]: the mapped Joomla usergroup IDs; the com_users registration group when none maps.
     */
    private function mapGroupsToJoomla(array $kcGroups): array
    {
        $map = json_decode($this->requireEnv(self::ENV_GROUP_MAP), true);
        if (!is_array($map) || $map === []) {
            throw new \RuntimeException('plg_system_keycloak: ' . self::ENV_GROUP_MAP . ' is not a JSON object of group path to usergroup ID');
        }

        $mapped = [];
        foreach ($kcGroups as $group) {
            $path = '/' . ltrim((string) $group, '/');
            if (array_key_exists($path, $map)) {
                $mapped[] = (int) $map[$path];
            }
        }
        if ($mapped === []) {
            $registration = (int) ComponentHelper::getParams('com_users')->get('new_usertype');
            if ($registration <= 0) {
                throw new \RuntimeException('plg_system_keycloak: com_users carries no New User Registration Group');
            }
            $mapped[] = $registration;
        }
        return array_values(array_unique($mapped));
    }

    /**
     * Args:
     *   $locale: BCP 47 locale claim such as "de" or "en-GB".
     * Returns:
     *   string: the installed site language tag it names, or '' for the site default.
     */
    private function resolveLanguage(string $locale): string
    {
        $wanted = strtolower(str_replace('_', '-', $locale));
        if ($wanted === '') {
            return '';
        }
        $tags = array_keys(LanguageHelper::getKnownLanguages(JPATH_SITE));
        foreach ($tags as $tag) {
            if (strtolower($tag) === $wanted) {
                return $tag;
            }
        }
        $primary = explode('-', $wanted)[0];
        foreach ($tags as $tag) {
            if (strtolower(explode('-', $tag)[0]) === $primary) {
                return $tag;
            }
        }
        return '';
    }

    /**
     * Args:
     *   $zoneinfo: IANA time zone claim such as "Europe/Berlin".
     * Returns:
     *   string: the zone when PHP knows it, or '' for the site default.
     */
    private function resolveTimezone(string $zoneinfo): string
    {
        return in_array($zoneinfo, \DateTimeZone::listIdentifiers(), true) ? $zoneinfo : '';
    }

    private function handleLogout(): void
    {
        $this->app->logout();
        $this->app->redirect($this->requireEnv(self::ENV_LOGOUT_URL));
    }
}
