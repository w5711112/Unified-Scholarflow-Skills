import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { access, mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

import * as edgeCdp from '../scripts/edge_cdp_client.mjs';
import {
  CdpConnection,
  assertLoopbackEndpoint,
  buildProjectionExpression,
  buildSearchUrl,
  collectMarketplaceItems,
  parseActivePort,
  runEdgeCursor,
} from '../scripts/edge_cdp_client.mjs';


class FakeWebSocket extends EventTarget {
  constructor(reply) {
    super();
    this.reply = reply;
    this.sent = [];
    this.readyState = 0;
    queueMicrotask(() => {
      this.readyState = 1;
      this.dispatchEvent(new Event('open'));
    });
  }

  send(raw) {
    const message = JSON.parse(raw);
    this.sent.push(message);
    const result = this.reply(message);
    if (result !== undefined) {
      queueMicrotask(() => this.dispatchEvent(new MessageEvent('message', {
        data: JSON.stringify({ id: message.id, result }),
      })));
    }
  }

  close() {
    this.readyState = 3;
    this.dispatchEvent(new Event('close'));
  }
}


test('parseActivePort accepts a numeric loopback port and browser path', () => {
  assert.deepEqual(
    parseActivePort('54321\n/devtools/browser/abc-123\n'),
    {
      port: 54321,
      browserPath: '/devtools/browser/abc-123',
      endpoint: 'ws://127.0.0.1:54321/devtools/browser/abc-123',
    },
  );
  assert.throws(() => parseActivePort('9222\nhttp://evil.example/x\n'), /edge_active_port_invalid/);
  assert.throws(() => parseActivePort('0\n/devtools/browser/a\n'), /edge_active_port_invalid/);
});


test('assertLoopbackEndpoint rejects non-loopback and non-WebSocket endpoints', () => {
  assert.equal(
    assertLoopbackEndpoint('ws://127.0.0.1:9222/devtools/browser/a').hostname,
    '127.0.0.1',
  );
  assert.throws(
    () => assertLoopbackEndpoint('ws://192.168.1.4:9222/devtools/browser/a'),
    /edge_endpoint_not_loopback/,
  );
  assert.throws(
    () => assertLoopbackEndpoint('https://127.0.0.1:9222/devtools/browser/a'),
    /edge_endpoint_not_loopback/,
  );
});


test('default Edge transport completes a permission-compatible WebSocket handshake', async () => {
  let acceptedSocket = null;
  const server = createServer();
  server.on('upgrade', (request, socket) => {
    const compatible = (
      request.headers['user-agent'] === 'Puppeteer 25.4.0'
      && request.headers.origin === undefined
      && request.headers['sec-websocket-extensions'] === undefined
    );
    if (!compatible) {
      socket.end('HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n');
      return;
    }
    const key = request.headers['sec-websocket-key'];
    const accept = createHash('sha1')
      .update(`${key}258EAFA5-E914-47DA-95CA-C5AB0DC85B11`)
      .digest('base64');
    acceptedSocket = socket;
    socket.write([
      'HTTP/1.1 101 Switching Protocols',
      'Upgrade: websocket',
      'Connection: Upgrade',
      `Sec-WebSocket-Accept: ${accept}`,
      '',
      '',
    ].join('\r\n'));
  });
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  try {
    const address = server.address();
    assert.notEqual(address, null);
    const client = edgeCdp.createEdgeWebSocket(
      `ws://127.0.0.1:${address.port}/devtools/browser/test`,
    );
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('handshake timed out')), 1000);
      client.addEventListener('open', () => {
        clearTimeout(timer);
        resolve();
      }, { once: true });
      client.addEventListener('error', () => {
        clearTimeout(timer);
        reject(new Error('handshake failed'));
      }, { once: true });
    });
    assert.equal(client.readyState, 1);
    client.close();
  } finally {
    acceptedSocket?.destroy();
    await new Promise((resolve) => server.close(resolve));
  }
});


test('Edge transport reports a stable category when the ws runtime is unavailable', () => {
  assert.throws(
    () => edgeCdp.createEdgeWebSocket(
      'ws://127.0.0.1:9222/devtools/browser/test',
      null,
    ),
    /edge_transport_unavailable/u,
  );
});


test('buildSearchUrl emits only approved JD and Taobao search shapes', () => {
  assert.equal(
    buildSearchUrl('jd', '手机壳 透明', 1),
    'https://search.jd.com/Search?keyword=%E6%89%8B%E6%9C%BA%E5%A3%B3%20%E9%80%8F%E6%98%8E&enc=utf-8&page=1',
  );
  assert.equal(
    buildSearchUrl('jd', '手机壳', 2),
    'https://search.jd.com/Search?keyword=%E6%89%8B%E6%9C%BA%E5%A3%B3&enc=utf-8&page=3',
  );
  assert.equal(
    buildSearchUrl('taobao', '手机壳', 2),
    'https://s.taobao.com/search?q=%E6%89%8B%E6%9C%BA%E5%A3%B3&page=1',
  );
  assert.throws(() => buildSearchUrl('pdd', '手机壳', 1), /edge_platform_invalid/);
});


test('projection waits for the navigated document and triggers lazy cards', () => {
  const expression = buildProjectionExpression('jd', 1000);
  assert.match(expression, /document\.readyState/u);
  assert.match(expression, /window\.scrollTo/u);
  assert.match(expression, /await wait/u);
});


test('collectMarketplaceItems canonicalizes and deduplicates strict JD identities', () => {
  const result = collectMarketplaceItems('jd', [
    { href: 'https://item.jd.com/100123456789.html?utm_source=x', title: ' 透明壳 ' },
    { href: 'https://item.jd.com/100123456789.html', title: '重复标题' },
    { href: 'https://example.com/100123456789.html', title: '站外' },
  ], 1000);
  assert.deepEqual(result, [{
    product_id: '100123456789',
    title: '透明壳',
    url: 'https://item.jd.com/100123456789.html',
  }]);
});


test('collectMarketplaceItems accepts only verified Taobao and Tmall item URLs', () => {
  const result = collectMarketplaceItems('taobao', [
    { href: 'https://item.taobao.com/item.htm?id=123456&spm=x', title: '淘宝商品' },
    { href: 'https://detail.tmall.com/item.htm?id=987654', title: '天猫商品' },
    { href: 'https://s.taobao.com/item.htm?id=111', title: '搜索页伪链接' },
  ], 1000);
  assert.deepEqual(result, [
    {
      product_id: '123456',
      title: '淘宝商品',
      url: 'https://item.taobao.com/item.htm?id=123456',
    },
    {
      product_id: '987654',
      title: '天猫商品',
      url: 'https://detail.tmall.com/item.htm?id=987654',
    },
  ]);
});


test('CdpConnection rejects forbidden methods before sending', async () => {
  const socket = new FakeWebSocket(() => ({}));
  const connection = new CdpConnection('ws://127.0.0.1:9222/devtools/browser/a', {
    socketFactory: () => socket,
    timeoutMs: 100,
  });
  await connection.connect();
  await assert.rejects(
    connection.send('Network.getAllCookies', {}),
    /edge_cdp_method_forbidden/,
  );
  assert.equal(socket.sent.length, 0);
  connection.close();
});


test('CdpConnection correlates responses without exposing protocol frames', async () => {
  const socket = new FakeWebSocket((message) => ({ echoed: message.method }));
  const connection = new CdpConnection('ws://127.0.0.1:9222/devtools/browser/a', {
    socketFactory: () => socket,
    timeoutMs: 100,
  });
  await connection.connect();
  assert.deepEqual(
    await connection.send('Runtime.enable', {}, 'session-1'),
    { echoed: 'Runtime.enable' },
  );
  assert.equal(socket.sent[0].sessionId, 'session-1');
  connection.close();
});


function fakeCdp(calls, {
  projection,
  failAfterCreate = false,
  evaluationFailures = 0,
} = {}) {
  let remainingEvaluationFailures = evaluationFailures;
  return {
    async connect() {},
    async send(method, params, sessionId) {
      calls.push({ method, params, sessionId });
      if (method === 'Target.createTarget') {
        return { targetId: 'owned-target' };
      }
      if (failAfterCreate && method === 'Target.attachToTarget') {
        throw new Error('controlled failure');
      }
      if (method === 'Target.attachToTarget') {
        return { sessionId: 'owned-session' };
      }
      if (method === 'Runtime.evaluate') {
        if (remainingEvaluationFailures > 0) {
          remainingEvaluationFailures -= 1;
          throw new edgeCdp.EdgeCdpError(
            'edge_cdp_command_failed',
            5,
            'CDP command failed',
          );
        }
        return { result: { value: projection } };
      }
      return {};
    },
    close() { calls.push({ method: 'WebSocket.close' }); },
  };
}


const CONFIG = {
  platform: 'jd',
  query: '手机壳',
  query_family: '手机壳:default',
  cursor: { cursor_id: 'jd:abc', ordinal: 0, page_number: 1 },
  user_data_dir: '',
  deadline_seconds: 600,
  max_items: 1000,
};


test('runEdgeCursor creates a background target and closes it after failure', async () => {
  const calls = [];
  await assert.rejects(
    runEdgeCursor(CONFIG, { connection: fakeCdp(calls, { failAfterCreate: true }) }),
    /controlled failure/,
  );
  assert.deepEqual(calls[0], {
    method: 'Target.createTarget',
    params: { url: 'about:blank', background: true, focus: false },
    sessionId: undefined,
  });
  assert.equal(calls.at(-2).method, 'Target.closeTarget');
  assert.equal(calls.at(-2).params.targetId, 'owned-target');
  assert.equal(calls.at(-1).method, 'WebSocket.close');
});


test('runEdgeCursor returns only the strict public projection batch', async () => {
  const calls = [];
  const batch = await runEdgeCursor(CONFIG, {
    connection: fakeCdp(calls, {
      projection: {
        page_state: 'ready',
        source_url: 'https://search.jd.com/Search?keyword=x',
        anchors: [
          { href: 'https://item.jd.com/100123456789.html', title: '透明壳' },
        ],
      },
    }),
  });
  assert.deepEqual(batch, {
    platform: 'jd',
    page_state: 'ready',
    source_url: 'https://search.jd.com/Search?keyword=x',
    query_family: '手机壳:default',
    cursor: { cursor_id: 'jd:abc', page_number: 1, status: 'advanced' },
    items: [{
      product_id: '100123456789',
      title: '透明壳',
      url: 'https://item.jd.com/100123456789.html',
    }],
  });
  assert.equal(JSON.stringify(batch).includes('cookie'), false);
});


test('runEdgeCursor retries projection when navigation invalidates evaluation', async () => {
  const calls = [];
  const batch = await runEdgeCursor(CONFIG, {
    connection: fakeCdp(calls, {
      evaluationFailures: 1,
      projection: {
        page_state: 'ready',
        source_url: 'https://search.jd.com/Search?keyword=x',
        anchors: [],
      },
    }),
    retryDelay: async () => {},
  });

  assert.equal(batch.page_state, 'ready');
  assert.equal(
    calls.filter((call) => call.method === 'Runtime.evaluate').length,
    2,
  );
});


test('worker session reuses one CDP connection for two cursor requests', async () => {
  const calls = [];
  let connectCount = 0;
  let closeCount = 0;
  const connection = {
    async connect() { connectCount += 1; },
    async send(method, params, sessionId) {
      calls.push({ method, params, sessionId });
      if (method === 'Target.createTarget') {
        return { targetId: `owned-target-${calls.length}` };
      }
      if (method === 'Target.attachToTarget') {
        return { sessionId: `owned-session-${calls.length}` };
      }
      if (method === 'Runtime.evaluate') {
        return {
          result: {
            value: {
              page_state: 'ready',
              source_url: 'https://search.jd.com/Search?keyword=x',
              anchors: [
                { href: 'https://item.jd.com/100123456789.html', title: '透明壳' },
              ],
            },
          },
        };
      }
      return {};
    },
    close() { closeCount += 1; },
  };
  async function* lines() {
    yield JSON.stringify(CONFIG);
    yield JSON.stringify({
      ...CONFIG,
      query: '防摔手机壳',
      cursor: { cursor_id: 'jd:def', ordinal: 1, page_number: 1 },
    });
  }
  const output = [];

  await edgeCdp.runWorkerSession(lines(), {
    connectionFactory: async () => connection,
    writeLine: (line) => output.push(JSON.parse(line)),
  });

  assert.equal(connectCount, 1);
  assert.equal(closeCount, 1);
  assert.equal(calls.filter((call) => call.method === 'Target.createTarget').length, 2);
  assert.equal(calls.filter((call) => call.method === 'Target.closeTarget').length, 2);
  assert.equal(output.length, 2);
  assert.equal(output.every((item) => item.page_state === 'ready'), true);
});


test('owned Edge launcher uses an isolated loopback profile and kills only its child', async () => {
  const tempRoot = await mkdtemp(path.join(os.tmpdir(), 'edge-owned-launch-'));
  const profile = path.join(tempRoot, 'edge-profile');
  const calls = [];
  const child = {
    exitCode: null,
    killed: false,
    kill() { this.killed = true; this.exitCode = 0; },
  };
  try {
    const owner = await edgeCdp.launchOwnedEdge(profile, {
      locateEdge: async () => 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
      spawnFactory: (executable, args, options) => {
        calls.push({ executable, args, options });
        return child;
      },
      waitForActivePort: async () => ({
        endpoint: 'ws://127.0.0.1:54321/devtools/browser/owned-test',
      }),
    });

    assert.equal(owner.endpoint, 'ws://127.0.0.1:54321/devtools/browser/owned-test');
    assert.equal(calls.length, 1);
    assert.equal(calls[0].args.includes(`--user-data-dir=${profile}`), true);
    assert.equal(calls[0].args.includes('--remote-debugging-port=0'), true);
    assert.equal(calls[0].args.includes('--remote-debugging-address=127.0.0.1'), true);
    assert.equal(calls[0].args.includes('--start-minimized'), true);
    assert.equal(calls[0].options.detached, false);
    owner.close();
    assert.equal(child.killed, true);
  } finally {
    await rm(tempRoot, { recursive: true, force: true });
  }
});


test('owned Edge launcher removes only a verified stale active-port file', async () => {
  const tempRoot = await mkdtemp(path.join(os.tmpdir(), 'edge-owned-stale-'));
  const profile = path.join(tempRoot, 'edge-profile');
  await mkdir(profile);
  await writeFile(
    path.join(profile, 'DevToolsActivePort'),
    '59195\n/devtools/browser/stale-test\n',
    'utf8',
  );
  const child = {
    exitCode: null,
    kill() { this.exitCode = 0; },
  };
  try {
    const owner = await edgeCdp.launchOwnedEdge(profile, {
      activePortInUse: async () => false,
      locateEdge: async () => 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
      spawnFactory: () => child,
      waitForActivePort: async () => ({
        endpoint: 'ws://127.0.0.1:54321/devtools/browser/restarted-test',
      }),
    });

    await assert.rejects(
      access(path.join(profile, 'DevToolsActivePort')),
      /ENOENT/,
    );
    owner.close();
  } finally {
    await rm(tempRoot, { recursive: true, force: true });
  }
});
