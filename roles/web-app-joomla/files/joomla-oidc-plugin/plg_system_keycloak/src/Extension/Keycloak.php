<?php
namespace Joomla\Plugin\System\Keycloak\Extension;

defined('_JEXEC') or die;

use Joomla\CMS\Application\CMSApplicationInterface;
use Joomla\CMS\Factory;
use Joomla\CMS\Log\Log;
use Joomla\CMS\Plugin\CMSPlugin;
use Joomla\CMS\User\User;
use Joomla\CMS\User\UserHelper;
use Joomla\Event\Event;
use Jumbojett\OpenIDConnectClient;

/**
 * Native OIDC SSO against Keycloak for Joomla 6.
 *
 * Modus 3 ("Force-Frontend, Local-Backup-Backend") per the project's
 * RBAC requirement 013: every visit to "/" or "/administrator" is
 * redirected to Keycloak unless the request explicitly carries the
 * `?fallback=local` query AND the env-var
 * JOOMLA_OIDC_FALLBACK_ENABLED is "true".
 *
 * Keycloak-Group-Paths are mapped onto Joomla's standard usergroup
 * IDs (8 = Super Users, 4 = Editor, 2 = Registered) via the env-vars
 * JOOMLA_OIDC_GROUP_{ADMIN,EDITOR,USER}. A user whose Keycloak groups
 * match none of those paths is refused; this is the documented RBAC
 * gate per requirement 013.
 */
class Keycloak extends CMSPlugin
{
    protected $autoloadLanguage = true;
    protected ?CMSApplicationInterface $app = null;

    private const ENV_ISSUER         = 'JOOMLA_OIDC_ISSUER_URL';
    private const ENV_CLIENT_ID      = 'JOOMLA_OIDC_CLIENT_ID';
    private const ENV_CLIENT_SECRET  = 'JOOMLA_OIDC_CLIENT_SECRET';
    private const ENV_REDIRECT_URI   = 'JOOMLA_OIDC_REDIRECT_URI';
    private const ENV_SOCKS_PROXY    = 'JOOMLA_OIDC_SOCKS_PROXY';
    private const ENV_FALLBACK       = 'JOOMLA_OIDC_FALLBACK_ENABLED';
    private const ENV_GROUP_ADMIN    = 'JOOMLA_OIDC_GROUP_ADMIN';
    private const ENV_GROUP_EDITOR   = 'JOOMLA_OIDC_GROUP_EDITOR';
    private const ENV_GROUP_USER     = 'JOOMLA_OIDC_GROUP_USER';
    private const ENV_LOGOUT_URL     = 'JOOMLA_OIDC_END_SESSION_URL';

    private const JOOMLA_GROUP_SUPER      = 8;
    private const JOOMLA_GROUP_EDITOR     = 4;
    private const JOOMLA_GROUP_REGISTERED = 2;

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

    private const FALLBACK_FLAG = 'keycloak.fallback_until';
    private const FALLBACK_TTL  = 600;

    private function shouldGuardRoute(): bool
    {
        $user = Factory::getUser();
        if (!$user->guest) {
            return false;
        }
        $fallbackEnabled = strtolower(getenv(self::ENV_FALLBACK) ?: 'true') === 'true';
        if (!$fallbackEnabled) {
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
        $issuer       = (string) (getenv(self::ENV_ISSUER) ?: '');
        $clientId     = (string) (getenv(self::ENV_CLIENT_ID) ?: '');
        $clientSecret = (string) (getenv(self::ENV_CLIENT_SECRET) ?: '');
        $redirectUri  = (string) (getenv(self::ENV_REDIRECT_URI) ?: '');
        if ($issuer === '' || $clientId === '' || $clientSecret === '' || $redirectUri === '') {
            throw new \RuntimeException(
                'plg_system_keycloak: missing required env (issuer, client_id, client_secret, redirect_uri)'
            );
        }
        $client = new OpenIDConnectClient($issuer, $clientId, $clientSecret);
        $socksProxy = (string) (getenv(self::ENV_SOCKS_PROXY) ?: '');
        if ($socksProxy !== '') {
            $client->setHttpProxy($socksProxy);
        }
        $client->setRedirectURL($redirectUri);
        $client->addScope(['openid', 'profile', 'email', 'groups']);
        $client->setVerifyHost(true);
        $client->setVerifyPeer(true);
        $caPath = $this->resolveCaBundlePath();
        if ($caPath !== '') {
            $client->setCertPath($caPath);
        }
        return $client;
    }

    /**
     * Resolve the CA bundle for the server-side OIDC discovery cURL.
     *
     * The sys-svc-compose-ca override reliably bind-mounts the Infinito
     * root CA and exports CURL_CA_BUNDLE/CA_TRUST_CERT/SSL_CERT_FILE to
     * point at it, even when the CA-trust entrypoint wrapper was not
     * applied (e.g. locally-built image absent at inject time). Prefer
     * those over the system bundle, which only carries the Infinito CA
     * once update-ca-certificates has run inside the container.
     */
    private function resolveCaBundlePath(): string
    {
        $candidates = [
            getenv('CURL_CA_BUNDLE') ?: '',
            getenv('CA_TRUST_CERT') ?: '',
            getenv('SSL_CERT_FILE') ?: '',
            '/etc/ssl/certs/ca-certificates.crt',
        ];
        foreach ($candidates as $candidate) {
            $candidate = (string) $candidate;
            if ($candidate !== '' && is_file($candidate)) {
                return $candidate;
            }
        }
        return '';
    }

    private function handleCallback(): void
    {
        $oidc = $this->buildOidcClient();
        $oidc->authenticate();

        $sub      = (string) ($oidc->getVerifiedClaims('sub') ?? '');
        $email    = (string) ($oidc->getVerifiedClaims('email') ?? '');
        $username = (string) ($oidc->getVerifiedClaims('preferred_username') ?? $sub);
        $given    = (string) ($oidc->getVerifiedClaims('given_name') ?? '');
        $family   = (string) ($oidc->getVerifiedClaims('family_name') ?? '');
        $groups   = (array)  ($oidc->getVerifiedClaims('groups') ?? []);

        if ($username === '') {
            throw new \RuntimeException('Keycloak callback: missing preferred_username/sub');
        }
        if ($email === '') {
            $email = $username . '@kc.local';
        }
        $name = trim($given . ' ' . $family) ?: $username;

        $mappedGroups = $this->mapGroupsToJoomla($groups);
        if (count($mappedGroups) === 0) {
            $this->app->enqueueMessage(
                'Keycloak: no Joomla group mapping for your roles; access refused.',
                'error'
            );
            $this->app->redirect('index.php?option=keycloak&task=logout');
            return;
        }

        $userId = (int) UserHelper::getUserId($username);
        if ($userId === 0) {
            $userId = $this->createJoomlaUser($username, $email, $name, $mappedGroups);
        }
        $user = User::getInstance($userId);
        $user->name   = $name;
        $user->email  = $email;
        $user->groups = $mappedGroups;
        if (!$user->save()) {
            throw new \RuntimeException('Keycloak: failed to update Joomla user: ' . implode(' ', $user->getErrors()));
        }

        $session = Factory::getSession();
        $session->set('user', $user);
        $this->app->checkSession();

        $returnTo = (string) ($session->get('keycloak.return_to', 'index.php'));
        $session->clear('keycloak.return_to');
        $this->app->redirect($returnTo);
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

    private function mapGroupsToJoomla(array $kcGroups): array
    {
        $admin  = (string) (getenv(self::ENV_GROUP_ADMIN)  ?: '/roles/web-app-joomla/administrator');
        $editor = (string) (getenv(self::ENV_GROUP_EDITOR) ?: '/roles/web-app-joomla/editor');
        $user   = (string) (getenv(self::ENV_GROUP_USER)   ?: '/roles/web-app-joomla');
        $admin  = '/' . ltrim($admin, '/');
        $editor = '/' . ltrim($editor, '/');
        $user   = '/' . ltrim($user, '/');

        $mapped = [];
        foreach ($kcGroups as $g) {
            $g = '/' . ltrim((string) $g, '/');
            if ($g === $admin) {
                $mapped[] = self::JOOMLA_GROUP_SUPER;
            } elseif ($g === $editor) {
                $mapped[] = self::JOOMLA_GROUP_EDITOR;
            } elseif ($g === $user) {
                $mapped[] = self::JOOMLA_GROUP_REGISTERED;
            }
        }
        return array_values(array_unique($mapped));
    }

    private function handleLogout(): void
    {
        $this->app->logout();
        $endSession = (string) (getenv(self::ENV_LOGOUT_URL) ?: '');
        if ($endSession === '') {
            $issuer = (string) (getenv(self::ENV_ISSUER) ?: '');
            if ($issuer !== '') {
                $endSession = rtrim($issuer, '/') . '/protocol/openid-connect/logout';
            }
        }
        $target = $endSession !== '' ? $endSession : 'index.php?fallback=local';
        $this->app->redirect($target);
    }
}
