<?php

declare(strict_types=1);

namespace Psr\Http\Message {
    interface StreamInterface
    {
        public function __toString(): string;
    }

    interface RequestInterface
    {
        public function getMethod(): string;

        public function getUri(): string;
    }

    interface ResponseInterface
    {
        public function getBody(): StreamInterface;
    }
}

namespace GuzzleHttp\Promise {
    interface PromiseInterface
    {
    }
}

namespace GuzzleHttp\Psr7 {
    final class Uri
    {
        public function __construct(private string $uri)
        {
        }

        public function __toString(): string
        {
            return (string) preg_replace('#^(https://[^/:]+):443(?=/|$)#', '$1', $this->uri);
        }
    }
}

namespace GuzzleHttp {
    use GuzzleHttp\Promise\PromiseInterface;
    use Psr\Http\Message\RequestInterface;
    use Psr\Http\Message\ResponseInterface;

    interface ClientInterface
    {
        public function send(RequestInterface $request, array $options = []): ResponseInterface;

        public function sendAsync(RequestInterface $request, array $options = []): PromiseInterface;

        public function request(string $method, $uri, array $options = []): ResponseInterface;

        public function requestAsync(string $method, $uri, array $options = []): PromiseInterface;

        public function getConfig(?string $option = null);
    }
}

namespace App\Services {
    use GuzzleHttp\ClientInterface;

    class UserOidcService
    {
        public function __construct(private ClientInterface $httpClient)
        {
        }

        public function getHttpClient(): ClientInterface
        {
            return $this->httpClient;
        }

        public function setHttpClient(ClientInterface $client): static
        {
            $this->httpClient = $client;

            return $this;
        }
    }
}

namespace Illuminate\Routing\Events {
    final class RouteMatched
    {
        public function __construct(public object $route, public ?object $request)
        {
        }
    }
}

namespace Illuminate\Auth\Events {
    final class Login
    {
        public function __construct(public string $guard, public object $user, public bool $remember)
        {
        }
    }
}

namespace Illuminate\Support\Facades {
    final class Log
    {
        public static array $messages = [];

        public static function info(string $message): void
        {
            self::$messages[] = $message;
        }
    }
}

namespace {
    use GuzzleHttp\ClientInterface;
    use GuzzleHttp\Promise\PromiseInterface;
    use Psr\Http\Message\RequestInterface;
    use Psr\Http\Message\ResponseInterface;
    use Psr\Http\Message\StreamInterface;

    final class PixelfedStubStream implements StreamInterface
    {
        public function __construct(private string $contents)
        {
        }

        public function __toString(): string
        {
            return $this->contents;
        }
    }

    final class PixelfedStubRequest implements RequestInterface
    {
        public function __construct(private string $method, private string $uri)
        {
        }

        public function getMethod(): string
        {
            return $this->method;
        }

        public function getUri(): string
        {
            return $this->uri;
        }
    }

    final class PixelfedStubResponse implements ResponseInterface
    {
        public function __construct(private string $body)
        {
        }

        public function getBody(): StreamInterface
        {
            return new PixelfedStubStream($this->body);
        }
    }

    final class PixelfedStubPromise implements PromiseInterface
    {
    }

    final class PixelfedStubHttpClient implements ClientInterface
    {
        public array $calls = [];

        /**
         * @param array<string, string> $bodies response body per request URI
         */
        public function __construct(private array $bodies)
        {
        }

        public function send(RequestInterface $request, array $options = []): ResponseInterface
        {
            $this->calls[] = ['send', $request->getMethod(), $request->getUri(), $options];

            return new PixelfedStubResponse($this->bodies[$request->getUri()]);
        }

        public function sendAsync(RequestInterface $request, array $options = []): PromiseInterface
        {
            $this->calls[] = ['sendAsync', $request->getMethod(), $request->getUri(), $options];

            return new PixelfedStubPromise();
        }

        public function request(string $method, $uri, array $options = []): ResponseInterface
        {
            $this->calls[] = ['request', $method, $uri, $options];

            return new PixelfedStubResponse($this->bodies[$uri]);
        }

        public function requestAsync(string $method, $uri, array $options = []): PromiseInterface
        {
            $this->calls[] = ['requestAsync', $method, $uri, $options];

            return new PixelfedStubPromise();
        }

        public function getConfig(?string $option = null)
        {
            return ['config', $option];
        }
    }

    final class PixelfedStubContainer
    {
        public static ?self $current = null;
        public static array $config = [];

        public array $extenders = [];
        public array $instances = [];

        public function extend(string $abstract, \Closure $closure): void
        {
            $this->extenders[$abstract][] = $closure;
        }

        public function instance(string $abstract, object $instance): object
        {
            $this->instances[$abstract] = $instance;

            return $instance;
        }

        public function bound(string $abstract): bool
        {
            return array_key_exists($abstract, $this->instances);
        }

        public function make(string $abstract): object
        {
            return $this->instances[$abstract];
        }

        /**
         * Hand a freshly built service through the extenders, as the container does when a controller resolves it.
         *
         * @param string $abstract the binding the service was built for
         * @param object $service the service the binding's factory returned
         */
        public function resolve(string $abstract, object $service): object
        {
            foreach ($this->extenders[$abstract] ?? [] as $extender) {
                $service = $extender($service, $this);
            }

            return $service;
        }
    }

    function app(?string $abstract = null): object
    {
        return $abstract === null ? PixelfedStubContainer::$current : PixelfedStubContainer::$current->make($abstract);
    }

    function config(string $key): mixed
    {
        return PixelfedStubContainer::$config[$key] ?? null;
    }
}
