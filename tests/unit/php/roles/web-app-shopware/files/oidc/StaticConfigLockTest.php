<?php

declare(strict_types=1);

namespace Symfony\Component\HttpFoundation {
    final class ParameterBag
    {
        public function __construct(private array $parameters)
        {
        }

        public function get(string $key): mixed
        {
            return $this->parameters[$key] ?? null;
        }
    }

    final class Request
    {
        public ParameterBag $attributes;

        public function __construct(array $attributes)
        {
            $this->attributes = new ParameterBag($attributes);
        }
    }

    class Response
    {
        public function __construct(protected string $content)
        {
        }

        public function getContent(): string
        {
            return $this->content;
        }
    }

    final class JsonResponse extends Response
    {
        public function setData(mixed $data): void
        {
            $this->content = json_encode($data, JSON_THROW_ON_ERROR);
        }
    }
}

namespace Symfony\Component\HttpKernel\Event {
    use Symfony\Component\HttpFoundation\Request;
    use Symfony\Component\HttpFoundation\Response;

    final class ResponseEvent
    {
        public function __construct(private Request $request, private Response $response)
        {
        }

        public function getRequest(): Request
        {
            return $this->request;
        }

        public function getResponse(): Response
        {
            return $this->response;
        }
    }
}

namespace {

    use App\InfinitoRbac\StaticSystemConfigLock;
    use PHPUnit\Framework\TestCase;
    use Symfony\Component\HttpFoundation\JsonResponse;
    use Symfony\Component\HttpFoundation\Request;
    use Symfony\Component\HttpFoundation\Response;
    use Symfony\Component\HttpKernel\Event\ResponseEvent;

    require_once dirname(__DIR__, 7) . '/roles/web-app-shopware/files/php/oidc/static_config_lock.php';

    final class StaticConfigLockTest extends TestCase
    {
        private const STATIC = ['default' => ['KskHeptacomAdminOpenAuth.config.denyPasswordLogin' => true]];

        private const SCHEMA = '[{"title":"Login","elements":['
            . '{"name":"KskHeptacomAdminOpenAuth.config.denyPasswordLogin","type":"bool","config":{"label":"Deny"}},'
            . '{"name":"KskHeptacomAdminOpenAuth.config.enableAutoRedirect","type":"bool","config":{"label":"Redirect"}},'
            . '{"name":"KskHeptacomAdminOpenAuth.config.other","type":"text","config":[]}'
            . ']}]';

        private static function serve(array $static, string $route, Response $response): array
        {
            (new StaticSystemConfigLock($static))(new ResponseEvent(new Request(['_route' => $route]), $response));

            return json_decode($response->getContent(), true, 512, JSON_THROW_ON_ERROR)[0]['elements'];
        }

        public function testAStaticKeyIsDisabledAndTheOthersStayEditable(): void
        {
            $elements = self::serve(self::STATIC, 'api.action.core.system-config', new JsonResponse(self::SCHEMA));

            $this->assertTrue($elements[0]['config']['disabled']);
            $this->assertSame('Deny', $elements[0]['config']['label']);
            $this->assertArrayNotHasKey('disabled', $elements[1]['config']);
            $this->assertArrayNotHasKey('disabled', $elements[2]['config']);
        }

        public function testAKeyStaticForOneSalesChannelIsDisabledToo(): void
        {
            $static = ['0190f4c5a6a07a1f8d0c3b1e2f3a4b5c' => ['KskHeptacomAdminOpenAuth.config.enableAutoRedirect' => false]];

            $elements = self::serve($static, 'api.action.core.system-config', new JsonResponse(self::SCHEMA));

            $this->assertTrue($elements[1]['config']['disabled']);
            $this->assertArrayNotHasKey('disabled', $elements[0]['config']);
        }

        public function testAnEmptyConfigOfAStaticKeyBecomesAnObject(): void
        {
            $static = ['default' => ['KskHeptacomAdminOpenAuth.config.other' => 'x']];

            $elements = self::serve($static, 'api.action.core.system-config', new JsonResponse(self::SCHEMA));

            $this->assertSame(['disabled' => true], $elements[2]['config']);
        }

        public function testEveryOtherRouteIsLeftAlone(): void
        {
            $response = new JsonResponse(self::SCHEMA);

            self::serve(self::STATIC, 'api.action.core.system-config.value', $response);

            $this->assertSame(self::SCHEMA, $response->getContent());
        }

        public function testWithoutStaticKeysTheSchemaIsLeftAlone(): void
        {
            $response = new JsonResponse(self::SCHEMA);

            self::serve([], 'api.action.core.system-config', $response);

            $this->assertSame(self::SCHEMA, $response->getContent());
        }

        public function testANonJsonResponseIsLeftAlone(): void
        {
            $response = new Response(self::SCHEMA);

            self::serve(self::STATIC, 'api.action.core.system-config', $response);

            $this->assertSame(self::SCHEMA, $response->getContent());
        }
    }
}
