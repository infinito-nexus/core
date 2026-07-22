const redis = require('redis');
const settings = require('ep_etherpad-lite/node/utils/Settings');
const logger = { error: (...args) => console.error('[ep_redis_publisher]', ...args) };

const CHANNEL = settings.ep_redis_publisher.channel || 'from-etherpad-redis-channel';

const sanitizeMessageBody = (body) => {
  let response = { ...body };

  if (response.pad && response.pad._db) {
    response = {
      ...response,
      pad: {
        ...response.pad,
        _db: undefined,
      },
    };
  }

  if (body?.pad?.id) { body.pad.padId = body.pad.id; }

  return response;
};

const getCircularReplacer = () => {
  const seen = new WeakSet();

  return (key, value) => {
    if (typeof value === "object" && value !== null) {
      if (seen.has(value)) return;

      seen.add(value);
    }

    return value;
  };
};

const retry = (options) => {
  if (options.error && options.error.code === 'ECONNREFUSED') {
    logger.error('redis', 'connection refused');

    return new Error('refused');
  }

  if (options.total_retry_time > 1000 * 60 * 60) {
    logger.error('redis', 'retry exhausted');

    return new Error('exhausted');
  }

  if (options.attempt > 10) {
    logger.error('redis', 'attempt limit');

    return undefined;
  }

  return Math.min(options.attempt * 100, 3000);
};

const options = {
  host: settings.ep_redis_publisher.host || '127.0.0.1',
  port: settings.ep_redis_publisher.port || 6379,
  retry_strategy: retry,
};

if (settings.ep_redis_publisher.password) {
  options.password = settings.ep_redis_publisher.password;
}

const publisher = redis.createClient(options);

const buildEnvelope = (name) => {

  return {
    name,
    routing: { sender: 'etherpad' },
    timestamp: (new Date()).getTime(),
  };
};

const buildCore = (name, body) => {

  return {
    header: { name },
    body,
  };
};

const build = (name, body) => {

  return JSON.stringify({
    envelope: buildEnvelope(name),
    core: buildCore(name, sanitizeMessageBody(body)),
  }, getCircularReplacer());
};

exports.publish = (event, body) => {
  let message;
  switch (event) {
    case 'loadSettings':
      message = build('PadLoadSettingsSysMsg', body);
      break;
    case 'shutdown':
      message = build('PadShutdownSysMsg', body);
      break;
    case 'expressConfigure':
      message = build('PadConfigureSysMsg', body);
      break;
    case 'expressCreateServer':
      message = build('PadCreateServerSysMsg', body);
      break;
    case 'expressCloseServer':
      message = build('PadCloseServerSysMsg', body);
      break;
    case 'onAccessCheck':
      message = build('PadAccessCheckSysMsg', body);
      break;
    case 'padCreate':
      message = build('PadCreateSysMsg', body);
      break;
    case 'padLoad':
      message = build('PadLoadSysMsg', body);
      break;
    case 'padUpdate':
      message = build('PadUpdateSysMsg', body);
      break;
    case 'padCopy':
      message = build('PadCopySysMsg', body);
      break;
    case 'padRemove':
      message = build('PadRemoveSysMsg', body);
      break;
    case 'userLeave':
      message = build('PadUserLeaveSysMsg', body);
      break;

    default:
      return;
  }

  if (message) {
    publisher.publish(CHANNEL, message);
  }
};
