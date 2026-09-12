const {
  mcpEndpointUrl,
  registerMcpDisabledState,
  registerMcpGuestRejection,
} = require("./mcp-endpoint");

exports.register = function () {
  registerMcpGuestRejection(mcpEndpointUrl);
  registerMcpDisabledState(mcpEndpointUrl);
};
