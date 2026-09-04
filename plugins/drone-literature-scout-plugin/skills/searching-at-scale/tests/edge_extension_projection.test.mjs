import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';


const TEST_DIR = path.dirname(fileURLToPath(import.meta.url));
const SKILL_DIR = path.dirname(TEST_DIR);
const EXTENSION_DIR = path.join(SKILL_DIR, 'edge-extension');


async function loadProjection() {
  const source = await readFile(path.join(EXTENSION_DIR, 'projection.js'), 'utf8');
  const context = { URL, URLSearchParams };
  context.globalThis = context;
  vm.runInNewContext(source, context, { filename: 'projection.js' });
  return context.SearchingAtScaleProjection;
}


test('manifest grants minimal search permissions and reserves optional detail origins', async () => {
  const manifest = JSON.parse(
    await readFile(path.join(EXTENSION_DIR, 'manifest.json'), 'utf8'),
  );

  assert.equal(manifest.manifest_version, 3);
  assert.equal(manifest.version, '2.3.1');
  assert.deepEqual(manifest.permissions, ['nativeMessaging', 'storage', 'alarms']);
  assert.deepEqual(
    manifest.host_permissions,
    [
      'https://search.jd.com/*',
      'https://s.taobao.com/*',
      'https://cfe.m.jd.com/privatedomain/risk_handler/*',
      'https://passport.jd.com/new/login.aspx*',
    ],
  );
  assert.deepEqual(manifest.optional_host_permissions, [
    'https://item.jd.com/*',
    'https://item.taobao.com/*',
    'https://detail.tmall.com/*',
    'https://detail.tmall.hk/*',
  ]);
  assert.equal(typeof manifest.key, 'string');
  assert.ok(manifest.key.length > 100);
  assert.deepEqual(manifest.background, {
    service_worker: 'service_worker.js',
  });
});


test('projection library no longer exposes bootstrap routing', async () => {
  const projection = await loadProjection();

  assert.equal(Object.hasOwn(projection, 'parseBootstrapFragment'), false);
});


test('public anchor projection canonicalizes and deduplicates JD products', async () => {
  const projection = await loadProjection();
  const result = projection.projectItems('jd', [
    { href: 'https://item.jd.com/100123.html?utm_source=x', title: ' 透明 手机壳 ' },
    { href: 'https://item.m.jd.com/product/100123.html', title: '重复标题' },
    { href: 'https://evil.example/100999.html', title: '越界' },
    { href: 'javascript:alert(1)', title: '脚本' },
    { href: 'https://item.jd.com/100456.html', title: '' },
  ], 10);

  assert.deepEqual(JSON.parse(JSON.stringify(result)), [
    {
      product_id: '100123',
      title: '透明 手机壳',
      url: 'https://item.jd.com/100123.html',
      price: null,
      shop: null,
      commit: null,
      good_rate: null,
      promo: null,
      stock: null,
      image: null,
    },
  ]);
});


test('public anchor projection supports Taobao and enforces the item limit', async () => {
  const projection = await loadProjection();
  const result = projection.projectItems('taobao', [
    { href: 'https://item.taobao.com/item.htm?id=42&spm=x', title: 'A' },
    { href: 'https://detail.tmall.com/item.htm?id=43', title: 'B' },
  ], 1);

  assert.deepEqual(JSON.parse(JSON.stringify(result)), [
    {
      product_id: '42',
      title: 'A',
      url: 'https://item.taobao.com/item.htm?id=42',
      price: null,
      shop: null,
      commit: null,
      good_rate: null,
      promo: null,
      stock: null,
      image: null,
    },
  ]);
  assert.throws(() => projection.projectItems('jd', [], 0));
  assert.throws(() => projection.projectItems('unknown', [], 1));
});


test('projection exposes the stable card-field schema capability', async () => {
  const projection = await loadProjection();

  assert.equal(projection.PROJECTION_SCHEMA_VERSION, 4);
  assert.deepEqual(
    JSON.parse(JSON.stringify(projection.PROJECTION_CAPABILITIES)),
    [
      'stable_card_fields_v2',
      'verified_pagination_v1',
      'resilient_pagination_v1',
    ],
  );
});


test('lazy collection continues until bounded stability or item limit', async () => {
  const projection = await loadProjection();

  assert.equal(projection.shouldContinueCollection({
    itemCount: 20, stableRounds: 0, elapsedMs: 1000, maxItems: 100,
  }), true);
  assert.equal(projection.shouldContinueCollection({
    itemCount: 20, stableRounds: 2, elapsedMs: 1000, maxItems: 100,
  }), false);
  assert.equal(projection.shouldContinueCollection({
    itemCount: 100, stableRounds: 0, elapsedMs: 1000, maxItems: 100,
  }), false);
  assert.equal(projection.shouldContinueCollection({
    itemCount: 20, stableRounds: 0, elapsedMs: 20000, maxItems: 100,
  }), false);
  assert.equal(projection.shouldContinueCollection({
    itemCount: 0, stableRounds: 20, elapsedMs: 9000, maxItems: 100,
  }), true);
  assert.equal(projection.shouldContinueCollection({
    itemCount: 0, stableRounds: 20, elapsedMs: 10000, maxItems: 100,
  }), false);
});


test('JD pagination waits for the public next control after the first 30 cards', async () => {
  const projection = await loadProjection();

  assert.equal(projection.shouldContinueJdPaginationSettlement({
    paginationEnabled: true,
    platform: 'jd',
    itemCount: 30,
    hasNextPage: false,
    elapsedMs: 2500,
  }), true);
  assert.equal(projection.shouldContinueJdPaginationSettlement({
    paginationEnabled: true,
    platform: 'jd',
    itemCount: 30,
    hasNextPage: true,
    elapsedMs: 2500,
  }), false);
  assert.equal(projection.shouldContinueJdPaginationSettlement({
    paginationEnabled: true,
    platform: 'jd',
    itemCount: 30,
    hasNextPage: false,
    elapsedMs: 8000,
  }), false);
  assert.equal(projection.shouldContinueJdPaginationSettlement({
    paginationEnabled: false,
    platform: 'jd',
    itemCount: 30,
    hasNextPage: false,
    elapsedMs: 2500,
  }), false);
});


test('SKU digest is stable across DOM order and explicit for empty pages', async () => {
  const projection = await loadProjection();

  assert.equal(projection.skuDigest([{ product_id: '2' }, { product_id: '1' }]), '1,2');
  assert.equal(projection.skuDigest([{ product_id: '1' }, { product_id: '2' }]), '1,2');
  assert.equal(projection.skuDigest([]), 'none');
});


test('page-state classification ignores the normal JD login header and prioritizes blockers', async () => {
  const projection = await loadProjection();

  assert.equal(projection.classifyPageState('你好，请登录', 12), 'ready');
  assert.equal(projection.classifyPageState('你好，请登录', 0), 'page_structure_changed');
  assert.equal(projection.classifyPageState('账号登录 扫码登录', 0), 'authentication_required');
  assert.equal(projection.classifyPageState('访问过于频繁，请稍后再试，请登录', 0), 'rate_limited');
  assert.equal(
    projection.classifyPageState('抱歉由于访问频繁导致无法搜索，请稍后再试！', 0),
    'rate_limited',
  );
  assert.equal(
    projection.classifyPageState('内容太火爆了，请稍后再试！', 0),
    'rate_limited',
  );
  assert.equal(
    projection.classifyPageState('当前页面异常 请刷新或切换账户试试', 0),
    'rate_limited',
  );
  assert.equal(projection.classifyPageState('活动稍后再试', 0), 'page_structure_changed');
  assert.equal(projection.classifyPageState('请完成安全验证，拖动滑块', 0), 'captcha_required');
  assert.equal(projection.classifyPageState('没有找到相关商品', 0), 'ready');
});


test('JD logical pagination decodes the public odd page parameter', async () => {
  const projection = await loadProjection();

  assert.equal(
    projection.jdLogicalPage('https://search.jd.com/Search?keyword=x&page=1'),
    1,
  );
  assert.equal(
    projection.jdLogicalPage('https://search.jd.com/Search?keyword=x&page=3'),
    2,
  );
  assert.equal(
    projection.jdLogicalPage('https://search.jd.com/Search?keyword=x&page=19'),
    10,
  );
  assert.equal(
    projection.jdLogicalPage('https://search.jd.com/Search?keyword=x'),
    1,
  );
  assert.throws(
    () => projection.jdLogicalPage('https://evil.example/Search?page=3'),
    /JD search URL/u,
  );
});


test('JD next-page navigation accepts only the exact public sequential link', async () => {
  const projection = await loadProjection();
  const current = 'https://search.jd.com/Search?keyword=x&page=1';

  assert.equal(
    projection.jdNextPageHref(
      current,
      'https://search.jd.com/Search?keyword=x&page=3&click=0',
      2,
    ),
    'https://search.jd.com/Search?keyword=x&page=3&click=0',
  );
  assert.throws(
    () => projection.jdNextPageHref(
      current,
      'https://search.jd.com/Search?keyword=x&page=5',
      2,
    ),
    /sequential JD page/u,
  );
  assert.throws(
    () => projection.jdNextPageHref(
      current,
      'https://evil.example/Search?keyword=x&page=3',
      2,
    ),
    /JD next-page URL/u,
  );
  assert.throws(
    () => projection.jdNextPageHref(
      current,
      'https://search.jd.com/Search?keyword=x&page=2',
      2,
    ),
    /JD search URL page/u,
  );
  assert.throws(
    () => projection.jdNextPageHref(
      'https://evil.example/Search?keyword=x&page=1',
      'https://search.jd.com/Search?keyword=x&page=3',
      2,
    ),
    /JD next-page URL/u,
  );
});


test('JD next-page activation permits only a verified URL or the public inert click href', async () => {
  const projection = await loadProjection();
  const current = 'https://search.jd.com/Search?keyword=x&page=1';

  assert.equal(
    projection.jdNextPageActivation(
      current,
      'https://search.jd.com/Search?keyword=x&page=3&click=0',
      2,
    ),
    'verified_url',
  );
  assert.equal(
    projection.jdNextPageActivation(current, 'javascript:;', 2),
    'public_click',
  );
  assert.equal(
    projection.jdNextPageActivation(current, 'javascript:void(0);', 2),
    'public_click',
  );
  assert.throws(
    () => projection.jdNextPageActivation(current, 'javascript:alert(1)', 2),
    /JD next-page activation/u,
  );
});


test('JD next-page activation accepts a DOM-tracked current page for human flow', async () => {
  const projection = await loadProjection();
  // human_flow keeps no page parameter in the URL, so URL-derived page math
  // stays at 1 and can never reach page 3. The domCurrentPage option replaces
  // it with the tracked logical page while preserving the legacy behavior when
  // the option is absent.
  const humanUrl = 'https://search.jd.com/Search?keyword=x&enc=utf-8&from=home';
  assert.equal(
    projection.jdNextPageActivation(humanUrl, 'javascript:;', 3, { domCurrentPage: 2 }),
    'public_click',
  );
  // A page-bearing href is accepted the same way once DOM tracking is active.
  assert.equal(
    projection.jdNextPageActivation(
      humanUrl,
      'https://search.jd.com/Search?keyword=x&enc=utf-8&from=home&page=5',
      3,
      { domCurrentPage: 2 },
    ),
    'public_click',
  );
  // Without the option the URL-derived math still rejects page three.
  assert.throws(
    () => projection.jdNextPageActivation(humanUrl, 'javascript:;', 3),
    /JD next-page activation/u,
  );
});


test('JD pagination requires the rendered SKU set to change', async () => {
  const projection = await loadProjection();

  assert.equal(projection.jdSkuSetChanged(['1', '2'], ['1', '2']), false);
  assert.equal(projection.jdSkuSetChanged(['1', '2'], ['2', '1']), false);
  assert.equal(projection.jdSkuSetChanged(['1', '2'], ['2', '3']), true);
  assert.equal(projection.jdSkuSetChanged([], ['1']), false);
  assert.equal(projection.jdSkuSetChanged(['1'], []), false);
});


test('content script collects lazy cards to bounded stability and sends page evidence', async () => {
  const source = await readFile(path.join(EXTENSION_DIR, 'content.js'), 'utf8');

  assert.match(source, /const itemDeadline = Date\.now\(\) \+ 20000/u);
  assert.match(source, /projection\.shouldContinueCollection/u);
  assert.match(source, /projection\.shouldContinueJdPaginationSettlement/u);
  assert.match(source, /collectCandidates\(\)\.slice\(0, maxItems \* 4\)/u);
  assert.match(source, /querySelectorAll\('\[data-sku\]'\)/u);
  assert.match(source, /https:\/\/item\.jd\.com\/\$\{productId\}\.html/u);
  assert.match(source, /querySelector\('\[title\]'\)/u);
  assert.match(source, /querySelector\('img\[alt\]'\)/u);
  assert.match(source, /const collectJdCardsFrom = \(root\)/u);
  assert.match(source, /async function collectProjection\(\{ recoveryStage, recoveryAttempt, logicalPage = null \}\)/u);
  assert.match(source, /type !== 'pagination_recover'/u);
  assert.match(source, /recoveryStage: 'reproject'/u);
  assert.match(source, /diagnostics/u);
  assert.match(source, /source_path: '\/Search'/u);
  assert.match(source, /observed_page_number/u);
  assert.match(source, /pagination_state/u);
  assert.match(source, /has_next_page/u);
  assert.match(source, /sku_digest/u);
  assert.match(source, /chrome\.runtime\.onMessage\.addListener/u);
  assert.match(source, /projection\.jdNextPageActivation/u);
  assert.match(source, /setTimeout\(\(\) => next\.click\(\), 0\)/u);
  assert.doesNotMatch(source, /accum-load/u);
  assert.doesNotMatch(source, /new DOMParser\(\)\.parseFromString\(html, 'text\/html'\)/u);
  assert.doesNotMatch(source, /paginationReached \? projection\.classifyPageState/u);
  assert.doesNotMatch(source, /__sat_diag_/u);
});


async function exerciseJdPublicNextControl(controlDescriptors) {
  const source = await readFile(path.join(EXTENSION_DIR, 'content.js'), 'utf8');
  const realProjection = await loadProjection();
  const clicks = [];
  const activations = [];
  let listener;

  class PublicControl {
    constructor(descriptor) {
      this.descriptor = descriptor;
      this.textContent = descriptor.label || '下一页';
      this.href = descriptor.href || '';
      this.classList = {
        contains: (name) => descriptor.className === name,
      };
    }

    getAttribute(name) {
      if (name === 'href') return this.descriptor.href || null;
      if (name === 'target') return this.descriptor.target || null;
      if (name === 'title' || name === 'aria-label') return this.descriptor.label || null;
      if (name === 'aria-disabled') return this.descriptor.disabled ? 'true' : null;
      return null;
    }

    matches(selector) {
      if (selector === '.disabled, [disabled], [aria-disabled="true"]') {
        return this.descriptor.disabled === true;
      }
      return false;
    }

    click() {
      clicks.push(this.descriptor.id);
    }
  }

  class HTMLAnchorElement extends PublicControl {}
  class HTMLButtonElement extends PublicControl {}

  const controls = controlDescriptors.map((descriptor) => (
    descriptor.kind === 'button'
      ? new HTMLButtonElement(descriptor)
      : new HTMLAnchorElement(descriptor)
  ));
  const selectorMatches = (node, selector) => {
    const { descriptor } = node;
    const tag = descriptor.kind === 'button' ? 'button' : 'a';
    if (selector === `#J_${descriptor.region}Page ${tag}`) return true;
    if (selector === `#J_${descriptor.region}Page ${tag}.${descriptor.className}`) return true;
    return selector === `${tag}.${descriptor.className}`;
  };
  const document = {
    readyState: 'complete',
    body: { innerText: '', scrollHeight: 0 },
    documentElement: { scrollHeight: 0 },
    querySelectorAll: (selector) => {
      if (selector === '[data-sku]') return [];
      const selectors = String(selector).split(',').map((value) => value.trim());
      return controls.filter((node) => selectors.some((value) => selectorMatches(node, value)));
    },
    querySelector: () => null,
  };
  const context = {
    URL,
    Set,
    Promise,
    Date,
    Math,
    Number,
    document,
    location: {
      hostname: 'search.jd.com',
      href: 'https://search.jd.com/Search?keyword=x&page=1',
    },
    HTMLAnchorElement,
    HTMLButtonElement,
    setTimeout: (callback) => {
      callback();
      return 1;
    },
    clearTimeout: () => {},
    scrollTo: () => {},
    SearchingAtScaleProjection: {
      PROJECTION_SCHEMA_VERSION: 4,
      PROJECTION_CAPABILITIES: [
        'stable_card_fields_v2',
        'verified_pagination_v1',
        'resilient_pagination_v1',
      ],
      shouldContinueCollection: () => false,
      shouldContinueJdPaginationSettlement: () => false,
      projectItems: () => [],
      classifyPageState: () => 'ready',
      jdLogicalPage: realProjection.jdLogicalPage,
      jdNextPageHref: realProjection.jdNextPageHref,
      jdNextPageActivation: (current, href, expectedPage) => {
        activations.push([current, href, expectedPage]);
        return realProjection.jdNextPageActivation(current, href, expectedPage);
      },
      skuDigest: () => 'none',
    },
    chrome: {
      runtime: {
        id: 'extension-id',
        onMessage: { addListener: (value) => { listener = value; } },
        sendMessage: async (message) => {
          if (message.type === 'projection_config') {
            return { ok: true, max_items: 30, pagination_enabled: true };
          }
          if (message.type === 'projection') return { ok: true };
          throw new Error('unexpected message');
        },
      },
    },
  };
  context.globalThis = context;
  context.window = context;
  vm.runInNewContext(source, context, { filename: 'content.js' });

  for (let index = 0; index < 100 && typeof listener !== 'function'; index += 1) {
    await new Promise((resolve) => setImmediate(resolve));
  }
  assert.equal(typeof listener, 'function');
  let response;
  assert.equal(listener(
    { type: 'pagination_next', expected_page_number: 2 },
    { id: 'extension-id' },
    (value) => { response = value; },
  ), false);
  return {
    activations,
    clicks,
    response: response === undefined ? undefined : JSON.parse(JSON.stringify(response)),
  };
}


test('public next navigation natively clicks one enabled top fp-next anchor', async () => {
  const result = await exerciseJdPublicNextControl([{
    id: 'top-next',
    region: 'top',
    kind: 'anchor',
    className: 'fp-next',
    href: 'https://search.jd.com/Search?keyword=x&page=3',
  }]);

  assert.deepEqual(result.response, { ok: true });
  assert.deepEqual(result.clicks, ['top-next']);
  assert.equal(result.activations.length, 1);
});


test('public next navigation natively clicks one enabled bottom pn-next anchor', async () => {
  const result = await exerciseJdPublicNextControl([{
    id: 'bottom-next',
    region: 'bottom',
    kind: 'anchor',
    className: 'pn-next',
    href: 'https://search.jd.com/Search?keyword=x&page=3',
  }]);

  assert.deepEqual(result.response, { ok: true });
  assert.deepEqual(result.clicks, ['bottom-next']);
  assert.equal(result.activations.length, 1);
});


test('matching top and bottom destinations deterministically click only the top control', async () => {
  const destination = 'https://search.jd.com/Search?keyword=x&page=3&click=0';
  const result = await exerciseJdPublicNextControl([
    {
      id: 'top-next',
      region: 'top',
      kind: 'anchor',
      className: 'fp-next',
      href: destination,
    },
    {
      id: 'bottom-next',
      region: 'bottom',
      kind: 'anchor',
      className: 'pn-next',
      href: destination,
    },
  ]);

  assert.deepEqual(result.response, { ok: true });
  assert.deepEqual(result.clicks, ['top-next']);
  assert.equal(result.activations.length, 1);
});


test('conflicting top and bottom destinations fail closed without clicking', async () => {
  const result = await exerciseJdPublicNextControl([
    {
      id: 'top-next',
      region: 'top',
      kind: 'anchor',
      className: 'fp-next',
      href: 'https://search.jd.com/Search?keyword=x&page=3',
    },
    {
      id: 'bottom-next',
      region: 'bottom',
      kind: 'anchor',
      className: 'pn-next',
      href: 'https://search.jd.com/Search?keyword=x&page=5',
    },
  ]);

  assert.deepEqual(result.response, {
    ok: false,
    category: 'pagination_navigation_unavailable',
  });
  assert.deepEqual(result.clicks, []);
  assert.deepEqual(result.activations, []);
});


test('two button controls with unprovable destinations fail closed without clicking', async () => {
  const result = await exerciseJdPublicNextControl([
    {
      id: 'top-button',
      region: 'top',
      kind: 'button',
      className: 'fp-next',
    },
    {
      id: 'bottom-button',
      region: 'bottom',
      kind: 'button',
      className: 'pn-next',
    },
  ]);

  assert.deepEqual(result.response, {
    ok: false,
    category: 'pagination_navigation_unavailable',
  });
  assert.deepEqual(result.clicks, []);
  assert.deepEqual(result.activations, []);
});


test('public next navigation supports one enabled pagination button equivalent', async () => {
  const result = await exerciseJdPublicNextControl([{
    id: 'top-button',
    region: 'top',
    kind: 'button',
    className: 'fp-next',
  }]);

  assert.deepEqual(result.response, { ok: true });
  assert.deepEqual(result.clicks, ['top-button']);
  assert.equal(result.activations.length, 1);
});


test('public next navigation rejects a disabled control without clicking', async () => {
  const result = await exerciseJdPublicNextControl([{
    id: 'disabled-next',
    region: 'bottom',
    kind: 'anchor',
    className: 'pn-next',
    href: 'https://search.jd.com/Search?keyword=x&page=3',
    disabled: true,
  }]);

  assert.deepEqual(result.response, {
    ok: false,
    category: 'pagination_navigation_unavailable',
  });
  assert.deepEqual(result.clicks, []);
  assert.deepEqual(result.activations, []);
});


test('public next navigation rejects ambiguous enabled controls without clicking', async () => {
  const result = await exerciseJdPublicNextControl([
    {
      id: 'bottom-next-a',
      region: 'bottom',
      kind: 'anchor',
      className: 'pn-next',
      href: 'https://search.jd.com/Search?keyword=x&page=3',
    },
    {
      id: 'bottom-next-b',
      region: 'bottom',
      kind: 'anchor',
      className: 'pn-next',
      href: 'https://search.jd.com/Search?keyword=x&page=3',
    },
  ]);

  assert.deepEqual(result.response, {
    ok: false,
    category: 'pagination_navigation_unavailable',
  });
  assert.deepEqual(result.clicks, []);
  assert.deepEqual(result.activations, []);
});


test('public next navigation rejects a missing control without clicking', async () => {
  const result = await exerciseJdPublicNextControl([]);

  assert.deepEqual(result.response, {
    ok: false,
    category: 'pagination_navigation_unavailable',
  });
  assert.deepEqual(result.clicks, []);
  assert.deepEqual(result.activations, []);
});


test('pagination recovery is serialized, survives one failure, and never navigates', async () => {
  const source = await readFile(path.join(EXTENSION_DIR, 'content.js'), 'utf8');
  const projectionMessages = [];
  const navigationCalls = [];
  const responses = [];
  let listener;
  let releaseInitialProjection;
  const initialProjectionGate = new Promise((resolve) => {
    releaseInitialProjection = resolve;
  });
  const document = {
    readyState: 'complete',
    body: { innerText: '', scrollHeight: 0 },
    documentElement: { scrollHeight: 0 },
    querySelectorAll: () => [],
    querySelector: () => null,
  };
  class HTMLAnchorElement {
    click() { navigationCalls.push('next.click'); }
  }
  class HTMLButtonElement {}
  const location = {
    hostname: 'search.jd.com',
    href: 'https://search.jd.com/Search?page=1',
    assign() { navigationCalls.push('location.assign'); },
    replace() { navigationCalls.push('location.replace'); },
  };
  let classifications = 0;
  const context = {
    URL,
    Set,
    Promise,
    Date,
    Math,
    Number,
    document,
    location,
    HTMLAnchorElement,
    HTMLButtonElement,
    setTimeout,
    clearTimeout,
    scrollTo: () => {},
    open: () => navigationCalls.push('window.open'),
    SearchingAtScaleProjection: {
      PROJECTION_SCHEMA_VERSION: 4,
      PROJECTION_CAPABILITIES: [
        'stable_card_fields_v2',
        'verified_pagination_v1',
        'resilient_pagination_v1',
      ],
      shouldContinueCollection: () => false,
      shouldContinueJdPaginationSettlement: () => false,
      projectItems: () => [],
      classifyPageState: () => {
        classifications += 1;
        return 'ready';
      },
      jdLogicalPage: () => 1,
      jdNextPageActivation: () => { throw new Error('must not navigate'); },
      skuDigest: () => 'none',
    },
    chrome: {
      runtime: {
        id: 'extension-id',
        onMessage: { addListener: (value) => { listener = value; } },
        sendMessage: async (message) => {
          if (message.type === 'projection_config') {
            return { ok: true, max_items: 10, pagination_enabled: true };
          }
          if (message.type === 'projection') {
            projectionMessages.push(structuredClone(message));
            if (projectionMessages.length === 1) await initialProjectionGate;
            if (projectionMessages.length === 2) throw new Error('projection send failed');
            return { ok: true };
          }
          throw new Error('unexpected message');
        },
      },
      tabs: new Proxy({}, {
        get: (_target, name) => () => navigationCalls.push(`chrome.tabs.${String(name)}`),
      }),
    },
  };
  context.globalThis = context;
  context.window = context;
  vm.runInNewContext(source, context, { filename: 'content.js' });

  const waitFor = async (predicate) => {
    for (let index = 0; index < 100 && !predicate(); index += 1) {
      await new Promise((resolve) => setImmediate(resolve));
    }
    assert.equal(predicate(), true);
  };
  await waitFor(() => typeof listener === 'function' && projectionMessages.length === 1);
  const first = new Promise((resolve) => {
    assert.equal(listener(
      { type: 'pagination_recover', recovery_attempt: 1 },
      { id: 'extension-id' },
      (value) => { responses.push(value); resolve(); },
    ), true);
  });
  const second = new Promise((resolve) => {
    assert.equal(listener(
      { type: 'pagination_recover', recovery_attempt: 2 },
      { id: 'extension-id' },
      (value) => { responses.push(value); resolve(); },
    ), true);
  });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(projectionMessages.length, 1);

  releaseInitialProjection();
  await Promise.all([first, second]);
  await waitFor(() => projectionMessages.length === 3);
  assert.equal(classifications, 3);
  assert.deepEqual(
    projectionMessages.map((value) => value.diagnostics.recovery_attempt),
    [0, 1, 2],
  );
  assert.deepEqual(JSON.parse(JSON.stringify(responses)), [
    { ok: false, category: 'pagination_recovery_unavailable' },
    { ok: true },
  ]);
  assert.deepEqual(navigationCalls, []);
});


async function projectWithPageJumpEvidence({
  paginationRoute = 'page_jump', highlightedPage = 2, observedPage = 2,
  expectedPage = 2, classifiedState = 'ready',
} = {}) {
  const source = await readFile(path.join(EXTENSION_DIR, 'content.js'), 'utf8');
  const projectionMessages = [];
  let collectionChecks = 0;
  const item = {
    product_id: '200000', title: '第二页商品',
    url: 'https://item.jd.com/200000.html',
    price: null, shop: null, commit: null, good_rate: null,
    promo: null, stock: null, image: null,
  };
  const card = {
    textContent: '第二页商品',
    getAttribute(name) {
      if (name === 'data-sku') return '200000';
      if (name === 'aria-label') return '第二页商品';
      return null;
    },
    querySelector() { return null; },
  };
  const document = {
    readyState: 'complete',
    body: { innerText: '', scrollHeight: 1000 },
    documentElement: { scrollHeight: 1000 },
    querySelectorAll(selector) {
      if (selector === '[data-sku]') return [card];
      return [];
    },
    querySelector() { return null; },
  };
  class HTMLAnchorElement {}
  class HTMLButtonElement {}
  const context = {
    URL, Set, Promise, Date, Math, Number,
    document,
    location: {
      hostname: 'search.jd.com',
      href: `https://search.jd.com/Search?keyword=x&page=${observedPage * 2 - 1}`,
    },
    HTMLAnchorElement,
    HTMLButtonElement,
    setTimeout: (callback) => { callback(); return 1; },
    clearTimeout: () => {},
    scrollTo: () => {},
    SearchingAtScalePageJumpPagination: {
      highlightedPageNumber: () => highlightedPage,
    },
    SearchingAtScaleProjection: {
      PROJECTION_SCHEMA_VERSION: 4,
      PROJECTION_CAPABILITIES: [
        'stable_card_fields_v2',
        'verified_pagination_v1',
        'resilient_pagination_v1',
      ],
      shouldContinueCollection: () => {
        collectionChecks += 1;
        return collectionChecks === 1;
      },
      shouldContinueJdPaginationSettlement: () => false,
      projectItems: () => [item],
      classifyPageState: () => classifiedState,
      jdLogicalPage: () => observedPage,
      skuDigest: (items) => items.map((value) => value.product_id).join(',') || 'none',
    },
    chrome: {
      runtime: {
        id: 'extension-id',
        onMessage: { addListener() {} },
        sendMessage: async (message) => {
          if (message.type === 'projection_config') {
            return {
              ok: true,
              max_items: 30,
              expected_page_number: expectedPage,
              pagination_enabled: true,
              pagination_route: paginationRoute,
              recovery_stage: 'initial',
              recovery_attempt: 0,
            };
          }
          if (message.type === 'projection') {
            projectionMessages.push(structuredClone(message));
            return { ok: true };
          }
          throw new Error('unexpected message');
        },
      },
    },
  };
  context.globalThis = context;
  context.window = context;
  vm.runInNewContext(source, context, { filename: 'content.js' });
  for (let index = 0; index < 100 && projectionMessages.length === 0; index += 1) {
    await new Promise((resolve) => setImmediate(resolve));
  }
  assert.equal(projectionMessages.length, 1);
  return projectionMessages[0];
}


test('page-jump projection keeps cards only when URL and current highlight match target', async () => {
  const message = await projectWithPageJumpEvidence();

  assert.equal(message.observed_page_number, 2);
  assert.equal(message.page_state, 'ready');
  assert.equal(message.items.length, 1);
  assert.equal(message.sku_digest, '200000');
});


test('page-jump page one establishes a card baseline without rendered highlight', async () => {
  const message = await projectWithPageJumpEvidence({
    expectedPage: 1, observedPage: 1, highlightedPage: null,
  });

  assert.equal(message.observed_page_number, 1);
  assert.equal(message.page_state, 'ready');
  assert.equal(message.items.length, 1);
  assert.equal(message.sku_digest, '200000');
});


for (const [name, options] of [
  ['missing current highlight', { highlightedPage: null }],
  ['mismatched current highlight', { highlightedPage: 1 }],
  ['mismatched observed URL page', { highlightedPage: 3, observedPage: 3 }],
]) {
  test(`page-jump projection fails closed for ${name}`, async () => {
    const message = await projectWithPageJumpEvidence(options);

    assert.equal(message.page_state, 'page_structure_changed');
    assert.deepEqual(message.items, []);
    assert.equal(message.sku_digest, 'none');
    assert.equal(message.diagnostics.valid_item_count, 0);
  });
}


test('existing route remains compatible without page-jump highlight evidence', async () => {
  const message = await projectWithPageJumpEvidence({
    paginationRoute: 'existing', highlightedPage: null,
  });

  assert.equal(message.page_state, 'ready');
  assert.equal(message.items.length, 1);
});


test('infinite-scroll route projects only the next verified 30-SKU window', async () => {
  const source = await readFile(path.join(EXTENSION_DIR, 'content.js'), 'utf8');
  const projectionMessages = [];
  const runtimeListeners = [];
  let visibleCardCount = 30;
  const cards = Array.from({ length: 60 }, (_, index) => {
    const productId = String(300000 + index);
    return {
      textContent: `商品${productId}`,
      getAttribute(name) {
        if (name === 'data-sku') return productId;
        if (name === 'aria-label') return `商品${productId}`;
        return null;
      },
      querySelector() { return null; },
    };
  });
  const document = {
    readyState: 'complete',
    body: { innerText: '', scrollHeight: 2000 },
    documentElement: { scrollHeight: 2000 },
    querySelectorAll(selector) {
      if (selector === '[data-sku]') return cards.slice(0, visibleCardCount);
      return [];
    },
    querySelector() { return null; },
  };
  class HTMLAnchorElement {}
  class HTMLButtonElement {}
  const context = {
    URL, Set, Map, Promise, Date, Math, Number,
    document,
    location: {
      hostname: 'search.jd.com',
      href: 'https://search.jd.com/Search?keyword=x&page=1',
    },
    HTMLAnchorElement,
    HTMLButtonElement,
    setTimeout: (callback) => { callback(); return 1; },
    clearTimeout: () => {},
    scrollTo: () => { visibleCardCount = 60; },
    SearchingAtScaleProjection: {
      PROJECTION_SCHEMA_VERSION: 4,
      PROJECTION_CAPABILITIES: [
        'stable_card_fields_v2',
        'verified_pagination_v1',
        'resilient_pagination_v1',
      ],
      shouldContinueCollection: ({ itemCount }) => itemCount === 0,
      shouldContinueJdPaginationSettlement: () => false,
      projectItems: (_platform, anchors, limit) => anchors.slice(0, limit).map((anchor) => {
        const productId = new URL(anchor.href).pathname.split('/').at(-1).split('.')[0];
        return {
          product_id: productId,
          title: anchor.title,
          url: anchor.href,
          price: null, shop: null, commit: null, good_rate: null,
          promo: null, stock: null, image: null,
        };
      }),
      classifyPageState: () => 'ready',
      jdLogicalPage: () => 1,
      skuDigest: (items) => items.map((item) => item.product_id).join(',') || 'none',
    },
    chrome: {
      runtime: {
        id: 'extension-id',
        onMessage: { addListener(listener) { runtimeListeners.push(listener); } },
        sendMessage: async (message) => {
          if (message.type === 'projection_config') {
            return {
              ok: true,
              max_items: 300,
              expected_page_number: 1,
              pagination_enabled: true,
              pagination_route: 'infinite_scroll',
              recovery_stage: 'initial',
              recovery_attempt: 0,
            };
          }
          if (message.type === 'projection') {
            projectionMessages.push(structuredClone(message));
            return { ok: true };
          }
          throw new Error('unexpected message');
        },
      },
    },
  };
  context.globalThis = context;
  context.window = context;
  vm.runInNewContext(source, context, { filename: 'content.js' });
  for (let index = 0; index < 100 && projectionMessages.length === 0; index += 1) {
    await new Promise((resolve) => setImmediate(resolve));
  }
  projectionMessages.length = 0;

  const response = await new Promise((resolve) => {
    let responded = false;
    const returned = runtimeListeners[0](
      { type: 'pagination_infinite_scroll', expected_page_number: 2 },
      { id: 'extension-id' },
      (value) => { responded = true; resolve(value); },
    );
    if (returned !== true && !responded) resolve(undefined);
  });
  for (let index = 0; index < 100 && projectionMessages.length === 0; index += 1) {
    await new Promise((resolve) => setImmediate(resolve));
  }

  assert.equal(response?.ok, true);
  assert.deepEqual(Object.keys(response), ['ok']);
  assert.equal(projectionMessages.length, 1);
  const projected = projectionMessages[0];
  assert.equal(projected.observed_page_number, 2);
  assert.equal(projected.items.length, 30);
  assert.equal(projected.items[0].product_id, '300030');
  assert.equal(projected.items.at(-1).product_id, '300059');
  assert.equal(projected.diagnostics.observed_page_number, 2);
  assert.equal(projected.has_next_page, true);
});


test('page-jump highlight mismatch never masks a hard-risk classification', async () => {
  const message = await projectWithPageJumpEvidence({
    highlightedPage: null, classifiedState: 'rate_limited',
  });

  assert.equal(message.page_state, 'rate_limited');
});
