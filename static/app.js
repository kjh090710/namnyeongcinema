(() => {
  const btn = document.querySelector('.nyca-menu-btn');
  const sheet = document.getElementById('nycaMenu');
  const overlay = document.querySelector('.nyca-overlay');

  if (!btn || !sheet || !overlay) return;

  const links = () => Array.from(sheet.querySelectorAll('a[href]'));
  let lastFocused = null;

  const openMenu = () => {
    lastFocused = document.activeElement;
    sheet.hidden = false;
    overlay.hidden = false;

    requestAnimationFrame(() => {
      btn.classList.add('is-open');
      sheet.classList.add('is-open');
      overlay.classList.add('is-open');
      btn.setAttribute('aria-expanded', 'true');

      const first = links()[0];
      first && first.focus({ preventScroll: true });
    });
    trapFocus(true);
  };

  const closeMenu = () => {
    btn.classList.remove('is-open');
    sheet.classList.remove('is-open');
    overlay.classList.remove('is-open');
    btn.setAttribute('aria-expanded', 'false');

    const tidy = () => {
      sheet.hidden = true;
      overlay.hidden = true;
      sheet.removeEventListener('transitionend', tidy);
    };
    sheet.addEventListener('transitionend', tidy, { once: true });

    trapFocus(false);
    if (lastFocused) { lastFocused.focus({ preventScroll: true }); }
  };

  const toggleMenu = () => {
    const isOpen = btn.classList.contains('is-open');
    isOpen ? closeMenu() : openMenu();
  };

  const onKeydown = (e) => {
    if (e.key === 'Escape') {
      if (btn.classList.contains('is-open')) {
        e.preventDefault();
        closeMenu();
      }
      return;
    }
    if (e.key === 'Tab' && btn.classList.contains('is-open')) {
      const items = links();
      if (items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault(); last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault(); first.focus();
      }
    }
  };

  const onClickOutside = (e) => {
    if (!btn.classList.contains('is-open')) return;
    const insideSheet = sheet.contains(e.target);
    const onButton = btn.contains(e.target);
    if (!insideSheet && !onButton) closeMenu();
  };

  const trapFocus = (enable) => {
    if (enable) {
      document.addEventListener('keydown', onKeydown);
      document.addEventListener('click', onClickOutside);
    } else {
      document.removeEventListener('keydown', onKeydown);
      document.removeEventListener('click', onClickOutside);
    }
  };

  btn.addEventListener('click', toggleMenu);
  overlay.addEventListener('click', closeMenu);

  btn.setAttribute('aria-expanded', 'false');
})();
