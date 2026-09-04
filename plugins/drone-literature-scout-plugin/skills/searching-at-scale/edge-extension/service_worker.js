'use strict';

const NATIVE_HOST = 'com.codex.searching_at_scale';
const PROTOCOL_VERSION = 3;
const PROJECTION_SCHEMA_VERSION = 4;
const REQUIRED_PROJECTION_CAPABILITIES = Object.freeze([
  'stable_card_fields_v2',
  'verified_pagination_v1',
  'resilient_pagination_v1',
]);
const ROUTE_KEY = 'searching-at-scale-current-task';
const SESSION_KEY = 'searching-at-scale-pagination-session';
const JD_RISK_KEY = 'searching-at-scale-jd-risk-circuit';
const JD_PAGINATION_ROUTE_KEY = 'searching-at-scale-jd-pagination-route';
const JD_PAGE_JUMP_DEFAULT_MIGRATION_KEY =
  'searching-at-scale-jd-page-jump-default-v1';
const JD_PUBLIC_CONTROL_DEFAULT_MIGRATION_KEY =
  'searching-at-scale-jd-public-control-default-v1';
const JD_NUMBERED_LINK_DEFAULT_MIGRATION_KEY =
  'searching-at-scale-jd-numbered-link-default-v1';
const JD_INFINITE_SCROLL_DEFAULT_MIGRATION_KEY =
  'searching-at-scale-jd-infinite-scroll-default-v1';
const JD_EXPERIMENTAL_URL_DEFAULT_MIGRATION_KEY =
  'searching-at-scale-jd-experimental-url-default-v1';
const JD_RISK_COOLDOWN_MS = 60 * 60 * 1000;
const RECONNECT_ALARM = 'searching-at-scale-native-reconnect';
const TIMEOUT_PREFIX = 'searching-at-scale-timeout:';
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
const CURSOR_KEYS = new Set(['cursor_id', 'ordinal', 'page_number']);
const PROJECTION_KEYS = new Set([
  'type',
  'projection_schema_version',
  'capabilities',
  'platform',
  'page_state',
  'source_url',
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
  // 2026-08-12: pagination-DOM probe shipped with every JD projection so the
  // driver can see the live page-pagination structure (current-page marker,
  // next-page control href, bottom-page container) without extra round-trips.
  'pagination_dom',
]);
const PAGE_STATES = new Set([
  'ready',
  'authentication_required',
  'captcha_required',
  'page_structure_changed',
  'rate_limited',
]);
const SEARCH_HOSTS = Object.freeze({ jd: 'search.jd.com', taobao: 's.taobao.com' });
const SESSION_ACTIONS = new Set(['start', 'next', 'recover']);
const PAGINATION_STATES = new Set([
  'pagination_unverified', 'page_verified', 'page_exhausted', 'page_stalled',
]);
const DOCUMENT_READY_STATES = new Set(['loading', 'interactive', 'complete']);
const RECOVERY_STAGES = new Set(['initial', 'reproject', 'reload']);
const HARD_RISK_STATES = new Set([
  'authentication_required', 'captcha_required', 'rate_limited',
]);
const JD_PAGINATION_ROUTES = new Set([
  'existing', 'public_control', 'numbered_link', 'page_jump', 'infinite_scroll',
  // 2026-08-11 promoted: the foreground direct-URL route (physical page 2n-1).
  // It is the default and the only route proven to flip JD pages reliably
  // (zero risk-control across six canaries, deep to the page cap). Foreground
  // activation before navigation is an authorized stable behavior.
  'experimental_url',
  // 2026-08-12: human-shaped flow. The user's real Edge serves search results
  // to manual navigation but risk-pages direct-URL searches from about:blank,
  // on the same IP/browser/cookies. The only differing variable is navigation
  // shape. human_flow therefore (a) starts on the www.jd.com homepage so JD
  // seeds session/pvid context and the search request carries a real referer
  // chain, (b) searches with a from=home URL (no page parameter), and (c) flips
  // pages by clicking the real .pn-next control instead of rewriting the URL.
  'human_flow',
]);

let nativePort = null;
let currentTask = null;
const finishedRouteTokens = new Set();


function hasExactKeys(value, expected) {
  return value !== null
    && typeof value === 'object'
    && !Array.isArray(value)
    && Object.keys(value).length === expected.size
    && Object.keys(value).every((key) => expected.has(key));
}


function validText(value, maximum) {
  return typeof value === 'string'
    && value.trim().length > 0
    && value.trim().length <= maximum
    && !/[\u0000-\u001f]/u.test(value);
}


function validInteger(value, minimum, maximum) {
  return Number.isSafeInteger(value) && value >= minimum && value <= maximum;
}


function validDiagnostics(value, message) {
  return hasExactKeys(value, DIAGNOSTIC_KEYS)
    && DOCUMENT_READY_STATES.has(value.document_ready_state)
    && validInteger(value.data_sku_node_count, 0, 1000000)
    && validInteger(value.candidate_anchor_count, 0, 1000000)
    && validInteger(value.valid_item_count, 0, 1000)
    && validInteger(value.collection_elapsed_ms, 0, 600000)
    && validInteger(value.stable_rounds, 0, 1000000)
    && validInteger(value.observed_page_number, 1, 512)
    && RECOVERY_STAGES.has(value.recovery_stage)
    && validInteger(value.recovery_attempt, 0, 2)
    && value.source_path === '/Search'
    && value.observed_page_number === message.observed_page_number
    && value.valid_item_count === message.items.length
    && value.candidate_anchor_count >= value.valid_item_count
    && validText(value.pagination_dom, 2048);
}


function sessionIdentityMatches(session, message) {
  return session !== null
    && Number.isInteger(session.tab_id)
    && session.platform === message.platform
    && session.query === message.query.trim()
    && session.query_family === message.query_family
    && session.cursor_id === message.cursor.cursor_id
    && session.cursor_ordinal === message.cursor.ordinal;
}


function projectionRecoveryMatches(session, diagnostics) {
  if (session.recovery_stage === 'initial' && session.recovery_attempt === 0) {
    return diagnostics.recovery_stage === 'initial'
      && diagnostics.recovery_attempt === 0;
  }
  if (session.recovery_stage === 'reproject' && session.recovery_attempt === 1) {
    return diagnostics.recovery_stage === 'reproject'
      && diagnostics.recovery_attempt === 1;
  }
  if (session.recovery_stage === 'reload' && session.recovery_attempt === 2) {
    return (
      diagnostics.recovery_stage === 'reload'
      && diagnostics.recovery_attempt === 2
    ) || (
      diagnostics.recovery_stage === 'initial'
      && diagnostics.recovery_attempt === 0
    );
  }
  return false;
}


function createRouteToken() {
  if (typeof globalThis.crypto?.randomUUID !== 'function') {
    throw new Error('secure route token unavailable');
  }
  const token = globalThis.crypto.randomUUID();
  if (
    typeof token !== 'string'
    || !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu.test(token)
  ) {
    throw new Error('secure route token invalid');
  }
  return token;
}


function routeForTask(message, tabId, previousSkuDigest, routeToken) {
  return {
    route_token: routeToken,
    type: message.type,
    protocol_version: message.protocol_version,
    operation: message.operation,
    task_id: message.task_id,
    platform: message.platform,
    query: message.query.trim(),
    query_family: message.query_family,
    cursor: message.cursor,
    max_items: message.max_items,
    session_action: message.session_action,
    pagination_enabled: message.pagination_enabled,
    target_host: SEARCH_HOSTS[message.platform],
    tab_id: tabId,
    previous_sku_digest: previousSkuDigest,
  };
}


async function beginRoute(route, deadlineSeconds) {
  currentTask = route;
  await chrome.storage.session.set({ [ROUTE_KEY]: route });
  chrome.alarms.create(timeoutAlarm(route), {
    delayInMinutes: Math.max(1 / 60, deadlineSeconds / 60),
  });
}


function taskIdOrZero(message) {
  return typeof message?.task_id === 'string' && /^[0-9a-f]{32}$/u.test(message.task_id)
    ? message.task_id
    : '00000000000000000000000000000000';
}


function errorEnvelope(taskId, category, retryable) {
  return {
    type: 'error',
    protocol_version: PROTOCOL_VERSION,
    task_id: taskId,
    category,
    retryable,
  };
}


function postNative(message) {
  try {
    nativePort?.postMessage(message);
  } catch {
    // Native port disconnect handling performs cleanup and schedules reconnect.
  }
}


function validateTask(message) {
  if (
    !hasExactKeys(message, TASK_KEYS)
    || message.type !== 'task'
    || message.protocol_version !== PROTOCOL_VERSION
    || !/^[0-9a-f]{32}$/u.test(message.task_id)
    || !validText(message.operation, 16)
    || !Object.hasOwn(SEARCH_HOSTS, message.platform)
    || !validText(message.query, 512)
    || !validText(message.query_family, 512)
    || !hasExactKeys(message.cursor, CURSOR_KEYS)
    || !validText(message.cursor.cursor_id, 512)
    || !validInteger(message.cursor.ordinal, 0, 1000000)
    || !validInteger(message.cursor.page_number, 1, 512)
    || typeof message.deadline_seconds !== 'number'
    || !Number.isFinite(message.deadline_seconds)
    || message.deadline_seconds <= 0
    || message.deadline_seconds > 600
    || !validInteger(message.max_items, 1, 1000)
    || !SESSION_ACTIONS.has(message.session_action)
    || typeof message.pagination_enabled !== 'boolean'
    || (message.pagination_route !== null && !JD_PAGINATION_ROUTES.has(message.pagination_route))
    || (message.session_action === 'start' && message.cursor.page_number !== 1)
    || (message.session_action !== 'start' && !message.pagination_enabled)
    || (message.session_action === 'next' && message.cursor.page_number <= 1)
    || (message.session_action === 'recover' && message.platform !== 'jd')
  ) {
    return 'edge_native_message_invalid';
  }
  if (message.operation !== 'search') {
    return 'edge_operation_unsupported';
  }
  return null;
}


function buildSearchUrl(platform, query, pageNumber) {
  const url = platform === 'jd'
    ? new URL('https://search.jd.com/Search')
    : new URL('https://s.taobao.com/search');
  if (platform === 'jd') {
    url.searchParams.set('keyword', query.trim());
    url.searchParams.set('enc', 'utf-8');
    url.searchParams.set('page', String(pageNumber * 2 - 1));
  } else {
    url.searchParams.set('q', query.trim());
    url.searchParams.set('page', String(pageNumber - 1));
  }
  return url.href;
}


function buildHumanSearchUrl(query) {
  // Human-shaped page-1 search URL: keyword + enc + from=home, no page
  // parameter. Mirrors what the user's own search box produces after visiting
  // the www.jd.com homepage (referer chain + homepage-seeded session/pvid).
  const url = new URL('https://search.jd.com/Search');
  url.searchParams.set('keyword', String(query).trim());
  url.searchParams.set('enc', 'utf-8');
  url.searchParams.set('from', 'home');
  return url.href;
}


const JD_HOMEPAGE_URL = 'https://www.jd.com/';
const JD_HOMEPAGE_SETTLE_MS = 2500;

async function waitForTabComplete(tabId, timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    let tab;
    try {
      tab = await chrome.tabs.get(tabId);
    } catch {
      return false;
    }
    if (tab?.status === 'complete') return true;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  return false;
}

async function navigateHumanHomepageThenSearch(tabId, query) {
  // Visit the JD homepage first so the tab carries homepage session context
  // (pvid cookie, referer chain) into the search request, exactly like a
  // manual user flow. Fall back to a direct search URL if the homepage never
  // finishes loading within the budget.
  await chrome.tabs.update(tabId, { url: JD_HOMEPAGE_URL });
  const loaded = await waitForTabComplete(tabId, 30000);
  if (loaded) {
    // Let homepage JS seed session/pvid context before navigating onward.
    await new Promise((resolve) => setTimeout(resolve, JD_HOMEPAGE_SETTLE_MS));
  }
  await chrome.tabs.update(tabId, { url: buildHumanSearchUrl(query) });
}


function normalizeQuery(value) {
  return typeof value === 'string'
    ? value.normalize('NFKC').trim().replace(/\s+/gu, ' ')
    : '';
}


function validatedNumberedPageUrl(value, query, expectedPageNumber) {
  if (!validText(value, 4096)) return null;
  let destination;
  try {
    destination = new URL(value);
  } catch {
    return null;
  }
  const physicalPage = Number(destination.searchParams.get('page'));
  if (
    destination.protocol !== 'https:'
    || destination.host !== 'search.jd.com'
    || destination.pathname !== '/Search'
    || destination.username
    || destination.password
    || destination.hash
    || destination.searchParams.getAll('page').length !== 1
    || destination.searchParams.getAll('keyword').length !== 1
    || !Number.isSafeInteger(physicalPage)
    || physicalPage !== expectedPageNumber * 2 - 1
    || normalizeQuery(destination.searchParams.get('keyword')) !== normalizeQuery(query)
  ) return null;
  return destination.href;
}


function timeoutAlarm(route) {
  return `${TIMEOUT_PREFIX}${route.route_token}`;
}


async function storedRoute() {
  const stored = await chrome.storage.session.get(ROUTE_KEY);
  return stored[ROUTE_KEY] ?? null;
}


async function storedSession() {
  const stored = await chrome.storage.session.get(SESSION_KEY);
  return stored[SESSION_KEY] ?? null;
}


async function configuredJdPaginationRoute() {
  const stored = await chrome.storage.local.get(JD_PAGINATION_ROUTE_KEY);
  const configured = stored[JD_PAGINATION_ROUTE_KEY];
  // 2026-08-11 promoted: the foreground direct-URL route is the default. It is
  // the only route proven to flip JD pages reliably, and the user has
  // authorized foreground activation as a stable contract. Undefined/unknown
  // values converge here; legacy routes stay selectable via storage or the CLI
  // per-run override.
  if (configured === undefined) {
    await chrome.storage.local.set({
      [JD_PAGINATION_ROUTE_KEY]: 'experimental_url',
      [JD_EXPERIMENTAL_URL_DEFAULT_MIGRATION_KEY]: true,
    });
    return 'experimental_url';
  }
  if (configured === 'page_jump') {
    const migration = await chrome.storage.local.get(
      JD_PUBLIC_CONTROL_DEFAULT_MIGRATION_KEY,
    );
    if (migration[JD_PUBLIC_CONTROL_DEFAULT_MIGRATION_KEY] !== true) {
      await chrome.storage.local.set({
        [JD_PAGINATION_ROUTE_KEY]: 'public_control',
        [JD_PUBLIC_CONTROL_DEFAULT_MIGRATION_KEY]: true,
      });
      return 'public_control';
    }
  }
  if (configured === 'public_control') {
    const migration = await chrome.storage.local.get(
      JD_NUMBERED_LINK_DEFAULT_MIGRATION_KEY,
    );
    if (migration[JD_NUMBERED_LINK_DEFAULT_MIGRATION_KEY] !== true) {
      await chrome.storage.local.set({
        [JD_PAGINATION_ROUTE_KEY]: 'numbered_link',
        [JD_NUMBERED_LINK_DEFAULT_MIGRATION_KEY]: true,
      });
      return 'numbered_link';
    }
  }
  if (configured === 'numbered_link') {
    const activation = await chrome.storage.local.get(
      JD_NUMBERED_LINK_DEFAULT_MIGRATION_KEY,
    );
    const migration = await chrome.storage.local.get(
      JD_INFINITE_SCROLL_DEFAULT_MIGRATION_KEY,
    );
    if (
      activation[JD_NUMBERED_LINK_DEFAULT_MIGRATION_KEY] === true
      && migration[JD_INFINITE_SCROLL_DEFAULT_MIGRATION_KEY] !== true
    ) {
      await chrome.storage.local.set({
        [JD_PAGINATION_ROUTE_KEY]: 'infinite_scroll',
        [JD_INFINITE_SCROLL_DEFAULT_MIGRATION_KEY]: true,
      });
      return 'infinite_scroll';
    }
  }
  if (JD_PAGINATION_ROUTES.has(configured)) return configured;
  await chrome.storage.local.set({
    [JD_PAGINATION_ROUTE_KEY]: 'experimental_url',
    [JD_EXPERIMENTAL_URL_DEFAULT_MIGRATION_KEY]: true,
  });
  return 'experimental_url';
}


async function clearStoredSession(options = {}) {
  const session = await storedSession().catch(() => null);
  await chrome.storage.session.remove(SESSION_KEY).catch(() => {});
  if (options.closeTab !== false && Number.isInteger(session?.tab_id)) {
    await chrome.tabs.remove(session.tab_id).catch(() => {});
  }
}


async function activeJdRiskCircuit() {
  const stored = await chrome.storage.local.get(JD_RISK_KEY);
  const circuit = stored[JD_RISK_KEY];
  if (
    circuit === null
    || typeof circuit !== 'object'
    || !Number.isFinite(circuit.blocked_until_ms)
    || circuit.blocked_until_ms <= Date.now()
  ) {
    await chrome.storage.local.remove(JD_RISK_KEY).catch(() => {});
    return null;
  }
  return circuit;
}


async function setJdRiskCircuit(reason) {
  const observedAt = Date.now();
  await chrome.storage.local.set({
    [JD_RISK_KEY]: {
      blocked_until_ms: observedAt + JD_RISK_COOLDOWN_MS,
      reason,
      observed_at_ms: observedAt,
    },
  });
}


async function finishTask(route, envelope, options = {}) {
  if (
    route === null
    || typeof route !== 'object'
    || typeof route.route_token !== 'string'
    || route.route_token.length === 0
    || finishedRouteTokens.has(route.route_token)
  ) return false;
  if (currentTask !== null) {
    if (currentTask.route_token !== route.route_token) return false;
    currentTask = null;
  } else {
    const activeRoute = await storedRoute().catch(() => null);
    if (
      activeRoute?.route_token !== route.route_token
      || finishedRouteTokens.has(route.route_token)
    ) return false;
  }
  finishedRouteTokens.add(route.route_token);
  await chrome.storage.session.remove(ROUTE_KEY).catch(() => {});
  await chrome.alarms.clear(timeoutAlarm(route)).catch(() => false);
  if (options.closeTab !== false && Number.isInteger(route.tab_id)) {
    const session = await storedSession().catch(() => null);
    if (session?.tab_id === route.tab_id) {
      await chrome.storage.session.remove(SESSION_KEY).catch(() => {});
    }
    await chrome.tabs.remove(route.tab_id).catch(() => {});
  }
  postNative(envelope);
  return true;
}


async function handleTask(message) {
  const invalidCategory = validateTask(message);
  if (invalidCategory !== null) {
    postNative(errorEnvelope(
      taskIdOrZero(message),
      invalidCategory,
      false,
    ));
    return;
  }
  if (currentTask !== null || await storedRoute() !== null) {
    postNative(errorEnvelope(message.task_id, 'edge_background_bridge_busy', true));
    return;
  }
  if (message.platform === 'jd' && await activeJdRiskCircuit() !== null) {
    await clearStoredSession();
    postNative(errorEnvelope(message.task_id, 'rate_limited', false));
    return;
  }
  let routeToken;
  try {
    routeToken = createRouteToken();
  } catch {
    postNative(errorEnvelope(message.task_id, 'edge_extension_failure', false));
    return;
  }
  if (
    message.platform === 'jd'
    && new Set(['next', 'recover']).has(message.session_action)
  ) {
    const session = await storedSession();
    const nextMatches = message.session_action === 'next'
      && sessionIdentityMatches(session, message)
      && session.verified_page_number + 1 === message.cursor.page_number
      && session.pending_page_number === null
      && (
        session.has_next_page === true
        || session.allow_sequential_fallback === true
        || session.allow_page_jump === true
        || session.allow_numbered_link === true
        || session.allow_infinite_scroll === true
        || session.allow_experimental_url === true
        || session.allow_human_flow === true
      );
    const recoverMatches = message.session_action === 'recover'
      && sessionIdentityMatches(session, message)
      && session.pending_page_number === message.cursor.page_number
      && new Set(['reproject', 'reload']).has(session.recovery_stage)
      && validInteger(session.recovery_attempt, 1, 2);
    if (!nextMatches && !recoverMatches) {
      await clearStoredSession();
      postNative(errorEnvelope(message.task_id, 'pagination_session_missing', false));
      return;
    }
    const route = routeForTask(
      message,
      session.tab_id,
      session.previous_sku_digest,
      routeToken,
    );
    try {
      if (message.session_action === 'next') {
        await chrome.storage.session.set({
          [SESSION_KEY]: {
            ...session,
            pending_page_number: message.cursor.page_number,
            recovery_stage: 'initial',
            recovery_attempt: 0,
          },
        });
      }
      await beginRoute(route, message.deadline_seconds);
      if (message.session_action === 'recover') {
        if (session.recovery_stage === 'reproject') {
          const response = await chrome.tabs.sendMessage(session.tab_id, {
            type: 'pagination_recover',
            recovery_attempt: session.recovery_attempt,
          });
          if (response?.ok !== true) {
            throw new Error('pagination recovery unavailable');
          }
        } else {
          await chrome.tabs.reload(session.tab_id);
        }
        return;
      }
      if (session.pagination_route === 'infinite_scroll') {
        const response = await chrome.tabs.sendMessage(session.tab_id, {
          type: 'pagination_infinite_scroll',
          expected_page_number: message.cursor.page_number,
        });
        if (response?.ok !== true) {
          throw new Error('infinite-scroll pagination unavailable');
        }
      } else if (session.pagination_route === 'experimental_url') {
        // 2026-08-11 promoted: foreground direct-URL navigation (physical page
        // 2n-1). Foreground activation is the single variable that makes JD
        // render the next page in the same tab; it is an authorized stable
        // behavior. Same tab, no new tab.
        await chrome.tabs.update(session.tab_id, { active: true });
        await chrome.tabs.update(session.tab_id, {
          url: buildSearchUrl('jd', message.query, message.cursor.page_number),
        });
      } else if (session.pagination_route === 'page_jump') {
        const response = await chrome.tabs.sendMessage(session.tab_id, {
          type: 'pagination_page_jump',
          expected_page_number: message.cursor.page_number,
        });
        if (response?.ok !== true) {
          throw new Error('page-jump pagination unavailable');
        }
      } else if (session.pagination_route === 'numbered_link') {
        const response = await chrome.tabs.sendMessage(session.tab_id, {
          type: 'pagination_numbered_link',
          expected_page_number: message.cursor.page_number,
          query: message.query.trim(),
        });
        const destination = response?.ok === true
          ? validatedNumberedPageUrl(
            response.url,
            message.query,
            message.cursor.page_number,
          )
          : null;
        if (destination === null) {
          throw new Error('numbered pagination unavailable');
        }
        await chrome.tabs.update(session.tab_id, { url: destination });
      } else if (session.pagination_route === 'human_flow') {
        // 2026-08-12: flip pages by clicking the real page-2+ control, the way
        // a human does. The search URL stays unchanged (JD re-renders the list
        // in place); advancement is verified downstream by SKU-digest change.
        const response = await chrome.tabs.sendMessage(session.tab_id, {
          type: 'pagination_next',
          expected_page_number: message.cursor.page_number,
        });
        if (response?.ok !== true) {
          throw new Error('pagination navigation unavailable');
        }
      } else if (session.allow_sequential_fallback === true) {
        await chrome.tabs.update(session.tab_id, {
          url: buildSearchUrl('jd', message.query, message.cursor.page_number),
        });
      } else {
        const response = await chrome.tabs.sendMessage(session.tab_id, {
          type: 'pagination_next',
          expected_page_number: message.cursor.page_number,
        });
        if (response?.ok !== true) {
          throw new Error('pagination navigation unavailable');
        }
      }
    } catch {
      await finishTask(
        route,
        errorEnvelope(
          message.task_id,
          message.session_action === 'recover'
            ? 'pagination_recovery_unavailable'
            : 'pagination_navigation_unavailable',
          false,
        ),
      );
    }
    return;
  }
  if (message.session_action === 'start') {
    await clearStoredSession();
  }
  let tab;
  let route;
  try {
    const paginationRoute = message.platform === 'jd' && message.pagination_enabled
      ? (message.pagination_route ?? await configuredJdPaginationRoute())
      : 'existing';
    if (paginationRoute === null) {
      postNative(errorEnvelope(
        message.task_id,
        'pagination_navigation_unavailable',
        false,
      ));
      return;
    }
    tab = await chrome.tabs.create({ url: 'about:blank', active: false });
    if (!Number.isInteger(tab?.id)) throw new Error('tab id unavailable');
    route = routeForTask(message, tab.id, null, routeToken);
    currentTask = route;
    if (message.platform === 'jd' && message.pagination_enabled) {
      await chrome.storage.session.set({
        [SESSION_KEY]: {
          tab_id: tab.id,
          platform: message.platform,
          query: message.query.trim(),
          query_family: message.query_family,
          cursor_id: message.cursor.cursor_id,
          cursor_ordinal: message.cursor.ordinal,
          verified_page_number: 0,
          pending_page_number: 1,
          previous_sku_digest: null,
          has_next_page: false,
          allow_sequential_fallback: false,
          allow_page_jump: false,
          allow_numbered_link: false,
          allow_infinite_scroll: false,
          allow_experimental_url: false,
          allow_human_flow: false,
          pagination_route: paginationRoute,
          recovery_stage: 'initial',
          recovery_attempt: 0,
        },
      });
    }
    await beginRoute(route, message.deadline_seconds);
    if (
      message.platform === 'jd'
      && message.pagination_enabled
      && paginationRoute === 'human_flow'
    ) {
      // Simulate the human flow: homepage first (session/pvid context +
      // referer chain), then the from=home search URL.
      await navigateHumanHomepageThenSearch(tab.id, message.query);
    } else {
      await chrome.tabs.update(tab.id, {
        url: buildSearchUrl(message.platform, message.query, message.cursor.page_number),
      });
    }
  } catch {
    if (route === undefined) {
      postNative(errorEnvelope(
        message.task_id,
        'edge_background_tab_create_failed',
        true,
      ));
      return;
    }
    await finishTask(
      route,
      errorEnvelope(message.task_id, 'edge_background_tab_create_failed', true),
    );
  }
}


function connectHost() {
  if (nativePort !== null) return;
  try {
    const port = chrome.runtime.connectNative(NATIVE_HOST);
    nativePort = port;
    port.onMessage.addListener((message) => {
      handleTask(message).catch(() => {
        postNative(errorEnvelope(
          taskIdOrZero(message),
          'edge_extension_failure',
          false,
        ));
      });
    });
    port.onDisconnect.addListener(() => {
      if (nativePort !== port) return;
      nativePort = null;
      void (async () => {
        const route = currentTask ?? await storedRoute().catch(() => null);
        if (route !== null) {
          await chrome.alarms.clear(timeoutAlarm(route)).catch(() => false);
          await chrome.storage.session.remove(ROUTE_KEY).catch(() => {});
          currentTask = null;
          if (Number.isInteger(route.tab_id)) {
            await chrome.tabs.remove(route.tab_id).catch(() => {});
          }
        }
        await clearStoredSession();
        chrome.alarms.create(RECONNECT_ALARM, { delayInMinutes: 0.1 });
      })();
    });
  } catch {
    nativePort = null;
    chrome.alarms.create(RECONNECT_ALARM, { delayInMinutes: 0.1 });
  }
}


function senderUrl(sender) {
  try {
    return new URL(sender.url);
  } catch {
    return null;
  }
}


function forwardProjection(message, sender, sendResponse) {
  const source = senderUrl(sender);
  const tabId = sender.tab?.id;
  if (
    message?.type === 'projection'
    && (
      message.projection_schema_version !== PROJECTION_SCHEMA_VERSION
      || !Array.isArray(message.capabilities)
      || message.capabilities.length !== REQUIRED_PROJECTION_CAPABILITIES.length
      || message.capabilities.some(
        (value, index) => value !== REQUIRED_PROJECTION_CAPABILITIES[index]
      )
    )
  ) {
    sendResponse({ ok: false, category: 'edge_extension_reload_required' });
    return false;
  }
  if (
    sender.id !== chrome.runtime.id
    || source === null
    || source.protocol !== 'https:'
    || !new Set(Object.values(SEARCH_HOSTS)).has(source.hostname)
    || !Number.isInteger(tabId)
    || !hasExactKeys(message, PROJECTION_KEYS)
    || message.type !== 'projection'
    || !Object.hasOwn(SEARCH_HOSTS, message.platform)
    || !PAGE_STATES.has(message.page_state)
    || !validInteger(message.observed_page_number, 1, 512)
    || !PAGINATION_STATES.has(message.pagination_state)
    || typeof message.has_next_page !== 'boolean'
    || !validText(message.sku_digest, 4096)
    || !Array.isArray(message.items)
    || message.items.length > 1000
    || !validDiagnostics(message.diagnostics, message)
  ) {
    sendResponse({ ok: false, category: 'edge_extension_message_invalid' });
    return false;
  }
  void (async () => {
    const route = await storedRoute();
    const session = await storedSession();
    let projectedSource;
    try {
      projectedSource = new URL(message.source_url);
    } catch {
      projectedSource = null;
    }
    if (
      route === null
      || route.tab_id !== tabId
      || route.platform !== message.platform
      || route.target_host !== source.hostname
      || projectedSource === null
      || projectedSource.protocol !== 'https:'
      || projectedSource.hostname !== route.target_host
      || projectedSource.username
      || projectedSource.password
      || projectedSource.search
      || projectedSource.hash
      || projectedSource.pathname !== (route.platform === 'jd' ? '/Search' : '/search')
      || message.observed_page_number !== route.cursor.page_number
    ) {
      sendResponse({ ok: false, category: 'edge_extension_task_missing' });
      return;
    }
    if (route.platform === 'jd' && HARD_RISK_STATES.has(message.page_state)) {
      await setJdRiskCircuit(message.page_state);
      await finishTask(route, errorEnvelope(route.task_id, message.page_state, false));
      sendResponse({ ok: true });
      return;
    }
    const pendingJdSession = route.platform === 'jd'
      && route.pagination_enabled
      && sessionIdentityMatches(session, route)
      && session.pending_page_number === route.cursor.page_number;
    if (route.platform === 'jd' && route.pagination_enabled && !pendingJdSession) {
      await finishTask(
        route,
        errorEnvelope(route.task_id, 'pagination_session_missing', false),
      );
      sendResponse({ ok: true });
      return;
    }
    if (
      pendingJdSession
      && !projectionRecoveryMatches(session, message.diagnostics)
    ) {
      sendResponse({ ok: false, category: 'edge_extension_task_missing' });
      return;
    }
    const zeroCards = message.items.length === 0
      && new Set(['ready', 'page_structure_changed']).has(message.page_state);
    const unchangedSku = pendingJdSession
      && session.previous_sku_digest !== null
      && session.previous_sku_digest === message.sku_digest;
    const isolatedEvidenceFailure = pendingJdSession
      && new Set(['page_jump', 'infinite_scroll', 'human_flow'])
        .has(session.pagination_route)
      && (message.page_state !== 'ready' || zeroCards || unchangedSku);
    if (isolatedEvidenceFailure) {
      await finishTask(
        route,
        errorEnvelope(route.task_id, 'pagination_navigation_unavailable', false),
      );
      sendResponse({ ok: true });
      return;
    }
    if (pendingJdSession && (zeroCards || unchangedSku)) {
      if (session.recovery_stage === 'reload' && session.recovery_attempt === 2) {
        await finishTask(
          route,
          errorEnvelope(route.task_id, 'browser_page_structure_changed', false),
        );
        sendResponse({ ok: true });
        return;
      }
      const reprojected = session.recovery_stage === 'reproject';
      await chrome.storage.session.set({
        [SESSION_KEY]: {
          ...session,
          pending_page_number: route.cursor.page_number,
          recovery_stage: reprojected ? 'reload' : 'reproject',
          recovery_attempt: reprojected ? 2 : 1,
        },
      });
      await finishTask(
        route,
        errorEnvelope(
          route.task_id,
          zeroCards ? 'pagination_page_transient_empty' : 'pagination_page_stalled',
          true,
        ),
        { closeTab: false },
      );
      sendResponse({ ok: true });
      return;
    }
    const status = message.page_state === 'ready'
      ? (message.items.length > 0 ? 'advanced' : 'exhausted')
      : 'stalled';
    const allowSequentialFallback = route.platform === 'jd'
      && route.pagination_enabled
      && session.pagination_route === 'existing'
      && message.page_state === 'ready'
      && message.items.length === 30
      && message.pagination_state === 'page_verified'
      && message.has_next_page === false
      && session.pagination_route !== 'page_jump';
    const allowPageJump = route.platform === 'jd'
      && route.pagination_enabled
      && session.pagination_route === 'page_jump'
      && message.page_state === 'ready'
      && message.items.length === 30
      && message.pagination_state === 'page_verified'
      && message.has_next_page === false;
    const allowNumberedLink = route.platform === 'jd'
      && route.pagination_enabled
      && session.pagination_route === 'numbered_link'
      && message.page_state === 'ready'
      && message.items.length === 30
      && message.pagination_state === 'page_verified'
      && message.has_next_page === false;
    const allowInfiniteScroll = route.platform === 'jd'
      && route.pagination_enabled
      && session.pagination_route === 'infinite_scroll'
      && message.page_state === 'ready'
      && message.items.length === 30
      && message.pagination_state === 'page_verified';
    // 2026-08-11: page two and later render ~60 cards because JD mixes earlier-page
    // repeats into the DOM, so a full verified page is `>= 30`, not exactly 30.
    // Short/incomplete pages (< 30) still do not retain the session.
    const allowExperimentalUrl = route.platform === 'jd'
      && route.pagination_enabled
      && session.pagination_route === 'experimental_url'
      && message.page_state === 'ready'
      && message.items.length >= 30
      && message.pagination_state === 'page_verified';
    const allowHumanFlow = route.platform === 'jd'
      && route.pagination_enabled
      && session.pagination_route === 'human_flow'
      && message.page_state === 'ready'
      && message.items.length > 0
      && message.pagination_state === 'page_verified';
    const retainJdSession = route.platform === 'jd'
      && route.pagination_enabled
      && message.page_state === 'ready'
      && message.items.length > 0
      && message.pagination_state === 'page_verified'
      && (
        message.has_next_page
        || allowSequentialFallback
        || allowPageJump
        || allowNumberedLink
        || allowInfiniteScroll
        || allowExperimentalUrl
        || allowHumanFlow
      );
    if (retainJdSession) {
      await chrome.storage.session.set({
        [SESSION_KEY]: {
          tab_id: route.tab_id,
          platform: route.platform,
          query: route.query,
          query_family: route.query_family,
          cursor_id: route.cursor.cursor_id,
          cursor_ordinal: route.cursor.ordinal,
          verified_page_number: message.observed_page_number,
          pending_page_number: null,
          previous_sku_digest: message.sku_digest,
          has_next_page: message.has_next_page,
          allow_sequential_fallback: allowSequentialFallback,
          allow_page_jump: allowPageJump,
          allow_numbered_link: allowNumberedLink,
          allow_infinite_scroll: allowInfiniteScroll,
          allow_experimental_url: allowExperimentalUrl,
          allow_human_flow: allowHumanFlow,
          pagination_route: session.pagination_route,
          recovery_stage: 'initial',
          recovery_attempt: 0,
        },
      });
    }
    await finishTask(route, {
      type: 'result',
      protocol_version: PROTOCOL_VERSION,
      task_id: route.task_id,
      payload: {
        projection_schema_version: message.projection_schema_version,
        capabilities: message.capabilities,
        platform: message.platform,
        page_state: message.page_state,
        source_url: projectedSource.href,
        query_family: route.query_family,
        cursor: {
          cursor_id: route.cursor.cursor_id,
          page_number: route.cursor.page_number,
          status,
        },
        observed_page_number: message.observed_page_number,
        pagination_state: message.pagination_state,
        has_next_page: message.has_next_page,
        sku_digest: message.sku_digest,
        diagnostics: message.diagnostics,
        items: message.items,
      },
    }, { closeTab: !retainJdSession });
    sendResponse({ ok: true });
  })().catch(() => {
    sendResponse({ ok: false, category: 'edge_extension_storage_unavailable' });
  });
  return true;
}


chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === 'projection_config') {
    void (async () => {
      const route = await storedRoute();
      const session = await storedSession();
      const source = senderUrl(sender);
      if (
        sender.id !== chrome.runtime.id
        || route === null
        || sender.tab?.id !== route.tab_id
        || source === null
        || source.protocol !== 'https:'
        || source.hostname !== route.target_host
      ) {
        sendResponse({ ok: false, category: 'edge_extension_task_missing' });
        return;
      }
      sendResponse({
        ok: true,
        max_items: route.max_items,
        expected_page_number: route.cursor.page_number,
        pagination_enabled: route.pagination_enabled,
        pagination_route: session?.pagination_route ?? 'existing',
        recovery_stage: session?.pending_page_number === route.cursor.page_number
          ? session.recovery_stage
          : 'initial',
        recovery_attempt: session?.pending_page_number === route.cursor.page_number
          ? session.recovery_attempt
          : 0,
      });
    })().catch(() => {
      sendResponse({ ok: false, category: 'edge_extension_storage_unavailable' });
    });
    return true;
  }
  if (message?.type === 'projection') {
    return forwardProjection(message, sender, sendResponse);
  }
  sendResponse({ ok: false, category: 'edge_extension_message_invalid' });
  return false;
});


chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (typeof changeInfo.url !== 'string') return;
  void (async () => {
    const route = await storedRoute();
    if (route === null || route.tab_id !== tabId) return;
    let url;
    try {
      url = new URL(changeInfo.url);
    } catch {
      return;
    }
    let category = null;
    if (url.hostname === 'cfe.m.jd.com'
        && url.pathname.startsWith('/privatedomain/risk_handler/')) {
      category = 'rate_limited';
    } else if (url.hostname === 'passport.jd.com'
        && url.pathname === '/new/login.aspx') {
      category = 'authentication_required';
    }
    if (category !== null) {
      await setJdRiskCircuit(category);
      await finishTask(route, errorEnvelope(route.task_id, category, category === 'rate_limited'));
    }
  })();
});


chrome.tabs.onRemoved.addListener((tabId) => {
  void (async () => {
    const route = await storedRoute();
    if (route === null || route.tab_id !== tabId) {
      const session = await storedSession();
      if (session?.tab_id === tabId) {
        await chrome.storage.session.remove(SESSION_KEY).catch(() => {});
      }
      return;
    }
    await finishTask(
      route,
      errorEnvelope(route.task_id, 'edge_background_tab_closed', false),
      { closeTab: false },
    );
  })();
});


chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === RECONNECT_ALARM) {
    connectHost();
    return;
  }
  if (!alarm.name.startsWith(TIMEOUT_PREFIX)) return;
  void (async () => {
    const route = await storedRoute();
    if (route === null || alarm.name !== timeoutAlarm(route)) return;
    await finishTask(
      route,
      errorEnvelope(route.task_id, 'edge_extension_timeout', true),
    );
  })();
});


chrome.runtime.onStartup.addListener(connectHost);
chrome.runtime.onInstalled.addListener(connectHost);
connectHost();
