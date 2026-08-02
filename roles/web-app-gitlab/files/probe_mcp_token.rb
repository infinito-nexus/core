require 'json'
require 'net/http'
require 'uri'

uri = URI("http://#{ENV.fetch('GITLAB_MCP_HOST')}:#{ENV.fetch('GITLAB_MCP_PORT')}#{ENV.fetch('GITLAB_MCP_PATH')}")

request = Net::HTTP::Post.new(uri)
request['Authorization'] = "Bearer #{ENV.fetch('GITLAB_MCP_TOKEN')}"
request['Content-Type'] = 'application/json'
request['Accept'] = 'application/json, text/event-stream'
request.body = JSON.generate(
  jsonrpc: '2.0',
  id: 1,
  method: 'initialize',
  params: {
    protocolVersion: ENV.fetch('GITLAB_MCP_PROTOCOL_VERSION'),
    capabilities: {},
    clientInfo: { name: 'infinito-nexus', version: '1' }
  }
)

response = Net::HTTP.start(uri.hostname, uri.port, read_timeout: 30, open_timeout: 10) do |http|
  http.request(request)
end

abort("REJECTED #{response.code}") unless response.code.to_i == 200

puts "ACCEPTED #{response.code}"
