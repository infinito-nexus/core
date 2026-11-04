<?php

namespace App\Services;

use GuzzleHttp\ClientInterface;
use GuzzleHttp\Promise\PromiseInterface;
use GuzzleHttp\Psr7\Uri;
use Psr\Http\Message\RequestInterface;
use Psr\Http\Message\ResponseInterface;
use RuntimeException;

/**
 * HTTP client of UserOidcService that keeps the claims of the userinfo response it relays.
 *
 * Args:
 *   client      the provider's own HTTP client, which sends every request
 *   profileUrl  userinfo endpoint (remote-auth.oidc.profileURL) whose JSON response is kept
 */
class InfinitoRbacUserinfoClient implements ClientInterface
{
    private ?array $claims = null;

    public function __construct(private ClientInterface $client, private string $profileUrl)
    {
    }

    // The `= []` and `= null` defaults are GuzzleHttp\ClientInterface's own: PHP rejects an implementation that makes them required.
    public function send(RequestInterface $request, array $options = []): ResponseInterface
    {
        $response = $this->client->send($request, $options);

        if ((string) $request->getUri() === (string) new Uri($this->profileUrl)) {
            $claims = json_decode((string) $response->getBody(), true);
            $this->claims = is_array($claims) ? $claims : null;
        }

        return $response;
    }

    public function sendAsync(RequestInterface $request, array $options = []): PromiseInterface
    {
        return $this->client->sendAsync($request, $options);
    }

    public function request(string $method, $uri, array $options = []): ResponseInterface
    {
        return $this->client->request($method, $uri, $options);
    }

    public function requestAsync(string $method, $uri, array $options = []): PromiseInterface
    {
        return $this->client->requestAsync($method, $uri, $options);
    }

    public function getConfig(?string $option = null)
    {
        return $this->client->getConfig($option);
    }

    /**
     * @return array<string, mixed> the claims of the last userinfo response
     */
    public function claims(): array
    {
        if ($this->claims === null) {
            throw new RuntimeException('InfinitoRbac: the OIDC sign-in relayed no JSON userinfo response from '.$this->profileUrl);
        }

        return $this->claims;
    }
}
