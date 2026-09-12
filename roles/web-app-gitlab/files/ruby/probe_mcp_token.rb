# nocheck: mirrored-unit-test - opens an MCP session against the running GitLab sidecar
# from inside `gitlab-rails runner`, reading the host, port and path from the
# container's environment; the live handshake is the entire contract
require 'json'
require 'net/http'
require 'uri'

uri = URI("http://#{ENV.fetch('GITLAB_MCP_HOST')}:#{ENV.fetch('GITLAB_MCP_PORT')}#{ENV.fetch('GITLAB_MCP_PATH')}")

def post(uri, token, payload, session_id)
  request = Net::HTTP::Post.new(uri)
  request['Authorization'] = "Bearer #{token}"
  request['Content-Type'] = 'application/json'
  request['Accept'] = 'application/json, text/event-stream'
  request['Mcp-Session-Id'] = session_id if session_id
  request.body = JSON.generate(payload)
  Net::HTTP.start(uri.hostname, uri.port, read_timeout: 30, open_timeout: 10) do |http|
    http.request(request)
  end
end

def rpc_body(response)
  raw = response.body.to_s
  return JSON.parse(raw) if response['Content-Type'].to_s.include?('application/json')

  data = raw.each_line.select { |line| line.start_with?('data:') }
            .map { |line| line.sub(/\Adata:\s*/, '').strip }
            .join
  data.empty? ? {} : JSON.parse(data)
rescue JSON::ParserError
  {}
end

token = ENV.fetch('GITLAB_MCP_TOKEN')

response = post(uri, token, {
  jsonrpc: '2.0',
  id: 1,
  method: 'initialize',
  params: {
    protocolVersion: ENV.fetch('GITLAB_MCP_PROTOCOL_VERSION'),
    capabilities: {},
    clientInfo: { name: 'infinito-nexus', version: '1' }
  }
}, nil)

abort("REJECTED #{response.code}") unless response.code.to_i == 200

session_id = response['Mcp-Session-Id']
post(uri, token, { jsonrpc: '2.0', method: 'notifications/initialized' }, session_id)

listing = post(uri, token, { jsonrpc: '2.0', id: 2, method: 'tools/list', params: {} }, session_id)
tools = rpc_body(listing).dig('result', 'tools')
tools = [] unless tools.is_a?(Array)

puts "ACCEPTED #{response.code} tools=#{tools.length}"
