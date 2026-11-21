const http = require("node:http");

const REPLY = "OK";
const CALL_ID = "call_infinito_mock";

function valueFor(property) {
  if (Array.isArray(property.enum) && property.enum.length > 0) return property.enum[0];
  if (property.type === "integer" || property.type === "number") return 0;
  if (property.type === "boolean") return true;
  if (property.type === "array") return [];
  if (property.type === "object") return argumentsFor(property);
  return REPLY;
}

function argumentsFor(schema) {
  const properties = schema && typeof schema.properties === "object" ? schema.properties : {};
  const names = Array.isArray(schema && schema.required) ? schema.required : Object.keys(properties);
  return Object.fromEntries(names.map((name) => [name, valueFor(properties[name] || {})]));
}

function toolCall(body) {
  const tools = Array.isArray(body.tools) ? body.tools.filter((tool) => tool && tool.function) : [];
  const messages = Array.isArray(body.messages) ? body.messages : [];
  const last = messages[messages.length - 1];
  if (tools.length === 0 || body.tool_choice === "none" || (last && last.role === "tool")) return null;
  const pinned = body.tool_choice && body.tool_choice.function && body.tool_choice.function.name;
  const tool = tools.find((candidate) => candidate.function.name === pinned) || tools[0];
  return {
    id: CALL_ID,
    type: "function",
    function: { name: tool.function.name, arguments: JSON.stringify(argumentsFor(tool.function.parameters)) },
  };
}

function envelope(body, object) {
  return { id: "chatcmpl-infinito-mock", object, created: Math.floor(Date.now() / 1000), model: body.model };
}

const USAGE = { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 };

function completion(body) {
  const call = toolCall(body);
  const message = call
    ? { role: "assistant", content: null, tool_calls: [call] }
    : { role: "assistant", content: REPLY };
  return {
    ...envelope(body, "chat.completion"),
    choices: [{ index: 0, message, finish_reason: call ? "tool_calls" : "stop" }],
    usage: USAGE,
  };
}

function chunks(body) {
  const call = toolCall(body);
  const base = envelope(body, "chat.completion.chunk");
  const delta = call ? { tool_calls: [{ index: 0, ...call }] } : { content: REPLY };
  const out = [
    { ...base, choices: [{ index: 0, delta: { role: "assistant" }, finish_reason: null }] },
    { ...base, choices: [{ index: 0, delta, finish_reason: null }] },
    { ...base, choices: [{ index: 0, delta: {}, finish_reason: call ? "tool_calls" : "stop" }] },
  ];
  if (body.stream_options && body.stream_options.include_usage) out.push({ ...base, choices: [], usage: USAGE });
  return out;
}

function models(model) {
  return { object: "list", data: [{ id: model, object: "model", created: 0, owned_by: "infinito" }] };
}

function sendJson(response, status, payload) {
  response.writeHead(status, { "Content-Type": "application/json" });
  response.end(JSON.stringify(payload));
}

function handle(model) {
  return (request, response) => {
    const path = request.url.split("?")[0].replace(/\/+$/, "");
    if (request.method === "GET" && path === "/health") return sendJson(response, 200, { status: "ok" });
    if (request.method === "GET" && path === "/v1/models") return sendJson(response, 200, models(model));
    if (request.method !== "POST" || path !== "/v1/chat/completions") {
      return sendJson(response, 404, { error: { message: "not found", type: "invalid_request_error" } });
    }
    const parts = [];
    request.on("data", (part) => parts.push(part));
    request.on("end", () => {
      let body;
      try {
        body = JSON.parse(Buffer.concat(parts).toString("utf8"));
      } catch {
        return sendJson(response, 400, { error: { message: "invalid JSON body", type: "invalid_request_error" } });
      }
      if (!body || typeof body !== "object") {
        return sendJson(response, 400, { error: { message: "JSON object expected", type: "invalid_request_error" } });
      }
      if (!body.stream) return sendJson(response, 200, completion(body));
      response.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache" });
      for (const chunk of chunks(body)) response.write(`data: ${JSON.stringify(chunk)}\n\n`);
      response.end("data: [DONE]\n\n");
    });
  };
}

function main() {
  const port = Number.parseInt(process.env.PORT, 10);
  const model = process.env.MOCK_MODEL;
  if (!Number.isInteger(port) || port <= 0 || !model) {
    console.error("PORT and MOCK_MODEL are required");
    process.exit(1);
  }
  http.createServer(handle(model)).listen(port, "0.0.0.0");
}

module.exports = { argumentsFor, toolCall, completion, chunks, models, handle, main, REPLY };

if (require.main === module) main();
