"""Inputs: stdin base_url, model, timeout, max_output_tokens, reasoning_effort and workers;
LITELLM_MASTER_KEY authenticates the gateway probes.
Outputs: sanitized protocol/operation verdicts, never model text or keys.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor


def request(payload, key, path, body):
    return urllib.request.urlopen(  # noqa: S310 deployment-owned gateway endpoint
        urllib.request.Request(  # noqa: S310 deployment-owned gateway endpoint
            payload["base_url"].rstrip("/") + path,
            headers={
                "Authorization": "Bearer " + key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            data=json.dumps(body).encode(),
        ),
        timeout=payload["timeout"],
    )


def events(response, timeout):
    deadline = time.monotonic() + timeout
    fragments = []
    for raw in response:
        if time.monotonic() > deadline:
            raise TimeoutError("Stream exceeded its validation deadline")
        line = raw.decode().rstrip("\r\n")
        if line.startswith("data:"):
            fragments.append(line[5:].lstrip())
        elif not line and fragments:
            data = "\n".join(fragments)
            fragments = []
            yield {"type": "done"} if data == "[DONE]" else json.loads(data)
    if fragments:
        data = "\n".join(fragments)
        yield {"type": "done"} if data == "[DONE]" else json.loads(data)


def text_present(data, path):
    if data.get("error"):
        return False
    if path == "/v1/responses" and (
        data.get("object") != "response" or data.get("status") != "completed"
    ):
        return False
    if path == "/v1/chat/completions":
        return any(
            isinstance(c["message"].get("content"), str)
            and c["message"]["content"].strip()
            for c in data["choices"]
        )
    content = (
        data["content"]
        if path == "/v1/messages"
        else [
            b
            for item in data["output"]
            if item["type"] == "message"
            for b in item["content"]
        ]
    )
    return any(isinstance(b.get("text"), str) and b["text"].strip() for b in content)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def probe(payload, key, job):
    path, operation = job
    result = {"endpoint": path, "operation": operation}
    message = {
        "role": "user",
        "content": "Call infinito_probe with value OK, then reply with the tool result."
        if operation == "tools"
        else "Reply only OK.",
    }
    body = {"model": payload["model"]}
    if path == "/v1/responses":
        body.update(
            input=[message],
            max_output_tokens=payload["max_output_tokens"],
            store=False,
            reasoning={"effort": payload["reasoning_effort"]},
        )
    else:
        body.update(messages=[message], max_tokens=payload["max_output_tokens"])
    try:
        if operation == "stream":
            body["stream"] = True
            text = False
            complete = False
            with request(payload, key, path, body) as response:
                for event in events(response, payload["timeout"]):
                    require(
                        not (
                            event.get("error")
                            or event.get("type")
                            in (
                                "error",
                                "response.failed",
                                "response.incomplete",
                            )
                        ),
                        "Stream returned an error or incomplete response",
                    )
                    if path == "/v1/chat/completions":
                        require(
                            not any(
                                c.get("finish_reason") == "length"
                                for c in event.get("choices", [])
                            ),
                            "Stream exhausted its output budget",
                        )
                        text = text or any(
                            c.get("delta", {}).get("content")
                            for c in event.get("choices", [])
                        )
                        complete = complete or event.get("type") == "done"
                    elif path == "/v1/messages":
                        require(
                            event.get("delta", {}).get("stop_reason") != "max_tokens",
                            "Stream exhausted its output budget",
                        )
                        text = text or (
                            event.get("delta", {}).get("type") == "text_delta"
                            and bool(event["delta"].get("text"))
                        )
                        complete = complete or event.get("type") == "message_stop"
                    else:
                        require(
                            not (event.get("response") or {}).get("error"),
                            "Response stream returned an error",
                        )
                        text = text or (
                            event.get("type") == "response.output_text.delta"
                            and bool(event.get("delta"))
                        )
                        complete = complete or event.get("type") == "response.completed"
            require(
                text and complete, "Stream must contain text and a completion event"
            )
        else:
            schema = {
                "type": "object",
                "properties": {"value": {"type": "string", "enum": ["OK"]}},
                "required": ["value"],
                "additionalProperties": False,
            }
            function = {
                "name": "infinito_probe",
                "description": "Return the supplied value.",
                "parameters": schema,
            }
            if path == "/v1/messages":
                body.update(
                    tools=[
                        {
                            "name": function["name"],
                            "description": function["description"],
                            "input_schema": schema,
                        }
                    ],
                    tool_choice={"type": "tool", "name": function["name"]},
                )
            elif path == "/v1/responses":
                body.update(
                    tools=[{"type": "function", **function}],
                    tool_choice={"type": "function", "name": function["name"]},
                )
            else:
                body.update(
                    tools=[{"type": "function", "function": function}],
                    tool_choice={
                        "type": "function",
                        "function": {"name": function["name"]},
                    },
                )
            with request(payload, key, path, body) as response:
                data = json.load(response)
            if path == "/v1/messages":
                call = next(
                    item for item in data["content"] if item["type"] == "tool_use"
                )
                name, arguments = call["name"], call["input"]
                body["messages"] += [
                    {"role": "assistant", "content": data["content"]},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": call["id"],
                                "content": "OK",
                            }
                        ],
                    },
                ]
            elif path == "/v1/responses":
                call = next(
                    item for item in data["output"] if item["type"] == "function_call"
                )
                name, arguments = call["name"], json.loads(call["arguments"])
                body["input"] += data["output"] + [
                    {
                        "type": "function_call_output",
                        "call_id": call["call_id"],
                        "output": "OK",
                    }
                ]
            else:
                assistant = data["choices"][0]["message"]
                call = assistant["tool_calls"][0]
                name, arguments = (
                    call["function"]["name"],
                    json.loads(call["function"]["arguments"]),
                )
                body["messages"] += [
                    assistant,
                    {"role": "tool", "tool_call_id": call["id"], "content": "OK"},
                ]
            require(
                name == function["name"] and arguments == {"value": "OK"},
                "Tool call did not match the declared schema",
            )
            body.pop("tool_choice")
            with request(payload, key, path, body) as response:
                require(
                    text_present(json.load(response), path),
                    "Tool result did not produce answer text",
                )
        return dict(result, ok=True)
    except urllib.error.HTTPError as error:
        error.close()
        return dict(
            result,
            ok=False,
            http_status=error.code,
            reason="gateway_rejected_protocol_probe",
        )
    except (
        ValueError,
        KeyError,
        IndexError,
        TypeError,
        AttributeError,
        StopIteration,
        OSError,
    ):
        return dict(
            result, ok=False, reason="invalid_protocol_response_or_connection_failed"
        )


def validate(payload, key):
    for name in ("workers", "max_output_tokens"):
        if type(payload[name]) is not int or payload[name] <= 0:
            raise ValueError(f"{name} must be positive")
    jobs = [
        (path, operation)
        for path in ("/v1/chat/completions", "/v1/messages", "/v1/responses")
        for operation in ("stream", "tools")
    ]
    with ThreadPoolExecutor(max_workers=payload["workers"]) as pool:
        checks = list(pool.map(lambda job: probe(payload, key, job), jobs))
    return {"ok": all(check["ok"] for check in checks), "checks": checks}


def main():
    try:
        result = validate(json.load(sys.stdin), os.environ["LITELLM_MASTER_KEY"])
    except Exception:
        result = {"ok": False, "reason": "invalid_protocol_validation_input"}
    print(json.dumps(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
