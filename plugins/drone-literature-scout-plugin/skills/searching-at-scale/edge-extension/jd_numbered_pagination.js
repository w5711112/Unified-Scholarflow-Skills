(function installJdNumberedPagination() {
  'use strict';

  if (globalThis.location.hostname !== 'search.jd.com') return;

  const PAGINATION_SELECTOR = '#J_topPage a, #J_bottomPage a';

  function normalizeQuery(value) {
    return typeof value === 'string'
      ? value.normalize('NFKC').trim().replace(/\s+/gu, ' ')
      : '';
  }

  function isVisibleAnchor(anchor) {
    if (!(anchor instanceof HTMLAnchorElement)) return false;
    if (anchor.hidden || anchor.matches('[hidden]')) return false;
    if (anchor.classList.contains('disabled')) return false;
    if (anchor.getAttribute('disabled') !== null) return false;
    if (anchor.getAttribute('aria-disabled') === 'true') return false;
    if (anchor.getAttribute('aria-hidden') === 'true') return false;
    const style = globalThis.getComputedStyle(anchor);
    return style.display !== 'none'
      && style.visibility !== 'hidden'
      && anchor.getClientRects().length > 0;
  }

  function validatedDestination(anchor, expectedPageNumber, query) {
    if (!isVisibleAnchor(anchor)) return null;
    if (String(anchor.textContent || '').trim() !== String(expectedPageNumber)) return null;
    if (!(anchor instanceof HTMLAnchorElement)) return null;
    let destination;
    try {
      destination = new URL(anchor.getAttribute('href') || anchor.href, globalThis.location.href);
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

  function findAdjacentPageUrl({ expectedPageNumber, query }) {
    let current;
    try {
      current = new URL(globalThis.location.href);
    } catch {
      return null;
    }
    const currentPhysicalPage = Number(current.searchParams.get('page') || '1');
    const currentLogicalPage = (currentPhysicalPage + 1) / 2;
    if (
      current.protocol !== 'https:'
      || current.host !== 'search.jd.com'
      || current.pathname !== '/Search'
      || current.username
      || current.password
      || current.hash
      || current.searchParams.getAll('page').length !== 1
      || current.searchParams.getAll('keyword').length !== 1
      || normalizeQuery(current.searchParams.get('keyword')) !== normalizeQuery(query)
      || !Number.isSafeInteger(currentLogicalPage)
      || expectedPageNumber !== currentLogicalPage + 1
    ) return null;
    const candidates = Array.from(document.querySelectorAll(PAGINATION_SELECTOR))
      .map((anchor) => validatedDestination(anchor, expectedPageNumber, query))
      .filter((value) => value !== null);
    const unique = [...new Set(candidates)];
    return unique.length === 1 ? unique[0] : null;
  }

  globalThis.SearchingAtScaleNumberedPagination = Object.freeze({
    findAdjacentPageUrl,
  });

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message?.type !== 'pagination_numbered_link') return false;
    if (sender.id !== chrome.runtime.id) {
      sendResponse({ ok: false, category: 'pagination_numbered_link_unavailable' });
      return false;
    }
    const url = findAdjacentPageUrl({
      expectedPageNumber: message.expected_page_number,
      query: message.query,
    });
    sendResponse(url === null
      ? { ok: false, category: 'pagination_numbered_link_unavailable' }
      : { ok: true, url });
    return false;
  });
}());
