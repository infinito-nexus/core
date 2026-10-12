<?php
// nocheck: mirrored-unit-test - boots Magento through app/bootstrap.php and rewrites the
// admin_user row through Magento's own encryptor; running it against a live install is the
// whole behaviour
/**
 * Realign the Magento administrator password with the value the deployment renders.
 *
 * `password` takes the plaintext: `User::beforeSave()` replaces it with
 * `EncryptorInterface::getHash($password, true)`, so pre-hashing it here would store a hash
 * of a hash and lock the administrator out.
 *
 * Every failure is caught and reduced to its message: PHP's uncaught-exception trace carries
 * the call arguments unless `zend.exception_ignore_args` is on, and the official PHP images
 * activate no php.ini, so an uncaught throw would put the password on stderr.
 *
 * Env, passed with `container exec -e <name>` so it never reaches the host-side argv:
 *   MAGENTO_REALIGN_ROOT      Magento base directory, the one holding app/bootstrap.php
 *   MAGENTO_REALIGN_USERNAME  administrator login to realign
 *   MAGENTO_REALIGN_PASSWORD  password that login must accept afterwards
 *
 * Exit: 0 with [CHANGED] or [UNCHANGED] on stdout, 1 with [FAIL] on stderr.
 */

declare(strict_types=1);

use Magento\Framework\App\Area;
use Magento\Framework\App\Bootstrap;
use Magento\Framework\App\State;
use Magento\Framework\Encryption\EncryptorInterface;
use Magento\User\Model\UserFactory;

function required(string $name): string
{
    $value = getenv($name);
    if ($value === false || $value === '') {
        fwrite(STDERR, "[FAIL] $name is empty\n");
        exit(1);
    }

    return $value;
}

$root = required('MAGENTO_REALIGN_ROOT');
$username = required('MAGENTO_REALIGN_USERNAME');
$password = required('MAGENTO_REALIGN_PASSWORD');

require_once $root . '/app/bootstrap.php';

try {
    $objects = Bootstrap::create(BP, $_SERVER)->getObjectManager();
    // Exception: AREA_ADMINHTML would register admin_user_save_after, whose observer
    // constructs Backend\Model\Auth\Session and starts a PHP session the CLI has no
    // request for. The cost of AREA_GLOBAL is the admin_passwords history row.
    $objects->get(State::class)->setAreaCode(Area::AREA_GLOBAL);

    $user = $objects->get(UserFactory::class)->create()->loadByUsername($username);
    if (!$user->getId()) {
        fwrite(STDERR, "[FAIL] no Magento administrator named '$username'\n");
        exit(1);
    }

    if ($objects->get(EncryptorInterface::class)->isValidHash($password, (string) $user->getPassword())) {
        echo "[UNCHANGED] the Magento administrator already accepts the declared password\n";
        exit(0);
    }

    $user->setPassword($password)->save();

    $written = $objects->get(UserFactory::class)->create()->loadByUsername($username);
    if (!$objects->get(EncryptorInterface::class)->isValidHash($password, (string) $written->getPassword())) {
        fwrite(STDERR, "[FAIL] the realigned password is not the one '$username' now accepts\n");
        exit(1);
    }
} catch (Throwable $error) {
    fwrite(STDERR, '[FAIL] ' . $error->getMessage() . "\n");
    exit(1);
}

echo "[CHANGED] the Magento administrator was realigned with the declared password\n";
