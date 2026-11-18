(() => {
  let key = null;
  // Keep the saved preference separate from the viewport's effective mode.
  let enabled = false;
  const desktop = window.matchMedia('(min-width: 76.25em)');
  const presenting = () => enabled && desktop.matches;
  let targets = [];
  let slides = [];
  const pageSlides = new WeakMap();
  let active = 0;
  let pending = false;
  const tocLabels = new WeakMap();

  const content = () => document.querySelector('.presentation-content');
  const offset = () => {
    const header = document.querySelector('.md-header');
    return Math.max(0, header?.getBoundingClientRect().bottom || 0) + 32;
  };

  function updateNavigation() {
    const page = content();
    if (!page) return;
    const nav = page.querySelector('.presentation-nav');
    nav.hidden = !presenting() || targets.length < 2;
    if (nav.hidden) return;
    const index = active;
    const heading = targets[index];
    const label = heading?.textContent.replace(/¶\s*$/, '').trim() || `Section ${index + 1}`;
    nav.querySelector('[data-section-title]').textContent = label;
    nav.querySelector('[data-section-count]').textContent = `${index + 1} / ${targets.length}`;
    nav.querySelector('[data-section-step="-1"]').disabled = index === 0;
    nav.querySelector('[data-section-step="1"]').disabled = index === targets.length - 1;
  }

  function render() {
    const page = content();
    if (!page) { targets = []; slides = []; return; }
    if (key === null) {
      const siteRoot = new URL(page.dataset.presentationRoot, location.href).pathname;
      key = `relcon-docs:presentation:${siteRoot}`;
      try { enabled = localStorage.getItem(key) === 'true'; } catch (_) {}
    }
    const button = page.querySelector('.presentation-toggle');
    const controls = page.querySelector('.presentation-controls');
    const copyButton = page.querySelector('[data-md-copy-url]');
    if (copyButton && copyButton.parentElement !== controls) controls.prepend(copyButton);
    page.classList.toggle('presentation-mode', presenting());
    document.querySelectorAll('.md-nav--secondary').forEach(nav => {
      const title = nav.querySelector(':scope > .md-nav__title');
      if (!title) return;
      // Preserve the theme's label and icon, including translated titles.
      if (!tocLabels.has(nav)) {
        tocLabels.set(nav, {
          aria: nav.getAttribute('aria-label'),
          text: [...title.childNodes].filter(node => node.nodeType === Node.TEXT_NODE)
            .map(node => [node, node.textContent]),
        });
      }
      const original = tocLabels.get(nav);
      original.text.forEach(([node, text], index) => {
        node.textContent = presenting() ? (index === 0 ? 'Table of contents' : '') : text;
      });
      if (presenting()) nav.setAttribute('aria-label', 'Table of contents');
      else if (original.aria !== null) nav.setAttribute('aria-label', original.aria);
      else nav.removeAttribute('aria-label');
    });
    button.setAttribute('aria-pressed', String(presenting()));
    button.hidden = !desktop.matches;

    // Wrap only top-level article blocks; nested rules remain inside their slide.
    if (!pageSlides.has(page)) {
      const groups = [];
      let section = null;
      [...page.children].forEach(element => {
        if (element.matches('.presentation-controls, .presentation-nav')) return;
        if (element.matches('hr')) { section = null; return; }
        if (!section) {
          section = document.createElement('section');
          section.className = 'presentation-slide';
          page.insertBefore(section, element);
          groups.push(section);
        }
        section.append(element);
      });
      pageSlides.set(page, {groups, active: 0});
    }
    const state = pageSlides.get(page);
    slides = state.groups;
    active = state.active;
    targets = slides.map(slide => {
      const heading = slide.querySelector('h1,h2,h3,h4,h5,h6');
      heading?.classList.add('presentation-slide-title');
      return heading;
    });
    const linked = hashTarget();
    if (linked) {
      const index = slides.findIndex(slide => slide.contains(linked));
      if (index >= 0) active = index;
    }
    showSlide(active);
  }

  function hashTarget(hash = location.hash) {
    if (!hash || hash === '#') return null;
    try { return document.getElementById(decodeURIComponent(hash.slice(1))); }
    catch (_) { return null; }
  }

  function updateToc() {
    if (!presenting() || !slides[active]) return;
    const headings = [...slides[active].querySelectorAll('h1,h2,h3,h4,h5,h6')];
    let current = headings[0];
    headings.forEach(heading => {
      if (heading.getBoundingClientRect().top <= offset() + 48) current = heading;
    });
    document.querySelectorAll('.md-nav--secondary a[href]').forEach(link => {
      const target = hashTarget(new URL(link.href).hash);
      link.classList.toggle('presentation-toc-active', target === current);
    });
  }

  function showSlide(index) {
    if (!slides.length) return;
    active = index;
    pageSlides.get(content()).active = index;
    slides.forEach((slide, i) => { slide.hidden = presenting() && i !== index; });
    updateNavigation();
    updateToc();
    // Let plots and diagrams recalculate their layout after becoming visible.
    requestAnimationFrame(() => window.dispatchEvent(new Event('resize')));
  }

  function move(step) {
    const index = Math.max(0, Math.min(slides.length - 1, active + step));
    if (!presenting() || !slides[index] || index === active) return;
    showSlide(index);
    const target = targets[index];
    if (target?.id) history.pushState(null, '', `#${encodeURIComponent(target.id)}`);
    else history.pushState(null, '', location.pathname + location.search);
    window.scrollTo({top: 0, behavior: 'instant'});
  }

  // Reveal a hidden slide before the theme follows a TOC or in-page link.
  document.addEventListener('click', event => {
    if (!presenting() || event.defaultPrevented || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const link = event.target instanceof Element ? event.target.closest('a[href]') : null;
    if (!link || link.target || link.hasAttribute('download')) return;
    const url = new URL(link.href);
    if (url.origin !== location.origin || url.pathname !== location.pathname || url.search !== location.search) return;
    const target = hashTarget(url.hash);
    const index = slides.findIndex(slide => slide.contains(target));
    if (index >= 0) showSlide(index);
  }, true);

  window.addEventListener('hashchange', () => {
    if (!presenting()) return;
    const target = hashTarget();
    const index = slides.findIndex(slide => slide.contains(target));
    if (index >= 0) {
      showSlide(index);
      target.scrollIntoView({block: 'start', behavior: 'instant'});
    }
  });

  document.addEventListener('click', event => {
    if (!(event.target instanceof Element)) return;
    if (desktop.matches && event.target.closest('.presentation-toggle')) {
      enabled = !enabled;
      try { localStorage.setItem(key, String(enabled)); } catch (_) {}
      render();
    }
    const step = event.target.closest('[data-section-step]');
    if (step && !step.disabled) move(Number(step.dataset.sectionStep));
  });

  document.addEventListener('keydown', event => {
    if (!presenting() || !content() || event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
    if (event.target instanceof Element && event.target.closest('input, textarea, select, [contenteditable], [role="dialog"], [role="slider"], .glightbox-container')) return;
    if (document.querySelector('.glightbox-open, dialog[open]')) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      enabled = false;
      try { localStorage.setItem(key, 'false'); } catch (_) {}
      render();
      return;
    }
    if (targets.length < 2 || window.getSelection()?.toString()) return;
    if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
      event.preventDefault();
      move(event.key === 'ArrowRight' ? 1 : -1);
    }
  });

  function onScroll() {
    if (!presenting() || pending) return;
    pending = true;
    requestAnimationFrame(() => { pending = false; updateNavigation(); updateToc(); });
  }
  window.addEventListener('scroll', onScroll, {passive: true});
  window.addEventListener('resize', onScroll);
  desktop.addEventListener('change', render);

  if (typeof document$ !== 'undefined') document$.subscribe(render);
  else if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', render);
  else render();
})();
