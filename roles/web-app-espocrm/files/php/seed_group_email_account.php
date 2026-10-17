<?php
// nocheck: mirrored-unit-test - requires /var/www/html/bootstrap.php at the top level
// and rewrites the live InboundEmail table through EspoCRM's own entity manager
/**
 * Provision the Group Email Account EspoCRM sends system mail through.
 *
 * Since 9.1 Espo\Core\Mail\Sender::applyGlobal() takes the system mailer from
 * SendingAccountProvider::getSystem(), which resolves an Active InboundEmail row with
 * useSmtp whose emailAddress equals outboundEmailFromAddress, and never reads
 * config.smtpServer. EmailSender::hasSystemSmtp() still reads that config key, so
 * without this row EspoCRM reports SMTP as configured and then throws
 * NoSmtp("No system SMTP settings.") on an actual send.
 *
 * Reads: the app's own config, seeded from templates/env.j2 via ESPOCRM_CONFIG_SMTP_*.
 * Exit: 0 with [CHANGED] or [UNCHANGED] on stdout, 1 with [FAIL] on stderr.
 */

require "/var/www/html/bootstrap.php";

$app = new \Espo\Core\Application();
$app->setupSystemUser();

$container = $app->getContainer();
$config = $container->get('config');
$crypt = $container->get('crypt');
$entityManager = $container->getByClass(\Espo\Core\ORM\EntityManager::class);

$address = $config->get('outboundEmailFromAddress');
$host = $config->get('smtpServer');
$port = $config->get('smtpPort');
$security = $config->get('smtpSecurity');
$auth = $config->get('smtpAuth') === true;
$username = $config->get('smtpUsername');
$password = $config->get('smtpPassword');

if (!is_string($address) || $address === '') {
    fwrite(STDERR, "[FAIL] config outboundEmailFromAddress is empty; the system account is resolved by that address\n");
    exit(1);
}

if (!is_string($host) || $host === '') {
    fwrite(STDERR, "[FAIL] config smtpServer is empty; there is no mail host to carry onto the group email account\n");
    exit(1);
}

if (!is_int($port)) {
    fwrite(STDERR, "[FAIL] config smtpPort is not an integer; Espo rejects the account with NoSmtp(\"Empty port.\")\n");
    exit(1);
}

if (!is_string($security)) {
    fwrite(STDERR, "[FAIL] config smtpSecurity is not a string; a null would silently downgrade the transport to plaintext\n");
    exit(1);
}

if ($auth && (!is_string($username) || $username === '')) {
    fwrite(STDERR, "[FAIL] config smtpAuth is on but smtpUsername is empty\n");
    exit(1);
}

if ($auth && !is_string($password)) {
    fwrite(STDERR, "[FAIL] config smtpAuth is on but smtpPassword is not a string\n");
    exit(1);
}

$password = $auth ? $password : null;

$repository = $entityManager->getRDBRepositoryByClass(\Espo\Entities\InboundEmail::class);

$account = $repository
    ->where(
        \Espo\ORM\Query\Part\Condition::equal(
            \Espo\ORM\Query\Part\Expression::lowerCase(
                \Espo\ORM\Query\Part\Expression::column('emailAddress')
            ),
            strtolower($address)
        )
    )
    ->findOne();

$changed = false;

if (!$account) {
    $account = $repository->getNew();
    $account->set('name', $address . ' (system)');
    $account->set('useImap', false);
    $changed = true;
}

$values = [
    'emailAddress' => $address,
    'status' => \Espo\Entities\InboundEmail::STATUS_ACTIVE,
    'useSmtp' => true,
    'smtpHost' => $host,
    'smtpPort' => $port,
    'smtpSecurity' => $security,
    'smtpAuth' => $auth,
    'smtpUsername' => $username,
    'fromName' => $config->get('outboundEmailFromName'),
];

foreach ($values as $attribute => $value) {
    if ($account->get($attribute) === $value) {
        continue;
    }

    $account->set($attribute, $value);
    $changed = true;
}

$stored = $account->get('smtpPassword');
$current = null;

if (is_string($stored) && $stored !== '') {
    try {
        $current = $crypt->decrypt($stored);
    } catch (\Throwable) {
        $current = null;
    }
}

if ($current !== $password) {
    $account->set('smtpPassword', is_string($password) ? $crypt->encrypt($password) : null);
    $changed = true;
}

if (!$changed) {
    echo "[UNCHANGED] the group email account already carries the deployed mail host\n";
    exit(0);
}

try {
    $entityManager->saveEntity($account, [
        \Espo\Core\ORM\Repository\Option\SaveOption::SKIP_HOOKS => true,
    ]);
} catch (\Throwable $exc) {
    fwrite(STDERR, sprintf(
        "[FAIL] saving the group email account failed: %s: %s (%s:%d)\n",
        get_class($exc),
        $exc->getMessage(),
        $exc->getFile(),
        $exc->getLine()
    ));
    exit(1);
}

echo "[CHANGED] the group email account now carries the deployed mail host\n";
