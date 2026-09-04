import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';


const TEST_DIR = path.dirname(fileURLToPath(import.meta.url));
const SCRIPT_PATH = path.join(
  path.dirname(TEST_DIR),
  'edge-extension',
  'jd_numbered_pagination.js',
);
const MANIFEST_PATH = path.join(path.dirname(SCRIPT_PATH), 'manifest.json');
const EXTENSION_ID = 'ackhakolgkcedgagblkfbjfnkceplcop';


class FakeAnchor {
  constructor({ text = '2', href = '', attributes = {}, hidden = false } = {}) {
    this.textContent = text;
    this.href = href;
    this.hidden = hidden;
    this.attributes = new Map(Object.entries(attributes));
    this.classList = {
      contains: (name) => String(attributes.class || '').split(/\s+/u).includes(name),
    };
  }

  getAttribute(name) {
    if (name === 'href') return this.attributes.has(name) ? this.attributes.get(name) : this.href;
    return this.attributes.has(name) ? this.attributes.get(name) : null;
  }

  matches(selector) {
    if (selector === '[hidden]') return this.hidden || this.attributes.has('hidden');
    return false;
  }

  getClientRects() {
    return this.attributes.get('data-no-rect') === 'true' ? [] : [{}];
  }
}


async function loadNumberedPagination(
  anchors = [],
  currentHref = 'https://search.jd.com/Search?keyword=%E5%B0%8F%E7%B1%B315&page=1',
) {
  const listeners = [];
  const context = {
    URL,
    HTMLAnchorElement: FakeAnchor,
    location: new URL(currentHref),
    document: {
      querySelectorAll(selector) {
        assert.equal(selector, '#J_topPage a, #J_bottomPage a');
        return anchors;
      },
    },
    getComputedStyle(anchor) {
      return {
        display: anchor.attributes.get('data-display') || 'block',
        visibility: anchor.attributes.get('data-visibility') || 'visible',
      };
    },
    chrome: {
      runtime: {
        id: EXTENSION_ID,
        onMessage: {
          addListener(listener) { listeners.push(listener); },
        },
      },
    },
    console,
  };
  context.globalThis = context;
  const source = await readFile(SCRIPT_PATH, 'utf8').catch(() => '');
  vm.runInNewContext(source, context, { filename: 'jd_numbered_pagination.js' });
  return { context, listeners };
}


test('returns the visible adjacent numbered JD search link', async () => {
  const anchor = new FakeAnchor({
    text: '2',
    href: 'https://search.jd.com/Search?keyword=%E5%B0%8F%E7%B1%B315&page=3',
  });
  const { context } = await loadNumberedPagination([anchor]);

  const url = context.SearchingAtScaleNumberedPagination.findAdjacentPageUrl({
    expectedPageNumber: 2,
    query: '小米15',
  });

  assert.equal(
    url,
    'https://search.jd.com/Search?keyword=%E5%B0%8F%E7%B1%B315&page=3',
  );
});


test('rejects a numbered link that skips over the adjacent logical page', async () => {
  const anchor = new FakeAnchor({
    text: '3',
    href: 'https://search.jd.com/Search?keyword=%E5%B0%8F%E7%B1%B315&page=5',
  });
  const { context } = await loadNumberedPagination([anchor]);

  const url = context.SearchingAtScaleNumberedPagination.findAdjacentPageUrl({
    expectedPageNumber: 3,
    query: '小米15',
  });

  assert.equal(url, null);
});


const INVALID_LINKS = [
  ['wrong host', { href: 'https://example.com/Search?keyword=%E5%B0%8F%E7%B1%B315&page=3' }],
  ['non-HTTPS scheme', { href: 'http://search.jd.com/Search?keyword=%E5%B0%8F%E7%B1%B315&page=3' }],
  ['wrong path', { href: 'https://search.jd.com/search?keyword=%E5%B0%8F%E7%B1%B315&page=3' }],
  ['different query family', { href: 'https://search.jd.com/Search?keyword=Redmi&page=3' }],
  ['wrong physical page', { href: 'https://search.jd.com/Search?keyword=%E5%B0%8F%E7%B1%B315&page=5' }],
  ['duplicate keyword parameter', {
    href: 'https://search.jd.com/Search?keyword=%E5%B0%8F%E7%B1%B315&keyword=Redmi&page=3',
  }],
  ['duplicate page parameter', {
    href: 'https://search.jd.com/Search?keyword=%E5%B0%8F%E7%B1%B315&page=3&page=5',
  }],
  ['userinfo', { href: 'https://example:password@localhost/Search?keyword=%E5%B0%8F%E7%B1%B315&page=3' }],
  ['fragment', { href: 'https://search.jd.com/Search?keyword=%E5%B0%8F%E7%B1%B315&page=3#next' }],
  ['hidden attribute', { href: 'https://search.jd.com/Search?keyword=%E5%B0%8F%E7%B1%B315&page=3', hidden: true }],
  ['disabled class', {
    href: 'https://search.jd.com/Search?keyword=%E5%B0%8F%E7%B1%B315&page=3',
    attributes: { class: 'disabled' },
  }],
  ['aria-disabled node', {
    href: 'https://search.jd.com/Search?keyword=%E5%B0%8F%E7%B1%B315&page=3',
    attributes: { 'aria-disabled': 'true' },
  }],
  ['CSS-hidden node', {
    href: 'https://search.jd.com/Search?keyword=%E5%B0%8F%E7%B1%B315&page=3',
    attributes: { 'data-display': 'none' },
  }],
  ['layout-hidden node', {
    href: 'https://search.jd.com/Search?keyword=%E5%B0%8F%E7%B1%B315&page=3',
    attributes: { 'data-no-rect': 'true' },
  }],
  ['javascript URL', { href: 'javascript:void(0)' }],
  ['non-numeric label', {
    text: '下一页',
    href: 'https://search.jd.com/Search?keyword=%E5%B0%8F%E7%B1%B315&page=3',
  }],
];


for (const [reason, options] of INVALID_LINKS) {
  test(`rejects adjacent numbered link with ${reason}`, async () => {
    const { context } = await loadNumberedPagination([new FakeAnchor(options)]);

    const url = context.SearchingAtScaleNumberedPagination.findAdjacentPageUrl({
      expectedPageNumber: 2,
      query: '小米15',
    });

    assert.equal(url, null);
  });
}


test('message handler returns only the validated adjacent destination', async () => {
  const anchor = new FakeAnchor({
    text: '2',
    href: 'https://search.jd.com/Search?keyword=%E5%B0%8F%E7%B1%B315&page=3',
  });
  const { listeners } = await loadNumberedPagination([anchor]);
  assert.equal(listeners.length, 1);

  const response = await new Promise((resolve) => {
    const keepChannel = listeners[0]({
      type: 'pagination_numbered_link',
      expected_page_number: 2,
      query: '小米15',
    }, { id: EXTENSION_ID }, resolve);
    assert.equal(keepChannel, false);
  });

  assert.deepEqual(JSON.parse(JSON.stringify(response)), {
    ok: true,
    url: 'https://search.jd.com/Search?keyword=%E5%B0%8F%E7%B1%B315&page=3',
  });
});


test('message handler rejects a request from outside the extension', async () => {
  const anchor = new FakeAnchor({
    text: '2',
    href: 'https://search.jd.com/Search?keyword=%E5%B0%8F%E7%B1%B315&page=3',
  });
  const { listeners } = await loadNumberedPagination([anchor]);

  const response = await new Promise((resolve) => {
    listeners[0]({
      type: 'pagination_numbered_link',
      expected_page_number: 2,
      query: '小米15',
    }, { id: 'untrusted-extension' }, resolve);
  });

  assert.deepEqual(JSON.parse(JSON.stringify(response)), {
    ok: false,
    category: 'pagination_numbered_link_unavailable',
  });
});


test('rejects takeover when the current page belongs to another query', async () => {
  const anchor = new FakeAnchor({
    text: '2',
    href: 'https://search.jd.com/Search?keyword=%E5%B0%8F%E7%B1%B315&page=3',
  });
  const { context } = await loadNumberedPagination(
    [anchor],
    'https://search.jd.com/Search?keyword=Redmi&page=1',
  );

  const url = context.SearchingAtScaleNumberedPagination.findAdjacentPageUrl({
    expectedPageNumber: 2,
    query: '小米15',
  });

  assert.equal(url, null);
});


test('manifest loads numbered pagination before the projection content script', async () => {
  const manifest = JSON.parse(await readFile(MANIFEST_PATH, 'utf8'));
  const scripts = manifest.content_scripts[0].js;

  assert.ok(scripts.includes('jd_numbered_pagination.js'));
  assert.ok(
    scripts.indexOf('jd_numbered_pagination.js') < scripts.indexOf('content.js'),
  );
});


test('script installs no numbered-link surface on a non-JD search host', async () => {
  const { context, listeners } = await loadNumberedPagination(
    [],
    'https://s.taobao.com/search?q=%E5%B0%8F%E7%B1%B315&page=0',
  );

  assert.equal(context.SearchingAtScaleNumberedPagination, undefined);
  assert.equal(listeners.length, 0);
});
