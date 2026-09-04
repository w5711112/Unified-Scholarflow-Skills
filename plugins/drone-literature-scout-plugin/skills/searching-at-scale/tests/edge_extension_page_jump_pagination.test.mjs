import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';


const TEST_DIR = path.dirname(fileURLToPath(import.meta.url));
const EXTENSION_DIR = path.join(path.dirname(TEST_DIR), 'edge-extension');
const SCRIPT_PATH = path.join(EXTENSION_DIR, 'jd_page_jump_pagination.js');
const MANIFEST_PATH = path.join(EXTENSION_DIR, 'manifest.json');
const EXTENSION_ID = 'ackhakolgkcedgagblkfbjfnkceplcop';


class FakeNode {
  constructor({
    text = '', hidden = false, disabled = false, readOnly = false,
    attributes = {}, noRect = false, display = 'block', visibility = 'visible',
  } = {}) {
    this.textContent = text;
    this.hidden = hidden;
    this.disabled = disabled;
    this.readOnly = readOnly;
    this.attributes = new Map(Object.entries(attributes));
    this.noRect = noRect;
    this.display = display;
    this.visibility = visibility;
  }

  getAttribute(name) {
    return this.attributes.has(name) ? this.attributes.get(name) : null;
  }

  matches(selector) {
    if (selector === '[hidden]') return this.hidden || this.attributes.has('hidden');
    return false;
  }

  getClientRects() {
    return this.noRect ? [] : [{}];
  }
}


class FakeInput extends FakeNode {
  constructor(options = {}) {
    super(options);
    this._value = options.value || '';
    this.events = [];
  }

  get value() { return this._value; }

  set value(value) { this._value = String(value); }

  dispatchEvent(event) {
    this.events.push([event.type, event.bubbles]);
    return true;
  }
}


class FakeAnchor extends FakeNode {
  constructor(options = {}) {
    super(options);
    this.clicks = 0;
  }

  click() { this.clicks += 1; }
}


class FakeButton extends FakeAnchor {}


class FakeContainer extends FakeNode {
  constructor({ inputs = [], confirms = [], ...options } = {}) {
    super(options);
    this.inputs = inputs;
    this.confirms = confirms;
  }

  querySelectorAll(selector) {
    if (selector === 'input') return this.inputs;
    if (selector === 'a, button') return this.confirms;
    throw new Error(`unexpected container selector: ${selector}`);
  }
}


async function loadPageJump({
  containers = [], highlights = [],
  href = 'https://search.jd.com/Search?keyword=x&page=1',
} = {}) {
  const listeners = [];
  const scheduled = [];
  const context = {
    URL,
    Event: class Event {
      constructor(type, options = {}) {
        this.type = type;
        this.bubbles = options.bubbles === true;
      }
    },
    HTMLInputElement: FakeInput,
    HTMLAnchorElement: FakeAnchor,
    HTMLButtonElement: FakeButton,
    location: new URL(href),
    document: {
      querySelectorAll(selector) {
        if (selector === '#J_bottomPage .p-skip') return containers;
        if (selector === '#J_topPage .curr, #J_bottomPage .curr') return highlights;
        throw new Error(`unexpected document selector: ${selector}`);
      },
    },
    getComputedStyle(node) {
      return { display: node.display, visibility: node.visibility };
    },
    setTimeout(callback) {
      scheduled.push(callback);
      callback();
      return scheduled.length;
    },
    chrome: {
      runtime: {
        id: EXTENSION_ID,
        onMessage: { addListener(listener) { listeners.push(listener); } },
      },
    },
    console,
  };
  context.globalThis = context;
  const source = await readFile(SCRIPT_PATH, 'utf8').catch(() => '');
  vm.runInNewContext(source, context, { filename: 'jd_page_jump_pagination.js' });
  assert.ok(
    context.SearchingAtScalePageJumpPagination,
    'page-jump module must install on search.jd.com',
  );
  return { context, listeners, scheduled };
}


function validControls() {
  const input = new FakeInput();
  const confirm = new FakeAnchor({ attributes: { target: '_self' } });
  const container = new FakeContainer({ inputs: [input], confirms: [confirm] });
  return { input, confirm, container };
}


test('fills and clicks exactly one visible adjacent public page-jump form', async () => {
  const controls = validControls();
  const { context } = await loadPageJump({ containers: [controls.container] });

  const result = context.SearchingAtScalePageJumpPagination.jumpToAdjacentPage(2);

  assert.equal(result, true);
  assert.equal(controls.input.value, '2');
  assert.deepEqual(controls.input.events, [['input', true], ['change', true]]);
  assert.equal(controls.confirm.clicks, 1);
});


test('message handler accepts only the extension sender and adjacent target', async () => {
  const controls = validControls();
  const { listeners } = await loadPageJump({ containers: [controls.container] });
  assert.equal(listeners.length, 1);

  let response;
  const keepChannel = listeners[0](
    { type: 'pagination_page_jump', expected_page_number: 2 },
    { id: EXTENSION_ID },
    (value) => { response = value; },
  );

  assert.equal(keepChannel, false);
  assert.deepEqual(JSON.parse(JSON.stringify(response)), { ok: true });
  assert.equal(controls.confirm.clicks, 1);
});


test('message handler rejects an untrusted sender without any interaction', async () => {
  const controls = validControls();
  const { listeners } = await loadPageJump({ containers: [controls.container] });
  let response;

  listeners[0](
    { type: 'pagination_page_jump', expected_page_number: 2 },
    { id: 'untrusted-extension' },
    (value) => { response = value; },
  );

  assert.deepEqual(JSON.parse(JSON.stringify(response)), {
    ok: false,
    category: 'pagination_page_jump_unavailable',
  });
  assert.equal(controls.input.value, '');
  assert.equal(controls.confirm.clicks, 0);
});


for (const [name, mutate] of [
  ['missing container', () => []],
  ['ambiguous visible containers', (c) => [c, validControls().container]],
  ['hidden container', (c) => { c.hidden = true; return [c]; }],
  ['missing input', (c) => { c.inputs = []; return [c]; }],
  ['ambiguous inputs', (c) => { c.inputs.push(new FakeInput()); return [c]; }],
  ['disabled input', (c) => { c.inputs[0].disabled = true; return [c]; }],
  ['read-only input', (c) => { c.inputs[0].readOnly = true; return [c]; }],
  ['missing confirmation', (c) => { c.confirms = []; return [c]; }],
  ['ambiguous confirmations', (c) => { c.confirms.push(new FakeButton()); return [c]; }],
  ['disabled confirmation', (c) => { c.confirms[0].disabled = true; return [c]; }],
  ['cross-tab confirmation', (c) => {
    c.confirms[0].attributes.set('target', '_blank'); return [c];
  }],
]) {
  test(`fails closed for ${name}`, async () => {
    const controls = validControls();
    const { context } = await loadPageJump({ containers: mutate(controls.container) });

    const result = context.SearchingAtScalePageJumpPagination.jumpToAdjacentPage(2);

    assert.equal(result, false);
    assert.equal(controls.confirm.clicks, 0);
  });
}


for (const [name, target, href] of [
  ['same page', 1, 'https://search.jd.com/Search?keyword=x&page=1'],
  ['skipped page', 3, 'https://search.jd.com/Search?keyword=x&page=1'],
  ['duplicate current page parameter', 2, 'https://search.jd.com/Search?keyword=x&page=1&page=3'],
  ['even physical current page', 2, 'https://search.jd.com/Search?keyword=x&page=2'],
]) {
  test(`rejects ${name} without interacting`, async () => {
    const controls = validControls();
    const { context } = await loadPageJump({
      containers: [controls.container], href,
    });

    assert.equal(
      context.SearchingAtScalePageJumpPagination.jumpToAdjacentPage(target),
      false,
    );
    assert.equal(controls.confirm.clicks, 0);
  });
}


test('returns one current highlight when top and bottom agree', async () => {
  const { context } = await loadPageJump({
    highlights: [new FakeNode({ text: '2' }), new FakeNode({ text: ' 2 ' })],
  });

  assert.equal(
    context.SearchingAtScalePageJumpPagination.highlightedPageNumber(),
    2,
  );
});


for (const [name, highlights] of [
  ['missing highlight', []],
  ['ambiguous highlights', [new FakeNode({ text: '2' }), new FakeNode({ text: '3' })]],
  ['hidden highlight', [new FakeNode({ text: '2', hidden: true })]],
  ['non-numeric highlight', [new FakeNode({ text: '下一页' })]],
]) {
  test(`current highlight fails closed for ${name}`, async () => {
    const { context } = await loadPageJump({ highlights });
    assert.equal(
      context.SearchingAtScalePageJumpPagination.highlightedPageNumber(),
      null,
    );
  });
}


test('manifest loads page-jump module before content integration', async () => {
  const manifest = JSON.parse(await readFile(MANIFEST_PATH, 'utf8'));
  const scripts = manifest.content_scripts[0].js;

  assert.ok(scripts.includes('jd_page_jump_pagination.js'));
  assert.ok(
    scripts.indexOf('jd_page_jump_pagination.js') < scripts.indexOf('content.js'),
  );
});


test('script exposes no page-jump surface on a non-JD host', async () => {
  const listeners = [];
  const context = {
    URL,
    location: new URL('https://s.taobao.com/search?q=x&page=0'),
    chrome: { runtime: { id: EXTENSION_ID, onMessage: {
      addListener(listener) { listeners.push(listener); },
    } } },
    console,
  };
  context.globalThis = context;
  const source = await readFile(SCRIPT_PATH, 'utf8').catch(() => '');
  vm.runInNewContext(source, context, { filename: 'jd_page_jump_pagination.js' });

  assert.equal(context.SearchingAtScalePageJumpPagination, undefined);
  assert.equal(listeners.length, 0);
});
