/* Load the pinned renderer only when a page contains mathematical notation. */
(() => {
  let engine;
  function renderMath() {
    if (!document.querySelector('.arithmatex')) return;
    if (!engine) {
      engine = new Promise((resolve, reject) => {
        window.MathJax = {
          tex: {
            inlineMath: [['\\(', '\\)']],
            displayMath: [['\\[', '\\]']],
            processEscapes: true,
            processEnvironments: true,
          },
          options: { ignoreHtmlClass: '.*|', processHtmlClass: 'arithmatex' },
          startup: { typeset: false },
        };
        const script = document.createElement('script');
        script.src = 'https://cdn.jsdelivr.net/npm/mathjax@3.2.2/es5/tex-mml-chtml.js';
        script.onload = () => resolve(window.MathJax.startup.promise);
        script.onerror = () => reject(new Error('Could not load the MathJax renderer.'));
        document.head.appendChild(script);
      });
    }
    engine = engine.then(() => window.MathJax.typesetPromise()).catch(console.error);
  }
  if (typeof document$ !== 'undefined') {
    document$.subscribe(renderMath);
  } else if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', renderMath);
  } else {
    renderMath();
  }
})();
