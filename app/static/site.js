/* Scroll effects: progress bar, nav state, reveal, parallax, count-up, sticky story, timeline fill */
(() => {
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const bar = document.querySelector('.progress i');
  const nav = document.querySelector('.pubnav');
  const parallax = $$('[data-speed]');
  const timeline = document.querySelector('.timeline');

  // auto-tag common blocks for reveal
  $$('.content > *, .cards3 > *, .bento > *, .section-head, .stats > *, .faq, .timeline li, .step, .cta > *').forEach((el, i) => {
    if (!el.hasAttribute('data-reveal')) { el.setAttribute('data-reveal', ''); el.style.setProperty('--d', (i % 4) * 0.08 + 's'); }
  });

  const countUp = el => {
    const target = parseFloat(el.dataset.count), dec = (el.dataset.count.split('.')[1] || '').length;
    if (reduce) { el.textContent = target.toFixed(dec); return; }
    const t0 = performance.now(), dur = 1400;
    const tick = t => { const p = Math.min((t - t0) / dur, 1), e = 1 - Math.pow(1 - p, 3);
      el.textContent = (target * e).toFixed(dec); if (p < 1) requestAnimationFrame(tick); };
    requestAnimationFrame(tick);
  };

  const io = new IntersectionObserver(es => es.forEach(e => {
    if (!e.isIntersecting) return;
    e.target.classList.add('in');
    $$('[data-count]', e.target).forEach(countUp);
    if (e.target.matches('[data-count]')) countUp(e.target);
    $$('[data-w]', e.target).forEach(b => b.style.width = b.dataset.w);
    io.unobserve(e.target);
  }), { threshold: .15, rootMargin: '0px 0px -6% 0px' });
  $$('[data-reveal],[data-count]').forEach(el => io.observe(el));

  // sticky story: activate step in the middle of the viewport
  const steps = $$('.story-steps .step'), arts = $$('.story-art .sa');
  if (steps.length) {
    const so = new IntersectionObserver(es => es.forEach(e => {
      if (!e.isIntersecting) return;
      const i = steps.indexOf(e.target);
      steps.forEach((s, k) => s.classList.toggle('active', k === i));
      arts.forEach((a, k) => a.classList.toggle('active', k === i));
    }), { rootMargin: '-45% 0px -45% 0px' });
    steps.forEach(s => so.observe(s));
    steps[0].classList.add('active'); arts[0]?.classList.add('active');
  }

  let ticking = false;
  const onScroll = () => {
    const y = scrollY, h = document.documentElement.scrollHeight - innerHeight;
    if (bar) bar.style.width = (h > 0 ? (y / h) * 100 : 0) + '%';
    if (nav) nav.classList.toggle('scrolled', y > 10);
    if (!reduce) parallax.forEach(el => { el.style.transform = `translate3d(0,${(y * parseFloat(el.dataset.speed)).toFixed(1)}px,0)`; });
    if (timeline) {
      const r = timeline.getBoundingClientRect(), p = Math.min(Math.max((innerHeight * .6 - r.top) / r.height, 0), 1);
      timeline.style.setProperty('--fill', (p * (r.height - 12)) + 'px');
    }
    ticking = false;
  };
  addEventListener('scroll', () => { if (!ticking) { ticking = true; requestAnimationFrame(onScroll); } }, { passive: true });
  onScroll();
})();
