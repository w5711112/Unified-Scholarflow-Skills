(function installProjection(global) {
  'use strict';

  const PLATFORM_HOSTS = Object.freeze({
    jd: new Set(['item.jd.com', 'item.m.jd.com']),
    taobao: new Set(['item.taobao.com', 'detail.tmall.com', 'detail.tmall.hk']),
  });

  function canonicalIdentity(platform, href) {
    let parsed;
    try {
      parsed = new URL(href);
    } catch {
      return null;
    }
    if (parsed.protocol !== 'https:' || parsed.username || parsed.password) {
      return null;
    }
    if (platform === 'jd' && PLATFORM_HOSTS.jd.has(parsed.hostname)) {
      const match = parsed.hostname === 'item.jd.com'
        ? parsed.pathname.match(/^\/(\d+)\.html$/u)
        : parsed.pathname.match(/^\/product\/(\d+)\.html$/u);
      return match === null ? null : {
        product_id: match[1],
        url: `https://item.jd.com/${match[1]}.html`,
      };
    }
    if (
      platform === 'taobao'
      && PLATFORM_HOSTS.taobao.has(parsed.hostname)
      && parsed.pathname === '/item.htm'
    ) {
      const ids = parsed.searchParams.getAll('id');
      if (ids.length === 1 && /^\d+$/u.test(ids[0])) {
        return {
          product_id: ids[0],
          url: `https://${parsed.hostname}/item.htm?id=${ids[0]}`,
        };
      }
    }
    return null;
  }

  const CARD_FIELDS = ['price', 'shop', 'commit', 'good_rate', 'promo', 'stock', 'image'];
  const PROJECTION_SCHEMA_VERSION = 4;
  const PROJECTION_CAPABILITIES = Object.freeze([
    'stable_card_fields_v2',
    'verified_pagination_v1',
    'resilient_pagination_v1',
  ]);

  function shouldContinueCollection({ itemCount, stableRounds, elapsedMs, maxItems }) {
    if (
      !Number.isSafeInteger(itemCount) || itemCount < 0
      || !Number.isSafeInteger(stableRounds) || stableRounds < 0
      || !Number.isFinite(elapsedMs) || elapsedMs < 0
      || !Number.isSafeInteger(maxItems) || maxItems < 1 || maxItems > 1000
    ) {
      throw new Error('collection evidence is invalid');
    }
    if (itemCount === 0) return elapsedMs < 10000;
    return itemCount < maxItems && elapsedMs < 20000 && stableRounds < 2;
  }

  function shouldContinueJdPaginationSettlement({
    paginationEnabled,
    platform,
    itemCount,
    hasNextPage,
    elapsedMs,
  }) {
    if (
      typeof paginationEnabled !== 'boolean'
      || (platform !== 'jd' && platform !== 'taobao')
      || !Number.isSafeInteger(itemCount) || itemCount < 0
      || typeof hasNextPage !== 'boolean'
      || !Number.isFinite(elapsedMs) || elapsedMs < 0
    ) {
      throw new Error('pagination settlement evidence is invalid');
    }
    return paginationEnabled
      && platform === 'jd'
      && itemCount > 0
      && !hasNextPage
      && elapsedMs < 8000;
  }

  function skuDigest(items) {
    if (!Array.isArray(items)) throw new Error('SKU evidence is invalid');
    const productIds = items.map((item) => item?.product_id);
    if (productIds.some((value) => typeof value !== 'string' || !/^\d+$/u.test(value))) {
      throw new Error('SKU evidence is invalid');
    }
    return [...new Set(productIds)].sort().join(',') || 'none';
  }

  function projectItems(platform, anchors, maxItems) {
    if (!Object.hasOwn(PLATFORM_HOSTS, platform)) {
      throw new Error('unsupported marketplace');
    }
    if (!Number.isSafeInteger(maxItems) || maxItems < 1 || maxItems > 1000) {
      throw new Error('maxItems is invalid');
    }
    if (!Array.isArray(anchors) || anchors.length > maxItems * 4) {
      throw new Error('anchor projection is invalid');
    }
    const seen = new Set();
    const items = [];
    for (const anchor of anchors) {
      if (anchor === null || typeof anchor !== 'object' || Array.isArray(anchor)) {
        continue;
      }
      const title = typeof anchor.title === 'string'
        ? anchor.title.trim().replace(/\s+/gu, ' ')
        : '';
      const identity = typeof anchor.href === 'string'
        ? canonicalIdentity(platform, anchor.href)
        : null;
      if (identity === null || !title || seen.has(identity.product_id)) {
        continue;
      }
      seen.add(identity.product_id);
      const item = { ...identity, title };
      for (const field of CARD_FIELDS) {
        item[field] = null;
        const value = anchor[field];
        if (typeof value === 'string' && value.trim()) {
          item[field] = value.trim().replace(/\s+/gu, ' ');
        }
      }
      items.push(item);
      if (items.length === maxItems) {
        break;
      }
    }
    return items;
  }

  function classifyPageState(text, itemCount) {
    if (typeof text !== 'string' || !Number.isSafeInteger(itemCount) || itemCount < 0) {
      throw new Error('page-state evidence is invalid');
    }
    if (/验证码|安全验证|滑块/u.test(text)) {
      return 'captcha_required';
    }
    if (
      /访问(?:过于)?频繁|请求过于频繁|操作过于频繁|内容太火爆|当前页面异常|rate limit/iu
        .test(text)
    ) {
      return 'rate_limited';
    }
    if (itemCount > 0) {
      return 'ready';
    }
    if (/账号登录|扫码登录/u.test(text)) {
      return 'authentication_required';
    }
    if (/暂无|没有找到|无相关商品/u.test(text)) {
      return 'ready';
    }
    return 'page_structure_changed';
  }

  function jdLogicalPage(href) {
    let parsed;
    try {
      parsed = new URL(href);
    } catch {
      throw new Error('invalid JD search URL');
    }
    if (parsed.protocol !== 'https:' || parsed.hostname !== 'search.jd.com') {
      throw new Error('invalid JD search URL');
    }
    const rawPage = parsed.searchParams.get('page');
    if (rawPage === null) return 1;
    if (!/^\d+$/u.test(rawPage)) throw new Error('invalid JD search URL page');
    const internalPage = Number(rawPage);
    if (!Number.isSafeInteger(internalPage) || internalPage < 1 || internalPage % 2 === 0) {
      throw new Error('invalid JD search URL page');
    }
    return (internalPage + 1) / 2;
  }

  function jdNextPageHref(currentHref, candidateHref, expectedPage) {
    if (!Number.isSafeInteger(expectedPage) || expectedPage < 2 || expectedPage > 512) {
      throw new Error('invalid sequential JD page');
    }
    let current;
    let candidate;
    try {
      current = new URL(currentHref);
      candidate = new URL(candidateHref, current);
    } catch {
      throw new Error('invalid JD next-page URL');
    }
    if (
      current.protocol !== 'https:'
      || current.hostname !== 'search.jd.com'
      || current.pathname !== '/Search'
      || candidate.protocol !== 'https:'
      || candidate.hostname !== 'search.jd.com'
      || candidate.pathname !== '/Search'
      || candidate.username
      || candidate.password
      || candidate.hash
    ) {
      throw new Error('invalid JD next-page URL');
    }
    if (
      jdLogicalPage(current.href) + 1 !== expectedPage
      || jdLogicalPage(candidate.href) !== expectedPage
      || current.searchParams.get('keyword') !== candidate.searchParams.get('keyword')
    ) {
      throw new Error('invalid sequential JD page');
    }
    return candidate.href;
  }

  function jdNextPageActivation(currentHref, candidateHref, expectedPage, options = {}) {
    if (typeof candidateHref !== 'string') {
      throw new Error('invalid JD next-page activation');
    }
    // 2026-08-12: human-flow pages re-render in place (the search URL never
    // gains a page parameter), so URL-derived page math stays 1 forever. The
    // caller may supply a DOM/cursor-tracked current page instead; when absent
    // the legacy URL-derived behavior is used unchanged.
    const domCurrentPage = options?.domCurrentPage;
    const domTracked = Number.isSafeInteger(domCurrentPage)
      && domCurrentPage >= 1
      && domCurrentPage <= 512;
    let currentPage;
    if (domTracked) {
      currentPage = domCurrentPage;
    } else {
      try {
        currentPage = jdLogicalPage(currentHref);
      } catch {
        throw new Error('invalid JD next-page activation');
      }
    }
    if (
      !Number.isSafeInteger(expectedPage)
      || expectedPage < 2
      || expectedPage > 512
      || currentPage + 1 !== expectedPage
    ) {
      throw new Error('invalid JD next-page activation');
    }
    const compact = candidateHref.trim().toLowerCase().replace(/\s+/gu, '');
    if (
      compact === 'javascript:;'
      || compact === 'javascript:void(0)'
      || compact === 'javascript:void(0);'
    ) {
      return 'public_click';
    }
    if (domTracked) {
      // In-place re-render next controls carry no page-bearing URL; a same-tab
      // click is the human activation. The flip itself is verified downstream
      // by SKU-digest change, not by the URL.
      return 'public_click';
    }
    try {
      jdNextPageHref(currentHref, candidateHref, expectedPage);
    } catch {
      throw new Error('invalid JD next-page activation');
    }
    return 'verified_url';
  }

  function jdSkuSetChanged(before, after) {
    if (!Array.isArray(before) || !Array.isArray(after)) {
      throw new Error('invalid JD SKU evidence');
    }
    const left = new Set(before.filter((value) => /^\d+$/u.test(value)));
    const right = new Set(after.filter((value) => /^\d+$/u.test(value)));
    if (left.size === 0 || right.size === 0 || left.size !== right.size) {
      return left.size > 0 && right.size > 0;
    }
    return Array.from(left).some((value) => !right.has(value));
  }

  global.SearchingAtScaleProjection = Object.freeze({
    PROJECTION_CAPABILITIES,
    PROJECTION_SCHEMA_VERSION,
    classifyPageState,
    jdLogicalPage,
    jdNextPageActivation,
    jdNextPageHref,
    jdSkuSetChanged,
    projectItems,
    shouldContinueCollection,
    shouldContinueJdPaginationSettlement,
    skuDigest,
  });
}(globalThis));
