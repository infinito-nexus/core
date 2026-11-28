<?php

declare(strict_types=1);

use PHPUnit\Framework\TestCase;

final class EventsTest extends TestCase
{
    public function testOnlyTheSignInEventReachesADeclaredObserverMethod(): void
    {
        $plugin = dirname(__DIR__, 10) . '/roles/web-app-moodle/files/build/local/mfaenforce';
        $observers = (static function (string $file): array {
            defined('MOODLE_INTERNAL') || define('MOODLE_INTERNAL', true);
            require $file;
            return $observers;
        })($plugin . '/db/events.php');
        require_once $plugin . '/classes/observer.php';

        $this->assertSame(['\core\event\user_loggedin'], array_column($observers, 'eventname'));
        [$class, $method] = explode('::', $observers[0]['callback']);
        $this->assertTrue(method_exists($class, $method), $observers[0]['callback']);
    }
}
