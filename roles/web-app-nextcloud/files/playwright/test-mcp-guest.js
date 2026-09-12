const { decodeDotenvQuotedValue } = require("./personas");
const { registerMcpDisabledState, registerMcpGuestRejection } = require("./mcp-endpoint");

const mcpEndpointPath = decodeDotenvQuotedValue(process.env.NEXTCLOUD_MCP_ENDPOINT_PATH);
const mcpUpstreamPath = decodeDotenvQuotedValue(process.env.NEXTCLOUD_MCP_UPSTREAM_PATH);

const withoutFrontController = (path) => path.replace(/^\/index\.php/, "");

exports.register = function (shared) {
  const url = (path) => new URL(path, shared.env.nextcloudBaseUrl).toString();

  registerMcpGuestRejection(() => url(mcpEndpointPath), "the adapter endpoint");
  registerMcpGuestRejection(() => url(mcpUpstreamPath), "the hub route");
  registerMcpGuestRejection(
    () => url(withoutFrontController(mcpUpstreamPath)),
    "the hub route without its front controller",
  );

  registerMcpDisabledState(() => url(mcpEndpointPath));
};
