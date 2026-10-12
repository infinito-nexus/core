<?php
// nocheck: mirrored-unit-test - requires /var/www/html/bootstrap.php at the top level
// and rewrites the live user table through EspoCRM's own entity manager
/**
 * Move the administrator EspoCRM persisted at install onto the declared username.
 *
 * Env (from the container):
 *   ESPOCRM_ADMIN_USERNAME  username the deployment declares
 *
 * Exit: 0 with [CHANGED] or [UNCHANGED] on stdout, 1 with [FAIL] on stderr.
 */

require "/var/www/html/bootstrap.php";

$userName = getenv('ESPOCRM_ADMIN_USERNAME');

if ($userName === false || $userName === '') {
    fwrite(STDERR, "[FAIL] ESPOCRM_ADMIN_USERNAME is empty\n");
    exit(1);
}

$app = new \Espo\Core\Application();
$app->setupSystemUser();

$entityManager = $app->getContainer()->getByClass(\Espo\Core\ORM\EntityManager::class);
$repository = $entityManager->getRDBRepositoryByClass(\Espo\Entities\User::class);

if ($repository->where(['userName' => $userName])->findOne()) {
    echo "[UNCHANGED] an account already carries the declared username\n";
    exit(0);
}

$administrators = [];

foreach ($repository->where(['type' => \Espo\Entities\User::TYPE_ADMIN])->find() as $administrator) {
    $administrators[] = $administrator;
}

if (count($administrators) !== 1) {
    fwrite(STDERR, sprintf(
        "[FAIL] no account carries the declared username and %d administrator rows exist,"
            . " so none of them can be carried onto it without picking one by hand\n",
        count($administrators)
    ));
    exit(1);
}

$administrators[0]->setUserName($userName);
$entityManager->saveEntity($administrators[0]);

echo "[CHANGED] the installed administrator was carried onto the declared username\n";
