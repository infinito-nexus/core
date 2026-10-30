<?php
// nocheck: mirrored-unit-test - needs a booted Nextcloud, which only exists inside the container
// Params: $argv[1] the Nextcloud server root; $occBatch, assigned in front of this script on
// stdin, the base64 of a JSON list of {"argv": [occ arguments], "label": "<call name>"}.
// Output: what occ prints for each call; on the first call that exits non-zero,
// "occ <command> failed for <label>" on stderr and exit code 1.

define("OC_CONSOLE", 1);

[, $serverRoot] = $argv;

$calls = json_decode(base64_decode($occBatch, true), true, 512, JSON_THROW_ON_ERROR);

require_once $serverRoot . "/lib/base.php";

chdir($serverRoot);

$application = \OCP\Server::get(\OC\Console\Application::class);
$application->loadCommands(
    new \Symfony\Component\Console\Input\ArgvInput(["occ", ...$calls[0]["argv"]]),
    new \Symfony\Component\Console\Output\ConsoleOutput(),
);
$application->setAutoExit(false);

foreach ($calls as $call) {
    if ($application->run(new \Symfony\Component\Console\Input\ArgvInput(["occ", ...$call["argv"]])) !== 0) {
        fwrite(STDERR, "occ " . $call["argv"][0] . " failed for " . $call["label"] . "\n");
        exit(1);
    }
}
