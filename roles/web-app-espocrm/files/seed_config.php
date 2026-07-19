<?php
/**
 * Generic EspoCRM config seeder.
 *
 * Automatically scans all environment variables starting with ESPOCRM_SEED_,
 * converts them into EspoCRM camelCase config keys, and writes them via ConfigWriter.
 *
 * Example:
 *   ESPOCRM_SEED_RECAPTCHA_SECRET_KEY=xyz
 * becomes:
 *   recaptchaSecretKey => "xyz"
 */

require "/var/www/html/bootstrap.php";

$app    = new \Espo\Core\Application();
$c      = $app->getContainer();
$config = $c->get("config");
$writer = $c->get("injectableFactory")->create("\Espo\Core\Utils\Config\ConfigWriter");

/**
 * Convert an ENV suffix like "RECAPTCHA_SECRET_KEY" to camelCase "recaptchaSecretKey".
 */
function to_camel_case(string $input): string
{
    $input = strtolower($input);
    $parts = explode('_', $input);
    $result = array_shift($parts);

    foreach ($parts as $part) {
        $result .= ucfirst($part);
    }

    return $result;
}

/**
 * Normalize booleans if the value looks boolean-like.
 * Returns true/false for typical boolean strings, otherwise the original string.
 */
function cast_value(string $value)
{
    $normalized = strtolower(trim($value));

    if (in_array($normalized, ['1', 'true', 'yes', 'on'], true)) {
        return true;
    }

    if (in_array($normalized, ['0', 'false', 'no', 'off'], true)) {
        return false;
    }

    return $value; // keep as string
}

/**
 * Simple debug logger to STDERR.
 * This keeps STDOUT clean so automation can rely on "CHANGED"/"UNCHANGED".
 */
function seed_debug(string $message): void
{
    fwrite(STDERR, "[seed] " . $message . PHP_EOL);
}

$debugEnv = getenv('ESPOCRM_SEEDER_DEBUG');
$debug = false;
if ($debugEnv !== false) {
    $normalized = strtolower(trim($debugEnv));
    $debug = in_array($normalized, ['1', 'true', 'yes', 'on'], true);
}

if ($debug) {
    seed_debug("Seeder started, scanning ESPOCRM_SEED_* variables …");
}

$changed = false;

foreach ($_ENV as $envKey => $envValue) {
    if (strpos($envKey, 'ESPOCRM_SEED_') !== 0) {
        continue;
    }

    $rawKey = substr($envKey, strlen('ESPOCRM_SEED_')); // e.g. "RECAPTCHA_SECRET_KEY"

    if ($rawKey === '') {
        continue;
    }

    $configKey = to_camel_case($rawKey);

    $value = cast_value((string) $envValue);

    if ($debug) {
        seed_debug(sprintf(
            "ENV %s -> config key '%s' = %s",
            $envKey,
            $configKey,
            var_export($value, true)
        ));
    }

    $current = $config->get($configKey);

    if ($current !== $value) {
        if ($debug) {
            seed_debug(sprintf(
                "Updating '%s': %s -> %s",
                $configKey,
                var_export($current, true),
                var_export($value, true)
            ));
        }

        $writer->set($configKey, $value);
        $changed = true;
    } else {
        if ($debug) {
            seed_debug(sprintf(
                "No change for '%s' (already %s)",
                $configKey,
                var_export($current, true)
            ));
        }
    }
}

if ($changed) {
    if ($debug) {
        seed_debug("Changes detected, saving configuration …");
    }
    $writer->save();
    echo "CHANGED\n";
} else {
    if ($debug) {
        seed_debug("No changes detected.");
    }
    echo "UNCHANGED\n";
}

if ($debug) {
    seed_debug("Seeder finished.");
}
