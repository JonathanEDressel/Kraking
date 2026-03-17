const HelpTooltip = (() => {

  function init(root: HTMLElement | Document = document): void {
    const labels = root.querySelectorAll<HTMLElement>('[data-help]');
    labels.forEach((label) => {
      // Don't double-init
      if (label.querySelector('.help-icon')) return;

      const text = label.getAttribute('data-help') || '';
      if (!text) return;

      const wrapper = document.createElement('span');
      wrapper.className = 'help-tooltip-wrapper';

      const icon = document.createElement('span');
      icon.className = 'help-icon';
      icon.setAttribute('tabindex', '0');
      icon.setAttribute('aria-label', 'Help');
      icon.textContent = '?';

      const dropdown = document.createElement('span');
      dropdown.className = 'help-dropdown';
      dropdown.textContent = text;

      wrapper.appendChild(icon);
      wrapper.appendChild(dropdown);
      label.appendChild(wrapper);

      wrapper.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
      });

      icon.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        // Close any other open dropdowns first
        document.querySelectorAll('.help-dropdown.open').forEach((d) => {
          if (d !== dropdown) d.classList.remove('open');
        });
        dropdown.classList.toggle('open');
      });
    });
  }

  document.addEventListener('click', () => {
    document.querySelectorAll('.help-dropdown.open').forEach((d) => {
      d.classList.remove('open');
    });
  });

  return { init };
})();
