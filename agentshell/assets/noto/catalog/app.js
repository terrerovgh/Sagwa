/**
 * Noto Emoji Supercharge Hub — Official Google Fonts Emoji CDN Client App
 * Features:
 * - Instantaneous First Paint: Progressive chunked DOM rendering + tight IntersectionObserver image hydration
 * - 100% Official Emoji CDN URLs (fonts.gstatic.com/s/e/notoemoji/latest & noto3demoji/latest)
 * - Zero layout thrashing: O(1) viewport card tracking for GPU FLIP animations
 * - Lazy-loaded Lottie (lottie_light.min.js) runtime for 2D vector animations
 * - WAI-ARIA Roving tabindex with 2D Arrow-Key Grid Navigation (ArrowRight/Left/Down/Up)
 */

(function () {
  'use strict';

  const EMPTY_PIXEL = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7';
  const FIRST_EAGER_IMAGES = 24;  // Eagerly fetch only the immediate above-the-fold emojis
  const INITIAL_MOUNT_COUNT = 60; // Synchronously mount only the first 60 cards on initial load
  const SCROLL_BATCH_SIZE = 96;   // Mount 96 cards each time user scrolls near the bottom sentinel

  const prefersReducedMotion = () =>
    window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // Sandbox-safe helpers for x20web (Content-Security-Policy: sandbox allow-scripts with Origin: null)
  function safeStorageGet(key) {
    try {
      return window.localStorage.getItem(key);
    } catch (_) {
      return null;
    }
  }

  function safeStorageSet(key, val) {
    try {
      window.localStorage.setItem(key, val);
    } catch (_) {}
  }

  function safeStorageRemove(key) {
    try {
      window.localStorage.removeItem(key);
    } catch (_) {}
  }

  function safeUpdateUrlParams(mutatorFn) {
    try {
      const url = new URL(window.location.href);
      mutatorFn(url);
      window.history.replaceState({}, '', url.toString());
    } catch (_) {}
  }

  // --- Application State ---
  const state = {
    categories: [],
    emojis: [],
    emojiById: new Map(),
    filteredList: [],

    // Filter state
    searchQuery: '',
    activeCategory: 'all',

    // Selection & Drawer
    selectedEmoji: null,
    isDrawerOpen: false,
    activeDimension: '3d', // '3d' | '2d'
    activePreviewMode: 'static',
    activeLottieAnim: null,

    // Lazy runtime promise
    lottiePromise: null,

    // Progressive rendering token
    renderToken: null,

    // Theme
    theme: 'light',
  };

  // --- DOM References ---
  const dom = {
    html: document.documentElement,
    srStatus: document.getElementById('sr-status'),
    appHeader: document.getElementById('app-header'),
    brandHomeLink: document.getElementById('brand-home-link'),
    navHomeBtn: document.getElementById('nav-home-btn'),
    navDocsBtn: document.getElementById('nav-docs-btn'),
    emojiViewContainer: document.getElementById('emoji-view-container'),
    docsViewContainer: document.getElementById('docs-view-container'),
    docsExpandAllBtn: document.getElementById('docs-expand-all-btn'),
    docsFaqList: document.getElementById('docs-faq-list'),
    toolbarSticky: document.getElementById('toolbar-sticky'),
    workspaceLayout: document.getElementById('workspace-layout'),
    themeToggleBtn: document.getElementById('theme-toggle-btn'),
    headerDownloadSiteBtn: document.getElementById('header-download-site-btn'),
    docsDownloadSiteBtn: document.getElementById('docs-download-site-btn'),
    searchInput: document.getElementById('search-input'),
    searchClearBtn: document.getElementById('search-clear-btn'),
    categoryPills: document.getElementById('category-pills'),
    gridSectionsContainer: document.getElementById('grid-sections-container'),

    // Side Drawer
    sideDrawer: document.getElementById('emoji-side-drawer'),
    drawerEmojiName: document.getElementById('drawer-emoji-name'),
    drawerCodepointChips: document.getElementById('drawer-codepoint-chips'),
    drawerShareBtn: document.getElementById('drawer-share-btn'),
    drawerCloseBtn: document.getElementById('drawer-close-btn'),

    // Dimension Toggle & Preview Stage
    dimToggleGroup: document.getElementById('dimension-toggle-group'),
    dimBtn3d: document.getElementById('dim-btn-3d'),
    dimBtn2d: document.getElementById('dim-btn-2d'),
    previewStageContent: document.getElementById('preview-stage-content'),
    previewModePills: document.getElementById('preview-mode-pills'),
    previewDownloadBtn: document.getElementById('preview-download-btn'),
    downloadDropdownMenu: document.getElementById('download-dropdown-menu'),

    // Embed Code & UTC Proposal
    drawerEmbedList: document.getElementById('drawer-embed-list'),
    drawerDateAdded: document.getElementById('drawer-date-added'),
    drawerUtcLink: document.getElementById('drawer-utc-link'),
    drawerUtcDoc: document.getElementById('drawer-utc-doc'),
    drawerUtcTitle: document.getElementById('drawer-utc-title'),

    // Toast
    toastContainer: document.getElementById('toast-container'),
  };

  // --- Official Emoji CDN URL Helpers (https://g3doc.corp.google.com/company/teams/emoji/cdn.md) ---
  function getEmojiRgi(emoji) {
    if (emoji && emoji.rgi) return emoji.rgi;
    const cp = String((emoji && emoji.codepoint) || '').toLowerCase();
    return cp
      .split('_')
      .map((part) => part.padStart(4, '0'))
      .join('_');
  }

  function getCdn2dUrl(emoji, file) {
    return `https://fonts.gstatic.com/s/e/notoemoji/latest/${getEmojiRgi(emoji)}/${file}`;
  }

  function getCdn3dUrl(emoji, file) {
    return `https://fonts.gstatic.com/s/e/noto3demoji/latest/${getEmojiRgi(emoji)}/${file}`;
  }

  function announceSrStatus(msg) {
    if (dom.srStatus) {
      dom.srStatus.textContent = msg;
    }
  }

  // --- Tight Viewport IntersectionObservers (Zero Network Saturation & Zero Layout Thrashing) ---
  const visibleCardsSet = new Set();

  // Tracks which cards are currently near the viewport so FLIP never calls getBoundingClientRect on all 3,988 nodes
  const viewportCardObserver =
    typeof IntersectionObserver !== 'undefined'
      ? new IntersectionObserver(
          (entries) => {
            for (let i = 0; i < entries.length; i++) {
              const entry = entries[i];
              if (entry.isIntersecting) {
                visibleCardsSet.add(entry.target);
              } else {
                visibleCardsSet.delete(entry.target);
              }
            }
          },
          { rootMargin: '280px 0px' }
        )
      : null;

  // Hydrates data-src -> src strictly when a card is within 220px of the viewport
  function hydrateCardImage(imgEl) {
    if (!imgEl) return;
    const dataSrc = imgEl.getAttribute('data-src');
    if (!dataSrc) return;
    imgEl.removeAttribute('data-src');

    const wrap = imgEl.parentElement;
    const onDone = () => {
      imgEl.classList.remove('emoji-card__img--loading');
      imgEl.classList.add('emoji-card__img--loaded');
      if (wrap) wrap.classList.remove('is-loading');
    };

    imgEl.onload = onDone;
    imgEl.onerror = onDone;
    imgEl.src = dataSrc;
    if (imgEl.complete && imgEl.naturalWidth > 0) {
      onDone();
    }
  }

  const imageHydrationObserver =
    typeof IntersectionObserver !== 'undefined'
      ? new IntersectionObserver(
          (entries, observer) => {
            for (let i = 0; i < entries.length; i++) {
              const entry = entries[i];
              if (entry.isIntersecting) {
                const card = entry.target;
                observer.unobserve(card);
                const img = card.querySelector('img[data-src]');
                if (img) hydrateCardImage(img);
              }
            }
          },
          { rootMargin: '220px 0px' }
        )
      : null;

  // --- Lazy Runtime Loader for Lottie ---
  function ensureLottieLoaded() {
    if (window.lottie) {
      return Promise.resolve();
    }
    if (!state.lottiePromise) {
      state.lottiePromise = new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = 'lottie_light.min.js';
        script.onload = () => resolve();
        script.onerror = (err) => reject(err);
        document.head.appendChild(script);
      });
    }
    return state.lottiePromise;
  }

  // --- View Switcher (Emoji Grid vs Documentation) ---
  function showView(viewName, updateHistory = true) {
    const isDocs = viewName === 'docs';
    gridFlipState.isFlipping = true;

    if (dom.emojiViewContainer) {
      dom.emojiViewContainer.style.display = isDocs ? 'none' : 'block';
    }
    if (dom.docsViewContainer) {
      dom.docsViewContainer.style.display = isDocs ? 'block' : 'none';
    }
    if (dom.navHomeBtn) {
      dom.navHomeBtn.classList.toggle('active', !isDocs);
      if (!isDocs) dom.navHomeBtn.setAttribute('aria-current', 'page');
      else dom.navHomeBtn.removeAttribute('aria-current');
    }
    if (dom.navDocsBtn) {
      dom.navDocsBtn.classList.toggle('active', isDocs);
      if (isDocs) dom.navDocsBtn.setAttribute('aria-current', 'page');
      else dom.navDocsBtn.removeAttribute('aria-current');
    }
    if (isDocs && state.isDrawerOpen) {
      state.isDrawerOpen = false;
      state.selectedEmoji = null;
      dom.gridSectionsContainer.querySelectorAll('.emoji-card.selected').forEach((el) => {
        el.classList.remove('selected');
      });
      dom.sideDrawer.classList.remove('open');
      document.body.classList.remove('drawer-open');
    }

    requestAnimationFrame(() => {
      if (!isDocs && dom.workspaceLayout) {
        snapshotVisibleGridRects();
        gridFlipState.lastWidth = dom.workspaceLayout.clientWidth;
      }
      gridFlipState.isFlipping = false;
    });

    if (updateHistory) {
      safeUpdateUrlParams((url) => {
        if (isDocs) {
          url.searchParams.set('view', 'docs');
        } else {
          url.searchParams.delete('view');
        }
      });
    }
  }

  // --- Cute Minimal Emoji Page Loader (100% CDN Animated WebP Emojis) ---
  const CUTE_LOADER_EMOJIS = [
    { src: 'https://fonts.gstatic.com/s/e/notoemoji/latest/2728/512.webp', alt: 'Sparkles', halo: 'rgba(255, 214, 0, 0.25)' },
    { src: 'https://fonts.gstatic.com/s/e/notoemoji/latest/1f496/512.webp', alt: 'Sparkling Heart', halo: 'rgba(255, 75, 120, 0.25)' },
    { src: 'https://fonts.gstatic.com/s/e/notoemoji/latest/1f31f/512.webp', alt: 'Glowing Star', halo: 'rgba(255, 193, 7, 0.25)' },
    { src: 'https://fonts.gstatic.com/s/e/notoemoji/latest/1f602/512.webp', alt: 'Joy', halo: 'rgba(255, 183, 77, 0.25)' },
    { src: 'https://fonts.gstatic.com/s/e/notoemoji/latest/1f525/512.webp', alt: 'Fire', halo: 'rgba(255, 112, 67, 0.25)' },
    { src: 'https://fonts.gstatic.com/s/e/notoemoji/latest/1f340/512.webp', alt: 'Four Leaf Clover', halo: 'rgba(102, 187, 106, 0.25)' },
  ];

  let loaderCycleTimer = null;
  let loaderEmojiIdx = 0;

  function startLoaderEmojiCycle() {
    const imgEl = document.getElementById('loader-emoji-img');
    const haloEl = document.querySelector('.loader-emoji-halo');
    if (!imgEl) return;

    loaderCycleTimer = setInterval(() => {
      loaderEmojiIdx = (loaderEmojiIdx + 1) % CUTE_LOADER_EMOJIS.length;
      const next = CUTE_LOADER_EMOJIS[loaderEmojiIdx];

      imgEl.style.opacity = '0';
      imgEl.style.transform = 'scale(0.82)';

      setTimeout(() => {
        imgEl.src = next.src;
        imgEl.alt = next.alt;
        if (haloEl && next.halo) {
          haloEl.style.background = `radial-gradient(circle, ${next.halo} 0%, rgba(255, 180, 0, 0.08) 55%, transparent 70%)`;
        }
        imgEl.style.opacity = '1';
        imgEl.style.transform = 'scale(1)';
      }, 240);
    }, 2000);
  }

  function dismissPageLoader() {
    if (loaderCycleTimer) {
      clearInterval(loaderCycleTimer);
      loaderCycleTimer = null;
    }
    const loader = document.getElementById('page-loader');
    if (!loader) return;

    loader.classList.add('fade-out');
    setTimeout(() => {
      if (loader.parentNode) {
        loader.parentNode.removeChild(loader);
      }
    }, 320);
  }

  // --- Initialization ---
  async function init() {
    try {
      initTheme();
    } catch (e) {
      console.warn('initTheme error ignored in sandbox:', e);
    }
    try {
      setupEventListeners();
    } catch (e) {
      console.warn('setupEventListeners error ignored:', e);
    }
    dom.gridSectionsContainer?.classList.add('loading');
    startLoaderEmojiCycle();

    try {
      let data = window.__NOTO_EMOJIS_DATA__;
      if (!data) {
        const response = await fetch('data/emojis.json?v=20260916_v7');
        data = await response.json();
      }

      state.emojis = Array.isArray(data) ? data : data.emojis || [];

      const categorySet = new Set();
      state.emojis.forEach((em) => {
        state.emojiById.set(em.id, em);
        if (em.category) {
          categorySet.add(em.category);
        }
      });

      state.categories = Array.from(categorySet).map((name) => ({ name }));

      renderCategoryPills();

      // Render the first viewport immediately and progressively stream the rest on scroll
      renderFilteredGrid();

      dom.gridSectionsContainer?.classList.remove('loading');
      dom.gridSectionsContainer?.classList.add('loaded');
      dismissPageLoader();

      // URL parameters
      const urlParams = new URLSearchParams(window.location.search);
      const initialView = urlParams.get('view');
      const initialEmojiId = urlParams.get('emoji');
      const initialDim = urlParams.get('dim') || '3d';
      const initialMode = urlParams.get('mode');

      if (initialView === 'docs' || window.location.pathname.endsWith('/documentation')) {
        showView('docs', false);
      } else if (initialEmojiId && state.emojiById.has(initialEmojiId)) {
        const targetEmoji = state.emojiById.get(initialEmojiId);
        await openDrawerForEmoji(targetEmoji, false, initialDim, initialMode);
        if (urlParams.get('menu') === 'open' && dom.previewDownloadBtn) {
          dom.previewDownloadBtn.click();
        }
      }
      setupGridResizeFlipObserver();
    } catch (err) {
      console.error('Failed to initialize Noto Emoji dataset:', err);
      dismissPageLoader();
      if (dom.gridSectionsContainer) {
        dom.gridSectionsContainer.innerHTML = `
          <div class="empty-state">
            <h3>Unable to load emoji catalog</h3>
            <p>Ensure data/emojis.json is accessible.</p>
          </div>
        `;
      }
    }
  }

  // --- Theme Management (Respects System Intent & x20web Sandbox) ---
  function initTheme() {
    const urlParams = new URLSearchParams(window.location.search);
    const themeParam = urlParams.get('theme');
    if (themeParam === 'dark' || themeParam === 'light') {
      applyTheme(themeParam, false);
      return;
    }

    const systemDarkQuery = window.matchMedia
      ? window.matchMedia('(prefers-color-scheme: dark)')
      : null;
    const savedTheme = safeStorageGet('noto_luminous_theme');
    if (savedTheme === 'dark' || savedTheme === 'light') {
      applyTheme(savedTheme, false);
    } else {
      const sysTheme = systemDarkQuery && systemDarkQuery.matches ? 'dark' : 'light';
      applyTheme(sysTheme, false);
    }

    if (systemDarkQuery && systemDarkQuery.addEventListener) {
      systemDarkQuery.addEventListener('change', (e) => {
        const sysTheme = e.matches ? 'dark' : 'light';
        safeStorageRemove('noto_luminous_theme');
        applyTheme(sysTheme, false);
      });
    }
  }

  function applyTheme(theme, persist = false) {
    state.theme = theme;
    dom.html.setAttribute('data-theme', theme);
    if (persist) {
      safeStorageSet('noto_luminous_theme', theme);
    }
    if (dom.themeToggleBtn) {
      const icon = dom.themeToggleBtn.querySelector('.material-symbols-outlined');
      if (icon) {
        icon.textContent = theme === 'dark' ? 'light_mode' : 'dark_mode';
      }
    }
  }

  function toggleTheme() {
    applyTheme(state.theme === 'light' ? 'dark' : 'light', true);
  }

  async function downloadStaticSiteZip(e) {
    if (e) e.preventDefault();
    showToast('Preparing static site .zip package...');
    try {
      const prebuiltRes = await fetch('noto-emoji-explorer-static-site.zip').catch(() => null);
      if (prebuiltRes && prebuiltRes.ok) {
        const blob = await prebuiltRes.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'noto-emoji-explorer-static-site.zip';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        setTimeout(() => URL.revokeObjectURL(url), 2000);
        showToast('Downloaded noto-emoji-explorer-static-site.zip');
        return;
      }
    } catch (_) {}

    // Fallback for x20web null-origin sandbox: build the complete static site .zip directly in memory
    try {
      const enc = new TextEncoder();
      const files = [];

      const fetchTextOrFallback = async (path, fallbackFn) => {
        try {
          const r = await fetch(path);
          if (r.ok) return await r.text();
        } catch (_) {}
        return fallbackFn ? fallbackFn() : '';
      };

      const htmlText = await fetchTextOrFallback('index.html', () => '<!DOCTYPE html>\n' + document.documentElement.outerHTML);
      const cssText = await fetchTextOrFallback('styles.css', () => {
        let css = '';
        for (const sheet of Array.from(document.styleSheets)) {
          try {
            if (sheet.href && sheet.href.includes('styles.css')) {
              css = Array.from(sheet.cssRules).map((r) => r.cssText).join('\n');
            }
          } catch (_) {}
        }
        return css;
      });
      const jsText = await fetchTextOrFallback('app.js', () => '');
      const lottieText = await fetchTextOrFallback('lottie_light.min.js', () => '');
      const emojisJsonStr = JSON.stringify(state.emojis);
      const emojisDataJsStr = 'window.__NOTO_EMOJIS_DATA__ = ' + emojisJsonStr + ';\n';
      const readmeStr = `# Noto Emoji Explorer — Self-Contained Static Site\n\nUpload this unzipped folder to your own x20web directory:\n  cp -r noto-emoji-explorer /google/data/rw/users/<xy>/<username>/www/\n\nThen open:\n  https://<username>.users.x20web.corp.google.com/www/noto-emoji-explorer/index.html\n`;

      if (htmlText) files.push({ name: 'noto-emoji-explorer/index.html', data: enc.encode(htmlText) });
      if (cssText) files.push({ name: 'noto-emoji-explorer/styles.css', data: enc.encode(cssText) });
      if (jsText) files.push({ name: 'noto-emoji-explorer/app.js', data: enc.encode(jsText) });
      if (lottieText) files.push({ name: 'noto-emoji-explorer/lottie_light.min.js', data: enc.encode(lottieText) });
      files.push({ name: 'noto-emoji-explorer/data/emojis_data.js', data: enc.encode(emojisDataJsStr) });
      files.push({ name: 'noto-emoji-explorer/data/emojis.json', data: enc.encode(emojisJsonStr) });
      files.push({ name: 'noto-emoji-explorer/README.md', data: enc.encode(readmeStr) });

      const zipBlob = createZipBlob(files);
      const url = URL.createObjectURL(zipBlob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'noto-emoji-explorer-static-site.zip';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(url), 2000);
      showToast('Downloaded noto-emoji-explorer-static-site.zip');
    } catch (err) {
      console.error('Failed to generate static site zip:', err);
      showToast('Unable to download zip');
    }
  }

  // --- Event Listeners & Keyboard Accessibility ---
  function setupEventListeners() {
    dom.themeToggleBtn?.addEventListener('click', toggleTheme);
    dom.headerDownloadSiteBtn?.addEventListener('click', downloadStaticSiteZip);
    dom.docsDownloadSiteBtn?.addEventListener('click', downloadStaticSiteZip);

    if (dom.brandHomeLink) {
      dom.brandHomeLink.addEventListener('click', (e) => {
        e.preventDefault();
        showView('emoji', true);
      });
    }
    if (dom.navHomeBtn) {
      dom.navHomeBtn.addEventListener('click', () => showView('emoji', true));
    }
    if (dom.navDocsBtn) {
      dom.navDocsBtn.addEventListener('click', () => showView('docs', true));
    }
    if (dom.docsExpandAllBtn && dom.docsFaqList) {
      dom.docsExpandAllBtn.addEventListener('click', () => {
        const items = Array.from(dom.docsFaqList.querySelectorAll('details.docs-faq-item'));
        const allOpen = items.every((d) => d.open);
        items.forEach((d) => {
          d.open = !allOpen;
        });
        dom.docsExpandAllBtn.textContent = allOpen ? 'Expand All' : 'Collapse All';
      });
    }

    // Search (always global — resets any active category filter chip to 'all')
    let searchTimer = null;
    dom.searchInput?.addEventListener('input', (e) => {
      const val = e.target.value;
      dom.searchClearBtn?.classList.toggle('visible', val.length > 0);
      if (val.trim().length > 0 && state.activeCategory !== 'all') {
        state.activeCategory = 'all';
        updateActiveCategoryPill();
      }
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => {
        state.searchQuery = val.trim().toLowerCase();
        renderFilteredGrid();
      }, 60);
    });

    dom.searchClearBtn?.addEventListener('click', () => {
      if (dom.searchInput) dom.searchInput.value = '';
      dom.searchClearBtn.classList.remove('visible');
      state.searchQuery = '';
      renderFilteredGrid();
      dom.searchInput?.focus();
    });

    // Side Drawer controls
    dom.drawerCloseBtn?.addEventListener('click', closeDrawer);
    dom.drawerShareBtn?.addEventListener('click', copyDirectLink);

    // 3D / 2D Segmented Toggle + Arrow key support
    dom.dimBtn3d?.addEventListener('click', () => {
      if (state.selectedEmoji) setDimension(state.selectedEmoji, '3d');
    });
    dom.dimBtn2d?.addEventListener('click', () => {
      if (state.selectedEmoji) setDimension(state.selectedEmoji, '2d');
    });
    setupTablistArrowNavigation(dom.dimToggleGroup);

    // Icon-only Download Button (top right of preview area) opens download menu
    dom.previewDownloadBtn?.addEventListener('click', (e) => {
      e.stopPropagation();
      if (!state.selectedEmoji) return;
      renderDownloadDropdownMenu(state.selectedEmoji);
      const isOpen = dom.downloadDropdownMenu?.classList.toggle('open');
      dom.previewDownloadBtn.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    });

    document.addEventListener('click', (e) => {
      if (
        dom.downloadDropdownMenu &&
        dom.downloadDropdownMenu.classList.contains('open') &&
        !dom.downloadDropdownMenu.contains(e.target) &&
        e.target !== dom.previewDownloadBtn &&
        !dom.previewDownloadBtn?.contains(e.target)
      ) {
        dom.downloadDropdownMenu.classList.remove('open');
        dom.previewDownloadBtn?.setAttribute('aria-expanded', 'false');
      }
    });

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && dom.downloadDropdownMenu && dom.downloadDropdownMenu.classList.contains('open')) {
        dom.downloadDropdownMenu.classList.remove('open');
        dom.previewDownloadBtn?.setAttribute('aria-expanded', 'false');
      }
    });

    // Global Keyboard Shortcuts & Roving Grid Arrow Navigation
    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        if (state.isDrawerOpen) {
          closeDrawer();
        }
      } else if (e.key === '/' && document.activeElement !== dom.searchInput) {
        e.preventDefault();
        dom.searchInput?.focus();
      }
    });
  }

  function setupTablistArrowNavigation(container) {
    if (!container) return;
    container.addEventListener('keydown', (e) => {
      if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
      const tabs = Array.from(container.querySelectorAll('[role="tab"]'));
      const currentIdx = tabs.indexOf(document.activeElement);
      if (currentIdx === -1) return;
      e.preventDefault();
      const nextIdx =
        e.key === 'ArrowRight'
          ? (currentIdx + 1) % tabs.length
          : (currentIdx - 1 + tabs.length) % tabs.length;
      tabs[nextIdx].focus();
      tabs[nextIdx].click();
    });
  }

  const CATEGORY_MATERIAL_ICONS = {
    'Smileys & Emotion': 'emoji_emotions',
    'People & Body': 'emoji_people',
    'Animals & Nature': 'emoji_nature',
    'Food & Drink': 'emoji_food_beverage',
    'Activity': 'emoji_events',
    'Travel & Places': 'emoji_transportation',
    'Objects': 'emoji_objects',
    'Symbols': 'emoji_symbols',
    'Flags': 'emoji_flags',
  };

  // --- Category Filter Pills (ARIA Tablist with Arrow Key Navigation) ---
  function renderCategoryPills() {
    dom.categoryPills.innerHTML = '';

    dom.categoryPills.appendChild(createCategoryPillButton('all', 'All'));

    state.categories.forEach((cat) => {
      dom.categoryPills.appendChild(createCategoryPillButton(cat.name, cat.name));
    });

    setupTablistArrowNavigation(dom.categoryPills);
    updateActiveCategoryPill();
  }

  function createCategoryPillButton(categoryId, labelText) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'cat-pill';
    btn.setAttribute('role', 'tab');
    btn.dataset.category = categoryId;
    btn.title = labelText;
    btn.setAttribute('aria-label', labelText);

    const iconName = CATEGORY_MATERIAL_ICONS[categoryId];
    if (iconName) {
      btn.classList.add('cat-pill--icon');
      btn.innerHTML = `<span class="material-symbols-outlined cat-pill-icon" aria-hidden="true">${iconName}</span>`;
    } else {
      btn.textContent = labelText;
    }

    btn.addEventListener('click', () => {
      state.activeCategory = categoryId;
      if (categoryId !== 'all' && state.searchQuery) {
        state.searchQuery = '';
        if (dom.searchInput) dom.searchInput.value = '';
        if (dom.searchClearBtn) dom.searchClearBtn.classList.remove('visible');
      }
      updateActiveCategoryPill();
      renderFilteredGrid();
      window.scrollTo({
        top: 0,
        behavior: prefersReducedMotion() ? 'auto' : 'smooth',
      });
    });
    return btn;
  }

  function updateActiveCategoryPill() {
    dom.categoryPills.querySelectorAll('.cat-pill').forEach((btn) => {
      const isActive = btn.dataset.category === state.activeCategory;
      btn.classList.toggle('active', isActive);
      btn.setAttribute('aria-selected', isActive ? 'true' : 'false');
      btn.tabIndex = isActive ? 0 : -1;
    });
  }

  // --- Progressive Chunked Grid Filtering & Rendering Engine ---
  function getFilteredEmojis() {
    let list = state.emojis;

    // Searches are always global across all emojis
    if (state.searchQuery) {
      const q = state.searchQuery;
      return list.filter((e) => {
        return (
          (e.name && e.name.toLowerCase().includes(q)) ||
          (e.cldrName && e.cldrName.toLowerCase().includes(q)) ||
          (e.shortcode && e.shortcode.toLowerCase().includes(q)) ||
          (e.codepoint && e.codepoint.toLowerCase().includes(q)) ||
          (e.id && e.id.toLowerCase().includes(q))
        );
      });
    }

    if (state.activeCategory !== 'all') {
      list = list.filter((e) => e.category === state.activeCategory);
    }

    return list;
  }

  let gridSentinelObserver = null;

  function renderFilteredGrid() {
    // Cancel any in-flight progressive chunk loop or sentinel observer
    if (state.renderToken) {
      state.renderToken.cancelled = true;
    }
    const currentToken = { cancelled: false };
    state.renderToken = currentToken;

    if (gridSentinelObserver) {
      gridSentinelObserver.disconnect();
      gridSentinelObserver = null;
    }
    if (viewportCardObserver) {
      viewportCardObserver.disconnect();
    }
    if (imageHydrationObserver) {
      imageHydrationObserver.disconnect();
    }
    visibleCardsSet.clear();

    const filtered = getFilteredEmojis();
    state.filteredList = filtered;
    dom.gridSectionsContainer.innerHTML = '';

    announceSrStatus(
      filtered.length === 0
        ? 'No matching emojis found'
        : `Showing ${filtered.length} emojis`
    );

    if (filtered.length === 0) {
      dom.gridSectionsContainer.innerHTML = `
        <div class="empty-state">
          <h3>No matching emojis</h3>
          <p>Try searching for another name or clearing filters.</p>
        </div>
      `;
      return;
    }

    // Build flat ordered list of render tasks
    const renderTasks = filtered.map((emoji, index) => ({
      emoji,
      index,
      category: emoji.category || 'Other',
    }));

    const mountedCategoryGrids = new Map();
    let cursor = 0;

    // Create scroll sentinel at the bottom of the container
    const sentinelEl = document.createElement('div');
    sentinelEl.id = 'grid-scroll-sentinel';
    sentinelEl.className = 'grid-scroll-sentinel';
    sentinelEl.setAttribute('aria-hidden', 'true');
    dom.gridSectionsContainer.appendChild(sentinelEl);

    function mountCardsUpTo(targetCount) {
      if (currentToken.cancelled) return;
      const limit = Math.min(targetCount, renderTasks.length);
      if (cursor >= limit) return;

      const fragmentByGrid = new Map();

      for (; cursor < limit; cursor++) {
        const task = renderTasks[cursor];
        let grid = mountedCategoryGrids.get(task.category);
        if (!grid) {
          const section = document.createElement('section');
          section.className = 'category-section';
          section.setAttribute('data-category', task.category);

          const header = document.createElement('div');
          header.className = 'category-header';
          header.innerHTML = `<h2 class="category-title">${escapeHtml(task.category)}</h2>`;
          section.appendChild(header);

          grid = document.createElement('div');
          grid.className = 'emoji-grid';
          section.appendChild(grid);

          if (sentinelEl.parentNode === dom.gridSectionsContainer) {
            dom.gridSectionsContainer.insertBefore(section, sentinelEl);
          } else {
            dom.gridSectionsContainer.appendChild(section);
          }
          mountedCategoryGrids.set(task.category, grid);
        }

        let frag = fragmentByGrid.get(grid);
        if (!frag) {
          frag = document.createDocumentFragment();
          fragmentByGrid.set(grid, frag);
        }
        const card = createEmojiCard(task.emoji, task.index);
        frag.appendChild(card);
      }

      fragmentByGrid.forEach((frag, grid) => {
        grid.appendChild(frag);
      });

      if (cursor >= renderTasks.length && sentinelEl.parentNode) {
        if (gridSentinelObserver) {
          gridSentinelObserver.disconnect();
          gridSentinelObserver = null;
        }
        sentinelEl.parentNode.removeChild(sentinelEl);
      }
    }

    // Expose on state so keyboard navigation or deep links can mount up to any index on demand
    state.ensureCardMounted = (targetIndex) => {
      mountCardsUpTo(targetIndex + 24);
    };

    // 1. Synchronously mount ONLY the initial viewport batch (60 cards) in < 3ms
    mountCardsUpTo(INITIAL_MOUNT_COUNT);
    requestAnimationFrame(() => snapshotVisibleGridRects());

    // 2. Observe the bottom sentinel so additional cards mount strictly when the user scrolls down
    if (cursor < renderTasks.length && typeof IntersectionObserver !== 'undefined') {
      gridSentinelObserver = new IntersectionObserver(
        (entries) => {
          if (currentToken.cancelled) return;
          for (let i = 0; i < entries.length; i++) {
            if (entries[i].isIntersecting) {
              mountCardsUpTo(cursor + SCROLL_BATCH_SIZE);
              // If the sentinel is still within 500px of viewport (e.g. tall monitor or fast flick scroll),
              // check once on the next animation frame
              requestAnimationFrame(() => {
                if (!currentToken.cancelled && cursor < renderTasks.length && sentinelEl.parentNode) {
                  const rect = sentinelEl.getBoundingClientRect();
                  if (rect.top <= (window.innerHeight || 900) + 500) {
                    mountCardsUpTo(cursor + SCROLL_BATCH_SIZE);
                  }
                }
              });
              break;
            }
          }
        },
        { rootMargin: '500px 0px' }
      );
      gridSentinelObserver.observe(sentinelEl);
    }
  }

  // Progressive CDN Emoji Card with Tight Viewport Hydration & Roving Tabindex
  function createEmojiCard(emoji, index) {
    const card = document.createElement('article');
    card.className = 'emoji-card';
    const isSelected = state.selectedEmoji && state.selectedEmoji.id === emoji.id;
    if (isSelected) {
      card.classList.add('selected');
    }
    card.dataset.id = emoji.id;
    card.dataset.index = index;
    card.tabIndex = isSelected || (!state.selectedEmoji && index === 0) ? 0 : -1;
    card.setAttribute('role', 'gridcell');
    card.setAttribute('aria-label', `${emoji.cldrName || emoji.name}`);

    const thumbUrl = getCdn3dUrl(emoji, '128.png');
    const isEager = index < FIRST_EAGER_IMAGES;

    const imgWrap = document.createElement('div');
    imgWrap.className = 'emoji-card__img-wrap is-loading';

    const img = document.createElement('img');
    img.className = 'emoji-card__img emoji-card__img--loading';
    img.width = 76;
    img.height = 76;
    img.decoding = 'async';
    img.alt = emoji.cldrName || emoji.name;

    const onImgReady = () => {
      img.classList.remove('emoji-card__img--loading');
      img.classList.add('emoji-card__img--loaded');
      imgWrap.classList.remove('is-loading');
    };

    if (isEager) {
      // Top visible rows download immediately at high priority with zero observer delay
      img.onload = onImgReady;
      img.onerror = onImgReady;
      img.src = thumbUrl;
      if (img.complete && img.naturalWidth > 0) {
        onImgReady();
      }
    } else {
      // Offscreen cards hold a lightweight 1x1 transparent pixel until within 220px of viewport
      img.src = EMPTY_PIXEL;
      img.setAttribute('data-src', thumbUrl);
    }

    imgWrap.appendChild(img);

    const nameDiv = document.createElement('div');
    nameDiv.className = 'emoji-card__name';
    nameDiv.title = emoji.cldrName || emoji.name;
    nameDiv.textContent = emoji.name;

    card.appendChild(imgWrap);
    card.appendChild(nameDiv);

    if (viewportCardObserver) {
      viewportCardObserver.observe(card);
    }
    if (!isEager && imageHydrationObserver) {
      imageHydrationObserver.observe(card);
    }

    card.addEventListener('click', () => {
      if (state.isDrawerOpen && state.selectedEmoji && state.selectedEmoji.id === emoji.id) {
        closeDrawer();
        return;
      }
      openDrawerForEmoji(emoji, true, state.activeDimension);
    });

    card.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        if (state.isDrawerOpen && state.selectedEmoji && state.selectedEmoji.id === emoji.id) {
          closeDrawer();
          return;
        }
        openDrawerForEmoji(emoji, true, state.activeDimension).then(() => {
          dom.dimBtn3d.focus();
        });
      } else if (
        ['ArrowRight', 'ArrowLeft', 'ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key)
      ) {
        e.preventDefault();
        handleGridArrowNavigation(card, e.key);
      }
    });

    return card;
  }

  // WAI-ARIA 2D Roving Tabindex Grid Navigation
  function handleGridArrowNavigation(currentCard, key) {
    let cards = Array.from(dom.gridSectionsContainer.querySelectorAll('.emoji-card'));
    const idx = cards.indexOf(currentCard);
    if (idx === -1) return;

    // If navigating forward near the end of mounted cards, mount more cards on demand
    if (
      state.ensureCardMounted &&
      (key === 'ArrowRight' || key === 'ArrowDown' || key === 'End') &&
      idx >= cards.length - 16
    ) {
      state.ensureCardMounted(key === 'End' ? state.filteredList.length : idx + 32);
      cards = Array.from(dom.gridSectionsContainer.querySelectorAll('.emoji-card'));
    }

    let targetIdx = idx;
    if (key === 'ArrowRight') targetIdx = Math.min(cards.length - 1, idx + 1);
    else if (key === 'ArrowLeft') targetIdx = Math.max(0, idx - 1);
    else if (key === 'Home') targetIdx = 0;
    else if (key === 'End') targetIdx = cards.length - 1;
    else if (key === 'ArrowDown' || key === 'ArrowUp') {
      const currentRect = currentCard.getBoundingClientRect();
      const step = key === 'ArrowDown' ? 1 : -1;
      let candidate = idx + step;
      while (candidate >= 0 && candidate < cards.length) {
        const rect = cards[candidate].getBoundingClientRect();
        if (
          Math.abs(rect.left - currentRect.left) < 30 &&
          Math.abs(rect.top - currentRect.top) > 40
        ) {
          targetIdx = candidate;
          break;
        }
        candidate += step;
      }
    }

    if (targetIdx !== idx && cards[targetIdx]) {
      currentCard.tabIndex = -1;
      cards[targetIdx].tabIndex = 0;
      cards[targetIdx].focus();
    }
  }

  // --- GPU-Composited FLIP (First, Last, Invert, Play) Grid Transition Engine ---
  const gridFlipState = {
    lastRects: new Map(),
    lastWidth: 0,
    isFlipping: false,
    scrollRaf: null,
  };

  function getViewportEmojiCards() {
    // O(1) lookup via IntersectionObserver set — never query or measure all 3,988 DOM nodes!
    const visible = [];
    const vh = window.innerHeight || 900;
    const buffer = 280;
    const candidates =
      visibleCardsSet.size > 0
        ? visibleCardsSet
        : dom.gridSectionsContainer.querySelectorAll('.emoji-card');

    candidates.forEach((el) => {
      const r = el.getBoundingClientRect();
      if (r.bottom >= -buffer && r.top <= vh + buffer) {
        visible.push({ el, rect: r });
      }
    });
    return visible;
  }

  function snapshotVisibleGridRects() {
    gridFlipState.lastRects.clear();
    const visible = getViewportEmojiCards();
    visible.forEach(({ el, rect }) => {
      gridFlipState.lastRects.set(el, { left: rect.left, top: rect.top });
    });
  }

  function animateFlipFromSnapshot(firstRectsMap) {
    if (prefersReducedMotion()) {
      snapshotVisibleGridRects();
      return;
    }

    const visibleAfter = getViewportEmojiCards();
    const inverted = [];

    visibleAfter.forEach(({ el, rect }) => {
      const prev = firstRectsMap.get(el);
      if (!prev) return;
      const dx = prev.left - rect.left;
      const dy = prev.top - rect.top;
      if (Math.abs(dx) > 1 || Math.abs(dy) > 1) {
        el.classList.add('flip-inverting');
        el.style.transform = `translate3d(${dx}px, ${dy}px, 0)`;
        inverted.push(el);
      }
    });

    if (inverted.length > 0) {
      gridFlipState.isFlipping = true;
      void document.body.offsetHeight;
      requestAnimationFrame(() => {
        inverted.forEach((el) => {
          el.classList.remove('flip-inverting');
          el.style.transform = '';
        });
        setTimeout(() => {
          gridFlipState.isFlipping = false;
          snapshotVisibleGridRects();
        }, 380);
      });
    } else {
      snapshotVisibleGridRects();
    }
  }

  function runWithGridFlip(mutateFn) {
    const firstRects = new Map();
    getViewportEmojiCards().forEach(({ el, rect }) => {
      firstRects.set(el, { left: rect.left, top: rect.top });
    });
    mutateFn();
    animateFlipFromSnapshot(firstRects);
  }

  function setupGridResizeFlipObserver() {
    snapshotVisibleGridRects();
    gridFlipState.lastWidth = dom.workspaceLayout ? dom.workspaceLayout.clientWidth : window.innerWidth;

    window.addEventListener(
      'scroll',
      () => {
        if (gridFlipState.scrollRaf || gridFlipState.isFlipping) return;
        gridFlipState.scrollRaf = requestAnimationFrame(() => {
          gridFlipState.scrollRaf = null;
          snapshotVisibleGridRects();
        });
      },
      { passive: true }
    );

    if (window.ResizeObserver && dom.workspaceLayout) {
      const ro = new ResizeObserver((entries) => {
        const entry = entries[0];
        if (!entry) return;
        const currentWidth = entry.contentRect.width;
        if (
          gridFlipState.isFlipping ||
          currentWidth === 0 ||
          gridFlipState.lastWidth === 0 ||
          Math.abs(currentWidth - gridFlipState.lastWidth) < 1
        ) {
          gridFlipState.lastWidth = currentWidth;
          if (currentWidth > 0) snapshotVisibleGridRects();
          return;
        }
        gridFlipState.lastWidth = currentWidth;
        animateFlipFromSnapshot(gridFlipState.lastRects);
      });
      ro.observe(dom.workspaceLayout);
    }
  }

  // --- Side Drawer & 3D / 2D Segmented Switcher ---
  async function openDrawerForEmoji(emoji, updateUrl = true, dimension = '3d', modeOverride = null) {
    const wasDrawerOpen = state.isDrawerOpen;
    state.selectedEmoji = emoji;
    state.isDrawerOpen = true;

    if (!wasDrawerOpen) {
      runWithGridFlip(() => {
        dom.sideDrawer.classList.add('open');
        document.body.classList.add('drawer-open');
      });
    } else {
      dom.sideDrawer.classList.add('open');
      document.body.classList.add('drawer-open');
    }

    // Update roving tabindex and selected state across mounted grid cards
    dom.gridSectionsContainer.querySelectorAll('.emoji-card.selected').forEach((el) => {
      el.classList.remove('selected');
      el.tabIndex = -1;
    });
    const activeCard = dom.gridSectionsContainer.querySelector(`.emoji-card[data-id="${emoji.id}"]`);
    if (activeCard) {
      activeCard.classList.add('selected');
      activeCard.tabIndex = 0;
    }

    const displayName = emoji.name || emoji.cldrName;
    dom.drawerEmojiName.textContent = displayName;
    dom.drawerEmojiName.title = displayName;

    if (dom.drawerCodepointChips) {
      dom.drawerCodepointChips.innerHTML = '';
      const cps = String(emoji.codepoint || '')
        .replace(/-/g, '_')
        .split('_')
        .filter(Boolean);
      if (cps.length > 0) {
        const formattedCp = cps.map((cp) => `U+${cp.toUpperCase()}`).join(' + ');
        const chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'codepoint-chip';
        chip.textContent = formattedCp;
        chip.title = `Copy ${formattedCp}`;
        chip.addEventListener('click', () => {
          navigator.clipboard.writeText(formattedCp).then(() => {
            showToast(`Copied ${formattedCp}`);
          });
        });
        dom.drawerCodepointChips.appendChild(chip);
      }
    }

    if (dom.downloadDropdownMenu) {
      dom.downloadDropdownMenu.classList.remove('open');
      if (dom.previewDownloadBtn) {
        dom.previewDownloadBtn.setAttribute('aria-expanded', 'false');
      }
    }

    if (dom.drawerDateAdded) {
      dom.drawerDateAdded.textContent = emoji.dateAdded || 'Aug 4, 2015 (Unicode 8.0 / Emoji 1.0)';
    }
    if (dom.drawerUtcLink) {
      dom.drawerUtcLink.href = emoji.utcUrl || 'https://www.unicode.org/cgi-bin/GetDocumentLink?L2/09-026R';
      const authorSuffix = emoji.utcAuthor ? ` (${emoji.utcAuthor})` : '';
      dom.drawerUtcLink.title = `${emoji.utcDoc || 'L2/09-026R'} — ${emoji.utcTitle || 'UTC Proposal'}${authorSuffix}`;
    }
    if (dom.drawerUtcDoc) {
      dom.drawerUtcDoc.textContent = emoji.utcDoc || 'L2/09-026R';
    }
    if (dom.drawerUtcTitle) {
      const authorSuffix = emoji.utcAuthor ? ` · ${emoji.utcAuthor}` : '';
      dom.drawerUtcTitle.textContent = `${emoji.utcTitle || 'Emoji Symbols Proposed for New Inclusion in Unicode'}${authorSuffix}`;
    }

    if (updateUrl) {
      safeUpdateUrlParams((url) => {
        url.searchParams.set('emoji', emoji.id);
      });
    }

    await setDimension(emoji, dimension, modeOverride || 'static');
  }

  // Returns rendering type pills below the preview image:
  // - In 3D: Static, Animated (strictly no 3D Model)
  // - In 2D: Static, plus Animated ONLY if emoji.hasGfontsAnim is true (strictly no Monochromatic)
  function getFormatPillsForDimension(emoji, dim) {
    if (dim === '3d') {
      return [
        { id: 'static', label: 'Static' },
        { id: 'animated', label: 'Animated' },
      ];
    } else {
      const pills = [{ id: 'static', label: 'Static' }];
      if (emoji.hasGfontsAnim) {
        pills.push({ id: 'animated', label: 'Animated' });
      }
      return pills;
    }
  }

  async function setDimension(emoji, dim, modeOverride = null) {
    state.activeDimension = dim;
    dom.dimBtn3d.classList.toggle('active', dim === '3d');
    dom.dimBtn3d.setAttribute('aria-selected', dim === '3d' ? 'true' : 'false');
    dom.dimBtn2d.classList.toggle('active', dim === '2d');
    dom.dimBtn2d.setAttribute('aria-selected', dim === '2d' ? 'true' : 'false');

    const pills = getFormatPillsForDimension(emoji, dim);
    dom.previewModePills.innerHTML = '';

    let targetMode = modeOverride;
    if (!targetMode || !pills.some((p) => p.id === targetMode)) {
      if (state.activePreviewMode && pills.some((p) => p.id === state.activePreviewMode)) {
        targetMode = state.activePreviewMode;
      } else {
        targetMode = 'static';
      }
    }

    pills.forEach((p) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      const isActive = p.id === targetMode;
      btn.className = `preview-pill ${isActive ? 'active' : ''}`;
      btn.setAttribute('role', 'tab');
      btn.setAttribute('aria-selected', isActive ? 'true' : 'false');
      btn.tabIndex = isActive ? 0 : -1;
      btn.dataset.mode = p.id;
      btn.textContent = p.label;
      btn.addEventListener('click', () => {
        setPreviewMode(emoji, p.id);
      });
      dom.previewModePills.appendChild(btn);
    });

    setupTablistArrowNavigation(dom.previewModePills);
    await setPreviewMode(emoji, targetMode);
  }

  // Updates Embed Code snippets strictly using official Emoji CDN URLs
  function updateEmbedSnippets(emoji) {
    const embedSection = document.getElementById('drawer-embed-section');
    dom.drawerEmbedList.innerHTML = '';

    const dim = state.activeDimension;
    const charAlt = escapeHtml(emoji.char || emoji.name);

    if (dim === '3d') {
      if (embedSection) embedSection.style.display = 'block';
      const png3dUrl = getCdn3dUrl(emoji, '512.png');
      const pngSnippet = `<img src="${png3dUrl}" alt="${charAlt}" width="72" height="72">`;
      dom.drawerEmbedList.appendChild(
        createEmbedBox(
          'Web (3D Static PNG)',
          pngSnippet,
          'Embed the high-resolution 3D PNG directly from the Google Fonts Emoji CDN.'
        )
      );

      if (emoji.hasCdn3dAnim) {
        const webp3dUrl = getCdn3dUrl(emoji, '512.webp');
        const gif3dUrl = getCdn3dUrl(emoji, '512.gif');
        const anim3dSnippet = `<picture>\n  <source srcset="${webp3dUrl}" type="image/webp">\n  <img src="${gif3dUrl}" alt="${charAlt}" width="72" height="72">\n</picture>`;
        dom.drawerEmbedList.appendChild(
          createEmbedBox(
            'Web (3D Animated)',
            anim3dSnippet,
            'Reference both the animated 3D WebP and GIF versions from the Google Fonts Emoji CDN.'
          )
        );
      }
    } else {
      if (embedSection) embedSection.style.display = 'block';
      const svg2dUrl = getCdn2dUrl(emoji, 'emoji.svg');
      const svgSnippet = `<img src="${svg2dUrl}" alt="${charAlt}" width="72" height="72">`;
      dom.drawerEmbedList.appendChild(
        createEmbedBox(
          'Web (2D Vector SVG)',
          svgSnippet,
          'Embed the crisp vector SVG directly from the Google Fonts Emoji CDN.'
        )
      );

      if (emoji.hasGfontsAnim) {
        const lottieUrl = getCdn2dUrl(emoji, 'lottie.json');
        dom.drawerEmbedList.appendChild(
          createEmbedBox(
            'Lottie',
            lottieUrl,
            'With Lottie files, you have control over where and how the animation is played back.'
          )
        );
        const webpUrl = getCdn2dUrl(emoji, '512.webp');
        const gifUrl = getCdn2dUrl(emoji, '512.gif');
        const webpSnippet = `<picture>\n  <source srcset="${webpUrl}" type="image/webp">\n  <img src="${gifUrl}" alt="${charAlt}" width="72" height="72">\n</picture>`;
        dom.drawerEmbedList.appendChild(
          createEmbedBox(
            'Web (2D Animated)',
            webpSnippet,
            'With the <picture> HTML element, you can reference both the WebP and GIF versions to let the browser figure out which version to use based on what it supports.'
          )
        );
      }
    }
  }

  function createEmbedBox(label, codeStr, description = '') {
    const box = document.createElement('div');
    box.className = 'embed-box';
    const descHtml = description
      ? `<p class="embed-box__desc">${escapeHtml(description)}</p>`
      : '';
    box.innerHTML = `
      <div class="embed-box__header">
        <span class="embed-box__label">${escapeHtml(label)}</span>
        <button type="button" class="embed-copy-btn" title="Copy ${escapeHtml(label)}" aria-label="Copy ${escapeHtml(label)}">
          <span class="material-symbols-outlined">content_copy</span>
        </button>
      </div>
      ${descHtml}
      <div class="embed-box__code">${escapeHtml(codeStr)}</div>
    `;

    const copyBtn = box.querySelector('.embed-copy-btn');
    copyBtn.addEventListener('click', () => {
      navigator.clipboard.writeText(codeStr).then(() => {
        copyBtn.innerHTML = `<span class="material-symbols-outlined">check</span>`;
        showToast(`Copied ${label}`);
        setTimeout(() => {
          copyBtn.innerHTML = `<span class="material-symbols-outlined">content_copy</span>`;
        }, 1500);
      });
    });

    return box;
  }

  function renderComingSoonPlaceholder(formatName) {
    const placeholder = document.createElement('div');
    placeholder.className = 'tiff-preview-placeholder coming-soon-placeholder';
    placeholder.innerHTML = `
      <span class="material-symbols-outlined tiff-placeholder-icon">schedule</span>
      <div class="tiff-placeholder-title">Coming Soon</div>
      <div class="tiff-placeholder-sub">${escapeHtml(formatName)} asset is not yet available</div>
    `;
    dom.previewStageContent.appendChild(placeholder);
  }

  function setDownloadButtonEnabled() {
    if (dom.previewDownloadBtn) {
      dom.previewDownloadBtn.disabled = false;
      dom.previewDownloadBtn.style.opacity = '';
      dom.previewDownloadBtn.title = 'Download files';
    }
  }

  async function setPreviewMode(emoji, mode) {
    state.activePreviewMode = mode;
    setDownloadButtonEnabled();

    if (state.activeLottieAnim) {
      try {
        state.activeLottieAnim.destroy();
      } catch (e) {}
      state.activeLottieAnim = null;
    }

    dom.previewModePills.querySelectorAll('.preview-pill').forEach((btn) => {
      const isActive = btn.dataset.mode === mode;
      btn.classList.toggle('active', isActive);
      btn.setAttribute('aria-selected', isActive ? 'true' : 'false');
      btn.tabIndex = isActive ? 0 : -1;
    });

    updateEmbedSnippets(emoji);
    renderDownloadDropdownMenu(emoji);
    dom.previewStageContent.innerHTML = '';

    const dim = state.activeDimension;

    if (mode === 'static') {
      if (dim === '3d') {
        const img = document.createElement('img');
        img.className = 'preview-img-3d';
        img.src = getCdn3dUrl(emoji, '512.png');
        img.alt = `${emoji.name} 3D Static PNG`;
        dom.previewStageContent.appendChild(img);
      } else {
        const img = document.createElement('img');
        img.className = 'preview-img-2d-svg';
        img.src = getCdn2dUrl(emoji, 'emoji.svg');
        img.alt = `${emoji.name} 2D SVG`;
        dom.previewStageContent.appendChild(img);
      }
    } else if (mode === 'animated') {
      if (dim === '3d') {
        if (emoji.hasCdn3dAnim) {
          const img = document.createElement('img');
          img.className = 'preview-img-3d';
          img.src = getCdn3dUrl(emoji, '512.webp');
          img.alt = `${emoji.name} 3D Animated WebP`;
          dom.previewStageContent.appendChild(img);
        } else {
          renderComingSoonPlaceholder('Animated 3D');
        }
      } else {
        if (emoji.hasGfontsAnim) {
          const container = document.createElement('div');
          container.className = 'lottie-stage';
          dom.previewStageContent.appendChild(container);

          await ensureLottieLoaded();
          if (window.lottie) {
            state.activeLottieAnim = window.lottie.loadAnimation({
              container: container,
              renderer: 'svg',
              loop: true,
              autoplay: !prefersReducedMotion(),
              path: getCdn2dUrl(emoji, 'lottie.json'),
            });
          }
        }
      }
    }
  }

  // --- Clean Download Dropdown Menu (Strictly CDN formats: 3D & 2D sections with clear divider & ZIP Download All) ---
  function getEmojiDownloadGroups(emoji) {
    const items3d = [
      { id: '3d_png', label: 'PNG', available: true },
      { id: '3d_webp', label: 'WebP', available: Boolean(emoji.hasCdn3dAnim) },
      { id: '3d_gif', label: 'GIF', available: Boolean(emoji.hasCdn3dAnim) },
    ];

    const items2d = [
      { id: '2d_svg', label: 'SVG', available: true },
      { id: '2d_png', label: 'PNG', available: true },
    ];
    if (emoji.hasGfontsAnim) {
      items2d.push(
        { id: '2d_lottie', label: 'Lottie JSON', available: true },
        { id: '2d_webp', label: 'WebP', available: true },
        { id: '2d_gif', label: 'GIF', available: true }
      );
    }

    return [
      { title: '3D', items: items3d },
      { title: '2D', items: items2d },
    ];
  }

  function renderDownloadDropdownMenu(emoji) {
    if (!dom.downloadDropdownMenu || !emoji) return;
    dom.downloadDropdownMenu.innerHTML = '';

    const groups = getEmojiDownloadGroups(emoji);
    const activeFirst = state.activeDimension === '2d' ? [groups[1], groups[0]] : [groups[0], groups[1]];

    activeFirst.forEach((group, groupIdx) => {
      if (groupIdx > 0) {
        const divider = document.createElement('div');
        divider.className = 'download-menu-divider';
        dom.downloadDropdownMenu.appendChild(divider);
      }

      const header = document.createElement('div');
      header.className = 'download-menu-header';
      header.textContent = group.title;
      dom.downloadDropdownMenu.appendChild(header);

      group.items.forEach((item) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'download-menu-item';
        btn.setAttribute('role', 'menuitem');
        btn.disabled = !item.available;

        btn.innerHTML = `
          <span class="download-menu-item__left">
            <span>${escapeHtml(item.label)}</span>
          </span>
          <span class="download-menu-item__badge">
            ${
              item.available
                ? '<span class="material-symbols-outlined" style="font-size: 16px;">download</span>'
                : 'Coming soon'
            }
          </span>
        `;

        if (item.available) {
          btn.addEventListener('click', () => {
            dom.downloadDropdownMenu.classList.remove('open');
            if (dom.previewDownloadBtn) {
              dom.previewDownloadBtn.setAttribute('aria-expanded', 'false');
            }
            downloadSpecificFormat(emoji, item.id);
          });
        }
        dom.downloadDropdownMenu.appendChild(btn);
      });
    });

    const divider = document.createElement('div');
    divider.className = 'download-menu-divider';
    dom.downloadDropdownMenu.appendChild(divider);

    const allBtn = document.createElement('button');
    allBtn.type = 'button';
    allBtn.className = 'download-menu-item download-menu-item--all';
    allBtn.setAttribute('role', 'menuitem');
    allBtn.innerHTML = `
      <span class="download-menu-item__left">
        <span class="material-symbols-outlined" style="font-size: 18px;">download_for_offline</span>
        <span>Download All</span>
      </span>
    `;
    allBtn.addEventListener('click', () => {
      dom.downloadDropdownMenu.classList.remove('open');
      if (dom.previewDownloadBtn) {
        dom.previewDownloadBtn.setAttribute('aria-expanded', 'false');
      }
      downloadAllEmojiAssets(emoji);
    });
    dom.downloadDropdownMenu.appendChild(allBtn);
  }

  function downloadSpecificFormat(emoji, formatId) {
    if (!emoji) return;
    if (formatId === '3d_png') {
      downloadExternalAsset(getCdn3dUrl(emoji, '512.png'), `${emoji.id}_3d.png`);
    } else if (formatId === '3d_webp' && emoji.hasCdn3dAnim) {
      downloadExternalAsset(getCdn3dUrl(emoji, '512.webp'), `${emoji.id}_3d.webp`);
    } else if (formatId === '3d_gif' && emoji.hasCdn3dAnim) {
      downloadExternalAsset(getCdn3dUrl(emoji, '512.gif'), `${emoji.id}_3d.gif`);
    } else if (formatId === '2d_svg') {
      downloadExternalAsset(getCdn2dUrl(emoji, 'emoji.svg'), `${emoji.id}_2d.svg`);
    } else if (formatId === '2d_png') {
      downloadExternalAsset(getCdn2dUrl(emoji, '512.png'), `${emoji.id}_2d.png`);
    } else if (formatId === '2d_lottie' && emoji.hasGfontsAnim) {
      downloadExternalAsset(getCdn2dUrl(emoji, 'lottie.json'), `${emoji.id}_lottie.json`);
    } else if (formatId === '2d_webp' && emoji.hasGfontsAnim) {
      downloadExternalAsset(getCdn2dUrl(emoji, '512.webp'), `${emoji.id}_2d.webp`);
    } else if (formatId === '2d_gif' && emoji.hasGfontsAnim) {
      downloadExternalAsset(getCdn2dUrl(emoji, '512.gif'), `${emoji.id}_2d.gif`);
    }
  }

  // Zero-dependency uncompressed ZIP generator (STORE method 0) so Download All bundles into a single .zip
  function createZipBlob(files) {
    const crcTable = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) {
        c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      }
      crcTable[n] = c;
    }

    function crc32(bytes) {
      let crc = 0xffffffff;
      for (let i = 0; i < bytes.length; i++) {
        crc = crcTable[(crc ^ bytes[i]) & 0xff] ^ (crc >>> 8);
      }
      return (crc ^ 0xffffffff) >>> 0;
    }

    const encoder = new TextEncoder();
    const localHeaders = [];
    const centralHeaders = [];
    let offset = 0;

    for (const file of files) {
      const nameBytes = encoder.encode(file.name);
      const dataBytes = file.data;
      const crc = crc32(dataBytes);
      const size = dataBytes.length;

      const localHeader = new Uint8Array(30 + nameBytes.length);
      const lv = new DataView(localHeader.buffer);
      lv.setUint32(0, 0x04034b50, true);
      lv.setUint16(4, 20, true);
      lv.setUint16(6, 0, true);
      lv.setUint16(8, 0, true); // STORE (no compression)
      lv.setUint16(10, 0, true);
      lv.setUint16(12, 0, true);
      lv.setUint32(14, crc, true);
      lv.setUint32(18, size, true);
      lv.setUint32(22, size, true);
      lv.setUint16(26, nameBytes.length, true);
      lv.setUint16(28, 0, true);
      localHeader.set(nameBytes, 30);

      localHeaders.push(localHeader, dataBytes);

      const centralHeader = new Uint8Array(46 + nameBytes.length);
      const cv = new DataView(centralHeader.buffer);
      cv.setUint32(0, 0x02014b50, true);
      cv.setUint16(4, 20, true);
      cv.setUint16(6, 20, true);
      cv.setUint16(8, 0, true);
      cv.setUint16(10, 0, true);
      cv.setUint16(12, 0, true);
      cv.setUint16(14, 0, true);
      cv.setUint32(16, crc, true);
      cv.setUint32(20, size, true);
      cv.setUint32(24, size, true);
      cv.setUint16(28, nameBytes.length, true);
      cv.setUint16(30, 0, true);
      cv.setUint16(32, 0, true);
      cv.setUint16(34, 0, true);
      cv.setUint16(36, 0, true);
      cv.setUint32(38, 0, true);
      cv.setUint32(42, offset, true);
      centralHeader.set(nameBytes, 46);

      centralHeaders.push(centralHeader);
      offset += localHeader.length + size;
    }

    let centralSize = 0;
    centralHeaders.forEach((ch) => (centralSize += ch.length));

    const endRecord = new Uint8Array(22);
    const ev = new DataView(endRecord.buffer);
    ev.setUint32(0, 0x06054b50, true);
    ev.setUint16(4, 0, true);
    ev.setUint16(6, 0, true);
    ev.setUint16(8, files.length, true);
    ev.setUint16(10, files.length, true);
    ev.setUint32(12, centralSize, true);
    ev.setUint32(16, offset, true);
    ev.setUint16(20, 0, true);

    return new Blob([...localHeaders, ...centralHeaders, endRecord], { type: 'application/zip' });
  }

  async function downloadAllEmojiAssets(emoji) {
    if (!emoji) return;
    showToast(`Preparing ${emoji.id}_assets.zip...`);
    const files = [];

    async function tryFetchBytes(url) {
      try {
        const res = await fetch(url);
        if (!res.ok) return null;
        return new Uint8Array(await res.arrayBuffer());
      } catch (e) {
        return null;
      }
    }

    // 3D CDN Assets
    const png3dBytes = await tryFetchBytes(getCdn3dUrl(emoji, '512.png'));
    if (png3dBytes) {
      files.push({ name: `${emoji.id}_3d.png`, data: png3dBytes });
    }

    if (emoji.hasCdn3dAnim) {
      const webp3dBytes = await tryFetchBytes(getCdn3dUrl(emoji, '512.webp'));
      if (webp3dBytes) files.push({ name: `${emoji.id}_3d_animated.webp`, data: webp3dBytes });

      const gif3dBytes = await tryFetchBytes(getCdn3dUrl(emoji, '512.gif'));
      if (gif3dBytes) files.push({ name: `${emoji.id}_3d_animated.gif`, data: gif3dBytes });
    }

    // 2D CDN Assets
    const svgBytes = await tryFetchBytes(getCdn2dUrl(emoji, 'emoji.svg'));
    if (svgBytes) files.push({ name: `${emoji.id}_2d.svg`, data: svgBytes });

    const png2dBytes = await tryFetchBytes(getCdn2dUrl(emoji, '512.png'));
    if (png2dBytes) files.push({ name: `${emoji.id}_2d.png`, data: png2dBytes });

    if (emoji.hasGfontsAnim) {
      const lottieBytes = await tryFetchBytes(getCdn2dUrl(emoji, 'lottie.json'));
      if (lottieBytes) files.push({ name: `${emoji.id}_2d_lottie.json`, data: lottieBytes });

      const webp2dBytes = await tryFetchBytes(getCdn2dUrl(emoji, '512.webp'));
      if (webp2dBytes) files.push({ name: `${emoji.id}_2d_animated.webp`, data: webp2dBytes });

      const gif2dBytes = await tryFetchBytes(getCdn2dUrl(emoji, '512.gif'));
      if (gif2dBytes) files.push({ name: `${emoji.id}_2d_animated.gif`, data: gif2dBytes });
    }

    if (files.length === 0) {
      showToast('No downloadable files found');
      return;
    }

    const zipBlob = createZipBlob(files);
    const zipUrl = URL.createObjectURL(zipBlob);
    const a = document.createElement('a');
    a.href = zipUrl;
    a.download = `${emoji.id}_assets.zip`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(zipUrl), 1500);
    showToast(`Downloaded ${emoji.id}_assets.zip (${files.length} files)`);
  }

  function closeDrawer() {
    state.isDrawerOpen = false;
    state.selectedEmoji = null;
    dom.gridSectionsContainer.querySelectorAll('.emoji-card.selected').forEach((el) => {
      el.classList.remove('selected');
    });
    safeUpdateUrlParams((url) => {
      url.searchParams.delete('emoji');
    });
    runWithGridFlip(() => {
      dom.sideDrawer.classList.remove('open');
      document.body.classList.remove('drawer-open');
    });
  }

  // --- Download Helpers ---
  async function downloadExternalAsset(url, filename) {
    try {
      showToast(`Fetching ${filename}...`);
      const res = await fetch(url);
      const blob = await res.blob();
      const objUrl = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = objUrl;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(objUrl), 1000);
      showToast(`Downloaded ${filename}`);
    } catch (e) {
      window.open(url, '_blank', 'noopener');
    }
  }

  function copyDirectLink() {
    if (!state.selectedEmoji) return;
    const url = new URL(window.location.href);
    url.searchParams.set('emoji', state.selectedEmoji.id);
    url.searchParams.set('dim', state.activeDimension);
    url.searchParams.set('mode', state.activePreviewMode);
    navigator.clipboard.writeText(url.toString()).then(() => {
      showToast('Direct link copied');
    });
  }

  // --- Toast ---
  let toastTimer = null;
  function showToast(message) {
    dom.toastContainer.textContent = message;
    dom.toastContainer.classList.add('visible');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      dom.toastContainer.classList.remove('visible');
    }, 2200);
  }

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  document.addEventListener('DOMContentLoaded', init);
})();
