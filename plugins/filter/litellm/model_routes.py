"""Turn the model sources LiteLLM serves into one ordered route list.

The proxy config used to grow a loop per source, so the rule for "how is this
alias called" lived in four places that drifted apart: the LM Studio branch
published no context window although its README promised one, and a mock needed
a fifth branch. Here the sources meet once, the template renders one loop, and
every shape is a unit test instead of a rendered fixture.

Order is the contract: the first route of the list is what ``LITELLM_CHAT_MODEL``
names, so a locally served model outranks a declared one, and the earlier
backend outranks the later.
"""


def _local_route(
    alias, model, api_base, *, max_tokens, timeout, context, traits, api_key=None
):
    params = {
        "model": model,
        "api_base": api_base,
        "rpm": 1000,
        "max_tokens": max_tokens,
        "timeout": timeout,
    }
    if api_key:
        params["api_key"] = api_key
    if context:
        params["num_ctx"] = context
    return {"alias": alias, "params": params, "context": context, "traits": traits}


def litellm_model_routes(
    ollama_models,
    lmstudio_models,
    declared_models,
    *,
    ollama_url,
    lmstudio_url,
    max_tokens,
    timeout,
    mock_provider,
    router_alias=None,
):
    """Every model LiteLLM publishes, as ``{alias, params, context, traits}``.

    Args:
        ollama_models: preload entries svc-ai-ollama serves; empty when it is
            not a backend of this deployment.
        lmstudio_models: preload entries svc-ai-lmstudio serves, same rule. An
            alias Ollama already serves is dropped here rather than published
            twice.
        declared_models: ``services.litellm.remote_models`` already narrowed to
            the providers this host holds a key for. An entry whose provider is
            ``mock`` answers from its own ``response`` and calls nothing.
        ollama_url: base URL of the Ollama API.
        lmstudio_url: base URL of the LM Studio API, without the ``/v1`` suffix.
        max_tokens: output bound every route carries.
        timeout: upstream timeout every calling route carries.
        mock_provider: the provider name that marks a mock, passed in rather
            than hardcoded so this and the Ansible side cannot drift apart.
        router_alias: when given and at least one route exists, one further
            route under that alias. The pre-call hook rewrites it to whichever
            route can serve the request, so this entry exists to make the alias
            listable and MUST never answer: it raises, because a router that
            silently served the default would hide its own failure behind a
            plausible reply.

    Returns:
        The routes in publication order: Ollama, then LM Studio, then declared,
        then the router alias.
    """
    routes = []
    served = set()

    for model in ollama_models or []:
        alias = model["alias"]
        served.add(alias)
        routes.append(
            _local_route(
                alias,
                f"ollama/{alias}",
                ollama_url,
                max_tokens=max_tokens,
                timeout=timeout,
                context=model.get("context"),
                traits=model.get("traits"),
            )
        )

    for model in lmstudio_models or []:
        alias = model["alias"]
        if alias in served:
            continue
        served.add(alias)
        routes.append(
            _local_route(
                alias,
                f"openai/{model['name']}",
                f"{lmstudio_url}/v1",
                max_tokens=max_tokens,
                timeout=timeout,
                context=model.get("context"),
                traits=model.get("traits"),
                api_key="lm-studio",
            )
        )

    for model in declared_models or []:
        alias = model["alias"]
        context = model.get("context")
        if model.get("provider") == mock_provider:
            params = {
                "model": f"openai/{alias}",
                "api_key": mock_provider,
                "mock_response": model["response"],
                "max_tokens": max_tokens,
            }
        else:
            params = {
                "model": model["model"],
                "api_key": f"os.environ/{model['provider'].upper()}_API_KEY",
                "max_tokens": max_tokens,
                "timeout": timeout,
            }
        routes.append(
            {
                "alias": alias,
                "params": params,
                "context": context,
                "traits": model.get("traits"),
            }
        )

    if router_alias and routes:
        routes.append(
            {
                "alias": router_alias,
                "params": {
                    "model": f"openai/{router_alias}",
                    "api_key": router_alias,
                    "mock_response": "litellm.InternalServerError",
                },
                "context": None,
                "traits": None,
            }
        )

    return routes


class FilterModule:
    """Expose the LiteLLM route builder to the proxy config template."""

    def filters(self):
        return {"litellm_model_routes": litellm_model_routes}
