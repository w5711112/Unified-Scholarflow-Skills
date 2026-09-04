import { randomBytes } from 'node:crypto';
import { createConnection } from 'node:net';
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';


export const DEFAULT_PIPE_PATH = String.raw`\\.\pipe\codex.searching_at_scale.v1`;
const PROTOCOL_VERSION = 3;
const MAX_INPUT_BYTES = 64 * 1024;
const MAX_BROKER_BYTES = 512 * 1024;
const MAX_OUTPUT_BYTES = 200 * 1024;
const CONFIG_KEYS = new Set([
  'platform',
  'query',
  'query_family',
  'cursor',
  'user_data_dir',
  'deadline_seconds',
  'max_items',
  'session_action',
  'pagination_enabled',
]);
const CURSOR_KEYS = new Set(['cursor_id', 'ordinal', 'page_number']);
const TASK_KEYS = new Set([
  'type',
  'protocol_version',
  'operation',
  'task_id',
  'platform',
  'query',
  'query_family',
  'cursor',
  'deadline_seconds',
  'max_items',
  'session_action',
  'pagination_enabled',
  'pagination_route',
]);
const RESULT_KEYS = new Set(['type', 'protocol_version', 'task_id', 'payload']);
const ERROR_KEYS = new Set([
  'type',
  'protocol_version',
  'task_id',
  'category',
  'retryable',
]);
const PAYLOAD_KEYS = new Set([
  'projection_schema_version',
  'capabilities',
  'platform',
  'page_state',
  'source_url',
  'query_family',
  'cursor',
  'observed_page_number',
  'pagination_state',
  'has_next_page',
  'sku_digest',
  'diagnostics',
  'items',
]);
const DIAGNOSTIC_KEYS = new Set([
  'document_ready_state',
  'data_sku_node_count',
  'candidate_anchor_count',
  'valid_item_count',
  'collection_elapsed_ms',
  'stable_rounds',
  'observed_page_number',
  'recovery_stage',
  'recovery_attempt',
  'source_path',
]);
const RESULT_CURSOR_KEYS = new Set(['cursor_id', 'page_number', 'status']);
const ITEM_KEYS = new Set(['product_id', 'title', 'url']);
const CARD_FIELD_KEYS = new Set([
  'price',
  'shop',
  'commit',
  'good_rate',
  'promo',
  'stock',
  'image',
]);
const PROJECTION_SCHEMA_VERSION = 4;
const REQUIRED_PROJECTION_CAPABILITIES = Object.freeze([
  'stable_card_fields_v2',
  'verified_pagination_v1',
  'resilient_pagination_v1',
]);
const SOURCE_HOSTS = Object.freeze({ jd: 'search.jd.com', taobao: 's.taobao.com' });
const SOURCE_PATHS = Object.freeze({ jd: '/Search', taobao: '/search' });
const PAGE_STATES = new Set([
  'ready',
  'authentication_required',
  'captcha_required',
  'page_structure_changed',
  'rate_limited',
]);
const CURSOR_STATUSES = new Set(['advanced', 'exhausted', 'stalled']);
const PAGINATION_STATES = new Set([
  'pagination_unverified',
  'page_verified',
  'page_exhausted',
  'page_stalled',
]);
const DOCUMENT_READY_STATES = new Set(['loading', 'interactive', 'complete']);
const RECOVERY_STAGES = new Set(['initial', 'reproject', 'reload']);
const RETRYABLE_CATEGORIES = new Set([
  'edge_background_bridge_unavailable',
  'edge_background_bridge_busy',
  'edge_background_bridge_disconnected',
  'edge_extension_timeout',
  'rate_limited',
]);


export class EdgeExtensionError extends Error {
  constructor(category, exitCode, detail, retryable = false) {
    super(`${category}: ${detail}`);
    this.name = 'EdgeExtensionError';
    this.category = category;
    this.exitCode = exitCode;
    this.detail = detail;
    this.retryable = retryable;
  }
}


export function probeBrokerPipe(options = {}) {
  const pipePath = options.pipePath ?? DEFAULT_PIPE_PATH;
  const timeoutMs = Math.max(1, Math.ceil(options.timeoutMs ?? 60_000));
  const connector = options.connector ?? createConnection;
  return new Promise((resolve, reject) => {
    let settled = false;
    let socket;
    const finish = (callback, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      socket?.destroy();
      callback(value);
    };
    const unavailable = () => new EdgeExtensionError(
      'edge_background_bridge_unavailable',
      3,
      'named pipe is unavailable',
      true,
    );
    const timer = setTimeout(() => finish(reject, unavailable()), timeoutMs);
    try {
      socket = connector(pipePath);
    } catch {
      finish(reject, unavailable());
      return;
    }
    socket.once('connect', () => finish(resolve, {
      ok: true,
      pipe: String(pipePath).split('\\').at(-1),
    }));
    socket.once('error', () => finish(reject, unavailable()));
  });
}


function fail(category, exitCode, detail, retryable = false) {
  throw new EdgeExtensionError(category, exitCode, detail, retryable);
}


function exactKeys(value, expected, name, category = 'edge_input_invalid') {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    fail(category, 2, `${name} must be an object`);
  }
  const keys = Object.keys(value);
  if (keys.length !== expected.size || keys.some((key) => !expected.has(key))) {
    fail(category, 2, `${name} keys must match the whitelist`);
  }
}

function keysWithinAllowed(value, required, optional, name, category) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    fail(category, 2, `${name} must be an object`);
  }
  const keys = Object.keys(value);
  const allowed = new Set([...required, ...optional]);
  if (
    keys.some((key) => !allowed.has(key))
    || required.some((key) => !keys.includes(key))
  ) {
    fail(category, 2, `${name} keys are outside the allowed whitelist`);
  }
}


function requiredText(
  value,
  name,
  { allowEmpty = false, maximum = 4096, category = 'edge_input_invalid' } = {},
) {
  if (typeof value !== 'string') {
    fail(category, 2, `${name} must be a string`);
  }
  const normalized = value.trim();
  if (
    (!allowEmpty && !normalized)
    || normalized.length > maximum
    || /[\u0000-\u001f]/u.test(normalized)
  ) {
    fail(category, 2, `${name} is invalid`);
  }
  return normalized;
}


function boundedInteger(value, name, minimum, maximum, category = 'edge_input_invalid') {
  if (!Number.isSafeInteger(value) || value < minimum || value > maximum) {
    fail(category, 2, `${name} is outside its allowed range`);
  }
  return value;
}


function validateConfig(value) {
  exactKeys(value, CONFIG_KEYS, 'config');
  const platform = requiredText(value.platform, 'platform', { maximum: 16 });
  if (!Object.hasOwn(SOURCE_HOSTS, platform)) {
    fail('edge_platform_invalid', 2, 'unsupported marketplace');
  }
  exactKeys(value.cursor, CURSOR_KEYS, 'cursor');
  const deadline = value.deadline_seconds;
  if (typeof deadline !== 'number' || !Number.isFinite(deadline) || deadline <= 0 || deadline > 600) {
    fail('edge_input_invalid', 2, 'deadline_seconds must be in (0, 600]');
  }
  const sessionAction = requiredText(value.session_action, 'session_action', { maximum: 16 });
  if (!new Set(['start', 'next', 'recover']).has(sessionAction)) {
    fail('edge_input_invalid', 2, 'session_action is unsupported');
  }
  if (typeof value.pagination_enabled !== 'boolean') {
    fail('edge_input_invalid', 2, 'pagination_enabled must be a boolean');
  }
  const pageNumber = boundedInteger(value.cursor.page_number, 'page_number', 1, 512);
  if (sessionAction === 'start' && pageNumber !== 1) {
    fail('edge_input_invalid', 2, 'start action must target page 1');
  }
  if (sessionAction !== 'start' && !value.pagination_enabled) {
    fail('edge_input_invalid', 2, 'pagination action requires explicit enablement');
  }
  if (sessionAction === 'next' && pageNumber <= 1) {
    fail('edge_input_invalid', 2, 'next action must target a later page');
  }
  return {
    platform,
    query: requiredText(value.query, 'query', { maximum: 512 }),
    queryFamily: requiredText(value.query_family, 'query_family', { maximum: 512 }),
    cursorId: requiredText(value.cursor.cursor_id, 'cursor_id', { maximum: 512 }),
    ordinal: boundedInteger(value.cursor.ordinal, 'ordinal', 0, 1000000),
    pageNumber,
    deadlineSeconds: deadline,
    maxItems: boundedInteger(value.max_items, 'max_items', 1, 1000),
    sessionAction,
    paginationEnabled: value.pagination_enabled,
  };
}


function validateTaskId(value, category = 'edge_input_invalid') {
  const taskId = requiredText(value, 'task_id', { maximum: 32, category });
  if (!/^[0-9a-f]{32}$/u.test(taskId)) {
    fail(category, 2, 'task_id is invalid');
  }
  return taskId;
}


export function buildBrokerTask(rawConfig, taskId) {
  const config = validateConfig(rawConfig);
  // The driver sets SAT_JD_PAGINATION_ROUTE to override the extension route for
  // one run. Absent/null means "use extension storage".
  const routeOverride = typeof process.env.SAT_JD_PAGINATION_ROUTE === 'string'
    ? process.env.SAT_JD_PAGINATION_ROUTE.trim()
    : '';
  const paginationRoute = routeOverride.length > 0 ? routeOverride : null;
  return {
    type: 'task',
    protocol_version: PROTOCOL_VERSION,
    operation: 'search',
    task_id: validateTaskId(taskId),
    platform: config.platform,
    query: config.query,
    query_family: config.queryFamily,
    cursor: {
      cursor_id: config.cursorId,
      ordinal: config.ordinal,
      page_number: config.pageNumber,
    },
    deadline_seconds: config.deadlineSeconds,
    max_items: config.maxItems,
    session_action: config.sessionAction,
    pagination_enabled: config.paginationEnabled,
    pagination_route: paginationRoute,
  };
}


function validateTask(task) {
  exactKeys(task, TASK_KEYS, 'task', 'edge_extension_projection_invalid');
  if (task.protocol_version !== PROTOCOL_VERSION || task.type !== 'task') {
    fail('edge_extension_projection_invalid', 5, 'task protocol is invalid');
  }
  validateTaskId(task.task_id, 'edge_extension_projection_invalid');
  if (task.operation !== 'search') {
    fail('edge_operation_unsupported', 2, 'only search is supported');
  }
}


export function encodeFrame(value) {
  const encoded = Buffer.from(JSON.stringify(value), 'utf8');
  if (encoded.length === 0 || encoded.length > MAX_BROKER_BYTES) {
    throw new Error('broker frame exceeded its limit');
  }
  const frame = Buffer.allocUnsafe(encoded.length + 4);
  frame.writeUInt32LE(encoded.length, 0);
  encoded.copy(frame, 4);
  return frame;
}


export function decodeFrame(frame) {
  if (!Buffer.isBuffer(frame) || frame.length < 4) {
    throw new Error('broker framing is incomplete');
  }
  const size = frame.readUInt32LE(0);
  if (size === 0 || size > MAX_BROKER_BYTES) {
    throw new Error('broker frame exceeded its limit');
  }
  if (frame.length !== size + 4) {
    throw new Error('broker framing has trailing or missing bytes');
  }
  try {
    return JSON.parse(frame.subarray(4).toString('utf8'));
  } catch {
    throw new Error('broker frame JSON is invalid');
  }
}


function canonicalItem(platform, item) {
  const category = 'edge_extension_projection_invalid';
  exactKeys(item, new Set([...ITEM_KEYS, ...CARD_FIELD_KEYS]), 'item', category);
  const productId = requiredText(item.product_id, 'product_id', { maximum: 64, category });
  const title = requiredText(item.title, 'title', { maximum: 1000, category });
  let url;
  try {
    url = new URL(requiredText(item.url, 'item url', { maximum: 2048, category }));
  } catch {
    fail(category, 5, 'item URL is invalid');
  }
  if (!/^\d+$/u.test(productId) || url.protocol !== 'https:') {
    fail(category, 5, 'item identity is invalid');
  }
  const valid = platform === 'jd'
    ? url.hostname === 'item.jd.com' && url.pathname === `/${productId}.html` && !url.search
    : new Set(['item.taobao.com', 'detail.tmall.com', 'detail.tmall.hk']).has(url.hostname)
      && url.pathname === '/item.htm'
      && url.searchParams.get('id') === productId
      && [...url.searchParams.keys()].length === 1;
  if (!valid) {
    fail(category, 5, 'item URL is outside the marketplace allowlist');
  }
  const canonical = { product_id: productId, title, url: url.href };
  for (const field of CARD_FIELD_KEYS) {
    const value = item[field];
    if (value === null) {
      canonical[field] = null;
    } else if (typeof value === 'string' && value.trim()) {
      canonical[field] = requiredText(value, field, { maximum: 1024, category });
    } else {
      fail(category, 5, `${field} must be non-empty text or null`);
    }
  }
  return canonical;
}


function validateDiagnostics(value, expectedPageNumber, category) {
  exactKeys(value, DIAGNOSTIC_KEYS, 'diagnostics', category);
  if (
    !DOCUMENT_READY_STATES.has(value.document_ready_state)
    || !RECOVERY_STAGES.has(value.recovery_stage)
    || value.source_path !== '/Search'
  ) {
    fail(category, 5, 'diagnostic values are invalid');
  }
  for (const key of [
    'data_sku_node_count',
    'candidate_anchor_count',
    'valid_item_count',
    'collection_elapsed_ms',
    'stable_rounds',
  ]) {
    boundedInteger(value[key], key, 0, Number.MAX_SAFE_INTEGER, category);
  }
  const observedPageNumber = boundedInteger(
    value.observed_page_number,
    'diagnostic observed_page_number',
    1,
    512,
    category,
  );
  const recoveryAttempt = boundedInteger(
    value.recovery_attempt,
    'recovery_attempt',
    0,
    2,
    category,
  );
  if (observedPageNumber !== expectedPageNumber) {
    fail(category, 5, 'diagnostic page evidence is invalid');
  }
  return {
    document_ready_state: value.document_ready_state,
    data_sku_node_count: value.data_sku_node_count,
    candidate_anchor_count: value.candidate_anchor_count,
    valid_item_count: value.valid_item_count,
    collection_elapsed_ms: value.collection_elapsed_ms,
    stable_rounds: value.stable_rounds,
    observed_page_number: observedPageNumber,
    recovery_stage: value.recovery_stage,
    recovery_attempt: recoveryAttempt,
    source_path: '/Search',
  };
}


function validateResultPayload(task, payload) {
  const category = 'edge_extension_projection_invalid';
  if (
    payload?.projection_schema_version !== PROJECTION_SCHEMA_VERSION
    || !Array.isArray(payload?.capabilities)
    || payload.capabilities.length !== REQUIRED_PROJECTION_CAPABILITIES.length
    || payload.capabilities.some(
      (value, index) => value !== REQUIRED_PROJECTION_CAPABILITIES[index]
    )
  ) {
    fail(
      'edge_extension_reload_required',
      5,
      'Edge extension projection schema is stale',
      false,
    );
  }
  exactKeys(payload, PAYLOAD_KEYS, 'payload', category);
  exactKeys(payload.cursor, RESULT_CURSOR_KEYS, 'payload cursor', category);
  const diagnostics = validateDiagnostics(
    payload.diagnostics,
    task.cursor.page_number,
    category,
  );
  if (
    payload.platform !== task.platform
    || payload.query_family !== task.query_family
    || payload.cursor.cursor_id !== task.cursor.cursor_id
    || payload.cursor.page_number !== task.cursor.page_number
    || !CURSOR_STATUSES.has(payload.cursor.status)
    || payload.observed_page_number !== task.cursor.page_number
    || !PAGINATION_STATES.has(payload.pagination_state)
    || typeof payload.has_next_page !== 'boolean'
    || typeof payload.sku_digest !== 'string'
    || !payload.sku_digest.trim()
    || payload.sku_digest.length > 4096
    || !PAGE_STATES.has(payload.page_state)
    || !Array.isArray(payload.items)
    || payload.items.length > 1000
  ) {
    fail(category, 5, 'projection values are invalid');
  }
  let source;
  try {
    source = new URL(requiredText(payload.source_url, 'source_url', { maximum: 4096, category }));
  } catch {
    fail(category, 5, 'projection source is invalid');
  }
  if (
    source.protocol !== 'https:'
    || source.hostname !== SOURCE_HOSTS[task.platform]
    || source.pathname !== SOURCE_PATHS[task.platform]
    || source.username
    || source.password
    || source.hash
    || source.search
  ) {
    fail(category, 5, 'projection source is outside the search allowlist');
  }
  const seen = new Set();
  const items = [];
  for (const rawItem of payload.items) {
    const item = canonicalItem(task.platform, rawItem);
    if (seen.has(item.product_id)) {
      fail(category, 5, 'projection contains duplicate products');
    }
    seen.add(item.product_id);
    if (items.length < task.max_items) {
      items.push(item);
    }
  }
  if (
    diagnostics.valid_item_count !== payload.items.length
    || diagnostics.candidate_anchor_count < diagnostics.valid_item_count
  ) {
    fail(category, 5, 'diagnostic counts do not match the projection');
  }
  const expectedStatus = payload.page_state === 'ready'
    ? (items.length > 0 ? 'advanced' : 'exhausted')
    : 'stalled';
  if (payload.cursor.status !== expectedStatus) {
    fail(category, 5, 'cursor status does not match the projection');
  }
  return {
    projection_schema_version: PROJECTION_SCHEMA_VERSION,
    capabilities: [...REQUIRED_PROJECTION_CAPABILITIES],
    platform: task.platform,
    page_state: payload.page_state,
    source_url: source.href,
    query_family: task.query_family,
    cursor: {
      cursor_id: task.cursor.cursor_id,
      page_number: task.cursor.page_number,
      status: expectedStatus,
    },
    observed_page_number: payload.observed_page_number,
    pagination_state: payload.pagination_state,
    has_next_page: payload.has_next_page,
    sku_digest: payload.sku_digest,
    diagnostics,
    items,
  };
}


export function validateBrokerEnvelope(task, envelope) {
  validateTask(task);
  const category = 'edge_extension_projection_invalid';
  if (envelope?.type === 'error') {
    exactKeys(envelope, ERROR_KEYS, 'error envelope', category);
    if (
      envelope.protocol_version !== PROTOCOL_VERSION
      || envelope.task_id !== task.task_id
      || typeof envelope.retryable !== 'boolean'
      || typeof envelope.category !== 'string'
      || !/^[a-z][a-z0-9_]{2,79}$/u.test(envelope.category)
    ) {
      fail(category, 5, 'broker error envelope is invalid');
    }
    throw new EdgeExtensionError(
      envelope.category,
      3,
      'background Edge broker returned an error',
      envelope.retryable,
    );
  }
  exactKeys(envelope, RESULT_KEYS, 'result envelope', category);
  if (
    envelope.type !== 'result'
    || envelope.protocol_version !== PROTOCOL_VERSION
    || envelope.task_id !== task.task_id
  ) {
    fail(category, 5, 'broker result envelope is invalid');
  }
  return validateResultPayload(task, envelope.payload);
}


export function exchangeBrokerFrame(task, dependencies = {}) {
  const pipePath = dependencies.pipePath ?? DEFAULT_PIPE_PATH;
  const connect = dependencies.connectFactory ?? createConnection;
  const timeoutMilliseconds = Math.max(1000, Math.ceil(task.deadline_seconds * 1000));
  return new Promise((resolve, reject) => {
    let settled = false;
    let connected = false;
    let expectedLength = null;
    let buffered = Buffer.alloc(0);
    let socket;
    const finish = (callback, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      socket?.destroy();
      callback(value);
    };
    const timer = setTimeout(() => finish(
      reject,
      new EdgeExtensionError('edge_extension_timeout', 3, 'background Edge task timed out', true),
    ), timeoutMilliseconds);
    try {
      socket = connect(pipePath);
    } catch {
      finish(reject, new EdgeExtensionError(
        'edge_background_bridge_unavailable', 3, 'named pipe is unavailable', true,
      ));
      return;
    }
    socket.once('connect', () => {
      connected = true;
      socket.write(encodeFrame(task));
    });
    socket.on('data', (chunk) => {
      buffered = Buffer.concat([buffered, chunk]);
      if (buffered.length > MAX_BROKER_BYTES + 4) {
        finish(reject, new EdgeExtensionError(
          'edge_extension_projection_invalid', 5, 'broker response exceeded its limit', false,
        ));
        return;
      }
      if (expectedLength === null && buffered.length >= 4) {
        expectedLength = buffered.readUInt32LE(0);
        if (expectedLength === 0 || expectedLength > MAX_BROKER_BYTES) {
          finish(reject, new EdgeExtensionError(
            'edge_extension_projection_invalid', 5, 'broker response length is invalid', false,
          ));
          return;
        }
      }
      if (expectedLength !== null && buffered.length === expectedLength + 4) {
        try {
          finish(resolve, decodeFrame(buffered));
        } catch {
          finish(reject, new EdgeExtensionError(
            'edge_extension_projection_invalid', 5, 'broker response framing is invalid', false,
          ));
        }
      } else if (expectedLength !== null && buffered.length > expectedLength + 4) {
        finish(reject, new EdgeExtensionError(
          'edge_extension_projection_invalid', 5, 'broker response has trailing bytes', false,
        ));
      }
    });
    socket.once('error', () => finish(
      reject,
      new EdgeExtensionError(
        connected ? 'edge_background_bridge_disconnected' : 'edge_background_bridge_unavailable',
        3,
        connected ? 'background broker disconnected' : 'named pipe is unavailable',
        true,
      ),
    ));
    socket.once('end', () => {
      if (!settled) {
        finish(reject, new EdgeExtensionError(
          'edge_background_bridge_disconnected', 3, 'background broker ended early', true,
        ));
      }
    });
  });
}


function fitBatch(batch) {
  const fitted = { ...batch, items: [...batch.items] };
  while (Buffer.byteLength(JSON.stringify(fitted), 'utf8') > MAX_OUTPUT_BYTES) {
    if (fitted.items.length === 0) {
      fail('edge_extension_projection_invalid', 5, 'batch output exceeded its limit');
    }
    fitted.items.pop();
  }
  return fitted;
}


export async function runEdgeCursor(rawConfig, dependencies = {}) {
  validateConfig(rawConfig);
  const taskId = (dependencies.randomTaskId ?? (() => randomBytes(16).toString('hex')))();
  const task = buildBrokerTask(rawConfig, taskId);
  const exchange = dependencies.exchange ?? exchangeBrokerFrame;
  const envelope = await exchange(task, dependencies);
  return fitBatch(validateBrokerEnvelope(task, envelope));
}


export async function runWorkerSession(lines, dependencies = {}) {
  if (lines === null || typeof lines?.[Symbol.asyncIterator] !== 'function'
      && typeof lines?.[Symbol.iterator] !== 'function') {
    fail('edge_input_invalid', 2, 'worker input must be iterable');
  }
  const writeLine = dependencies.writeLine ?? ((line) => process.stdout.write(`${line}\n`));
  for await (const rawLine of lines) {
    if (typeof rawLine !== 'string' || Buffer.byteLength(rawLine, 'utf8') > MAX_INPUT_BYTES) {
      writeLine(JSON.stringify({ error: { category: 'edge_input_invalid', retryable: false } }));
      continue;
    }
    try {
      const rawConfig = JSON.parse(rawLine);
      const batch = await runEdgeCursor(rawConfig, dependencies);
      writeLine(JSON.stringify(batch));
    } catch (error) {
      const category = error instanceof EdgeExtensionError
        ? error.category
        : 'edge_extension_failure';
      const retryable = error instanceof EdgeExtensionError
        ? error.retryable || RETRYABLE_CATEGORIES.has(category)
        : false;
      writeLine(JSON.stringify({ error: { category, retryable } }));
    }
  }
}


function cliPipePath() {
  const index = process.argv.indexOf('--pipe-path');
  if (index < 0 || !process.argv[index + 1]) {
    return null;
  }
  return process.argv[index + 1];
}


async function main() {
  const pipePath = cliPipePath();
  if (process.argv.includes('--probe-pipe')) {
    const timeoutIndex = process.argv.indexOf('--timeout-ms');
    const parsedTimeout = timeoutIndex >= 0
      ? Number(process.argv[timeoutIndex + 1])
      : 60_000;
    try {
      const result = await probeBrokerPipe({ timeoutMs: parsedTimeout, pipePath });
      process.stdout.write(`${JSON.stringify(result)}\n`);
    } catch (error) {
      const category = error instanceof EdgeExtensionError
        ? error.category
        : 'edge_background_bridge_unavailable';
      process.stdout.write(`${JSON.stringify({
        error: { category, retryable: true },
      })}\n`);
      process.exitCode = 3;
    }
    return;
  }
  const lines = createInterface({ input: process.stdin, crlfDelay: Infinity });
  await runWorkerSession(lines, pipePath ? { pipePath } : {});
}


if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  await main();
}
