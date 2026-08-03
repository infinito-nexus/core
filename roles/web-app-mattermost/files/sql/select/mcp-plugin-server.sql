SELECT coalesce(config::jsonb #>> '{mcp,enablePluginServer}', 'false')
  FROM agents_confighistory
 WHERE active = true;
