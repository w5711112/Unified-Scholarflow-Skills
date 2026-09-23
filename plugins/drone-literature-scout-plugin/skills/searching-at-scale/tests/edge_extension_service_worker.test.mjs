import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';


const TEST_DIR = path.dirname(fileURLToPath(import.meta.url));
const SKILL_DIR = path.dirname(TEST_DIR);
const EXTENSION_DIR = path.join(SKILL_DIR, 'edge-extension');
const EXTENSION_ID = 'ackhakolgkcedgagblkfbjfnkceplcop';
const TASK_ID = '0123456789abcdef0123456789abcdef';


function eventSlot() {
  const listeners = [];
  return {
    listeners,
    addListener(listener) { listeners.push(listener); },
  };
}


function task(overrides = {}) {
  return {
    type: 'task',
    protocol_version: 3,
    operation: 'search',
    task_id: TASK_ID,
    platform: 'jd',
    query: '小米15',
    query_family: '小米15:default',
    cursor: { cursor_id: 'jd:xiaomi15', ordinal: 0, page_number: 1 },
    deadline_seconds: 30,
    max_items: 100,
    session_action: 'start',
    pagination_enabled: false,
    pagination_route: null,
    ...overrides,
  };
}


function diagnostics(overrides = {}) {
  return {
    document_ready_state: 'complete',
    data_sku_node_count: 1,
    candidate_anchor_count: 1,
    valid_item_count: 1,
    collection_elapsed_ms: 20000,
    stable_rounds: 40,
    observed_page_number: 1,
    recovery_stage: 'initial',
    recovery_attempt: 0,
    source_path: '/Search',
    pagination_dom: 'bottom=0;curr=none;next=absent',
    ...overrides,
  };
}


function projection(overrides = {}) {
  const items = overrides.items ?? jdItems(1, 100123);
  const observedPageNumber = overrides.observed_page_number ?? 1;
  return {
    type: 'projection',
    projection_schema_version: 4,
    capabilities: [
      'stable_card_fields_v2',
      'verified_pagination_v1',
      'resilient_pagination_v1',
    ],
    platform: 'jd',
    page_state: 'ready',
    source_url: 'https://search.jd.com/Search',
    observed_page_number: observedPageNumber,
    pagination_state: 'page_verified',
    has_next_page: true,
    sku_digest: items.length > 0
      ? items.map((item) => item.product_id).join(',')
      : 'none',
    ...overrides,
    diagnostics: diagnostics({
      data_sku_node_count: items.length,
      candidate_anchor_count: items.length,
      valid_item_count: items.length,
      observed_page_number: observedPageNumber,
      ...(overrides.diagnostics ?? {}),
    }),
    items,
  };
}


function jdItems(count, start = 100000) {
  return Array.from({ length: count }, (_, index) => {
    const productId = String(start + index);
    return {
      product_id: productId,
      title: `商品${index + 1}`,
      url: `https://item.jd.com/${productId}.html`,
      price: null,
      shop: null,
      commit: null,
      good_rate: null,
      promo: null,
      stock: null,
      image: null,
    };
  });
}


async function loadWorker(
  sessionValues = new Map(),
  localValues = new Map([
    ['searching-at-scale-jd-pagination-route', 'existing'],
  ]),
  options = {},
) {
  const records = [];
  const posted = [];
  const runtimeMessage = eventSlot();
  const runtimeStartup = eventSlot();
  const runtimeInstalled = eventSlot();
  const tabUpdated = eventSlot();
  const tabRemoved = eventSlot();
  const alarmEvent = eventSlot();
  const portMessage = eventSlot();
  const portDisconnect = eventSlot();
  const port = {
    onMessage: portMessage,
    onDisconnect: portDisconnect,
    postMessage(message) {
      const cloned = JSON.parse(JSON.stringify(message));
      posted.push(cloned);
      options.onPostMessage?.(cloned, (nextMessage) => {
        portMessage.listeners[0](nextMessage);
      });
    },
  };
  let nextTabId = 7;
  let nextUuid = 1;
  const chrome = {
    runtime: {
      id: EXTENSION_ID,
      lastError: undefined,
      onMessage: runtimeMessage,
      onStartup: runtimeStartup,
      onInstalled: runtimeInstalled,
      connectNative(host) {
        records.push(['connectNative', host]);
        return port;
      },
    },
    storage: {
      session: {
        async get(key) {
          records.push(['storage.get', key]);
          return sessionValues.has(key) ? { [key]: sessionValues.get(key) } : {};
        },
        async set(values) {
          records.push(['storage.set', Object.keys(values)[0]]);
          for (const [key, value] of Object.entries(values)) sessionValues.set(key, value);
        },
        async remove(key) {
          records.push(['storage.remove', key]);
          sessionValues.delete(key);
        },
      },
      local: {
        async get(key) {
          records.push(['local.get', key]);
          return localValues.has(key) ? { [key]: localValues.get(key) } : {};
        },
        async set(values) {
          records.push(['local.set', Object.keys(values)[0]]);
          for (const [key, value] of Object.entries(values)) localValues.set(key, value);
        },
        async remove(key) {
          records.push(['local.remove', key]);
          localValues.delete(key);
        },
      },
    },
    tabs: {
      async create(options) {
        records.push(['tabs.create', JSON.parse(JSON.stringify(options))]);
        return { id: nextTabId++ };
      },
      async update(tabId, options) {
        records.push(['tabs.update', tabId, JSON.parse(JSON.stringify(options))]);
        return { id: tabId };
      },
      async remove(tabId) {
        records.push(['tabs.remove', tabId]);
      },
      async sendMessage(tabId, message) {
        records.push(['tabs.sendMessage', tabId, JSON.parse(JSON.stringify(message))]);
        return options.paginationResponse ?? { ok: true };
      },
      async reload(tabId) {
        records.push(['tabs.reload', tabId]);
        return { id: tabId };
      },
      async get(tabId) {
        records.push(['tabs.get', tabId]);
        return { id: tabId, status: 'complete' };
      },
      onUpdated: tabUpdated,
      onRemoved: tabRemoved,
    },
    alarms: {
      create(name, options) { records.push(['alarms.create', name, options]); },
      async clear(name) { records.push(['alarms.clear', name]); return true; },
      onAlarm: alarmEvent,
    },
  };
  const context = {
    chrome,
    crypto: options.crypto ?? {
      randomUUID() {
        return `00000000-0000-4000-8000-${String(nextUuid++).padStart(12, '0')}`;
      },
    },
    Date: options.Date ?? Date,
    URL,
    Set,
    Map,
    console,
    setTimeout,
    clearTimeout,
  };
  context.globalThis = context;
  vm.runInNewContext(
    await readFile(path.join(EXTENSION_DIR, 'service_worker.js'), 'utf8'),
    context,
    { filename: 'service_worker.js' },
  );
  return {
    alarmEvent,
    port,
    portDisconnect,
    portMessage,
    posted,
    records,
    runtimeMessage,
    localValues,
    sessionValues,
    tabRemoved,
    tabUpdated,
  };
}


async function settle() {
  await new Promise((resolve) => setTimeout(resolve, 0));
  await new Promise((resolve) => setTimeout(resolve, 0));
}


function invoke(listener, message, sender) {
  return new Promise((resolve) => {
    const asynchronous = listener(message, sender, resolve);
    if (asynchronous !== true) resolve({ asynchronous, missingResponse: true });
  });
}


function jdSender(tabId = 7) {
  return {
    id: EXTENSION_ID,
    url: 'https://search.jd.com/Search?keyword=x',
    tab: { id: tabId },
  };
}


async function verifyPageOne(worker, overrides = {}) {
  worker.portMessage.listeners[0](task({ pagination_enabled: true }));
  await settle();
  await invoke(
    worker.runtimeMessage.listeners[0],
    projection(overrides),
    jdSender(),
  );
  await settle();
}


async function requestPageTwo(worker, overrides = {}) {
  worker.portMessage.listeners[0](task({
    task_id: '1123456789abcdef0123456789abcdef',
    cursor: { cursor_id: 'jd:xiaomi15', ordinal: 0, page_number: 2 },
    session_action: 'next',
    pagination_enabled: true,
    ...overrides,
  }));
  await settle();
}


async function projectSoftFailure(worker, overrides = {}) {
  await invoke(
    worker.runtimeMessage.listeners[0],
    projection({
      observed_page_number: 2,
      page_state: 'page_structure_changed',
      items: [],
      diagnostics: { observed_page_number: 2 },
      ...overrides,
    }),
    jdSender(),
  );
  await settle();
}


test('worker connects one persistent native port at startup', async () => {
  const worker = await loadWorker();

  assert.deepEqual(worker.records[0], ['connectNative', 'com.codex.searching_at_scale']);
  assert.equal(worker.portMessage.listeners.length, 1);
  assert.equal(worker.portDisconnect.listeners.length, 1);
});


test('task creates an inactive blank tab, stores routing, then navigates', async () => {
  const worker = await loadWorker();
  worker.portMessage.listeners[0](task());
  await settle();

  const actions = worker.records.filter(([name]) => [
    'tabs.create', 'storage.set', 'tabs.update',
  ].includes(name));
  assert.equal(actions[0][0], 'tabs.create');
  assert.deepEqual(actions[0][1], { url: 'about:blank', active: false });
  assert.equal(actions[1][0], 'storage.set');
  assert.equal(actions[2][0], 'tabs.update');
  assert.equal(actions[2][1], 7);
  assert.match(actions[2][2].url, /^https:\/\/search\.jd\.com\/Search\?/u);
  assert.equal(Object.hasOwn(actions[2][2], 'active'), false);
});


test('unknown operation is rejected before any tab is created', async () => {
  const worker = await loadWorker();
  worker.portMessage.listeners[0](task({ operation: 'detail' }));
  await settle();

  assert.equal(worker.records.some(([name]) => name === 'tabs.create'), false);
  assert.equal(worker.posted[0].category, 'edge_operation_unsupported');
  assert.equal(worker.posted[0].retryable, false);
});


test('matching projection returns a versioned result and cleans the task tab', async () => {
  const worker = await loadWorker();
  worker.portMessage.listeners[0](task());
  await settle();
  const response = await invoke(
    worker.runtimeMessage.listeners[0],
    projection({
      pagination_state: 'pagination_unverified',
      has_next_page: false,
      items: [{
        ...jdItems(1, 100123)[0],
        title: '小米15 手机',
        price: '3999.00',
      }],
    }),
    {
      id: EXTENSION_ID,
      url: 'https://search.jd.com/Search?keyword=x',
      tab: { id: 7 },
    },
  );
  await settle();

  assert.deepEqual(JSON.parse(JSON.stringify(response)), { ok: true });
  assert.equal(worker.posted.length, 1);
  assert.equal(worker.posted[0].type, 'result');
  assert.equal(worker.posted[0].protocol_version, 3);
  assert.equal(worker.posted[0].task_id, TASK_ID);
  assert.equal(worker.posted[0].payload.projection_schema_version, 4);
  assert.deepEqual(
    worker.posted[0].payload.capabilities,
    ['stable_card_fields_v2', 'verified_pagination_v1', 'resilient_pagination_v1'],
  );
  assert.deepEqual(worker.posted[0].payload.diagnostics, diagnostics());
  assert.equal(worker.posted[0].payload.observed_page_number, 1);
  assert.equal(worker.posted[0].payload.items.length, 1);
  assert.ok(worker.records.some(([name, tabId]) => name === 'tabs.remove' && tabId === 7));
});


test('JD page two reuses the retained page-one tab and follows the public next link', async () => {
  const worker = await loadWorker();
  worker.portMessage.listeners[0](task({ pagination_enabled: true }));
  await settle();
  const response = await invoke(
    worker.runtimeMessage.listeners[0],
    projection({ items: [{ ...jdItems(1, 100123)[0], title: '第一页商品' }] }),
    {
      id: EXTENSION_ID,
      url: 'https://search.jd.com/Search?keyword=x&page=1',
      tab: { id: 7 },
    },
  );
  await settle();
  assert.deepEqual(JSON.parse(JSON.stringify(response)), { ok: true });
  assert.equal(worker.records.some(([name, tabId]) => name === 'tabs.remove' && tabId === 7), false);

  worker.portMessage.listeners[0](task({
    task_id: '1123456789abcdef0123456789abcdef',
    cursor: { cursor_id: 'jd:xiaomi15', ordinal: 0, page_number: 2 },
    session_action: 'next',
    pagination_enabled: true,
  }));
  await settle();

  assert.equal(worker.records.filter(([name]) => name === 'tabs.create').length, 1);
  assert.deepEqual(
    worker.records.filter(([name]) => name === 'tabs.sendMessage'),
    [['tabs.sendMessage', 7, { type: 'pagination_next', expected_page_number: 2 }]],
  );
});


test('explicit numbered-link route takes over the retained tab with one validated update', async () => {
  const localValues = new Map([
    ['searching-at-scale-jd-pagination-route', 'numbered_link'],
  ]);
  const worker = await loadWorker(new Map(), localValues, {
    paginationResponse: {
      ok: true,
      url: 'https://search.jd.com/Search?keyword=%E5%B0%8F%E7%B1%B315&page=3',
    },
  });
  await verifyPageOne(worker);

  await requestPageTwo(worker);

  assert.deepEqual(
    worker.records.filter(([name]) => name === 'tabs.sendMessage'),
    [[
      'tabs.sendMessage',
      7,
      {
        type: 'pagination_numbered_link',
        expected_page_number: 2,
        query: '小米15',
      },
    ]],
  );
  const updates = worker.records.filter(([name]) => name === 'tabs.update');
  assert.equal(updates.length, 2);
  assert.deepEqual(updates.at(-1), [
    'tabs.update',
    7,
    { url: 'https://search.jd.com/Search?keyword=%E5%B0%8F%E7%B1%B315&page=3' },
  ]);
});


test('stale invalid pagination route normalizes to the promoted experimental-url route', async () => {
  const localValues = new Map([
    ['searching-at-scale-jd-pagination-route', 'try_everything'],
    ['searching-at-scale-jd-page-jump-default-v1', true],
  ]);
  const worker = await loadWorker(new Map(), localValues, {
    paginationResponse: { ok: true },
  });
  await verifyPageOne(worker, { has_next_page: false, items: jdItems(30, 100000) });

  await requestPageTwo(worker);

  assert.equal(
    localValues.get('searching-at-scale-jd-pagination-route'),
    'experimental_url',
  );
  assert.equal(
    localValues.get('searching-at-scale-jd-experimental-url-default-v1'),
    true,
  );
  const updates = worker.records.filter(([name]) => name === 'tabs.update');
  assert.equal(updates.length, 3);
  assert.deepEqual(updates[1], ['tabs.update', 7, { active: true }]);
  assert.match(updates[2][2].url, /page=3/u);
});


test('one-time activation migrates a stale invalid route to experimental-url', async () => {
  const localValues = new Map([
    ['searching-at-scale-jd-pagination-route', 'try_everything'],
  ]);
  const worker = await loadWorker(new Map(), localValues, {
    paginationResponse: { ok: true },
  });
  await verifyPageOne(worker, { has_next_page: false, items: jdItems(30, 100000) });

  await requestPageTwo(worker);

  assert.equal(
    localValues.get('searching-at-scale-jd-pagination-route'),
    'experimental_url',
  );
  assert.equal(
    localValues.get('searching-at-scale-jd-experimental-url-default-v1'),
    true,
  );
  const updates = worker.records.filter(([name]) => name === 'tabs.update');
  assert.equal(updates.length, 3);
  assert.deepEqual(updates[1], ['tabs.update', 7, { active: true }]);
  assert.match(updates[2][2].url, /page=3/u);
});


test('one-time Route2 activation migrates page-jump to isolated public control', async () => {
  const localValues = new Map([
    ['searching-at-scale-jd-pagination-route', 'page_jump'],
  ]);
  const worker = await loadWorker(new Map(), localValues, {
    paginationResponse: { ok: true },
  });
  await verifyPageOne(worker);

  await requestPageTwo(worker);

  assert.equal(
    localValues.get('searching-at-scale-jd-pagination-route'),
    'public_control',
  );
  assert.equal(
    localValues.get('searching-at-scale-jd-public-control-default-v1'),
    true,
  );
  assert.deepEqual(
    worker.records.filter(([name]) => name === 'tabs.sendMessage'),
    [['tabs.sendMessage', 7, {
      type: 'pagination_next', expected_page_number: 2,
    }]],
  );
  assert.equal(worker.records.filter(([name]) => name === 'tabs.update').length, 1);
});


test('public-control route never enables sequential URL fallback without a control', async () => {
  const worker = await loadWorker(
    new Map(),
    new Map([
      ['searching-at-scale-jd-pagination-route', 'public_control'],
      ['searching-at-scale-jd-numbered-link-default-v1', true],
    ]),
  );

  await verifyPageOne(worker, {
    has_next_page: false,
    items: jdItems(30, 100000),
  });

  assert.equal(worker.sessionValues.has('searching-at-scale-pagination-session'), false);
  assert.equal(worker.records.filter(([name]) => name === 'tabs.update').length, 1);
  assert.equal(worker.records.some(([name, tabId]) => (
    name === 'tabs.remove' && tabId === 7
  )), true);
  assert.equal(worker.records.some(([, , body]) => (
    body?.type === 'pagination_next'
    || body?.type === 'pagination_numbered_link'
    || body?.type === 'pagination_page_jump'
  )), false);
});


test('one-time Route3 activation migrates public control to numbered link', async () => {
  const localValues = new Map([
    ['searching-at-scale-jd-pagination-route', 'public_control'],
  ]);
  const worker = await loadWorker(new Map(), localValues, {
    paginationResponse: {
      ok: true,
      url: 'https://search.jd.com/Search?keyword=%E5%B0%8F%E7%B1%B315&page=3',
    },
  });
  await verifyPageOne(worker, { has_next_page: false, items: jdItems(30) });

  await requestPageTwo(worker);

  assert.equal(
    localValues.get('searching-at-scale-jd-pagination-route'),
    'numbered_link',
  );
  assert.equal(
    localValues.get('searching-at-scale-jd-numbered-link-default-v1'),
    true,
  );
  const updates = worker.records.filter(([name]) => name === 'tabs.update');
  assert.equal(updates.length, 2);
  assert.deepEqual(updates.at(-1), [
    'tabs.update',
    7,
    { url: 'https://search.jd.com/Search?keyword=%E5%B0%8F%E7%B1%B315&page=3' },
  ]);
  assert.equal(
    worker.records.filter(([, , body]) => body?.type === 'pagination_next').length,
    0,
  );
});


test('one-time Route5 activation migrates numbered link to infinite scroll', async () => {
  const localValues = new Map([
    ['searching-at-scale-jd-pagination-route', 'numbered_link'],
    ['searching-at-scale-jd-numbered-link-default-v1', true],
  ]);
  const worker = await loadWorker(new Map(), localValues, {
    paginationResponse: {
      ok: true,
      url: 'https://search.jd.com/Search?keyword=%E5%B0%8F%E7%B1%B315&page=3',
    },
  });
  await verifyPageOne(worker, { has_next_page: false, items: jdItems(30) });

  await requestPageTwo(worker);

  assert.equal(
    localValues.get('searching-at-scale-jd-pagination-route'),
    'infinite_scroll',
  );
  assert.equal(
    localValues.get('searching-at-scale-jd-infinite-scroll-default-v1'),
    true,
  );
  assert.deepEqual(
    worker.records.filter(([name]) => name === 'tabs.sendMessage'),
    [['tabs.sendMessage', 7, {
      type: 'pagination_infinite_scroll', expected_page_number: 2,
    }]],
  );
  assert.equal(worker.records.filter(([name]) => name === 'tabs.update').length, 1);
});


test('numbered-link route remains frozen when local configuration changes mid-session', async () => {
  const localValues = new Map([
    ['searching-at-scale-jd-pagination-route', 'numbered_link'],
  ]);
  const worker = await loadWorker(new Map(), localValues, {
    paginationResponse: {
      ok: true,
      url: 'https://search.jd.com/Search?keyword=%E5%B0%8F%E7%B1%B315&page=3',
    },
  });
  await verifyPageOne(worker);
  localValues.set('searching-at-scale-jd-pagination-route', 'existing');

  await requestPageTwo(worker);

  assert.equal(
    worker.records.filter(([, , body]) => body?.type === 'pagination_numbered_link').length,
    1,
  );
  assert.equal(
    worker.records.filter(([, , body]) => body?.type === 'pagination_next').length,
    0,
  );
});


test('explicit numbered-link route does not fall through to sequential URL evidence', async () => {
  const localValues = new Map([
    ['searching-at-scale-jd-pagination-route', 'numbered_link'],
  ]);
  const worker = await loadWorker(new Map(), localValues, {
    paginationResponse: {
      ok: true,
      url: 'https://search.jd.com/Search?keyword=%E5%B0%8F%E7%B1%B315&page=3',
    },
  });
  await verifyPageOne(worker, { has_next_page: false, items: jdItems(30) });
  assert.equal(
    worker.sessionValues.get('searching-at-scale-pagination-session')
      .allow_sequential_fallback,
    false,
  );

  await requestPageTwo(worker);

  const messages = worker.records.filter(([name]) => name === 'tabs.sendMessage');
  assert.equal(messages.at(-1)[2].type, 'pagination_numbered_link');
  assert.equal(
    worker.records.filter(([name]) => name === 'tabs.update').length,
    2,
  );
});


const INVALID_NUMBERED_RESPONSES = [
  ['wrong host', 'https://example.com/Search?keyword=%E5%B0%8F%E7%B1%B315&page=3'],
  ['non-HTTPS scheme', 'http://search.jd.com/Search?keyword=%E5%B0%8F%E7%B1%B315&page=3'],
  ['wrong path', 'https://search.jd.com/search?keyword=%E5%B0%8F%E7%B1%B315&page=3'],
  ['different query', 'https://search.jd.com/Search?keyword=Redmi&page=3'],
  ['wrong page', 'https://search.jd.com/Search?keyword=%E5%B0%8F%E7%B1%B315&page=5'],
  ['duplicate keyword', 'https://search.jd.com/Search?keyword=%E5%B0%8F%E7%B1%B315&keyword=Redmi&page=3'],
  ['duplicate page', 'https://search.jd.com/Search?keyword=%E5%B0%8F%E7%B1%B315&page=3&page=5'],
  ['userinfo', 'https://user:pass@search.jd.com/Search?keyword=%E5%B0%8F%E7%B1%B315&page=3'],
  ['fragment', 'https://search.jd.com/Search?keyword=%E5%B0%8F%E7%B1%B315&page=3#next'],
];


for (const [reason, url] of INVALID_NUMBERED_RESPONSES) {
  test(`worker rejects numbered-link response with ${reason}`, async () => {
    const localValues = new Map([
      ['searching-at-scale-jd-pagination-route', 'numbered_link'],
    ]);
    const worker = await loadWorker(new Map(), localValues, {
      paginationResponse: { ok: true, url },
    });
    await verifyPageOne(worker);

    await requestPageTwo(worker);

    assert.equal(worker.posted.at(-1).category, 'pagination_navigation_unavailable');
    assert.equal(worker.posted.at(-1).retryable, false);
    assert.equal(worker.records.filter(([name]) => name === 'tabs.update').length, 1);
  });
}


test('JD page two uses persisted no-control evidence for the same-tab URL without re-probing DOM', async () => {
  const worker = await loadWorker(new Map(), new Map([
    ['searching-at-scale-jd-pagination-route', 'existing'],
  ]), {
    paginationResponse: { ok: true },
  });
  worker.portMessage.listeners[0](task({ pagination_enabled: true }));
  await settle();
  const firstItems = jdItems(30);
  await invoke(
    worker.runtimeMessage.listeners[0],
    projection({ has_next_page: false, items: firstItems }),
    {
      id: EXTENSION_ID,
      url: 'https://search.jd.com/Search?keyword=x&page=1',
      tab: { id: 7 },
    },
  );
  await settle();

  assert.equal(worker.records.some(([name, tabId]) => name === 'tabs.remove' && tabId === 7), false);
  assert.equal(
    worker.sessionValues.get('searching-at-scale-pagination-session').allow_sequential_fallback,
    true,
  );

  worker.portMessage.listeners[0](task({
    task_id: '1123456789abcdef0123456789abcdef',
    cursor: { cursor_id: 'jd:xiaomi15', ordinal: 0, page_number: 2 },
    session_action: 'next',
    pagination_enabled: true,
  }));
  await settle();

  const updates = worker.records.filter(([name]) => name === 'tabs.update');
  assert.equal(worker.records.filter(([name]) => name === 'tabs.create').length, 1);
  assert.deepEqual(worker.records.filter(([name]) => name === 'tabs.sendMessage'), []);
  assert.equal(updates.at(-1)[1], 7);
  assert.match(updates.at(-1)[2].url, /^https:\/\/search\.jd\.com\/Search\?/u);
  assert.match(updates.at(-1)[2].url, /(?:\?|&)page=3(?:&|$)/u);
});


test('zero-card page retains the owned tab for one reproject recovery', async () => {
  const worker = await loadWorker();
  await verifyPageOne(worker);
  await requestPageTwo(worker);
  await projectSoftFailure(worker);

  const session = worker.sessionValues.get('searching-at-scale-pagination-session');
  assert.equal(worker.posted.at(-1).category, 'pagination_page_transient_empty');
  assert.equal(worker.posted.at(-1).retryable, true);
  assert.equal(worker.records.some(([name, tabId]) => name === 'tabs.remove' && tabId === 7), false);
  assert.equal(session.verified_page_number, 1);
  assert.equal(session.pending_page_number, 2);
  assert.equal(session.recovery_stage, 'reproject');
  assert.equal(session.recovery_attempt, 1);
});


test('retained success accepts an immediately posted next task without busy or a second tab', async () => {
  const nextTask = task({
    task_id: '1123456789abcdef0123456789abcdef',
    cursor: { cursor_id: 'jd:xiaomi15', ordinal: 0, page_number: 2 },
    session_action: 'next', pagination_enabled: true,
  });
  const worker = await loadWorker(new Map(), new Map([
    ['searching-at-scale-jd-pagination-route', 'existing'],
  ]), {
    onPostMessage(message, emit) {
      if (message.type === 'result' && message.task_id === TASK_ID) emit(nextTask);
    },
  });
  await verifyPageOne(worker);

  assert.equal(worker.posted.some(({ category }) => category === 'edge_background_bridge_busy'), false);
  assert.deepEqual(worker.records.filter(([name]) => name === 'tabs.sendMessage'), [
    ['tabs.sendMessage', 7, { type: 'pagination_next', expected_page_number: 2 }],
  ]);
  assert.equal(worker.records.filter(([name]) => name === 'tabs.create').length, 1);
});


test('soft error accepts an immediately posted recover task without busy or a second tab', async () => {
  const recoverTask = task({
    task_id: '2123456789abcdef0123456789abcdef',
    cursor: { cursor_id: 'jd:xiaomi15', ordinal: 0, page_number: 2 },
    session_action: 'recover', pagination_enabled: true,
  });
  const worker = await loadWorker(new Map(), new Map([
    ['searching-at-scale-jd-pagination-route', 'existing'],
  ]), {
    onPostMessage(message, emit) {
      if (message.category === 'pagination_page_transient_empty') emit(recoverTask);
    },
  });
  await verifyPageOne(worker);
  await requestPageTwo(worker);
  await projectSoftFailure(worker);

  assert.equal(worker.posted.some(({ category }) => category === 'edge_background_bridge_busy'), false);
  assert.deepEqual(worker.records.filter(([name, , body]) => (
    name === 'tabs.sendMessage' && body.type === 'pagination_recover'
  )), [[
    'tabs.sendMessage', 7, { type: 'pagination_recover', recovery_attempt: 1 },
  ]]);
  assert.equal(worker.records.filter(([name]) => name === 'tabs.create').length, 1);
});


test('second recover reloads the same tab once and preserves reload authority', async () => {
  const worker = await loadWorker();
  await verifyPageOne(worker);
  await requestPageTwo(worker);
  await projectSoftFailure(worker);

  await requestPageTwo(worker, {
    task_id: '2123456789abcdef0123456789abcdef',
    session_action: 'recover',
  });
  assert.deepEqual(worker.records.at(-1), [
    'tabs.sendMessage', 7, { type: 'pagination_recover', recovery_attempt: 1 },
  ]);
  await projectSoftFailure(worker, {
    diagnostics: {
      observed_page_number: 2,
      recovery_stage: 'reproject',
      recovery_attempt: 1,
    },
  });

  await requestPageTwo(worker, {
    task_id: '3123456789abcdef0123456789abcdef',
    session_action: 'recover',
  });
  assert.deepEqual(
    worker.records.filter(([name]) => name === 'tabs.reload'),
    [['tabs.reload', 7]],
  );
  assert.equal(worker.records.filter(([name]) => name === 'tabs.create').length, 1);
  const config = await invoke(
    worker.runtimeMessage.listeners[0],
    { type: 'projection_config' },
    jdSender(),
  );
  assert.equal(config.expected_page_number, 2);
  assert.equal(config.recovery_stage, 'reload');
  assert.equal(config.recovery_attempt, 2);
});


test('automatic initial projection after reload belongs to pending page and third failure closes', async () => {
  const worker = await loadWorker();
  await verifyPageOne(worker);
  await requestPageTwo(worker);
  await projectSoftFailure(worker);
  await requestPageTwo(worker, {
    task_id: '2123456789abcdef0123456789abcdef', session_action: 'recover',
  });
  await projectSoftFailure(worker, {
    diagnostics: {
      observed_page_number: 2, recovery_stage: 'reproject', recovery_attempt: 1,
    },
  });
  await requestPageTwo(worker, {
    task_id: '3123456789abcdef0123456789abcdef', session_action: 'recover',
  });

  await projectSoftFailure(worker, {
    diagnostics: {
      observed_page_number: 2, recovery_stage: 'initial', recovery_attempt: 0,
    },
  });
  assert.equal(worker.posted.at(-1).category, 'browser_page_structure_changed');
  assert.equal(worker.posted.at(-1).retryable, false);
  assert.equal(worker.records.some(([name, tabId]) => name === 'tabs.remove' && tabId === 7), true);
  assert.equal(worker.records.filter(([name]) => name === 'tabs.reload').length, 1);
  assert.equal(worker.sessionValues.has('searching-at-scale-pagination-session'), false);
});


test('successful reproject verifies the pending page without creating a tab', async () => {
  const worker = await loadWorker();
  await verifyPageOne(worker);
  await requestPageTwo(worker);
  await projectSoftFailure(worker);
  await requestPageTwo(worker, {
    task_id: '2123456789abcdef0123456789abcdef', session_action: 'recover',
  });
  await invoke(
    worker.runtimeMessage.listeners[0],
    projection({
      observed_page_number: 2,
      items: jdItems(1, 200123),
      diagnostics: {
        observed_page_number: 2, recovery_stage: 'reproject', recovery_attempt: 1,
      },
    }),
    jdSender(),
  );
  await settle();

  const session = worker.sessionValues.get('searching-at-scale-pagination-session');
  assert.equal(worker.posted.at(-1).type, 'result');
  assert.equal(session.verified_page_number, 2);
  assert.equal(session.pending_page_number, null);
  assert.equal(session.previous_sku_digest, '200123');
  assert.equal(session.recovery_stage, 'initial');
  assert.equal(session.recovery_attempt, 0);
  assert.equal(worker.records.filter(([name]) => name === 'tabs.create').length, 1);
});


test('unchanged SKU digest enters the same reproject recovery state', async () => {
  const worker = await loadWorker();
  await verifyPageOne(worker);
  await requestPageTwo(worker);
  await invoke(
    worker.runtimeMessage.listeners[0],
    projection({
      observed_page_number: 2,
      diagnostics: { observed_page_number: 2 },
      items: jdItems(1, 100123),
    }),
    jdSender(),
  );
  await settle();

  const session = worker.sessionValues.get('searching-at-scale-pagination-session');
  assert.equal(worker.posted.at(-1).category, 'pagination_page_stalled');
  assert.equal(worker.posted.at(-1).retryable, true);
  assert.equal(session.pending_page_number, 2);
  assert.equal(session.recovery_stage, 'reproject');
  assert.equal(worker.records.some(([name, tabId]) => name === 'tabs.remove' && tabId === 7), false);
});


test('recover requires the exact pending page and stored session identity', async () => {
  const baseSession = {
    tab_id: 7, platform: 'jd', query: '小米15', query_family: '小米15:default',
    cursor_id: 'jd:xiaomi15', cursor_ordinal: 0,
    verified_page_number: 1, pending_page_number: 2,
    previous_sku_digest: '100123', has_next_page: true,
    recovery_stage: 'reproject', recovery_attempt: 1,
  };
  for (const overrides of [
    { cursor: { cursor_id: 'jd:xiaomi15', ordinal: 0, page_number: 3 } },
    { query: '机械键盘' },
    { query_family: '小米15:self-operated' },
    { cursor: { cursor_id: 'jd:other', ordinal: 0, page_number: 2 } },
    { cursor: { cursor_id: 'jd:xiaomi15', ordinal: 1, page_number: 2 } },
  ]) {
    const worker = await loadWorker(new Map([[
      'searching-at-scale-pagination-session', { ...baseSession },
    ]]));
    worker.portMessage.listeners[0](task({
      cursor: { cursor_id: 'jd:xiaomi15', ordinal: 0, page_number: 2 },
      session_action: 'recover', pagination_enabled: true, ...overrides,
    }));
    await settle();
    assert.equal(worker.posted.at(-1).category, 'pagination_session_missing');
    assert.equal(worker.records.some(([name]) => name === 'tabs.sendMessage'), false);
    assert.equal(worker.records.some(([name]) => name === 'tabs.reload'), false);
  }
});


test('recover on a non-JD platform fails closed before any tab or navigation effect', async () => {
  const worker = await loadWorker();
  worker.portMessage.listeners[0](task({
    platform: 'taobao', query: '键盘', query_family: '键盘:default',
    cursor: { cursor_id: 'taobao:keyboard', ordinal: 0, page_number: 2 },
    session_action: 'recover', pagination_enabled: true,
  }));
  await settle();

  assert.equal(worker.posted.length, 1);
  assert.equal(worker.posted.at(-1).category, 'edge_native_message_invalid');
  for (const effect of ['tabs.create', 'tabs.update', 'tabs.reload', 'tabs.sendMessage']) {
    assert.equal(worker.records.some(([name]) => name === effect), false);
  }
});


test('captcha rate-limit and authentication projections circuit-break before recovery', async () => {
  for (const pageState of ['captcha_required', 'rate_limited', 'authentication_required']) {
    const worker = await loadWorker();
    worker.portMessage.listeners[0](task({ pagination_enabled: true }));
    await settle();
    await invoke(
      worker.runtimeMessage.listeners[0],
      projection({
        page_state: pageState, pagination_state: 'pagination_unverified',
        has_next_page: false, items: [],
      }),
      jdSender(),
    );
    await settle();
    assert.equal(worker.localValues.get('searching-at-scale-jd-risk-circuit').reason, pageState);
    assert.equal(worker.records.some(([name, tabId]) => name === 'tabs.remove' && tabId === 7), true);
    assert.equal(worker.records.some(([name]) => name === 'tabs.sendMessage'), false);
    assert.equal(worker.records.some(([name]) => name === 'tabs.reload'), false);
  }
});


test('active JD circuit rejects recover without creating navigating reprojecting or reloading', async () => {
  const sessionValues = new Map([[
    'searching-at-scale-pagination-session',
    {
      tab_id: 7, platform: 'jd', query: '小米15', query_family: '小米15:default',
      cursor_id: 'jd:xiaomi15', cursor_ordinal: 0,
      verified_page_number: 1, pending_page_number: 2,
      previous_sku_digest: '100123', has_next_page: true,
      recovery_stage: 'reproject', recovery_attempt: 1,
    },
  ]]);
  const now = Date.now();
  const localValues = new Map([[
    'searching-at-scale-jd-risk-circuit',
    { blocked_until_ms: now + 3600000, observed_at_ms: now, reason: 'rate_limited' },
  ]]);
  const worker = await loadWorker(sessionValues, localValues);
  worker.portMessage.listeners[0](task({
    cursor: { cursor_id: 'jd:xiaomi15', ordinal: 0, page_number: 2 },
    session_action: 'recover', pagination_enabled: true,
  }));
  await settle();

  assert.equal(worker.posted.at(-1).category, 'rate_limited');
  for (const effect of ['tabs.create', 'tabs.update', 'tabs.reload', 'tabs.sendMessage']) {
    assert.equal(worker.records.some(([name]) => name === effect), false);
  }
});


test('stale initial projection cannot finish a newer reproject route on the same tab', async () => {
  const worker = await loadWorker();
  await verifyPageOne(worker);
  await requestPageTwo(worker);
  await projectSoftFailure(worker);
  await requestPageTwo(worker, {
    task_id: '2123456789abcdef0123456789abcdef', session_action: 'recover',
  });
  const postedBefore = worker.posted.length;

  const response = await invoke(
    worker.runtimeMessage.listeners[0],
    projection({
      observed_page_number: 2, page_state: 'page_structure_changed', items: [],
      diagnostics: {
        observed_page_number: 2, recovery_stage: 'initial', recovery_attempt: 0,
      },
    }),
    jdSender(),
  );
  await settle();

  assert.equal(response.category, 'edge_extension_task_missing');
  assert.equal(worker.posted.length, postedBefore);
  assert.equal(
    worker.sessionValues.get('searching-at-scale-current-task').task_id,
    '2123456789abcdef0123456789abcdef',
  );
});


test('duplicate third-failure projections emit and remove exactly once', async () => {
  const worker = await loadWorker();
  await verifyPageOne(worker);
  await requestPageTwo(worker);
  await projectSoftFailure(worker);
  await requestPageTwo(worker, {
    task_id: '2123456789abcdef0123456789abcdef', session_action: 'recover',
  });
  await projectSoftFailure(worker, {
    diagnostics: {
      observed_page_number: 2, recovery_stage: 'reproject', recovery_attempt: 1,
    },
  });
  await requestPageTwo(worker, {
    task_id: '3123456789abcdef0123456789abcdef', session_action: 'recover',
  });
  const duplicate = projection({
    observed_page_number: 2, page_state: 'page_structure_changed', items: [],
    diagnostics: {
      observed_page_number: 2, recovery_stage: 'initial', recovery_attempt: 0,
    },
  });

  await Promise.all([
    invoke(worker.runtimeMessage.listeners[0], duplicate, jdSender()),
    invoke(worker.runtimeMessage.listeners[0], duplicate, jdSender()),
  ]);
  await settle();

  assert.equal(worker.posted.filter(({ task_id: id }) => (
    id === '3123456789abcdef0123456789abcdef'
  )).length, 1);
  assert.equal(worker.records.filter(([name, tabId]) => (
    name === 'tabs.remove' && tabId === 7
  )).length, 1);
});


test('reused protocol task id can finish two distinct routes independently', async () => {
  const worker = await loadWorker();
  worker.portMessage.listeners[0](task());
  await settle();
  await invoke(
    worker.runtimeMessage.listeners[0],
    projection({ pagination_state: 'pagination_unverified', has_next_page: false }),
    jdSender(7),
  );
  await settle();

  worker.portMessage.listeners[0](task({
    query: '机械键盘', query_family: '机械键盘:default',
    cursor: { cursor_id: 'jd:keyboard', ordinal: 0, page_number: 1 },
  }));
  await settle();
  await invoke(
    worker.runtimeMessage.listeners[0],
    projection({ pagination_state: 'pagination_unverified', has_next_page: false }),
    jdSender(8),
  );
  await settle();

  assert.equal(worker.posted.filter(({ type }) => type === 'result').length, 2);
  assert.deepEqual(worker.records.filter(([name]) => name === 'tabs.remove'), [
    ['tabs.remove', 7], ['tabs.remove', 8],
  ]);
  assert.equal(worker.sessionValues.has('searching-at-scale-current-task'), false);
});


test('delayed route A projection cannot clear same-id retained route B', async () => {
  const worker = await loadWorker();
  await verifyPageOne(worker);
  await requestPageTwo(worker, { task_id: TASK_ID });
  const postedBefore = worker.posted.length;

  const staleResponse = await invoke(
    worker.runtimeMessage.listeners[0],
    projection(),
    jdSender(),
  );
  await settle();
  assert.equal(staleResponse.category, 'edge_extension_task_missing');
  assert.equal(worker.posted.length, postedBefore);
  assert.equal(worker.sessionValues.get('searching-at-scale-current-task').cursor.page_number, 2);

  await invoke(
    worker.runtimeMessage.listeners[0],
    projection({
      observed_page_number: 2,
      items: jdItems(1, 200123),
      diagnostics: { observed_page_number: 2 },
    }),
    jdSender(),
  );
  await settle();

  assert.equal(worker.posted.filter(({ type }) => type === 'result').length, 2);
  assert.equal(worker.posted.some(({ category }) => category === 'edge_background_bridge_busy'), false);
  assert.equal(worker.records.filter(([name]) => name === 'tabs.create').length, 1);
  assert.equal(worker.sessionValues.has('searching-at-scale-current-task'), false);
});


test('worker restart uses a collision-free route token and stale alarm cannot finish the new route', async () => {
  const sessionValues = new Map();
  class FixedDate extends Date {
    static now() { return 1700000000000; }
  }
  const workerA = await loadWorker(sessionValues, new Map(), {
    Date: FixedDate,
    crypto: { randomUUID: () => 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa' },
  });
  workerA.portMessage.listeners[0](task());
  await settle();
  const routeA = sessionValues.get('searching-at-scale-current-task');
  const alarmA = workerA.records.find(([name]) => name === 'alarms.create')[1];

  sessionValues.delete('searching-at-scale-current-task');
  const workerB = await loadWorker(sessionValues, new Map(), {
    Date: FixedDate,
    crypto: { randomUUID: () => 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb' },
  });
  workerB.portMessage.listeners[0](task());
  await settle();
  const routeB = sessionValues.get('searching-at-scale-current-task');
  const alarmB = workerB.records.find(([name]) => name === 'alarms.create')[1];

  assert.notEqual(routeA.route_token, routeB.route_token);
  assert.notEqual(alarmA, alarmB);
  workerB.alarmEvent.listeners[0]({ name: alarmA });
  await settle();
  assert.equal(workerB.posted.length, 0);
  assert.equal(
    sessionValues.get('searching-at-scale-current-task').route_token,
    routeB.route_token,
  );

  await invoke(
    workerB.runtimeMessage.listeners[0],
    projection({ pagination_state: 'pagination_unverified', has_next_page: false }),
    jdSender(),
  );
  await settle();
  assert.equal(workerB.posted.at(-1).type, 'result');
});


test('missing crypto randomUUID fails closed before tab or navigation effects', async () => {
  const worker = await loadWorker(new Map(), new Map(), { crypto: {} });
  worker.portMessage.listeners[0](task());
  await settle();

  assert.equal(worker.posted.length, 1);
  assert.equal(worker.posted[0].category, 'edge_extension_failure');
  assert.equal(worker.posted[0].retryable, false);
  for (const effect of ['tabs.create', 'tabs.update', 'tabs.reload', 'tabs.sendMessage']) {
    assert.equal(worker.records.some(([name]) => name === effect), false);
  }
});


test('JD next-page task fails closed when no matching retained session exists', async () => {
  const worker = await loadWorker();
  worker.portMessage.listeners[0](task({
    cursor: { cursor_id: 'jd:xiaomi15', ordinal: 0, page_number: 2 },
    session_action: 'next',
    pagination_enabled: true,
  }));
  await settle();

  assert.equal(worker.records.some(([name]) => name === 'tabs.create'), false);
  assert.equal(worker.records.some(([name]) => name === 'tabs.update'), false);
  assert.equal(worker.posted[0].category, 'pagination_session_missing');
  assert.equal(worker.posted[0].retryable, false);
});


test('JD sequential page is recoverable when the rendered SKU digest does not change', async () => {
  const sessionValues = new Map([[
    'searching-at-scale-pagination-session',
    {
      tab_id: 7, platform: 'jd', query: '小米15', query_family: '小米15:default',
      cursor_id: 'jd:xiaomi15', cursor_ordinal: 0,
      verified_page_number: 1, pending_page_number: null,
      previous_sku_digest: '100123', has_next_page: true,
      recovery_stage: 'initial', recovery_attempt: 0,
    },
  ]]);
  const worker = await loadWorker(sessionValues);
  worker.portMessage.listeners[0](task({
    task_id: '1123456789abcdef0123456789abcdef',
    cursor: { cursor_id: 'jd:xiaomi15', ordinal: 0, page_number: 2 },
    session_action: 'next', pagination_enabled: true,
  }));
  await settle();
  await invoke(
    worker.runtimeMessage.listeners[0],
    projection({
      observed_page_number: 2,
      diagnostics: { observed_page_number: 2 },
      items: [{ ...jdItems(1, 100123)[0], title: '重复商品' }],
    }),
    {
      id: EXTENSION_ID,
      url: 'https://search.jd.com/Search?keyword=x&page=3',
      tab: { id: 7 },
    },
  );
  await settle();

  assert.equal(worker.posted.at(-1).category, 'pagination_page_stalled');
  assert.equal(worker.posted.at(-1).retryable, true);
  assert.equal(worker.records.some(([name, tabId]) => name === 'tabs.remove' && tabId === 7), false);
  assert.equal(
    worker.sessionValues.get('searching-at-scale-pagination-session').recovery_stage,
    'reproject',
  );
});


test('starting a new JD topic closes the retained tab before creating one new tab', async () => {
  const sessionValues = new Map([[
    'searching-at-scale-pagination-session',
    {
      tab_id: 41,
      platform: 'jd',
      query: '小米15',
      query_family: '小米15:default',
      cursor_id: 'jd:xiaomi15',
      cursor_ordinal: 0,
      verified_page_number: 1,
      pending_page_number: null,
      previous_sku_digest: '100123',
      has_next_page: true,
      recovery_stage: 'initial',
      recovery_attempt: 0,
    },
  ]]);
  const worker = await loadWorker(sessionValues);
  worker.portMessage.listeners[0](task({
    query: '机械键盘',
    query_family: '机械键盘:default',
    cursor: { cursor_id: 'jd:keyboard', ordinal: 0, page_number: 1 },
    pagination_enabled: true,
  }));
  await settle();

  const removes = worker.records.filter(([name]) => name === 'tabs.remove');
  assert.deepEqual(removes, [['tabs.remove', 41]]);
  assert.equal(worker.records.filter(([name]) => name === 'tabs.create').length, 1);
});


test('stale content projection returns an explicit reload requirement', async () => {
  const worker = await loadWorker();
  worker.portMessage.listeners[0](task());
  await settle();
  const response = await invoke(
    worker.runtimeMessage.listeners[0],
    {
      type: 'projection',
      platform: 'jd',
      page_state: 'ready',
      source_url: 'https://search.jd.com/Search?keyword=x',
      items: [],
    },
    { id: EXTENSION_ID, url: 'https://search.jd.com/Search?keyword=x', tab: { id: 7 } },
  );

  assert.equal(response.category, 'edge_extension_reload_required');
  assert.equal(worker.posted.length, 0);
});


test('projection from another tab cannot reach the native host', async () => {
  const worker = await loadWorker();
  worker.portMessage.listeners[0](task());
  await settle();
  const response = await invoke(
    worker.runtimeMessage.listeners[0],
    {
      type: 'projection', projection_schema_version: 4,
      capabilities: [
        'stable_card_fields_v2', 'verified_pagination_v1', 'resilient_pagination_v1',
      ], platform: 'jd',
      page_state: 'ready', source_url: 'https://search.jd.com/Search',
      observed_page_number: 1, pagination_state: 'pagination_unverified',
      has_next_page: false, sku_digest: 'none', diagnostics: diagnostics({
        data_sku_node_count: 0, candidate_anchor_count: 0, valid_item_count: 0,
      }), items: [],
    },
    { id: EXTENSION_ID, url: 'https://search.jd.com/Search', tab: { id: 99 } },
  );

  assert.equal(response.category, 'edge_extension_task_missing');
  assert.equal(worker.posted.length, 0);
});


test('JD risk and login redirects fail quickly without DOM access', async () => {
  for (const [url, category] of [
    ['https://cfe.m.jd.com/privatedomain/risk_handler/03101900/', 'rate_limited'],
    ['https://passport.jd.com/new/login.aspx?ReturnUrl=x', 'authentication_required'],
  ]) {
    const worker = await loadWorker();
    worker.portMessage.listeners[0](task());
    await settle();
    worker.tabUpdated.listeners[0](7, { url }, { id: 7, url });
    await settle();
    assert.equal(worker.posted[0].category, category);
    assert.ok(worker.records.some(([name, tabId]) => name === 'tabs.remove' && tabId === 7));
  }
});


test('JD risk redirect persists a circuit that blocks a new worker before navigation', async () => {
  const localValues = new Map();
  const first = await loadWorker(new Map(), localValues);
  first.portMessage.listeners[0](task());
  await settle();
  first.tabUpdated.listeners[0](
    7,
    { url: 'https://cfe.m.jd.com/privatedomain/risk_handler/03101900/' },
    { id: 7 },
  );
  await settle();

  const circuit = localValues.get('searching-at-scale-jd-risk-circuit');
  assert.equal(circuit.reason, 'rate_limited');
  assert.ok(circuit.blocked_until_ms > circuit.observed_at_ms);

  const second = await loadWorker(new Map(), localValues);
  second.portMessage.listeners[0](task());
  await settle();
  assert.equal(second.posted[0].category, 'rate_limited');
  assert.equal(second.records.some(([name]) => name === 'tabs.create'), false);
  assert.equal(second.records.some(([name]) => name === 'tabs.update'), false);
  assert.equal(second.records.some(([name]) => name === 'tabs.sendMessage'), false);
});


test('JD rate-limited body projection persists the same hard-risk circuit', async () => {
  const worker = await loadWorker();
  worker.portMessage.listeners[0](task());
  await settle();
  await invoke(
    worker.runtimeMessage.listeners[0],
    projection({
      page_state: 'rate_limited', pagination_state: 'pagination_unverified',
      has_next_page: false, items: [],
    }),
    {
      id: EXTENSION_ID,
      url: 'https://search.jd.com/Search?keyword=x',
      tab: { id: 7 },
    },
  );
  await settle();

  const circuit = worker.localValues.get('searching-at-scale-jd-risk-circuit');
  assert.equal(circuit.reason, 'rate_limited');
});


test('expired JD risk circuit is removed before a new page-one slow-start task', async () => {
  const localValues = new Map([[
    'searching-at-scale-jd-risk-circuit',
    { blocked_until_ms: Date.now() - 1, observed_at_ms: Date.now() - 3600001, reason: 'rate_limited' },
  ]]);
  const worker = await loadWorker(new Map(), localValues);
  worker.portMessage.listeners[0](task());
  await settle();

  assert.equal(localValues.has('searching-at-scale-jd-risk-circuit'), false);
  assert.equal(worker.records.filter(([name]) => name === 'tabs.create').length, 1);
});


test('next page is rejected before tab creation unless explicitly enabled', async () => {
  const worker = await loadWorker();
  worker.portMessage.listeners[0](task({
    cursor: { cursor_id: 'jd:xiaomi15', ordinal: 0, page_number: 2 },
    session_action: 'next',
  }));
  await settle();

  assert.equal(worker.records.some(([name]) => name === 'tabs.create'), false);
  assert.equal(worker.posted[0].category, 'edge_native_message_invalid');
});


test('page 513 is rejected before tab creation even when pagination is enabled', async () => {
  const worker = await loadWorker();
  worker.portMessage.listeners[0](task({
    cursor: { cursor_id: 'jd:xiaomi15', ordinal: 0, page_number: 513 },
    session_action: 'next',
    pagination_enabled: true,
  }));
  await settle();

  assert.equal(worker.records.some(([name]) => name === 'tabs.create'), false);
  assert.equal(worker.posted[0].category, 'edge_native_message_invalid');
});


test('user-closing the owned background tab returns a stable error', async () => {
  const worker = await loadWorker();
  worker.portMessage.listeners[0](task());
  await settle();
  worker.tabRemoved.listeners[0](7, { windowId: 1, isWindowClosing: false });
  await settle();

  assert.equal(worker.posted[0].category, 'edge_background_tab_closed');
});


// 2026-08-11 promoted: the foreground direct-URL route (`experimental_url`) is
// the default JD pagination route. These tests cover it as stable behavior.

function experimentalUrlWorker() {
  return loadWorker(
    new Map(),
    new Map([
      ['searching-at-scale-jd-pagination-route', 'experimental_url'],
    ]),
  );
}


test('experimental-url route is stable and foregrounds the tab on next with a direct odd page URL', async () => {
  const worker = await experimentalUrlWorker();
  await verifyPageOne(worker, { has_next_page: false, items: jdItems(30, 100000) });

  await requestPageTwo(worker);

  assert.equal(
    worker.localValues.get('searching-at-scale-jd-pagination-route'),
    'experimental_url',
  );
  const updates = worker.records.filter(([name]) => name === 'tabs.update');
  // page-1 start navigation + page-2 active + page-2 direct URL navigation.
  assert.equal(updates.length, 3);
  assert.deepEqual(updates[1], ['tabs.update', 7, { active: true }]);
  assert.equal(updates[2][0], 'tabs.update');
  assert.equal(updates[2][1], 7);
  assert.match(updates[2][2].url, /page=3/u);
  assert.equal(Object.hasOwn(updates[2][2], 'active'), false);
  assert.equal(
    worker.records.some(([, , body]) => body?.type === 'pagination_page_jump'
      || body?.type === 'pagination_numbered_link'
      || body?.type === 'pagination_next'
      || body?.type === 'pagination_infinite_scroll'),
    false,
  );
});


test('experimental-url route retains a verified 30-item session', async () => {
  const worker = await experimentalUrlWorker();
  await verifyPageOne(worker, { has_next_page: false, items: jdItems(30, 100000) });

  const session = worker.sessionValues.get('searching-at-scale-pagination-session');
  assert.equal(session.pagination_route, 'experimental_url');
  assert.equal(session.allow_experimental_url, true);
  assert.equal(session.verified_page_number, 1);
  assert.equal(
    worker.records.some(([name, tabId]) => name === 'tabs.remove' && tabId === 7),
    false,
  );
});


test('experimental-url route does not retain a short page', async () => {
  const worker = await experimentalUrlWorker();
  await verifyPageOne(worker, { has_next_page: false, items: jdItems(12, 100000) });

  assert.equal(worker.sessionValues.has('searching-at-scale-pagination-session'), false);
  assert.equal(
    worker.records.some(([name, tabId]) => name === 'tabs.remove' && tabId === 7),
    true,
  );
});


test('experimental-url route retains a >30-card page two so page three can continue', async () => {
  const worker = await experimentalUrlWorker();
  await verifyPageOne(worker, { has_next_page: false, items: jdItems(30, 100000) });
  await requestPageTwo(worker);

  await invoke(
    worker.runtimeMessage.listeners[0],
    projection({
      has_next_page: false,
      observed_page_number: 2,
      items: jdItems(58, 100000),
      diagnostics: { observed_page_number: 2 },
    }),
    jdSender(),
  );
  await settle();

  const session = worker.sessionValues.get('searching-at-scale-pagination-session');
  assert.equal(session.verified_page_number, 2);
  assert.equal(session.allow_experimental_url, true);
  assert.equal(session.pagination_route, 'experimental_url');
  assert.equal(
    worker.records.some(([name, tabId]) => name === 'tabs.remove' && tabId === 7),
    false,
  );
});


test('experimental-url route still trips hard risk before continuation', async () => {
  const worker = await experimentalUrlWorker();
  await verifyPageOne(worker, { has_next_page: false, items: jdItems(30, 100000) });
  await requestPageTwo(worker);

  await invoke(
    worker.runtimeMessage.listeners[0],
    projection({
      observed_page_number: 2,
      page_state: 'rate_limited',
      items: [],
      diagnostics: { observed_page_number: 2 },
    }),
    jdSender(),
  );
  await settle();

  assert.equal(worker.posted.at(-1).category, 'rate_limited');
  assert.equal(
    worker.localValues.get('searching-at-scale-jd-risk-circuit').blocked_until_ms > Date.now(),
    true,
  );
  assert.equal(worker.records.some(([name]) => name === 'tabs.reload'), false);
});


test('task pagination_route override selects experimental_url without storage', async () => {
  const worker = await loadWorker();
  worker.portMessage.listeners[0](task({
    pagination_enabled: true,
    pagination_route: 'experimental_url',
  }));
  await settle();
  await invoke(
    worker.runtimeMessage.listeners[0],
    projection({ has_next_page: false, items: jdItems(30, 100000) }),
    jdSender(),
  );
  await settle();

  const session = worker.sessionValues.get('searching-at-scale-pagination-session');
  assert.equal(session.pagination_route, 'experimental_url');
  assert.equal(session.allow_experimental_url, true);

  worker.portMessage.listeners[0](task({
    task_id: '1123456789abcdef0123456789abcdef',
    cursor: { cursor_id: 'jd:xiaomi15', ordinal: 0, page_number: 2 },
    session_action: 'next',
    pagination_enabled: true,
    pagination_route: 'experimental_url',
  }));
  await settle();

  const updates = worker.records.filter(([name]) => name === 'tabs.update');
  assert.equal(updates.length, 3);
  assert.deepEqual(updates[1], ['tabs.update', 7, { active: true }]);
  assert.match(updates[2][2].url, /page=3/u);
});


test('task pagination_route override rejects an unknown route', async () => {
  const worker = await loadWorker();
  worker.portMessage.listeners[0](task({
    pagination_enabled: true,
    pagination_route: 'bogus_route',
  }));
  await settle();

  assert.equal(worker.posted[0].category, 'edge_native_message_invalid');
});


test('foreground activation is confined to the promoted JD direct-URL branch', async () => {
  const source = await readFile(path.join(EXTENSION_DIR, 'service_worker.js'), 'utf8');

  // 2026-08-11 promoted contract: the JD foreground direct-URL route
  // (`experimental_url`, the default) foregrounds the tab once before
  // navigating to the next odd physical page. The user has authorized this
  // stable behavior; `active: true` is permitted ONLY inside that navigation
  // branch, and nowhere else.
  const lines = source.split('\n');
  const branchLines = [];
  lines.forEach((line, index) => {
    if (line.includes("session.pagination_route === 'experimental_url'")) {
      branchLines.push(index + 1);
    }
  });
  assert.ok(branchLines.length > 0, 'JD direct-URL branch must exist');
  const activeLines = lines
    .map((line, index) => [line, index + 1])
    .filter(([line]) => /active\s*:\s*true/u.test(line));
  assert.equal(activeLines.length, 1, 'exactly one foreground activation');
  const [, activeLine] = activeLines[0];
  const nearest = branchLines.reduce((best, line) => (
    Math.abs(line - activeLine) < Math.abs(best - activeLine) ? line : best
  ));
  assert.ok(
    Math.abs(nearest - activeLine) <= 8,
    `active:true at line ${activeLine} must sit in the JD direct-URL branch`,
  );
  assert.doesNotMatch(source, /windows\.update|tabs\.highlight|sendNativeMessage|chrome\.debugger/u);
});


async function loadPageJumpWorker(options = {}) {
  return loadWorker(
    new Map(),
    new Map([
      ['searching-at-scale-jd-pagination-route', 'page_jump'],
      ['searching-at-scale-jd-public-control-default-v1', true],
    ]),
    options,
  );
}


async function verifyPageJumpPageOne(worker) {
  await verifyPageOne(worker, {
    has_next_page: false,
    items: jdItems(30, 100000),
  });
}


test('missing route configuration defaults to the promoted experimental-url route', async () => {
  const worker = await loadWorker(new Map(), new Map(), {
    paginationResponse: { ok: true },
  });
  await verifyPageOne(worker, { has_next_page: false, items: jdItems(30, 100000) });

  await requestPageTwo(worker);

  const updates = worker.records.filter(([name]) => name === 'tabs.update');
  assert.equal(updates.length, 3);
  assert.deepEqual(updates[1], ['tabs.update', 7, { active: true }]);
  assert.match(updates[2][2].url, /page=3/u);
  assert.equal(
    worker.records.some(([, , body]) => body?.type === 'pagination_page_jump'),
    false,
  );
});


test('page-jump route retains exact page-one evidence without enabling URL fallback', async () => {
  const worker = await loadPageJumpWorker();
  worker.portMessage.listeners[0](task({ pagination_enabled: true }));
  await settle();

  const config = await invoke(
    worker.runtimeMessage.listeners[0],
    { type: 'projection_config' },
    jdSender(),
  );
  assert.equal(config.pagination_route, 'page_jump');

  await invoke(
    worker.runtimeMessage.listeners[0],
    projection({ has_next_page: false, items: jdItems(30, 100000) }),
    jdSender(),
  );
  await settle();

  const session = worker.sessionValues.get('searching-at-scale-pagination-session');
  assert.equal(session.pagination_route, 'page_jump');
  assert.equal(session.allow_page_jump, true);
  assert.equal(session.allow_sequential_fallback, false);
  assert.equal(worker.records.some(([name, tabId]) => (
    name === 'tabs.remove' && tabId === 7
  )), false);
});


test('page-jump route sends only its isolated same-tab message for page two', async () => {
  const worker = await loadPageJumpWorker({ paginationResponse: { ok: true } });
  await verifyPageJumpPageOne(worker);

  await requestPageTwo(worker);

  assert.deepEqual(
    worker.records.filter(([name]) => name === 'tabs.sendMessage'),
    [['tabs.sendMessage', 7, {
      type: 'pagination_page_jump', expected_page_number: 2,
    }]],
  );
  assert.equal(worker.records.filter(([name]) => name === 'tabs.update').length, 1);
});


test('page-jump control rejection stops without URL or alternate-route fallback', async () => {
  const worker = await loadPageJumpWorker({
    paginationResponse: { ok: false, category: 'pagination_page_jump_unavailable' },
  });
  await verifyPageJumpPageOne(worker);

  await requestPageTwo(worker);

  assert.equal(worker.posted.at(-1).category, 'pagination_navigation_unavailable');
  assert.equal(worker.posted.at(-1).retryable, false);
  assert.equal(worker.records.filter(([name]) => name === 'tabs.update').length, 1);
  assert.equal(worker.records.filter(([, , body]) => (
    body?.type === 'pagination_next' || body?.type === 'pagination_numbered_link'
  )).length, 0);
});


for (const [name, failedProjection] of [
  ['zero cards', {
    observed_page_number: 2, page_state: 'page_structure_changed', items: [],
    diagnostics: { observed_page_number: 2 },
  }],
  ['unchanged SKU digest', {
    observed_page_number: 2, items: jdItems(30, 100000),
    diagnostics: { observed_page_number: 2 },
  }],
  ['non-ready structure', {
    observed_page_number: 2, page_state: 'page_structure_changed',
    items: jdItems(1, 200000), diagnostics: { observed_page_number: 2 },
  }],
]) {
  test(`page-jump route fails closed on ${name} without recovery`, async () => {
    const worker = await loadPageJumpWorker({ paginationResponse: { ok: true } });
    await verifyPageJumpPageOne(worker);
    await requestPageTwo(worker);

    await invoke(
      worker.runtimeMessage.listeners[0],
      projection(failedProjection),
      jdSender(),
    );
    await settle();

    assert.equal(worker.posted.at(-1).category, 'pagination_navigation_unavailable');
    assert.equal(worker.posted.at(-1).retryable, false);
    assert.equal(worker.sessionValues.has('searching-at-scale-pagination-session'), false);
    assert.equal(worker.records.some(([name]) => name === 'tabs.reload'), false);
    assert.equal(worker.records.filter(([, , body]) => (
      body?.type === 'pagination_recover'
    )).length, 0);
  });
}


test('page-jump route accepts page two only when SKU digest changes', async () => {
  const worker = await loadPageJumpWorker({ paginationResponse: { ok: true } });
  await verifyPageJumpPageOne(worker);
  await requestPageTwo(worker);

  await invoke(
    worker.runtimeMessage.listeners[0],
    projection({
      observed_page_number: 2,
      has_next_page: false,
      items: jdItems(30, 200000),
      diagnostics: { observed_page_number: 2 },
    }),
    jdSender(),
  );
  await settle();

  assert.equal(worker.posted.at(-1).type, 'result');
  assert.equal(worker.posted.at(-1).payload.observed_page_number, 2);
  assert.equal(worker.posted.at(-1).payload.sku_digest.startsWith('200000'), true);
});


// 2026-08-12: human-shaped JD flow (`human_flow`). The user's real Edge serves
// search results to manual navigation but risk-pages direct-URL searches from
// about:blank on the same IP/browser/cookies, so the differing variable is the
// navigation shape. These tests cover the homepage-first start, the from=home
// URL, and the click-based page flips verified by SKU-digest change.

function humanFlowWorker(options = {}) {
  return loadWorker(
    new Map(),
    new Map([
      ['searching-at-scale-jd-pagination-route', 'human_flow'],
    ]),
    options,
  );
}


// human_flow start navigates to the homepage, waits for it to settle
// (~2.5s in production code) and only then navigates to the search URL. The
// shared settle() helper is microtask-only, so human-flow assertions that
// depend on the completed navigation must wait out the settle window first.
const HUMAN_FLOW_SETTLE_MS = 2600;
async function settleHumanFlow() {
  await new Promise((resolve) => setTimeout(resolve, HUMAN_FLOW_SETTLE_MS));
  await settle();
}


test('human-flow start visits the JD homepage first, then the from=home search URL', async () => {
  const worker = await humanFlowWorker();
  worker.portMessage.listeners[0](task({ pagination_enabled: true }));
  await settleHumanFlow();

  const creates = worker.records.filter(([name]) => name === 'tabs.create');
  assert.equal(creates.length, 1);
  assert.deepEqual(creates[0][1], { url: 'about:blank', active: false });

  const updates = worker.records.filter(([name]) => name === 'tabs.update');
  assert.equal(updates.length, 2);
  assert.deepEqual(updates[0], ['tabs.update', 7, { url: 'https://www.jd.com/' }]);
  assert.equal(updates[1][0], 'tabs.update');
  assert.equal(updates[1][1], 7);
  const searchUrl = new URL(updates[1][2].url);
  assert.equal(searchUrl.hostname, 'search.jd.com');
  assert.equal(searchUrl.pathname, '/Search');
  assert.equal(searchUrl.searchParams.get('keyword'), '小米15');
  assert.equal(searchUrl.searchParams.get('from'), 'home');
  assert.equal(searchUrl.searchParams.has('page'), false);
});


test('human-flow route retains a verified page-one session with the human-flow flag', async () => {
  const worker = await humanFlowWorker();
  worker.portMessage.listeners[0](task({ pagination_enabled: true }));
  await settle();
  await invoke(
    worker.runtimeMessage.listeners[0],
    projection({ has_next_page: false, items: jdItems(1, 100123) }),
    jdSender(),
  );
  await settle();

  const session = worker.sessionValues.get('searching-at-scale-pagination-session');
  assert.equal(session.pagination_route, 'human_flow');
  assert.equal(session.allow_human_flow, true);
  assert.equal(session.verified_page_number, 1);
  assert.equal(worker.records.some(([name, tabId]) => name === 'tabs.remove' && tabId === 7), false);
});


test('human-flow page two flips by clicking the next control, not by rewriting the URL', async () => {
  const worker = await humanFlowWorker();
  await verifyPageOne(worker, { has_next_page: false, items: jdItems(1, 100123) });
  await settleHumanFlow();

  await requestPageTwo(worker);

  assert.deepEqual(
    worker.records.filter(([name]) => name === 'tabs.sendMessage'),
    [['tabs.sendMessage', 7, { type: 'pagination_next', expected_page_number: 2 }]],
  );
  const updates = worker.records.filter(([name]) => name === 'tabs.update');
  assert.equal(updates.length, 2, 'start navigation only; page two is a same-tab click');
  assert.equal(
    worker.records.filter(([, , body]) => body?.type === 'pagination_page_jump').length,
    0,
  );
});


test('human-flow page two fails closed when the SKU digest does not change', async () => {
  const worker = await humanFlowWorker();
  await verifyPageOne(worker, { has_next_page: false, items: jdItems(1, 100123) });

  await requestPageTwo(worker);
  await invoke(
    worker.runtimeMessage.listeners[0],
    projection({
      observed_page_number: 2,
      has_next_page: false,
      items: jdItems(1, 100123),
      diagnostics: { observed_page_number: 2 },
    }),
    jdSender(),
  );
  await settle();

  assert.equal(worker.posted.at(-1).category, 'pagination_navigation_unavailable');
  assert.equal(worker.posted.at(-1).retryable, false);
  assert.equal(worker.sessionValues.has('searching-at-scale-pagination-session'), false);
  assert.equal(worker.records.some(([name]) => name === 'tabs.reload'), false);
});


test('human-flow page two is accepted when the SKU digest changes', async () => {
  const worker = await humanFlowWorker();
  await verifyPageOne(worker, { has_next_page: false, items: jdItems(1, 100123) });

  await requestPageTwo(worker);
  await invoke(
    worker.runtimeMessage.listeners[0],
    projection({
      observed_page_number: 2,
      has_next_page: false,
      items: jdItems(1, 200123),
      diagnostics: { observed_page_number: 2 },
    }),
    jdSender(),
  );
  await settle();

  assert.equal(worker.posted.at(-1).type, 'result');
  assert.equal(worker.posted.at(-1).payload.observed_page_number, 2);
  assert.equal(worker.posted.at(-1).payload.sku_digest, '200123');
  assert.equal(worker.records.some(([name, tabId]) => name === 'tabs.remove' && tabId === 7), false);
});
