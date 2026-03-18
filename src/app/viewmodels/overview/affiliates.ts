(function () {

interface AffiliateProduct {
  name: string;
  description: string;
  link: string;
}

interface Affiliate {
  name: string;
  category: string;
  iconClass: string;
  iconColorClass: string;
  tags: string[];
  why: string;
  products: AffiliateProduct[];
}

const AFFILIATES: Affiliate[] = [
  {
    name: 'Nord Security',
    category: 'Privacy & Security',
    iconClass: 'fa-solid fa-shield-halved',
    iconColorClass: 'nord',
    tags: ['VPN', 'Password Manager', 'Privacy', 'Encryption'],
    why: `When you're managing real money and connecting to exchanges, <strong>your security posture matters</strong>.
          Nord Security's suite protects your internet traffic with a VPN, secures your credentials with a password manager,
          and keeps your identity safe — all tools we consider essential for any active trader or crypto user.`,
    products: [
      {
        name: 'NordVPN',
        description: 'Encrypt your internet traffic and hide your activity from ISPs and hackers — especially important on exchange connections.',
        link: 'https://go.nordvpn.net/aff_c?offer_id=15&aff_id=143568&url_id=902',
      },
      {
        name: 'NordPass',
        description: 'Store your exchange API keys and passwords in a zero-knowledge vault. Never reuse weak passwords again.',
        link: 'https://go.nordpass.io/aff_c?offer_id=488&aff_id=143568&url_id=9356',
      },
    ],
  },
  // ── Add more affiliates here ──────────────────────────────────
  // {
  //   name: 'Example Partner',
  //   category: 'Category',
  //   iconClass: 'fa-solid fa-icon-name',
  //   iconColorClass: 'example',
  //   tags: ['Tag1', 'Tag2'],
  //   why: 'Why this partner matters for Cyrus users...',
  //   products: [
  //     { name: 'Product', description: 'Short description.', link: 'https://...' },
  //   ],
  // },
];

class AffiliatesController {
  private current = 0;
  private track: HTMLElement | null = null;
  private dotsEl: HTMLElement | null = null;

  constructor() {
    this.track = document.getElementById('affiliate-track');
    this.dotsEl = document.getElementById('affiliate-dots');
    this.render();
    this.bindNav();
    this.bindSwipe();
  }

  private render(): void {
    if (!this.track || !this.dotsEl) return;

    this.track.innerHTML = AFFILIATES.map(a => this.buildCard(a)).join('');

    this.dotsEl.innerHTML = AFFILIATES.map((_, i) =>
      `<button class="affiliate-dot${i === 0 ? ' active' : ''}" data-index="${i}" aria-label="Go to slide ${i + 1}"></button>`
    ).join('');

    this.dotsEl.querySelectorAll('.affiliate-dot').forEach(dot => {
      dot.addEventListener('click', () => {
        const idx = parseInt((dot as HTMLElement).getAttribute('data-index') || '0', 10);
        this.goTo(idx);
      });
    });

    this.updateNav();
  }

  private buildCard(a: Affiliate): string {
    const tags = a.tags.map(t => `<span class="affiliate-tag">${this.esc(t)}</span>`).join('');
    const products = a.products.map(p => `
      <div class="affiliate-product">
        <div class="affiliate-product-info">
          <span class="affiliate-product-name">${this.esc(p.name)}</span>
          <span class="affiliate-product-desc">${this.esc(p.description)}</span>
        </div>
        <a href="${this.esc(p.link)}" class="affiliate-product-link" target="_blank" rel="noopener noreferrer">
          <i class="fa-solid fa-arrow-up-right-from-square"></i> Get Started
        </a>
      </div>`).join('');

    return `
      <div class="affiliate-card">
        <div class="affiliate-card-header">
          <div class="affiliate-icon-wrap ${this.esc(a.iconColorClass)}">
            <i class="${this.esc(a.iconClass)}"></i>
          </div>
          <div class="affiliate-card-meta">
            <h2 class="affiliate-card-name">${this.esc(a.name)}</h2>
            <span class="affiliate-card-category">${this.esc(a.category)}</span>
          </div>
        </div>
        <div class="affiliate-tags">${tags}</div>
        <p class="affiliate-why">${a.why}</p>
        <div class="affiliate-products">${products}</div>
      </div>`;
  }

  private goTo(index: number): void {
    this.current = Math.max(0, Math.min(index, AFFILIATES.length - 1));
    if (this.track) {
      this.track.style.transform = `translateX(-${this.current * 100}%)`;
    }
    this.dotsEl?.querySelectorAll('.affiliate-dot').forEach((dot, i) => {
      dot.classList.toggle('active', i === this.current);
    });
    this.updateNav();
  }

  private updateNav(): void {
    const prev = document.getElementById('affiliate-prev') as HTMLButtonElement | null;
    const next = document.getElementById('affiliate-next') as HTMLButtonElement | null;
    if (prev) prev.disabled = this.current === 0;
    if (next) next.disabled = this.current === AFFILIATES.length - 1;
  }

  private bindNav(): void {
    document.getElementById('affiliate-prev')?.addEventListener('click', () => this.goTo(this.current - 1));
    document.getElementById('affiliate-next')?.addEventListener('click', () => this.goTo(this.current + 1));
  }

  private bindSwipe(): void {
    const outer = document.querySelector('.affiliate-track-outer') as HTMLElement | null;
    if (!outer) return;

    let startX = 0;
    let dragging = false;

    outer.addEventListener('pointerdown', (e: PointerEvent) => {
      startX = e.clientX;
      dragging = true;
    });

    outer.addEventListener('pointerup', (e: PointerEvent) => {
      if (!dragging) return;
      dragging = false;
      const delta = e.clientX - startX;
      if (Math.abs(delta) > 50) {
        this.goTo(delta < 0 ? this.current + 1 : this.current - 1);
      }
    });

    outer.addEventListener('pointercancel', () => { dragging = false; });
  }

  private esc(str: string): string {
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
  }
}

new AffiliatesController();

})();
