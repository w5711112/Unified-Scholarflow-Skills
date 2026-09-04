(async function sendMarketplaceProjection() {
  'use strict';

  const projection = globalThis.SearchingAtScaleProjection;
  const platform = globalThis.location.hostname === 'search.jd.com' ? 'jd' : 'taobao';
  const wait = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));
  const routeConfig = await chrome.runtime.sendMessage({ type: 'projection_config' });
  if (routeConfig?.ok !== true) return;
  const maxItems = routeConfig.max_items;
  // 2026-08-12: human_flow re-renders the list in place (the search URL never
  // gains a page parameter), so URL page math stays 1 forever. The content
  // script tracks the logical page itself, seeded from the worker's expected
  // page and advanced on each clicked flip. The worker still verifies each
  // flip via SKU-digest change.
  let humanFlowCurrentPage = Number.isSafeInteger(routeConfig.expected_page_number)
    && routeConfig.expected_page_number >= 1
    ? routeConfig.expected_page_number
    : 1;

  function cleanTarget(value) {
    return typeof value === 'string' ? value.trim().toLowerCase() : '';
  }

  const jdNextPageControls = () => [
    ...Array.from(document.querySelectorAll(
      '#J_topPage a.fp-next, #J_topPage button.fp-next',
    )).map((node) => ({ node, region: 'top' })),
    ...Array.from(document.querySelectorAll(
      '#J_bottomPage a.pn-next, #J_bottomPage button.pn-next',
    )).map((node) => ({ node, region: 'bottom' })),
  ].filter(({ node }) => {
    if (
      !(node instanceof HTMLAnchorElement)
      && !(node instanceof HTMLButtonElement)
    ) return false;
    if (node.matches('.disabled, [disabled], [aria-disabled="true"]')) return false;
    const label = String(
      node.textContent
      || node.getAttribute('title')
      || node.getAttribute('aria-label')
      || '',
    ).trim();
    return node.classList.contains('fp-next')
      || node.classList.contains('pn-next')
      || /下一页|next/iu.test(label);
  });
  const jdNextPageControl = (expectedPageNumber) => {
    const controls = jdNextPageControls();
    if (controls.length === 1) return controls[0].node;
    // human_flow next controls may be JS-driven (no page-bearing URL), so the
    // strict top+bottom URL cross-check below cannot apply.
    if (routeConfig.pagination_route === 'human_flow' && controls.length > 0) {
      return controls.find(({ region }) => region === 'top')?.node || controls[0].node;
    }
    if (
      controls.length !== 2
      || new Set(controls.map(({ region }) => region)).size !== 2
      || !controls.every(({ node }) => node instanceof HTMLAnchorElement)
      || !Number.isSafeInteger(expectedPageNumber)
    ) return null;
    const destinations = [];
    try {
      for (const { node } of controls) {
        const target = cleanTarget(node.getAttribute('target'));
        if (target && target !== '_self') return null;
        const validated = projection.jdNextPageHref(
          globalThis.location.href,
          node.getAttribute('href') || node.href,
          expectedPageNumber,
        );
        const canonical = new URL(validated);
        canonical.searchParams.sort();
        destinations.push(canonical.href);
      }
    } catch {
      return null;
    }
    if (new Set(destinations).size !== 1) return null;
    return controls.find(({ region }) => region === 'top')?.node || null;
  };
  const jdExpectedNextPage = () => {
    try {
      return projection.jdLogicalPage(globalThis.location.href) + 1;
    } catch {
      return null;
    }
  };

  const selectors = platform === 'jd'
    ? 'a[href*="item.jd.com/"],a[href*="item.m.jd.com/product/"]'
    : 'a[href*="item.taobao.com/item.htm"],a[href*="detail.tmall.com/item.htm"],a[href*="detail.tmall.hk/item.htm"]';
  const cleanTitle = (value) => (typeof value === 'string'
    ? value.trim().replace(/\s+/gu, ' ')
    : '');
  const collectAnchors = () => Array.from(document.querySelectorAll(selectors))
    .slice(0, 4000)
    .map((anchor) => ({
      href: anchor.href,
      title: cleanTitle(
        anchor.getAttribute('title')
        || anchor.getAttribute('aria-label')
        || anchor.querySelector('img[alt]')?.getAttribute('alt')
        || anchor.textContent
        || '',
      ),
    }));
  const cardText = (card, cardSelectors) => {
    for (const selector of String(cardSelectors).split(',')) {
      const node = card.querySelector(selector.trim());
      const value = node?.textContent || node?.getAttribute('title') || '';
      if (value && cleanTitle(value)) return cleanTitle(value);
    }
    return '';
  };
  // Live pagination-DOM probe, shipped in every projection's diagnostics so the
  // driver can see the page-pagination structure without extra round-trips.
  const paginationDomProbe = () => {
    const currentMarker = Array.from(
      document.querySelectorAll('#J_bottomPage .curr, #J_topPage .curr'),
    ).map((node) => String(node.textContent || '').trim())
      .filter((value) => /^\d+$/u.test(value))[0] || '';
    const next = document.querySelector(
      '#J_bottomPage .pn-next, #J_bottomPage .fp-next, #J_topPage .fp-next',
    );
    let nextDesc = 'absent';
    if (next) {
      const href = String(next.getAttribute('href') || '').trim();
      const onClick = next.getAttribute('onclick') ? ';onclick' : '';
      nextDesc = `${href || 'no-href'}${onClick}`.slice(0, 600);
    }
    return `bottom=${document.querySelector('#J_bottomPage') ? 1 : 0};`
      + `curr=${currentMarker || 'none'};next=${nextDesc}`;
  };

  const collectJdCardsFrom = (root) => Array.from(root.querySelectorAll('[data-sku]'))
    .slice(0, 4000)
    .map((card) => {
      const productId = cleanTitle(card.getAttribute('data-sku'));
      const title = cleanTitle(
        card.querySelector('img[alt]')?.getAttribute('alt')
        || card.querySelector('[title]')?.getAttribute('title')
        || card.getAttribute('aria-label')
        || card.textContent
        || '',
      );
      const image = card.querySelector('img[data-lazy-img], img[data-src], img[src]');
      return {
        href: /^\d+$/u.test(productId)
          ? `https://item.jd.com/${productId}.html`
          : '',
        title,
        price: cardText(card, '.p-price, [class*="p-price"]'),
        shop: cardText(card, '.p-shop .shoptit, .p-shop [class*="shop"]'),
        commit: cardText(card, '.p-commit a, [class*="p-commit"]'),
        good_rate: cardText(card, '.p-comm, [class*="p-comm"]'),
        promo: cardText(card, '.p-icons, .p-promo, [class*="p-icons"], [class*="p-promo"]'),
        stock: cardText(card, '.p-stock, [class*="p-stock"]'),
        image: image ? cleanTitle(
          image.getAttribute('data-lazy-img')
          || image.getAttribute('data-src')
          || image.getAttribute('src')
          || '',
        ) : '',
      };
    });
  const collectJdCards = () => collectJdCardsFrom(document);
  const collectCandidates = () => platform === 'jd'
    ? collectJdCards()
    : collectAnchors();

  async function collectProjection({ recoveryStage, recoveryAttempt, logicalPage = null }) {
    if (
      !new Set(['initial', 'reproject', 'reload']).has(recoveryStage)
      || !Number.isSafeInteger(recoveryAttempt)
      || recoveryAttempt < 0
      || recoveryAttempt > 2
      || (
        logicalPage !== null
        && (!Number.isSafeInteger(logicalPage) || logicalPage < 1 || logicalPage > 512)
      )
    ) {
      throw new Error('invalid recovery evidence');
    }
    const readyDeadline = Date.now() + 10000;
    while (document.readyState === 'loading' && Date.now() < readyDeadline) {
      await wait(100);
    }

    let anchors = [];
    let items = [];
    let step = 0;
    let previousCount = -1;
    let stableRounds = 0;
    const collectionStarted = Date.now();
    const itemDeadline = Date.now() + 20000;
    while ((projection.shouldContinueCollection({
      itemCount: items.length,
      stableRounds,
      elapsedMs: Date.now() - collectionStarted,
      maxItems,
    }) || projection.shouldContinueJdPaginationSettlement({
      paginationEnabled: routeConfig.pagination_enabled === true,
      platform,
      itemCount: items.length,
      hasNextPage: Boolean(jdNextPageControl(jdExpectedNextPage())),
      elapsedMs: Date.now() - collectionStarted,
    })) && Date.now() < itemDeadline) {
      step = (step % 4) + 1;
      const height = Math.max(
        document.body?.scrollHeight || 0,
        document.documentElement?.scrollHeight || 0,
      );
      globalThis.scrollTo(0, Math.floor(height * step / 4));
      await wait(500);
      anchors = collectCandidates().slice(0, maxItems * 4);
      items = projection.projectItems(platform, anchors, maxItems);
      stableRounds = items.length === previousCount ? stableRounds + 1 : 0;
      previousCount = items.length;
    }

    if (routeConfig.pagination_route === 'infinite_scroll' && logicalPage !== null) {
      const windowStart = (logicalPage - 1) * 30;
      items = items.slice(windowStart, windowStart + 30);
    }

    // Page text is used only for local hard-risk classification and is never transmitted.
    const pageText = (document.body?.innerText || '').slice(0, 30000).toLowerCase();
    let pageState = projection.classifyPageState(pageText, items.length);
    const currentUrl = new URL(globalThis.location.href);
    currentUrl.hash = '';
    const observedPageNumber = platform === 'jd'
      ? (routeConfig.pagination_route === 'infinite_scroll' && logicalPage !== null
        ? logicalPage
        : routeConfig.pagination_route === 'human_flow'
          ? humanFlowCurrentPage
          : projection.jdLogicalPage(currentUrl.href))
      : Number(currentUrl.searchParams.get('page') || '0') + 1;
    if (
      platform === 'jd'
      && routeConfig.pagination_route === 'page_jump'
      && !new Set([
        'authentication_required', 'captcha_required', 'rate_limited',
      ]).has(pageState)
    ) {
      const highlightedPageNumber = globalThis.SearchingAtScalePageJumpPagination
        ?.highlightedPageNumber?.() ?? null;
      if (
        !Number.isSafeInteger(routeConfig.expected_page_number)
        || observedPageNumber !== routeConfig.expected_page_number
        || (
          routeConfig.expected_page_number > 1
          && highlightedPageNumber !== routeConfig.expected_page_number
        )
      ) {
        pageState = 'page_structure_changed';
        items = [];
      }
    }
    const sourceUrl = `${currentUrl.origin}${currentUrl.pathname}`;
    const diagnostics = {
      document_ready_state: document.readyState,
      data_sku_node_count: Math.min(document.querySelectorAll('[data-sku]').length, 4000),
      candidate_anchor_count: anchors.length,
      valid_item_count: items.length,
      collection_elapsed_ms: Math.max(0, Date.now() - collectionStarted),
      stable_rounds: stableRounds,
      observed_page_number: observedPageNumber,
      recovery_stage: recoveryStage,
      recovery_attempt: recoveryAttempt,
      source_path: '/Search',
      pagination_dom: paginationDomProbe(),
    };
    return { pageState, items, diagnostics, sourceUrl, observedPageNumber };
  }

  async function sendProjection(result) {
    const hasNextPage = platform === 'jd'
      ? (routeConfig.pagination_route === 'infinite_scroll'
        ? result.items.length === 30
        : Boolean(jdNextPageControl(jdExpectedNextPage())))
      : Boolean(document.querySelector('a.next:not(.disabled), button.next:not([disabled])'));
    await chrome.runtime.sendMessage({
      type: 'projection',
      projection_schema_version: projection.PROJECTION_SCHEMA_VERSION,
      capabilities: projection.PROJECTION_CAPABILITIES,
      platform,
      page_state: result.pageState,
      source_url: result.sourceUrl,
      observed_page_number: result.observedPageNumber,
      pagination_state: routeConfig.pagination_enabled
        ? 'page_verified'
        : 'pagination_unverified',
      has_next_page: hasNextPage,
      sku_digest: projection.skuDigest(result.items),
      diagnostics: result.diagnostics,
      items: result.items,
    });
  }

  let projectionQueue = Promise.resolve();
  function enqueueProjection(options) {
    const scheduled = projectionQueue.then(async () => {
      const result = await collectProjection(options);
      await sendProjection(result);
    });
    projectionQueue = scheduled.catch(() => {});
    return scheduled;
  }

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message?.type === 'pagination_infinite_scroll') {
      if (
        sender.id !== chrome.runtime.id
        || platform !== 'jd'
        || routeConfig.pagination_route !== 'infinite_scroll'
        || !Number.isSafeInteger(message.expected_page_number)
        || message.expected_page_number < 2
        || message.expected_page_number > 512
      ) {
        sendResponse({ ok: false, category: 'pagination_navigation_unavailable' });
        return false;
      }
      void (async () => {
        const targetCount = message.expected_page_number * 30;
        const deadline = Date.now() + 30000;
        let available = 0;
        while (Date.now() < deadline) {
          const anchors = collectCandidates().slice(0, maxItems * 4);
          available = projection.projectItems(platform, anchors, maxItems).length;
          if (available >= targetCount) break;
          const height = Math.max(
            document.body?.scrollHeight || 0,
            document.documentElement?.scrollHeight || 0,
          );
          globalThis.scrollTo(0, height);
          await wait(1000);
        }
        if (available < targetCount) {
          sendResponse({ ok: false, category: 'pagination_navigation_unavailable' });
          return;
        }
        await enqueueProjection({
          recoveryStage: 'initial',
          recoveryAttempt: 0,
          logicalPage: message.expected_page_number,
        });
        sendResponse({ ok: true });
      })().catch(() => {
        sendResponse({ ok: false, category: 'pagination_navigation_unavailable' });
      });
      return true;
    }

    if (message?.type === 'pagination_next') {
      if (
        sender.id !== chrome.runtime.id
        || platform !== 'jd'
        || !Number.isSafeInteger(message.expected_page_number)
      ) {
        sendResponse({ ok: false, category: 'pagination_navigation_unavailable' });
        return false;
      }
      const next = jdNextPageControl(message.expected_page_number);
      try {
        if (
          !(next instanceof HTMLAnchorElement)
          && !(next instanceof HTMLButtonElement)
        ) {
          throw new Error('next-page control unavailable');
        }
        if (next instanceof HTMLAnchorElement) {
          const target = cleanTarget(next.getAttribute('target'));
          if (target && target !== '_self') {
            throw new Error('next-page anchor opens another tab');
          }
          projection.jdNextPageActivation(
            globalThis.location.href,
            next.getAttribute('href') || next.href,
            message.expected_page_number,
            routeConfig.pagination_route === 'human_flow'
              ? { domCurrentPage: message.expected_page_number - 1 }
              : {},
          );
        } else {
          projection.jdNextPageActivation(
            globalThis.location.href,
            'javascript:;',
            message.expected_page_number,
            routeConfig.pagination_route === 'human_flow'
              ? { domCurrentPage: message.expected_page_number - 1 }
              : {},
          );
        }
      } catch {
        sendResponse({ ok: false, category: 'pagination_navigation_unavailable' });
        return false;
      }
      sendResponse({ ok: true });
      if (routeConfig.pagination_route === 'human_flow') {
        // Advance the in-place page tracker, then click and re-project after the
        // list re-renders. If the click instead triggers a full navigation, the
        // freshly injected content script projects on its own and this deferred
        // collection is discarded with the old document.
        humanFlowCurrentPage = message.expected_page_number;
        setTimeout(() => next.click(), 0);
        setTimeout(() => {
          void enqueueProjection({
            recoveryStage: 'initial',
            recoveryAttempt: 0,
            logicalPage: null,
          });
        }, 1500);
        return false;
      }
      setTimeout(() => next.click(), 0);
      return false;
    }

    if (message?.type !== 'pagination_recover') return false;
    if (
      sender.id !== chrome.runtime.id
      || platform !== 'jd'
      || !Number.isSafeInteger(message.recovery_attempt)
      || message.recovery_attempt < 1
      || message.recovery_attempt > 2
    ) {
      sendResponse({ ok: false, category: 'pagination_recovery_unavailable' });
      return false;
    }
    enqueueProjection({
      recoveryStage: 'reproject',
      recoveryAttempt: message.recovery_attempt,
    }).then(() => {
      sendResponse({ ok: true });
    }).catch(() => {
      sendResponse({ ok: false, category: 'pagination_recovery_unavailable' });
    });
    return true;
  });

  const configuredStage = new Set(['initial', 'reload']).has(routeConfig.recovery_stage)
    ? routeConfig.recovery_stage
    : 'initial';
  const configuredAttempt = Number.isSafeInteger(routeConfig.recovery_attempt)
    && routeConfig.recovery_attempt >= 0
    && routeConfig.recovery_attempt <= 2
    ? routeConfig.recovery_attempt
    : 0;
  await enqueueProjection({
    recoveryStage: configuredStage,
    recoveryAttempt: configuredAttempt,
    logicalPage: routeConfig.pagination_route === 'infinite_scroll'
      ? routeConfig.expected_page_number
      : null,
  });
}());
