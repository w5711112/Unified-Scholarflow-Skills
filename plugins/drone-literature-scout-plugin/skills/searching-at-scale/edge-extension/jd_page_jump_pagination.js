(function installJdPageJumpPagination() {
  'use strict';

  if (globalThis.location.hostname !== 'search.jd.com') return;

  const JUMP_CONTAINER_SELECTOR = '#J_bottomPage .p-skip';
  const CURRENT_PAGE_SELECTOR = '#J_topPage .curr, #J_bottomPage .curr';

  function isVisible(node) {
    if (node === null || typeof node !== 'object') return false;
    if (node.hidden || node.matches?.('[hidden]')) return false;
    if (node.getAttribute?.('aria-hidden') === 'true') return false;
    const style = globalThis.getComputedStyle(node);
    return style.display !== 'none'
      && style.visibility !== 'hidden'
      && node.getClientRects().length > 0;
  }

  function isEnabled(node) {
    return isVisible(node)
      && node.disabled !== true
      && node.readOnly !== true
      && node.getAttribute?.('disabled') === null
      && node.getAttribute?.('readonly') === null
      && node.getAttribute?.('aria-disabled') !== 'true';
  }

  function currentLogicalPage() {
    let current;
    try {
      current = new URL(globalThis.location.href);
    } catch {
      return null;
    }
    const physicalPage = Number(current.searchParams.get('page'));
    if (
      current.protocol !== 'https:'
      || current.host !== 'search.jd.com'
      || current.pathname !== '/Search'
      || current.username
      || current.password
      || current.hash
      || current.searchParams.getAll('page').length !== 1
      || !Number.isSafeInteger(physicalPage)
      || physicalPage < 1
      || physicalPage % 2 !== 1
    ) return null;
    return (physicalPage + 1) / 2;
  }

  function sameTabConfirmation(node) {
    if (!(node instanceof HTMLAnchorElement) && !(node instanceof HTMLButtonElement)) {
      return false;
    }
    if (!isEnabled(node)) return false;
    const target = String(
      node.getAttribute('target') || node.getAttribute('formtarget') || '',
    ).trim().toLowerCase();
    return target === '' || target === '_self';
  }

  function publicJumpControls() {
    const containers = Array.from(document.querySelectorAll(JUMP_CONTAINER_SELECTOR))
      .filter(isVisible);
    if (containers.length !== 1) return null;
    const inputs = Array.from(containers[0].querySelectorAll('input'));
    const confirmations = Array.from(containers[0].querySelectorAll('a, button'));
    if (
      inputs.length !== 1
      || !(inputs[0] instanceof HTMLInputElement)
      || !isEnabled(inputs[0])
      || confirmations.length !== 1
      || !sameTabConfirmation(confirmations[0])
    ) return null;
    return { input: inputs[0], confirmation: confirmations[0] };
  }

  function jumpToAdjacentPage(expectedPageNumber) {
    const currentPageNumber = currentLogicalPage();
    if (
      !Number.isSafeInteger(expectedPageNumber)
      || expectedPageNumber < 2
      || expectedPageNumber > 512
      || currentPageNumber === null
      || expectedPageNumber !== currentPageNumber + 1
    ) return false;
    const controls = publicJumpControls();
    if (controls === null) return false;
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      'value',
    )?.set;
    if (typeof setter !== 'function') return false;
    try {
      setter.call(controls.input, String(expectedPageNumber));
      controls.input.dispatchEvent(new Event('input', { bubbles: true }));
      controls.input.dispatchEvent(new Event('change', { bubbles: true }));
    } catch {
      return false;
    }
    if (String(controls.input.value) !== String(expectedPageNumber)) return false;
    globalThis.setTimeout(() => controls.confirmation.click(), 0);
    return true;
  }

  function highlightedPageNumber() {
    const values = Array.from(document.querySelectorAll(CURRENT_PAGE_SELECTOR))
      .filter(isVisible)
      .map((node) => String(node.textContent || '').trim())
      .filter((value) => /^\d+$/u.test(value))
      .map(Number)
      .filter((value) => Number.isSafeInteger(value) && value >= 1 && value <= 512);
    if (values.length === 0) return null;
    const unique = [...new Set(values)];
    return unique.length === 1 ? unique[0] : null;
  }

  globalThis.SearchingAtScalePageJumpPagination = Object.freeze({
    jumpToAdjacentPage,
    highlightedPageNumber,
  });

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message?.type !== 'pagination_page_jump') return false;
    if (sender.id !== chrome.runtime.id) {
      sendResponse({ ok: false, category: 'pagination_page_jump_unavailable' });
      return false;
    }
    const ok = jumpToAdjacentPage(message.expected_page_number);
    sendResponse(ok
      ? { ok: true }
      : { ok: false, category: 'pagination_page_jump_unavailable' });
    return false;
  });
}());
