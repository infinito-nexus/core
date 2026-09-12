const {
  registerMcpDisabledState,
  registerMcpGuestRejection,
} = require("./mcp-endpoint");

exports.register = function (shared) {
  registerMcpGuestRejection(() => shared.mcpEndpointUrl());
  registerMcpDisabledState(() => shared.mcpEndpointUrl());
};
