const test = require("node:test");
const assert = require("node:assert/strict");
const http = require("node:http");
const path = require("node:path");

const mock = require(path.resolve(__dirname, "../../../../../../roles/svc-ai-freellmapi/files/javascript/mock_upstream.js"));

const MODEL = "infinito-mock";
const PROBE = {
  type: "function",
  function: {
    name: "infinito_probe",
    description: "Return the supplied value.",
    parameters: {
      type: "object",
      properties: { value: { type: "string", enum: ["OK"] } },
      required: ["value"],
      additionalProperties: false,
    },
  },
};
const ASK = { role: "user", content: "Call infinito_probe with value OK, then reply with the tool result." };

async function withServer(run) {
  const server = http.createServer(mock.handle(MODEL));
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    await run(base);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
}

function post(base, body) {
  return fetch(`${base}/v1/chat/completions`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: "Bearer any" },
    body: JSON.stringify(body),
  });
}

function events(text) {
  return text
    .split("\n\n")
    .filter((block) => block.startsWith("data: "))
    .map((block) => block.slice(6))
    .map((data) => (data === "[DONE]" ? data : JSON.parse(data)));
}

test("schema-derived arguments satisfy the protocol probe's enum", () => {
  assert.deepEqual(mock.argumentsFor(PROBE.function.parameters), { value: "OK" });
  assert.deepEqual(
    mock.argumentsFor({
      type: "object",
      properties: { n: { type: "integer" }, flag: { type: "boolean" }, items: { type: "array" }, nested: { type: "object", properties: { s: { type: "string" } } } },
    }),
    { n: 0, flag: true, items: [], nested: { s: "OK" } },
  );
});

test("a schema property named __proto__ becomes an own argument, never the arguments' prototype", () => {
  const schema = JSON.parse(
    '{"type":"object","properties":{"__proto__":{"type":"object","properties":{"polluted":{"type":"boolean"}}}},"required":["__proto__"]}',
  );
  const args = mock.argumentsFor(schema);
  assert.equal(Object.getPrototypeOf(args), Object.prototype);
  assert.ok(Object.hasOwn(args, "__proto__"));
  assert.equal(args.polluted, undefined);
  assert.equal(JSON.stringify(args), '{"__proto__":{"polluted":true}}');
});

test("a pinned tool_choice is called; a tool result or tool_choice none yields text", () => {
  const other = { type: "function", function: { name: "other", parameters: {} } };
  const pinned = mock.toolCall({
    tools: [other, PROBE],
    tool_choice: { type: "function", function: { name: "infinito_probe" } },
    messages: [ASK],
  });
  assert.equal(pinned.function.name, "infinito_probe");
  assert.deepEqual(JSON.parse(pinned.function.arguments), { value: "OK" });
  assert.equal(mock.toolCall({ tools: [PROBE], tool_choice: "required", messages: [ASK] }).function.name, "infinito_probe");
  assert.equal(mock.toolCall({ tools: [PROBE], tool_choice: "none", messages: [ASK] }), null);
  assert.equal(mock.toolCall({ messages: [ASK] }), null);
  assert.equal(
    mock.toolCall({ tools: [PROBE], messages: [ASK, { role: "assistant", content: null, tool_calls: [pinned] }, { role: "tool", tool_call_id: pinned.id, content: "OK" }] }),
    null,
  );
});

test("the chat tool round trip the LiteLLM protocol validation drives", async () => {
  await withServer(async (base) => {
    const body = { model: MODEL, messages: [ASK], tools: [PROBE], tool_choice: { type: "function", function: { name: "infinito_probe" } } };
    const first = await post(base, body);
    assert.equal(first.status, 200);
    const data = await first.json();
    assert.equal(data.choices[0].finish_reason, "tool_calls");
    const call = data.choices[0].message.tool_calls[0];
    assert.deepEqual(JSON.parse(call.function.arguments), { value: "OK" });

    delete body.tool_choice;
    body.messages.push(data.choices[0].message, { role: "tool", tool_call_id: call.id, content: "OK" });
    const second = await (await post(base, body)).json();
    assert.equal(second.choices[0].message.content, mock.REPLY);
    assert.equal(second.choices[0].finish_reason, "stop");
  });
});

test("streams text and tool calls as SSE chunks ending in [DONE]", async () => {
  await withServer(async (base) => {
    const text = await post(base, { model: MODEL, stream: true, stream_options: { include_usage: true }, messages: [{ role: "user", content: "Reply only OK." }] });
    assert.match(text.headers.get("content-type"), /text\/event-stream/);
    const received = events(await text.text());
    assert.equal(received.at(-1), "[DONE]");
    assert.equal(received.map((e) => e.choices?.[0]?.delta?.content).filter(Boolean).join(""), mock.REPLY);
    assert.ok(received.some((e) => e.choices?.[0]?.finish_reason === "stop"));
    assert.ok(received.some((e) => e.usage && e.choices.length === 0));
    assert.ok(!received.some((e) => e.choices?.[0]?.finish_reason === "length"));

    const tools = events(await (await post(base, { model: MODEL, stream: true, messages: [ASK], tools: [PROBE], tool_choice: "required" })).text());
    const delta = tools.find((e) => e.choices?.[0]?.delta?.tool_calls);
    assert.equal(delta.choices[0].delta.tool_calls[0].function.name, "infinito_probe");
    assert.ok(tools.some((e) => e.choices?.[0]?.finish_reason === "tool_calls"));
    assert.ok(!tools.some((e) => e.usage));
  });
});

test("serves the model catalog and health, rejects unknown paths and bad JSON", async () => {
  await withServer(async (base) => {
    const catalog = await (await fetch(`${base}/v1/models`)).json();
    assert.deepEqual(catalog.data.map((m) => m.id), [MODEL]);
    assert.equal((await fetch(`${base}/health`)).status, 200);
    assert.equal((await fetch(`${base}/v1/responses`, { method: "POST", body: "{}" })).status, 404);
    const bad = await fetch(`${base}/v1/chat/completions`, { method: "POST", body: "{" });
    assert.equal(bad.status, 400);
    assert.ok((await bad.json()).error.message);
  });
});
