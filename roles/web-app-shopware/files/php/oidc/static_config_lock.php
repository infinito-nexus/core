<?php

declare(strict_types=1);

namespace App\InfinitoRbac;

use Symfony\Component\HttpFoundation\JsonResponse;
use Symfony\Component\HttpKernel\Event\ResponseEvent;

final class StaticSystemConfigLock
{
    private const SCHEMA_ROUTE = 'api.action.core.system-config';

    private array $staticKeys = [];

    /**
     * @param array<string, array<string, mixed>> $staticConfig %shopware.system_config%: the static values keyed by "default" or a sales channel id
     */
    public function __construct(array $staticConfig)
    {
        foreach ($staticConfig as $values) {
            foreach (array_keys($values) as $key) {
                $this->staticKeys[$key] = true;
            }
        }
    }

    public function __invoke(ResponseEvent $event): void
    {
        $response = $event->getResponse();

        if (
            $this->staticKeys === []
            || $event->getRequest()->attributes->get('_route') !== self::SCHEMA_ROUTE
            || !$response instanceof JsonResponse
        ) {
            return;
        }

        $cards = json_decode((string) $response->getContent(), false, 512, JSON_THROW_ON_ERROR);

        if (!\is_array($cards)) {
            return;
        }

        $locked = false;

        foreach ($cards as $card) {
            foreach ($card->elements ?? [] as $element) {
                if (!isset($this->staticKeys[$element->name ?? ''])) {
                    continue;
                }

                $element->config = (object) ($element->config ?? []);
                $element->config->disabled = true;
                $locked = true;
            }
        }

        if ($locked) {
            $response->setData($cards);
        }
    }
}
