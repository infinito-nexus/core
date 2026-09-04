const {
  mcpEndpointUrl,
  registerMcpDisabledState,
  registerMcpGuestRejection,
} = require("./mcp-endpoint");

const resolveEndpointUrl = () =>
  mcpEndpointUrl("/mcp", process.env.ZAMMAD_BASE_URL);

exports.register = function () {
  registerMcpGuestRejection(resolveEndpointUrl);
  registerMcpDisabledState(resolveEndpointUrl);
};
