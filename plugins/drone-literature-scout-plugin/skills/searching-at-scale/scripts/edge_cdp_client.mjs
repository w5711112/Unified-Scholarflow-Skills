import { spawn } from 'node:child_process';
import { access, mkdir, readFile, unlink } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { createConnection } from 'node:net';
import path from 'node:path';
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';


const CONFIG_KEYS = new Set([
  'platform',
  'query',
  'query_family',
  'cursor',
  'user_data_dir',
  'deadline_seconds',
  'max_items',
]);
const CURSOR_KEYS = new Set(['cursor_id', 'ordinal', 'page_number']);
const LOOPBACK_HOSTS = new Set(['127.0.0.1', 'localhost', '[::1]']);
const ALLOWED_PAGE_STATES = new Set([
  'ready',
  'authentication_required',
  'captcha_required',
  'page_structure_changed',
  'rate_limited',
]);
const SOURCE_HOSTS = {
  jd: new Set(['search.jd.com']),
  taobao: new Set(['s.taobao.com']),
};
const AUTH_HOSTS = new Set([
  'passport.jd.com',
  'login.taobao.com',
  'login.tmall.com',
]);
const CAPTCHA_HOSTS = new Set([
  'safe.jd.com',
  'sec.taobao.com',
  'captcha.jd.com',
]);
const MAX_PROTOCOL_MESSAGE_BYTES = 1024 * 1024;
const EDGE_CLIENT_USER_AGENT = 'Puppeteer 25.4.0';
const require = createRequire(import.meta.url);
let DefaultWebSocket = null;
try {
  const wsModule = require('ws');
  DefaultWebSocket = wsModule.WebSocket ?? wsModule;
} catch {
  // Converted to a compact stable category when the transport is requested.
}

export const ALLOWED_METHODS = new Set([
  'Target.createTarget',
  'Target.attachToTarget',
  'Target.closeTarget',
  'Page.enable',
  'Page.navigate',
  'Runtime.enable',
  'Runtime.evaluate',
]);


export class EdgeCdpError extends Error {
  constructor(category, exitCode, detail) {
    super(`${category}: ${detail}`);
    this.name = 'EdgeCdpError';
    this.category = category;
    this.exitCode = exitCode;
    this.detail = detail;
  }
}


function fail(category, exitCode, detail) {
  throw new EdgeCdpError(category, exitCode, detail);
}


function exactKeys(value, allowed, name) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    fail('edge_input_invalid', 2, `${name} must be an object`);
  }
  const keys = Object.keys(value);
  if (keys.length !== allowed.size || keys.some((key) => !allowed.has(key))) {
    fail('edge_input_invalid', 2, `${name} keys must match the whitelist`);
  }
}


function requiredText(value, name, { allowEmpty = false } = {}) {
  if (typeof value !== 'string') {
    fail('edge_input_invalid', 2, `${name} must be a string`);
  }
  const normalized = value.trim();
  if ((!allowEmpty && !normalized) || /[\u0000-\u001f]/u.test(normalized)) {
    fail('edge_input_invalid', 2, `${name} is invalid`);
  }
  return normalized;
}


function positiveInteger(value, name, maximum = Number.MAX_SAFE_INTEGER) {
  if (!Number.isSafeInteger(value) || value < 1 || value > maximum) {
    fail('edge_input_invalid', 2, `${name} must be a bounded positive integer`);
  }
  return value;
}


function validateConfig(value) {
  exactKeys(value, CONFIG_KEYS, 'config');
  const platform = requiredText(value.platform, 'platform');
  if (!Object.hasOwn(SOURCE_HOSTS, platform)) {
    fail('edge_platform_invalid', 2, 'unsupported marketplace');
  }
  const query = requiredText(value.query, 'query');
  const queryFamily = requiredText(value.query_family, 'query_family');
  exactKeys(value.cursor, CURSOR_KEYS, 'cursor');
  const cursorId = requiredText(value.cursor.cursor_id, 'cursor_id');
  if (!Number.isSafeInteger(value.cursor.ordinal) || value.cursor.ordinal < 0) {
    fail('edge_input_invalid', 2, 'cursor ordinal must be non-negative');
  }
  const pageNumber = positiveInteger(value.cursor.page_number, 'page_number');
  const userDataDir = requiredText(
    value.user_data_dir,
    'user_data_dir',
    { allowEmpty: true },
  );
  if (
    typeof value.deadline_seconds !== 'number'
    || !Number.isFinite(value.deadline_seconds)
    || value.deadline_seconds <= 0
    || value.deadline_seconds > 600
  ) {
    fail('edge_input_invalid', 2, 'deadline_seconds must be in (0, 600]');
  }
  const maxItems = positiveInteger(value.max_items, 'max_items', 1000);
  return {
    platform,
    query,
    queryFamily,
    cursorId,
    ordinal: value.cursor.ordinal,
    pageNumber,
    userDataDir,
    deadlineSeconds: value.deadline_seconds,
    maxItems,
  };
}


export function parseActivePort(text) {
  if (typeof text !== 'string' || text.length > 4096) {
    fail('edge_active_port_invalid', 3, 'DevToolsActivePort is invalid');
  }
  const lines = text.split(/\r?\n/u).filter((line) => line.length > 0);
  if (lines.length !== 2 || !/^\d{1,5}$/u.test(lines[0])) {
    fail('edge_active_port_invalid', 3, 'DevToolsActivePort is invalid');
  }
  const port = Number(lines[0]);
  const browserPath = lines[1];
  if (
    port < 1
    || port > 65535
    || !/^\/devtools\/browser\/[A-Za-z0-9-]+$/u.test(browserPath)
  ) {
    fail('edge_active_port_invalid', 3, 'DevToolsActivePort is invalid');
  }
  const endpoint = `ws://127.0.0.1:${port}${browserPath}`;
  assertLoopbackEndpoint(endpoint);
  return { port, browserPath, endpoint };
}


export function assertLoopbackEndpoint(endpoint) {
  let parsed;
  try {
    parsed = new URL(endpoint);
  } catch {
    fail('edge_endpoint_not_loopback', 2, 'endpoint URL is invalid');
  }
  if (
    parsed.protocol !== 'ws:'
    || !LOOPBACK_HOSTS.has(parsed.hostname)
    || !parsed.port
    || parsed.username
    || parsed.password
    || !/^\/devtools\/browser\/[A-Za-z0-9-]+$/u.test(parsed.pathname)
  ) {
    fail('edge_endpoint_not_loopback', 2, 'endpoint must be a loopback browser WebSocket');
  }
  return parsed;
}


export function createEdgeWebSocket(
  endpoint,
  WebSocketConstructor = DefaultWebSocket,
) {
  assertLoopbackEndpoint(endpoint);
  if (typeof WebSocketConstructor !== 'function') {
    fail('edge_transport_unavailable', 3, 'the ws runtime dependency is unavailable');
  }
  return new WebSocketConstructor(endpoint, [], {
    followRedirects: true,
    perMessageDeflate: false,
    allowSynchronousEvents: false,
    maxPayload: MAX_PROTOCOL_MESSAGE_BYTES,
    headers: {
      'User-Agent': EDGE_CLIENT_USER_AGENT,
    },
  });
}


function safeMessageData(data) {
  if (typeof data === 'string') {
    if (Buffer.byteLength(data, 'utf8') > MAX_PROTOCOL_MESSAGE_BYTES) {
      fail('edge_cdp_message_too_large', 5, 'protocol message exceeded limit');
    }
    return data;
  }
  if (data instanceof ArrayBuffer) {
    if (data.byteLength > MAX_PROTOCOL_MESSAGE_BYTES) {
      fail('edge_cdp_message_too_large', 5, 'protocol message exceeded limit');
    }
    return Buffer.from(data).toString('utf8');
  }
  fail('edge_cdp_message_invalid', 5, 'protocol message type is invalid');
}


export class CdpConnection {
  constructor(endpoint, {
    socketFactory = createEdgeWebSocket,
    timeoutMs = 15000,
    onClose = () => {},
  } = {}) {
    assertLoopbackEndpoint(endpoint);
    this.endpoint = endpoint;
    this.socketFactory = socketFactory;
    this.timeoutMs = timeoutMs;
    if (typeof onClose !== 'function') {
      fail('edge_input_invalid', 2, 'onClose must be callable');
    }
    this.onClose = onClose;
    this.closed = false;
    this.socket = null;
    this.nextId = 1;
    this.pending = new Map();
  }

  async connect() {
    if (this.socket !== null) {
      return;
    }
    const socket = this.socketFactory(this.endpoint);
    this.socket = socket;
    socket.addEventListener('message', (event) => this.#onMessage(event));
    socket.addEventListener('close', () => this.#rejectPending('edge_cdp_closed'));
    socket.addEventListener('error', () => this.#rejectPending('edge_cdp_socket_error'));
    await new Promise((resolve, reject) => {
      const timer = setTimeout(
        () => reject(new EdgeCdpError('edge_cdp_timeout', 5, 'WebSocket open timed out')),
        this.timeoutMs,
      );
      socket.addEventListener('open', () => {
        clearTimeout(timer);
        resolve();
      }, { once: true });
      socket.addEventListener('error', () => {
        clearTimeout(timer);
        reject(new EdgeCdpError('edge_cdp_socket_error', 5, 'WebSocket open failed'));
      }, { once: true });
    });
  }

  async send(method, params = {}, sessionId = undefined) {
    if (!ALLOWED_METHODS.has(method)) {
      throw new EdgeCdpError('edge_cdp_method_forbidden', 2, 'CDP method is not allowed');
    }
    if (this.socket === null || this.socket.readyState !== 1) {
      throw new EdgeCdpError('edge_cdp_not_connected', 5, 'CDP socket is not connected');
    }
    const id = this.nextId;
    this.nextId += 1;
    const message = { id, method, params };
    if (sessionId !== undefined) {
      message.sessionId = sessionId;
    }
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new EdgeCdpError('edge_cdp_timeout', 5, 'CDP command timed out'));
      }, this.timeoutMs);
      this.pending.set(id, { resolve, reject, timer });
      this.socket.send(JSON.stringify(message));
    });
  }

  #onMessage(event) {
    let payload;
    try {
      payload = JSON.parse(safeMessageData(event.data));
    } catch (error) {
      this.#rejectPending(error instanceof EdgeCdpError ? error.category : 'edge_cdp_json_invalid');
      return;
    }
    if (!Number.isSafeInteger(payload.id)) {
      return;
    }
    const pending = this.pending.get(payload.id);
    if (pending === undefined) {
      return;
    }
    clearTimeout(pending.timer);
    this.pending.delete(payload.id);
    if (payload.error !== undefined) {
      pending.reject(new EdgeCdpError('edge_cdp_command_failed', 5, 'CDP command failed'));
    } else {
      pending.resolve(payload.result ?? {});
    }
  }

  #rejectPending(category) {
    for (const { reject, timer } of this.pending.values()) {
      clearTimeout(timer);
      reject(new EdgeCdpError(category, 5, 'CDP connection ended'));
    }
    this.pending.clear();
  }

  close() {
    if (this.closed) {
      return;
    }
    this.closed = true;
    if (this.socket !== null && this.socket.readyState < 2) {
      this.socket.close();
    }
    this.#rejectPending('edge_cdp_closed');
    this.onClose();
  }
}


export function buildSearchUrl(platform, query, pageNumber) {
  if (!Object.hasOwn(SOURCE_HOSTS, platform)) {
    fail('edge_platform_invalid', 2, 'unsupported marketplace');
  }
  const normalizedQuery = requiredText(query, 'query');
  const page = positiveInteger(pageNumber, 'page_number');
  const encoded = encodeURIComponent(normalizedQuery);
  if (platform === 'jd') {
    return `https://search.jd.com/Search?keyword=${encoded}&enc=utf-8&page=${page * 2 - 1}`;
  }
  return `https://s.taobao.com/search?q=${encoded}&page=${page - 1}`;
}


function canonicalIdentity(platform, href) {
  let parsed;
  try {
    parsed = new URL(href);
  } catch {
    return null;
  }
  if (parsed.protocol !== 'https:' || parsed.username || parsed.password) {
    return null;
  }
  if (platform === 'jd') {
    let match = null;
    if (parsed.hostname === 'item.jd.com') {
      match = parsed.pathname.match(/^\/(\d+)\.html$/u);
    } else if (parsed.hostname === 'item.m.jd.com') {
      match = parsed.pathname.match(/^\/product\/(\d+)\.html$/u);
    }
    return match === null ? null : {
      product_id: match[1],
      url: `https://item.jd.com/${match[1]}.html`,
    };
  }
  if (
    platform === 'taobao'
    && new Set(['item.taobao.com', 'detail.tmall.com', 'detail.tmall.hk']).has(parsed.hostname)
    && parsed.pathname === '/item.htm'
  ) {
    const values = parsed.searchParams.getAll('id');
    if (values.length === 1 && /^\d+$/u.test(values[0])) {
      return {
        product_id: values[0],
        url: `https://${parsed.hostname}/item.htm?id=${values[0]}`,
      };
    }
  }
  return null;
}


export function collectMarketplaceItems(platform, anchors, maxItems) {
  if (!Object.hasOwn(SOURCE_HOSTS, platform)) {
    fail('edge_platform_invalid', 2, 'unsupported marketplace');
  }
  const limit = positiveInteger(maxItems, 'max_items', 1000);
  if (!Array.isArray(anchors) || anchors.length > limit * 4) {
    fail('edge_projection_invalid', 5, 'anchor projection is invalid');
  }
  const seen = new Set();
  const items = [];
  for (const anchor of anchors) {
    if (anchor === null || typeof anchor !== 'object' || Array.isArray(anchor)) {
      continue;
    }
    const title = typeof anchor.title === 'string' ? anchor.title.trim() : '';
    const identity = typeof anchor.href === 'string'
      ? canonicalIdentity(platform, anchor.href)
      : null;
    if (identity === null || !title || seen.has(identity.product_id)) {
      continue;
    }
    seen.add(identity.product_id);
    items.push({ ...identity, title });
    if (items.length === limit) {
      break;
    }
  }
  return items;
}


export function buildProjectionExpression(platform, maxItems) {
  const selectors = platform === 'jd'
    ? 'a[href*="item.jd.com/"],a[href*="item.m.jd.com/product/"]'
    : 'a[href*="item.taobao.com/item.htm"],a[href*="detail.tmall.com/item.htm"],a[href*="detail.tmall.hk/item.htm"]';
  return `(async () => {
    const wait = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));
    const readyDeadline = Date.now() + 10000;
    while (document.readyState === 'loading' && Date.now() < readyDeadline) {
      await wait(100);
    }
    for (let step = 1; step <= 4; step += 1) {
      const height = Math.max(document.body?.scrollHeight || 0, document.documentElement?.scrollHeight || 0);
      window.scrollTo(0, Math.floor(height * step / 4));
      await wait(350);
    }
    const host = location.hostname.toLowerCase();
    const href = location.href;
    const text = (document.body?.innerText || '').slice(0, 30000).toLowerCase();
    let pageState = 'ready';
    if (${JSON.stringify([...AUTH_HOSTS])}.includes(host) || /请登录|账号登录|扫码登录/u.test(text)) {
      pageState = 'authentication_required';
    } else if (${JSON.stringify([...CAPTCHA_HOSTS])}.includes(host) || /验证码|安全验证|滑块/u.test(text)) {
      pageState = 'captcha_required';
    } else if (/访问过于频繁|请求过于频繁|稍后再试|rate limit/u.test(text)) {
      pageState = 'rate_limited';
    }
    const anchors = Array.from(document.querySelectorAll(${JSON.stringify(selectors)}))
      .slice(0, ${Number(maxItems) * 4})
      .map((anchor) => ({
        href: anchor.href,
        title: (anchor.getAttribute('title') || anchor.getAttribute('aria-label') || anchor.textContent || '').trim(),
      }));
    if (pageState === 'ready' && anchors.length === 0 && !/暂无|没有找到|无相关商品/u.test(text)) {
      pageState = 'page_structure_changed';
    }
    return { page_state: pageState, source_url: href, anchors };
  })()`;
}


function validateProjection(platform, projection) {
  if (projection === null || typeof projection !== 'object' || Array.isArray(projection)) {
    fail('edge_projection_invalid', 5, 'projection must be an object');
  }
  const keys = Object.keys(projection);
  if (
    keys.length !== 3
    || !keys.includes('page_state')
    || !keys.includes('source_url')
    || !keys.includes('anchors')
    || !ALLOWED_PAGE_STATES.has(projection.page_state)
    || typeof projection.source_url !== 'string'
    || !Array.isArray(projection.anchors)
  ) {
    fail('edge_projection_invalid', 5, 'projection keys or values are invalid');
  }
  let parsed;
  try {
    parsed = new URL(projection.source_url);
  } catch {
    fail('edge_projection_invalid', 5, 'projection URL is invalid');
  }
  if (parsed.protocol !== 'https:') {
    fail('edge_navigation_outside_allowlist', 4, 'navigation left HTTPS');
  }
  const knownBlock = AUTH_HOSTS.has(parsed.hostname) || CAPTCHA_HOSTS.has(parsed.hostname);
  if (!SOURCE_HOSTS[platform].has(parsed.hostname) && !knownBlock) {
    fail('edge_navigation_outside_allowlist', 4, 'navigation left marketplace allowlist');
  }
  return projection;
}


async function locateEdgeExecutable() {
  const candidates = [
    process.env['PROGRAMFILES(X86)'],
    process.env.PROGRAMFILES,
    process.env.LOCALAPPDATA,
  ].filter((value) => typeof value === 'string' && value.length > 0)
    .map((root) => path.join(root, 'Microsoft', 'Edge', 'Application', 'msedge.exe'));
  for (const candidate of candidates) {
    try {
      await access(candidate);
      return candidate;
    } catch {
      // Continue through the fixed Edge installation candidates.
    }
  }
  fail('edge_executable_unavailable', 3, 'Microsoft Edge executable is unavailable');
}


async function waitForOwnedActivePort(root, child, timeoutMs = 15000) {
  const activePortPath = path.join(root, 'DevToolsActivePort');
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) {
      fail('edge_owned_browser_exited', 3, 'owned Edge exited before debugging was ready');
    }
    try {
      return parseActivePort(await readFile(activePortPath, 'utf8'));
    } catch (error) {
      if (error instanceof EdgeCdpError) {
        throw error;
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  fail('edge_owned_browser_timeout', 3, 'owned Edge did not expose debugging in time');
}


async function isLoopbackPortInUse(port, timeoutMs = 250) {
  return new Promise((resolve) => {
    const socket = createConnection({ host: '127.0.0.1', port });
    let settled = false;
    const finish = (value) => {
      if (settled) {
        return;
      }
      settled = true;
      socket.destroy();
      resolve(value);
    };
    socket.once('connect', () => finish(true));
    socket.once('error', () => finish(false));
    socket.setTimeout(timeoutMs, () => finish(false));
  });
}


export async function launchOwnedEdge(userDataDir, dependencies = {}) {
  const normalized = requiredText(userDataDir, 'user_data_dir');
  const root = path.resolve(normalized);
  if (!path.isAbsolute(normalized) || path.basename(root).toLowerCase() !== 'edge-profile') {
    fail('edge_profile_invalid', 2, 'owned Edge profile path is invalid');
  }
  await mkdir(root, { recursive: true });
  const activePortPath = path.join(root, 'DevToolsActivePort');
  let existingActivePort = null;
  try {
    existingActivePort = parseActivePort(await readFile(activePortPath, 'utf8'));
  } catch (error) {
    if (error instanceof EdgeCdpError) {
      fail('edge_profile_in_use', 3, 'owned Edge profile state is not safely reusable');
    }
    if (error?.code !== 'ENOENT') {
      fail('edge_profile_in_use', 3, 'owned Edge profile state is unavailable');
    }
  }
  if (existingActivePort !== null) {
    const activePortInUse = dependencies.activePortInUse ?? isLoopbackPortInUse;
    if (await activePortInUse(existingActivePort.port)) {
      fail('edge_profile_in_use', 3, 'owned Edge profile already has a live endpoint');
    }
    try {
      await unlink(activePortPath);
    } catch {
      fail('edge_profile_in_use', 3, 'stale Edge profile state could not be cleared');
    }
  }
  const locateEdge = dependencies.locateEdge ?? locateEdgeExecutable;
  const spawnFactory = dependencies.spawnFactory ?? spawn;
  const waitForActivePort = dependencies.waitForActivePort ?? waitForOwnedActivePort;
  const executable = await locateEdge();
  const args = [
    `--user-data-dir=${root}`,
    '--remote-debugging-port=0',
    '--remote-debugging-address=127.0.0.1',
    '--no-first-run',
    '--no-default-browser-check',
    '--start-minimized',
    'about:blank',
  ];
  const child = spawnFactory(executable, args, {
    detached: false,
    shell: false,
    stdio: 'ignore',
    windowsHide: false,
  });
  let closed = false;
  const close = () => {
    if (!closed) {
      closed = true;
      if (child.exitCode === null) {
        child.kill();
      }
    }
  };
  try {
    const { endpoint } = await waitForActivePort(root, child);
    assertLoopbackEndpoint(endpoint);
    return { endpoint, close };
  } catch (error) {
    close();
    throw error;
  }
}


async function defaultConnection(config) {
  const root = config.userDataDir || (
    process.env.LOCALAPPDATA
      ? path.join(process.env.LOCALAPPDATA, 'Microsoft', 'Edge', 'User Data')
      : ''
  );
  if (!root) {
    fail('edge_remote_debugging_disabled', 3, 'Edge user data directory is unavailable');
  }
  let endpoint;
  let owner = null;
  if (config.userDataDir) {
    owner = await launchOwnedEdge(root);
    endpoint = owner.endpoint;
  } else {
    let text;
    try {
      text = await readFile(path.join(root, 'DevToolsActivePort'), 'utf8');
    } catch {
      fail('edge_remote_debugging_disabled', 3, 'DevToolsActivePort is unavailable');
    }
    ({ endpoint } = parseActivePort(text));
  }
  return new CdpConnection(endpoint, {
    timeoutMs: Math.min(15000, Math.max(1000, config.deadlineSeconds * 1000)),
    onClose: owner === null ? () => {} : owner.close,
  });
}


export async function runEdgeCursor(rawConfig, dependencies = {}) {
  const config = validateConfig(rawConfig);
  const connection = dependencies.connection ?? await defaultConnection(config);
  const retryDelay = dependencies.retryDelay
    ?? ((milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds)));
  let targetId = null;
  try {
    await connection.connect();
    const created = await connection.send('Target.createTarget', {
      url: 'about:blank',
      background: true,
      focus: false,
    });
    targetId = requiredText(created.targetId, 'targetId');
    const attached = await connection.send('Target.attachToTarget', {
      targetId,
      flatten: true,
    });
    const sessionId = requiredText(attached.sessionId, 'sessionId');
    await connection.send('Page.enable', {}, sessionId);
    await connection.send('Runtime.enable', {}, sessionId);
    await connection.send('Page.navigate', {
      url: buildSearchUrl(config.platform, config.query, config.pageNumber),
    }, sessionId);
    const evaluationParams = {
      expression: buildProjectionExpression(config.platform, config.maxItems),
      awaitPromise: true,
      returnByValue: true,
    };
    const maxEvaluationAttempts = Math.max(
      1,
      Math.min(100, Math.ceil(config.deadlineSeconds * 10)),
    );
    let evaluated;
    for (let attempt = 1; attempt <= maxEvaluationAttempts; attempt += 1) {
      try {
        evaluated = await connection.send(
          'Runtime.evaluate',
          evaluationParams,
          sessionId,
        );
        break;
      } catch (error) {
        if (
          !(error instanceof EdgeCdpError)
          || error.category !== 'edge_cdp_command_failed'
          || attempt === maxEvaluationAttempts
        ) {
          throw error;
        }
        await retryDelay(100);
      }
    }
    if (evaluated.exceptionDetails !== undefined) {
      fail('edge_cdp_evaluation_failed', 5, 'page projection failed');
    }
    const projection = validateProjection(
      config.platform,
      evaluated.result?.value,
    );
    const items = collectMarketplaceItems(
      config.platform,
      projection.anchors,
      config.maxItems,
    );
    const cursorStatus = projection.page_state === 'ready'
      ? (items.length > 0 ? 'advanced' : 'exhausted')
      : 'stalled';
    return {
      platform: config.platform,
      page_state: projection.page_state,
      source_url: projection.source_url,
      query_family: config.queryFamily,
      cursor: {
        cursor_id: config.cursorId,
        page_number: config.pageNumber,
        status: cursorStatus,
      },
      items,
    };
  } finally {
    if (targetId !== null) {
      try {
        await connection.send('Target.closeTarget', { targetId });
      } catch {
        // Closing an owned target is best-effort after a broken CDP connection.
      }
    }
    connection.close();
  }
}


async function readStdin(limit = 64 * 1024) {
  process.stdin.setEncoding('utf8');
  let value = '';
  for await (const chunk of process.stdin) {
    value += chunk;
    if (Buffer.byteLength(value, 'utf8') > limit) {
      fail('edge_input_invalid', 2, 'stdin exceeds limit');
    }
  }
  return value;
}


export async function runWorkerSession(lines, dependencies = {}) {
  if (lines === null || typeof lines?.[Symbol.asyncIterator] !== 'function') {
    fail('edge_input_invalid', 2, 'worker input must be an async iterable');
  }
  const connectionFactory = dependencies.connectionFactory ?? defaultConnection;
  const writeLine = dependencies.writeLine ?? ((line) => process.stdout.write(`${line}\n`));
  if (typeof connectionFactory !== 'function' || typeof writeLine !== 'function') {
    fail('edge_input_invalid', 2, 'worker session dependencies are invalid');
  }
  let connection = null;
  let sessionUserDataDir = null;
  try {
    for await (const rawLine of lines) {
      if (typeof rawLine !== 'string' || Buffer.byteLength(rawLine, 'utf8') > 64 * 1024) {
        writeLine(JSON.stringify({ error: { category: 'edge_input_invalid', retryable: false } }));
        continue;
      }
      try {
        const rawConfig = JSON.parse(rawLine);
        const config = validateConfig(rawConfig);
        if (connection === null) {
          connection = await connectionFactory(config);
          await connection.connect();
          sessionUserDataDir = config.userDataDir;
        } else if (config.userDataDir !== sessionUserDataDir) {
          fail('edge_session_profile_changed', 2, 'worker session profile changed');
        }
        const borrowedConnection = {
          async connect() {},
          send: (method, params, sessionId) => connection.send(method, params, sessionId),
          close() {},
        };
        const batch = await runEdgeCursor(rawConfig, { connection: borrowedConnection });
        writeLine(JSON.stringify(batch));
      } catch (error) {
        const category = error instanceof EdgeCdpError ? error.category : 'edge_cdp_failure';
        writeLine(JSON.stringify({ error: { category, retryable: false } }));
      }
    }
  } finally {
    connection?.close();
  }
}


async function main() {
  const lines = createInterface({ input: process.stdin, crlfDelay: Infinity });
  await runWorkerSession(lines);
  return 0;
}


if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exitCode = await main();
}
