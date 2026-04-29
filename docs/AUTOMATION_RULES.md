# Automation Rules — Cyrus

Custom Commands let you automate exchange operations based on configurable triggers. All active rules are evaluated every **60 seconds** by the background automation worker.

---

## Shared Concepts

| Concept | Description |
|---|---|
| **Exchange** | Each rule is scoped to one exchange connection. Both the trigger and action run on the same connection. |
| **is_active** | Rules can be paused and resumed at any time via the toggle button in the rules table. Inactive rules are skipped by the worker. |
| **Execution Log** | Every execution attempt (success or failure) is written to the log table, visible on both the Commands page and the Overview page. |
| **Cooldown** | Prevents the same rule from firing repeatedly. The worker skips a rule if the time elapsed since `last_triggered_at` is less than `cooldown_minutes`. Minimum: 1 minute. |

---

## Rule Type 1 — Order is Filled (`order_filled`)

### When it triggers
When a specific open order on the exchange is **completely filled** (status changes to closed/filled).

### Available actions
- **Withdraw Crypto** — Sends the received asset to a pre-whitelisted withdrawal address.

> Converting is not available for this trigger type.

### Form fields

| Field | Description |
|---|---|
| **Order ID** | Select from currently open orders. A ✅ next to an order means a rule already exists for it. |
| **Asset** | Auto-populated. For a **sell** order: the quote asset (e.g. USDT). For a **buy** order: the base asset (e.g. BTC). |
| **Withdrawal Address Key** | Nickname key of the whitelisted withdrawal address on the exchange. |
| **Amount Mode** | `Fixed Amount` — specify an exact amount. `Use Filled Amount` — automatically uses the actual filled amount when the order completes. |
| **Amount** *(Fixed mode only)* | Amount to withdraw. Cannot exceed the estimated order amount. A slider shows 0–100% of the order value. |

### Execution flow
1. Worker polls all active `order_filled` rules every 60 seconds.
2. Fetches the current status of the trigger order ID via the exchange API.
3. If the order is **closed / filled**: executes the configured withdrawal.
4. Updates `last_triggered_at`, increments `trigger_count`.
5. Logs the result as `success` or `error`.

### Limits / notes
- Withdrawal addresses must be whitelisted on the exchange before creating the rule.
- Exchanges enforce minimum withdrawal amounts — amounts below the minimum will be rejected.
- An order fills at most once, so this rule type effectively fires at most once per order.
- No cooldown field is shown — it is only meaningful for repeating rules.

---

## Rule Type 2 — Balance Threshold (`balance_threshold`)

### When it triggers
When the balance of a monitored asset is **greater than or equal to** a configured threshold amount.

### Available actions
- **Withdraw Crypto** — Withdraws the monitored asset to a whitelisted address.
- **Convert Crypto** — Swaps the monitored asset for another asset via a market order.

### Form fields

| Field | Description |
|---|---|
| **Monitor Asset** | The asset whose balance to watch (populated from your current balances). |
| **Threshold Amount** | Trigger fires when the asset balance ≥ this value. |
| **Cooldown Period** | Hours + minutes to wait between executions. Minimum 1 minute. |
| **Do (Action)** | `Withdraw Crypto` or `Convert Crypto`. |
| **— Withdraw fields —** | |
| Asset | Auto-locked to the monitored asset. |
| Withdrawal Address Key | Whitelisted address on the exchange. |
| **— Convert fields —** | |
| From Asset | Auto-locked to the monitored asset. |
| To Asset | Target asset to receive (must have a valid trading pair on the exchange). |
| Amount | Optional. Leave empty to convert the full balance. Enter a fixed value for partial conversion. |

### Execution flow
1. Worker polls every 60 seconds.
2. Fetches the current balance of `trigger_asset`.
3. If `balance >= trigger_threshold` **and** cooldown has elapsed: executes the configured action.
4. Updates `last_triggered_at`, increments `trigger_count`.
5. Logs the result as `success` or `error`.

### Limits / notes
- Cooldown is essential — without it the rule fires every 60 seconds as long as balance stays above threshold.
- For convert actions the exchange must have a valid `FROM_ASSET/TO_ASSET` (or inverse) trading pair.
- An explicit amount is capped to the available balance at execution time.

---

## Rule Type 3 — Price Threshold (`price_threshold`)

### When it triggers
When the **market price** of a held coin reaches or exceeds a configured price in a chosen quote currency.  
`current_price >= trigger_price`

### Available actions
- **Convert Crypto only** — Swaps the source coin to the target asset via a market order. Withdrawals are not available for this rule type.

### Form fields

| Field | Description |
|---|---|
| **Coin to Monitor/Sell** | The asset to price-check and sell when the trigger price is reached (populated from your current balances). |
| **Trigger Price** | Rule fires when `current_price ≥ this_value`. Example: `0.67`. |
| **Price Quote Currency** | Quote currency for the price check: `USD`, `USDT` (default), or `USDC`. The worker checks the `COIN/QUOTE` pair. |
| **Convert Into** | Target asset/currency to receive. Defaults offered: USDT, USDC, USD, EUR, BTC, ETH, plus all currently held assets. |
| **Sell Amount Mode** | `Sell All` — converts full available balance each execution. `Percent` — converts X% of your balance each execution. `Fixed Amount` — converts a fixed quantity of the source coin. |
| **Amount Value** | Required for Percent (1–100) or Fixed (> 0) modes. Disabled for Sell All. |
| **Execution Limit** | Check "Unlimited executions" (default) to run indefinitely. Uncheck to set a `Max Executions` cap. |
| **Max Executions** | When the unlimited checkbox is unchecked: the rule auto-pauses after this many **successful** conversions (minimum 1). |
| **Cooldown Period** | Hours + minutes to wait between executions. Minimum 1 minute. |

### Execution flow
1. Worker polls every 60 seconds.
2. Fetches the current market price via `fetchTicker()` (CCXT).
   - Checks `COIN/QUOTE` first.
   - Falls back to the inverse pair `QUOTE/COIN` and returns `1 / inverse_price` if the direct pair does not exist.
   - Raises an error and logs if neither pair is available.
3. If `current_price >= trigger_threshold` **and** cooldown has elapsed:
   - Fetches the current balance of the source coin.
   - Resolves the sell amount based on mode (`all` → full balance, `percent` → `balance × pct / 100`, `fixed` → the stated amount, capped to available balance).
   - Executes a market `convert()` order on the exchange.
4. On success:
   - Increments `execution_count` (separate from `trigger_count`).
   - Updates `last_triggered_at`.
   - If `execution_count` now equals `max_executions`: auto-deactivates the rule (`is_active = 0`) and logs an auto-deactivation event.
5. Logs every attempt as `success` or `error`.

### Auto-deactivation
When `max_executions` is set and reached, the rule status changes to **Paused** automatically. It can be re-activated manually from the Commands or Overview table at any time.

### Execution progress in the rules table
The **Triggered** column shows a progress counter for price-threshold rules: e.g. `Success: 2 / 5`. Rules with unlimited executions show no counter.

### Limits / notes
- Only market-convert actions are supported (no withdrawals).
- The `COIN/QUOTE` or inverse `QUOTE/COIN` trading pair must exist on the selected exchange.
- Percent and fixed amounts are applied against the **current live balance** at execution time, not the balance at rule creation.
- Setting a cooldown prevents repeated rapid conversions when price oscillates around the threshold.

---

## Rule Status Reference

| Status | Meaning |
|---|---|
| **Active** | Rule is enabled and evaluated every 60-second poll cycle. |
| **Paused** | Rule is disabled — either manually toggled off or auto-deactivated after reaching `max_executions`. |

### Trigger-type action availability summary

| Trigger | Withdraw | Convert |
|---|---|---|
| `order_filled` | ✅ | ❌ |
| `balance_threshold` | ✅ | ✅ |
| `price_threshold` | ❌ | ✅ only |

---

## Execution Log Columns

| Column | Description |
|---|---|
| **Time** | UTC timestamp of the execution attempt. |
| **Trigger** | Description of the condition that was met (e.g. `Balance ≥ 0.01 BTC`). |
| **Action** | Description of what was attempted (e.g. `Withdraw 0.005 BTC`). |
| **Result** | Short result message or error description. |
| **Status** | `success` or `error`. |
