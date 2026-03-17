(function () {
class HomeController {
  private unsubscribe: (() => void) | null = null;

  constructor() {
    this.init();
  }

  private init(): void {
    this.attachEventListeners();
    this.loadDashboardData();

    this.unsubscribe = ExchangeStore.onUpdate(() => this.renderFromStore());

    const observer = new MutationObserver(() => {
      if (!document.getElementById('orders-tbody')) {
        if (this.unsubscribe) this.unsubscribe();
        observer.disconnect();
      }
    });
    const content = document.getElementById('app-content');
    if (content) observer.observe(content, { childList: true });
  }

  private attachEventListeners(): void {
    document.getElementById('view-all-positions')?.addEventListener('click', () => {
      router.navigate('positions');
    });
    document.getElementById('view-all-orders')?.addEventListener('click', () => {
      router.navigate('openorders');
    });
    document.getElementById('view-all-commands')?.addEventListener('click', () => {
      router.navigate('commands');
    });
    document.getElementById('view-all-commands2')?.addEventListener('click', () => {
      router.navigate('commands');
    });
  }

  private loadDashboardData(): void {
    this.setCardValue('total-balance', '$0.00');
    this.setCardValue('open-positions-count', '0');
    this.setCardValue('custom-commands-count', '0');

    this.setTableEmpty('positions-tbody', 6, 'No open positions');

    this.renderFromStore();
    this.loadCommands();
    this.loadLogs();
  }

  private renderFromStore(): void {
    const orders = ExchangeStore.openOrders;
    const isAll = ExchangeStore.isAllMode();

    // Update subtitle
    const subtitle = document.getElementById('page-subtitle');
    if (subtitle) {
      subtitle.textContent = isAll
        ? 'Overview of your exchange accounts'
        : `Overview of your ${ExchangeStore.getExchangeName(ExchangeStore.activeMode as number)} account`;
    }

    // Update orders table header for exchange column
    const thead = document.getElementById('orders-thead');
    if (thead) {
      const cols = isAll
        ? '<tr><th>Exchange</th><th>Pair</th><th>Type</th><th>Side</th><th>Price</th><th>Volume</th><th>Status</th></tr>'
        : '<tr><th>Pair</th><th>Type</th><th>Side</th><th>Price</th><th>Volume</th><th>Status</th></tr>';
      thead.innerHTML = cols;
    }

    if (ExchangeStore.error) {
      this.setTableEmpty('orders-tbody', isAll ? 7 : 6, 'Failed to load orders');
      this.setCardValue('open-orders-count', '--');
    } else {
      this.renderOrders(orders, isAll);
      this.setCardValue('open-orders-count', orders.length.toString());
    }
  }

  private async loadLogs(): Promise<void> {
    try {
      const logs = await AutomationController.getLogs(30);
      this.renderLogs(logs);
    } catch (error: any) {
    }
  }

  private renderLogs(logs: any[]): void {
    const tbody = document.getElementById('logs-tbody');
    if (!tbody) return;

    if (logs.length === 0) {
      tbody.innerHTML = '<tr class="empty-row"><td colspan="5">No execution history yet</td></tr>';
      return;
    }

    tbody.innerHTML = logs.map((l: any) => {
      const time = l.created_at ? new Date(l.created_at.endsWith('Z') ? l.created_at : l.created_at + 'Z').toLocaleString() : '--';
      const statusClass = l.status === 'success' ? 'log-success' : 'log-error';

      return `<tr>
        <td>${this.escapeHtml(time)}</td>
        <td>${this.escapeHtml(l.trigger_event)}</td>
        <td>${this.escapeHtml(l.action_executed)}</td>
        <td class="result-cell">${this.escapeHtml(l.action_result)}</td>
        <td><span class="log-status ${statusClass}">${this.escapeHtml(l.status)}</span></td>
      </tr>`;
    }).join('');
  }

  private renderOrders(orders: any[], isAll: boolean): void {
    const tbody = document.getElementById('orders-tbody');
    if (!tbody) return;

    const colspan = isAll ? 7 : 6;
    if (orders.length === 0) {
      tbody.innerHTML = `<tr class="empty-row"><td colspan="${colspan}">No open orders</td></tr>`;
      return;
    }

    tbody.innerHTML = orders.map((o: any) => {
      const sideClass = o.side === 'buy' ? 'side-buy' : 'side-sell';
      const exchangeCol = isAll
        ? `<td><span class="exchange-badge exchange-${this.escapeHtml(o.exchangeName).toLowerCase()}">${this.escapeHtml(o.exchangeName)}</span></td>`
        : '';
      return `<tr>
        ${exchangeCol}
        <td>${this.escapeHtml(o.pair)}</td>
        <td>${this.escapeHtml(o.type)}</td>
        <td><span class="${sideClass}">${this.escapeHtml(o.side)}</span></td>
        <td>${this.escapeHtml(o.price)}</td>
        <td>${this.escapeHtml(o.volume)}</td>
        <td><span class="status-badge">${this.escapeHtml(o.status)}</span></td>
      </tr>`;
    }).join('');
  }

  private async loadCommands(): Promise<void> {
    try {
      const rules = await AutomationController.getRules();
      this.renderCommands(rules);
      this.setCardValue('custom-commands-count', rules.length.toString());
    } catch {
      this.setTableEmpty('commands-tbody', 4, 'Failed to load commands');
    }
  }

  private renderCommands(rules: any[]): void {
    const tbody = document.getElementById('commands-tbody');
    if (!tbody) return;

    if (rules.length === 0) {
      tbody.innerHTML = '<tr class="empty-row"><td colspan="4">No custom commands</td></tr>';
      return;
    }

    tbody.innerHTML = rules.map((r: any) => {
      const statusClass = r.is_active ? 'status-active' : 'status-inactive';
      const statusText = r.is_active ? 'Active' : 'Paused';
      const trigger = this.formatTrigger(r);
      const action = this.formatAction(r);

      return `<tr>
        <td>${this.escapeHtml(r.rule_name)}</td>
        <td>${trigger}</td>
        <td>${action}</td>
        <td><span class="status-badge ${statusClass}">${statusText}</span></td>
      </tr>`;
    }).join('');
  }

  private formatTrigger(rule: any): string {
    if (rule.trigger_type === 'order_filled') {
      const orderId = rule.trigger_order_id
        ? this.escapeHtml(rule.trigger_order_id.substring(0, 10)) + '...'
        : 'Any';
      return `<span class="trigger-badge">Order Filled</span> <span class="mono-text">${orderId}</span>`;
    }
    if (rule.trigger_type === 'balance_threshold') {
      const asset = rule.trigger_asset || '';
      const threshold = rule.trigger_threshold || '0';
      const cooldown = this.formatCooldown(rule.cooldown_minutes || 1440);
      return `<span class="trigger-badge trigger-badge-balance">Balance ≥</span> `
        + `<strong>${this.escapeHtml(threshold)}</strong> `
        + `<span class="asset-badge">${this.escapeHtml(asset)}</span>`
        + `<br><span class="cooldown-text">Cooldown: ${cooldown}</span>`;
    }
    return this.escapeHtml(rule.trigger_type);
  }

  private formatAction(rule: any): string {
    if (rule.action_type === 'withdraw_crypto') {
      let amountText: string;
      if (rule.trigger_type === 'balance_threshold') {
        amountText = '<em>Full Balance</em>';
      } else if (rule.use_filled_amount) {
        amountText = '<em>Filled Amount</em>';
      } else {
        amountText = `<strong>${this.escapeHtml(rule.action_amount)}</strong>`;
      }
      return `Withdraw ${amountText} `
        + `<span class="asset-badge">${this.escapeHtml(rule.action_asset)}</span> `
        + `→ ${this.escapeHtml(rule.action_address_key)}`;
    }
    if (rule.action_type === 'convert_crypto') {
      const convertAmountText = rule.action_amount
        ? `<strong>${this.escapeHtml(rule.action_amount)}</strong>`
        : '<em>Full Balance</em>';
      return `Convert ${convertAmountText} `
        + `<span class="asset-badge">${this.escapeHtml(rule.action_asset)}</span> `
        + `→ <span class="asset-badge">${this.escapeHtml(rule.convert_to_asset || '?')}</span>`;
    }
    return this.escapeHtml(rule.action_type);
  }

  private formatCooldown(minutes: number): string {
    const hours = Math.floor(minutes / 60);
    const mins = minutes % 60;
    if (hours > 0 && mins > 0) return `${hours}h ${mins}m`;
    if (hours > 0) return `${hours}h`;
    return `${mins}m`;
  }

  private setCardValue(id: string, value: string): void {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  private setTableEmpty(tbodyId: string, colspan: number, message: string): void {
    const tbody = document.getElementById(tbodyId);
    if (tbody) {
      tbody.innerHTML = `<tr class="empty-row"><td colspan="${colspan}">${message}</td></tr>`;
    }
  }

  private escapeHtml(str: string): string {
    const div = document.createElement('div');
    div.textContent = String(str);
    return div.innerHTML;
  }
}

new HomeController();

})();