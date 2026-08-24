<?php
// nocheck: mirrored-unit-test - requires /var/www/html/bootstrap.php and writes through
// EspoCRM's config API; there is no function to call
// Idempotently set EspoCRM siteUrl to the canonical domain. The new URL
// is read from the ESPOCRM_URL env var (passed in via `compose exec -e`
// from the Ansible task) so quoting cannot leak into the PHP literal.
// Prints "CHANGED" on stdout when the value was rewritten.
require "/var/www/html/bootstrap.php";

$app    = new \Espo\Core\Application();
$c      = $app->getContainer();
$cfg    = $c->get("config");
$writer = $c->get("injectableFactory")->create("\Espo\Core\Utils\Config\ConfigWriter");

$new = getenv("ESPOCRM_URL");
if ($cfg->get("siteUrl") !== $new) {
    $writer->set("siteUrl", $new);
    $writer->save();
    echo "CHANGED";
}
