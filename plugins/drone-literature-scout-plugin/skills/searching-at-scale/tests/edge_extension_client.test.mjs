import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import test from 'node:test';

import {
  DEFAULT_PIPE_PATH,
  EdgeExtensionError,
  buildBrokerTask,
  decodeFrame,
  encodeFrame,
  probeBrokerPipe,
  runEdgeCursor,
  runWorkerSession,
  validateBrokerEnvelope,
} from '../scripts/edge_extension_client.mjs';


test('pipe preflight connects and closes without writing a task', async () => {
  class FakeSocket extends EventEmitter {
    constructor() {
      super();
      this.destroyedByProbe = false;
      this.writes = [];
    }
    destroy() { this.destroyedByProbe = true; }
    write(value) { this.writes.push(value); }
  }
  const socket = new FakeSocket();
  const promise = probeBrokerPipe({
    pipePath: String.raw`\\.\pipe\test`,
    timeoutMs: 50,
    connector: () => socket,
  });
  queueMicrotask(() => socket.emit('connect'));

  assert.deepEqual(await promise, { ok: true, pipe: 'test' });
  assert.equal(socket.destroyedByProbe, true);
  assert.deepEqual(socket.writes, []);
});


test('pipe preflight classifies an unavailable broker', async () => {
  class FakeSocket extends EventEmitter {
    destroy() {}
  }
  const socket = new FakeSocket();
  const promise = probeBrokerPipe({ timeoutMs: 50, connector: () => socket });
  queueMicrotask(() => socket.emit('error', new Error('ENOENT')));

  await assert.rejects(
    promise,
    (error) => error instanceof EdgeExtensionError
      && error.category === 'edge_background_bridge_unavailable',
  );
});


const TASK_ID = '0123456789abcdef0123456789abcdef';
const CONFIG = {
  platform: 'jd',
  query: '手机壳',
  query_family: '手机壳:default',
  cursor: { cursor_id: 'jd:abc', ordinal: 0, page_number: 1 },
  user_data_dir: 'C:\\legacy\\edge-profile',
  deadline_seconds: 30,
  max_items: 100,
  session_action: 'start',
  pagination_enabled: false,
};


function resultEnvelope(items = []) {
  return {
    type: 'result',
    protocol_version: 3,
    task_id: TASK_ID,
    payload: {
      projection_schema_version: 4,
      capabilities: [
        'stable_card_fields_v2',
        'verified_pagination_v1',
        'resilient_pagination_v1',
      ],
      platform: 'jd',
      page_state: 'ready',
      source_url: 'https://search.jd.com/Search',
      query_family: '手机壳:default',
      cursor: { cursor_id: 'jd:abc', page_number: 1, status: items.length ? 'advanced' : 'exhausted' },
      observed_page_number: 1,
      pagination_state: 'pagination_unverified',
      has_next_page: false,
      sku_digest: items.map((item) => item.product_id).sort().join(',') || 'none',
      diagnostics: {
        document_ready_state: 'complete',
        data_sku_node_count: items.length,
        candidate_anchor_count: items.length,
        valid_item_count: items.length,
        collection_elapsed_ms: 20000,
        stable_rounds: 40,
        observed_page_number: 1,
        recovery_stage: 'initial',
        recovery_attempt: 0,
        source_path: '/Search',
      },
      items,
    },
  };
}


test('stale extension projection requires a reload instead of generic invalid data', () => {
  const brokerTask = buildBrokerTask(CONFIG, TASK_ID);
  const stale = resultEnvelope();
  delete stale.payload.projection_schema_version;
  delete stale.payload.capabilities;

  assert.throws(
    () => validateBrokerEnvelope(brokerTask, stale),
    (error) => error instanceof EdgeExtensionError
      && error.category === 'edge_extension_reload_required'
      && error.retryable === false,
  );
});


test('broker task is versioned, exact, and omits legacy profile state', () => {
  const task = buildBrokerTask(CONFIG, TASK_ID);

  assert.deepEqual(task, {
    type: 'task',
    protocol_version: 3,
    operation: 'search',
    task_id: TASK_ID,
    platform: 'jd',
    query: '手机壳',
    query_family: '手机壳:default',
    cursor: { cursor_id: 'jd:abc', ordinal: 0, page_number: 1 },
    deadline_seconds: 30,
    max_items: 100,
    session_action: 'start',
    pagination_enabled: false,
    pagination_route: null,
  });
  assert.equal(Object.hasOwn(task, 'user_data_dir'), false);
});


test('SAT_JD_PAGINATION_ROUTE env override flows into the broker task', () => {
  process.env.SAT_JD_PAGINATION_ROUTE = 'experimental_url';
  try {
    const task = buildBrokerTask(CONFIG, TASK_ID);
    assert.equal(task.pagination_route, 'experimental_url');
  } finally {
    delete process.env.SAT_JD_PAGINATION_ROUTE;
  }
});


test('length-prefixed JSON framing rejects trailing and oversized data', () => {
  const task = buildBrokerTask(CONFIG, TASK_ID);
  const frame = encodeFrame(task);

  assert.equal(frame.readUInt32LE(0), frame.length - 4);
  assert.deepEqual(decodeFrame(frame), task);
  assert.throws(() => decodeFrame(Buffer.concat([frame, Buffer.from([0])])), /framing/u);
  const oversized = Buffer.alloc(4);
  oversized.writeUInt32LE(512 * 1024 + 1);
  assert.throws(() => decodeFrame(oversized), /limit/u);
});


test('broker result becomes the existing bounded marketplace batch', () => {
  const item = {
    product_id: '100123',
    title: '透明手机壳',
    url: 'https://item.jd.com/100123.html',
    price: null,
    shop: null,
    commit: null,
    good_rate: null,
    promo: null,
    stock: null,
    image: null,
  };
  const task = buildBrokerTask(CONFIG, TASK_ID);

  assert.deepEqual(validateBrokerEnvelope(task, resultEnvelope([item])), {
    projection_schema_version: 4,
    capabilities: [
      'stable_card_fields_v2',
      'verified_pagination_v1',
      'resilient_pagination_v1',
    ],
    platform: 'jd',
    page_state: 'ready',
    source_url: 'https://search.jd.com/Search',
    query_family: '手机壳:default',
    cursor: { cursor_id: 'jd:abc', page_number: 1, status: 'advanced' },
    observed_page_number: 1,
    pagination_state: 'pagination_unverified',
    has_next_page: false,
    sku_digest: '100123',
    diagnostics: {
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
    },
    items: [item],
  });
});


test('result validation rejects mismatched IDs, unknown keys, and foreign item URLs', () => {
  const task = buildBrokerTask(CONFIG, TASK_ID);
  const base = resultEnvelope();
  const invalid = [
    { ...base, task_id: 'fedcba9876543210fedcba9876543210' },
    { ...base, cookie: 'secret' },
    { ...base, payload: { ...base.payload, source_url: 'https://search.jd.com/Search?keyword=secret' } },
    { ...base, payload: { ...base.payload, source_url: 'https://account:secret@search.jd.com/Search' } },
    { ...base, payload: { ...base.payload, source_url: 'https://search.jd.com/account/secret' } },
    { ...base, payload: { ...base.payload, source_url: 'https://evil.example/Search' } },
    {
      ...base,
      payload: {
        ...base.payload,
        items: [{ product_id: '1', title: 'x', url: 'https://evil.example/1' }],
      },
    },
  ];

  for (const envelope of invalid) {
    assert.throws(
      () => validateBrokerEnvelope(task, envelope),
      (error) => error instanceof EdgeExtensionError
        && error.category === 'edge_extension_projection_invalid',
    );
  }
});


test('result validation accepts only the exact privacy-safe diagnostics schema', () => {
  const task = buildBrokerTask(CONFIG, TASK_ID);
  const base = resultEnvelope();
  const withoutStage = structuredClone(base);
  delete withoutStage.payload.diagnostics.recovery_stage;
  const invalidDiagnostics = [
    { ...base.payload.diagnostics, html: '<main>secret</main>' },
    { ...base.payload.diagnostics, cookie: 'session=secret' },
    { ...base.payload.diagnostics, text: 'page body' },
    { ...base.payload.diagnostics, source_path: '/search?keyword=secret' },
    { ...base.payload.diagnostics, data_sku_node_count: -1 },
    { ...base.payload.diagnostics, collection_elapsed_ms: -1 },
    { ...base.payload.diagnostics, observed_page_number: 513 },
    { ...base.payload.diagnostics, recovery_stage: 'retry' },
    { ...base.payload.diagnostics, recovery_attempt: 3 },
  ];

  assert.throws(
    () => validateBrokerEnvelope(task, withoutStage),
    (error) => error instanceof EdgeExtensionError
      && error.category === 'edge_extension_projection_invalid',
  );
  for (const diagnostics of invalidDiagnostics) {
    assert.throws(
      () => validateBrokerEnvelope(task, {
        ...base,
        payload: { ...base.payload, diagnostics },
      }),
      (error) => error instanceof EdgeExtensionError
        && error.category === 'edge_extension_projection_invalid',
    );
  }
});


test('broker errors preserve stable category and retryability', () => {
  const task = buildBrokerTask(CONFIG, TASK_ID);
  const error = {
    type: 'error',
    protocol_version: 3,
    task_id: TASK_ID,
    category: 'edge_background_bridge_busy',
    retryable: true,
  };

  assert.throws(
    () => validateBrokerEnvelope(task, error),
    (value) => value instanceof EdgeExtensionError
      && value.category === 'edge_background_bridge_busy'
      && value.exitCode === 3,
  );
});


test('unknown operation is explicitly unsupported', () => {
  const task = { ...buildBrokerTask(CONFIG, TASK_ID), operation: 'detail' };

  assert.throws(
    () => validateBrokerEnvelope(task, resultEnvelope()),
    (error) => error instanceof EdgeExtensionError
      && error.category === 'edge_operation_unsupported',
  );
});


test('next-page task is fail-closed without explicit pagination enablement', () => {
  const unsafe = {
    ...CONFIG,
    cursor: { ...CONFIG.cursor, page_number: 2 },
    session_action: 'next',
  };

  assert.throws(
    () => buildBrokerTask(unsafe, TASK_ID),
    (error) => error instanceof EdgeExtensionError
      && error.category === 'edge_input_invalid',
  );
});


test('client accepts bounded recovery and rejects page 513 and unknown actions', () => {
  assert.equal(buildBrokerTask({
    ...CONFIG,
    cursor: { ...CONFIG.cursor, page_number: 512 },
    session_action: 'recover',
    pagination_enabled: true,
  }, TASK_ID).session_action, 'recover');

  for (const unsafe of [
    {
      ...CONFIG,
      cursor: { ...CONFIG.cursor, page_number: 513 },
      session_action: 'next',
      pagination_enabled: true,
    },
    { ...CONFIG, session_action: 'close', pagination_enabled: true },
  ]) {
    assert.throws(
      () => buildBrokerTask(unsafe, TASK_ID),
      (error) => error instanceof EdgeExtensionError
        && error.category === 'edge_input_invalid',
    );
  }
});


test('one cursor exchanges exactly one broker frame and never needs browser state', async () => {
  const calls = [];
  const batch = await runEdgeCursor(CONFIG, {
    randomTaskId: () => TASK_ID,
    exchange: async (task) => {
      calls.push(task);
      return resultEnvelope();
    },
  });

  assert.equal(calls.length, 1);
  assert.equal(calls[0].task_id, TASK_ID);
  assert.equal(batch.page_state, 'ready');
  assert.equal(batch.items.length, 0);
});


test('worker maps unavailable bridge without a foreground fallback', async () => {
  const lines = [JSON.stringify(CONFIG)];
  const output = [];

  await runWorkerSession(lines, {
    writeLine: (line) => output.push(JSON.parse(line)),
    exchange: async () => {
      throw new EdgeExtensionError(
        'edge_background_bridge_unavailable',
        3,
        'pipe unavailable',
        true,
      );
    },
  });

  assert.deepEqual(output, [{
    error: { category: 'edge_background_bridge_unavailable', retryable: true },
  }]);
});


test('default transport is a current-machine named pipe', () => {
  assert.equal(DEFAULT_PIPE_PATH, String.raw`\\.\pipe\codex.searching_at_scale.v1`);
});
