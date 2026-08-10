## Limit Orders

A new **Limit Orders** page sits alongside Open Orders:

- **See every resting limit order** across all connected exchanges in one sortable, filterable table — buy and sell split into tabs, with partial fills and Kraken's synthetic (uncancellable) pairs called out.
- **Place a single limit order** through a three-step wizard that snaps price and size to the exchange's own tick grid.
- **Place a staggered ladder** — pick how many rungs, how far from the market to span (by percentage or by exact price), and what share of your balance to commit. Steps can rotate through several quote currencies, and every rung is editable before you submit.
- **Watch placement happen** rung by rung, paced to each exchange's rate limits, with per-leg success or failure and a stop button.

Cancelling is available from both the table and the wizard's results.

## Under the hood

- New exchange endpoints for creating and cancelling orders, plus a pairs endpoint that reports tick sizes, minimums, live prices and *free* balances (funds locked in resting orders no longer count toward what a ladder can spend).
- Robinhood adapter support for the above; post-only is hidden where the exchange has no such flag.
- Refreshed demo dataset with current market prices.

---

## Update — Limit Orders refinements

The installer above has been rebuilt with the following changes.

### Shaping a ladder

- **Advanced panel on the review step** (collapsed by default — an even split is still what you get without touching it). It draws the ladder the way an order book is drawn: price down the side, volume across, with the market price marked so you can see how far the whole ladder sits from it.
- **Drag the median line** to move the price level half your volume rests inside. Preset shapes — Even, Near market, Far out, Middle, Both ends — plus a slider for how tightly the rest clusters around it. The collapsed header always says what shape is in force, so a leaned ladder can't hide.
- **Buy ladders now plot spend rather than coins.** An even-money buy ladder used to draw as a rising ramp purely because the cheaper rungs buy more coins.
- **50 steps per selected trading pair**, up from 25 overall — two pairs allow 100, five reach the 250 cap.
- **Exact prices work across several dollar-quoted pairs.** A single price range is meaningful on USD, USDT and USDC at once, so those can now be laddered together; a pair quoted in something else still can't join them.

### Seeing where your orders are

- **Per-coin charts below the sell table** showing what each pair converts into if it fills, one chart per coin so the bars are always the same unit. Bars are coloured by exchange, matching the badges in the table.
- **A price histogram of resting orders**, binned by price so orders clustered at one level look clustered instead of evenly spaced.

### Fixes

- **Large amounts against fine tick sizes were rejected as off-tick.** The check compared `amount / tick` to a whole number using a fixed tolerance, which stops working once that quotient passes about 4.5 billion — so every rung of a SHIB ladder came back unplaceable, and editing the amount couldn't fix it.
- **Red inputs are now explained.** Problems are grouped by reason with the step numbers they affect, plus how many steps your balance actually supports at the exchange's minimum — the one thing that editing a row can never fix.
- **The wizard no longer closes when a drag ends outside it.** Releasing the mouse past the dialog's edge counted as a backdrop click and discarded the whole ladder.
- The fills-immediately check now runs against **every** selected pair rather than only the first, so a near end that clears one pair's market but not another's is caught.
- Exchange order-size minimums can be overridden where the exchange's API and its own app disagree (currently Kraken SHIB and LUNA); overridden figures are labelled in the UI as set in Cyrus rather than read from the exchange.
- A spinner while trading pairs load, replacing the previous coin's chips — which stayed live and clickable during the fetch.


---

## Update — Transfers page and bulk order cancelling

The installer above has been rebuilt with the following changes.

### New: Transfers

A **Transfers** page under Portfolio, showing every deposit and withdrawal across your connected exchanges.

- **Full history, not a recent window.** The first visit backfills as far back as each exchange goes — Kraken to 2015, Binance to 2017, Coinbase to 2013 — in bounded slices behind a progress bar. Interrupting it costs nothing: progress is written as it goes, so the next visit resumes where it stopped rather than starting over.
- **Cached locally**, so after the first sync the page opens instantly instead of re-hitting slow, rate-limited endpoints every visit.
- **Filter** by exchange, type or coin, with paging for long histories.
- **Pending transfers keep being watched.** A withdrawal that sits in *Processing* for days is re-read until it settles, rather than being frozen at whatever status it had when first seen.
- Coinbase↔Advanced moves arrive already marked as internal.

**Transfer history needs an API-key permission that trading does not** — *Query Funds* on Kraken, *Enable Reading* on Binance, transaction access on a Coinbase CDP key. A key that trades perfectly well can still be refused here. When that happens the page names the missing permission and stops retrying until you re-validate, instead of showing an empty table. Robinhood has no transfer-history API at all and says so rather than appearing broken.

One honest limitation worth stating: exchanges only ever report their own side of a transfer. A withdrawal to your own wallet looks identical to one sent to anyone else, so nothing on this page should be read as a record of who owns the far end.

### Limit Orders — select and cancel in bulk

- **Tick individual orders**, or use the header checkbox to select everything the current filter and Buy/Sell tab are showing. Selection follows what is on screen, so it can never act on rows a filter is hiding.
- **Cancel selected** opens a confirmation that lists every order in full — pair, side, limit price, volume, estimated total — rather than a bare count. Partially filled orders and Kraken synthetic pairs are called out before you confirm, not after they fail.
- Cancels go out **one at a time, paced to the exchange**, with a progress bar and a live per-order result. A failure never stops the run, and the dialog stays open afterwards showing exactly which orders went and which are still resting. Failed ones stay selected so you can retry them without hunting through the table.
- **Click any row** for the full order details, including how much is still resting. That view is deliberately read-only — cancelling stays behind the row's own Cancel button, so inspecting an order can never cancel it by accident.

### Also

- `src/backend/transfer_diagnostic.py` reports how much of your transfer history can actually be traced to a counterparty — groundwork for matching transfers between your own accounts.


## Update — An assistant that can answer questions and do the work

The installer above has been rebuilt with the following changes.

### New: the assistant

A button in the top-right corner of every page — or `Ctrl` + `K` — opens an assistant that reads your portfolio and acts on it.

- **Ask about what you hold.** It sees your holdings and their values across every connected exchange, the change so far this month, your automation rules and your resting orders. *"What are my biggest positions?"* · *"How has this month gone?"* · *"Explain my automations in plain English."*
- **Or tell it what to do.** *"Cancel all my BTC sell limit orders."* *"Create a rule that sends BTC to my Tangem wallet when the balance goes over 3."* It resolves the connection, looks up the real order ids and whitelisted address keys, and builds the request — the part that is tedious to do by hand and easy to get wrong.
- **Nothing changes without your say-so.** Reading happens automatically; anything that cancels, places or creates stops and shows you a card describing exactly what it is about to do. **That card is built from the values that will actually be sent, not from the assistant's description of them** — so what you approve is what happens.
- **Failures are reported, with the reason.** Ask it to cancel five orders and it cancels them one at a time, so one failure doesn't take the other four with it. Whatever the exchange or Cyrus's own validation said comes back in plain language — *"Withdraw Crypto is not supported for Coinbase Advanced"*, *"this order needs 0.5 BTC but only 0.3 is available"* — alongside a per-action tick or cross, drawn from the result itself rather than the assistant's account of it.
- **It can only do what you can.** Every action runs through the same endpoints, the same validation and the same permission checks as the buttons elsewhere in Cyrus, as you. It cannot reach another account, place a market order, or withdraw to an address you have not already whitelisted on the exchange — because Cyrus itself cannot.

Two things it deliberately will not do: give you trading opinions (it will carry out an order you ask for, but it will not tell you what to buy or sell), and create allocation caps — those still belong on the Balancer page.

### Bring your own Anthropic key

The assistant runs on Claude using **your own** Anthropic API key, set up under **Profile → Assistant**. There is no Cyrus-operated service in the middle: your portfolio goes from your machine to Anthropic and back, and usage is billed to your account — typically a fraction of a cent per question.

The key is verified with Anthropic before it is saved, and stored encrypted with the same Fernet key as your exchange credentials. Cyrus never sends it back to the interface; the Profile page only ever knows whether one is on file.

Conversations are kept on your device, per account, and are never written to your Cyrus database or sent anywhere. The history panel lists your recent conversations, and clears them on request.

### Profile, rebuilt

The Profile page had grown to six stacked sections, where the two anyone visits regularly — exchange connections and email — sat below three you set once and forget.

- **Four tabs**: Account, Exchanges, Assistant, Notifications.
- **An identity strip** at the top carrying the state people actually open this page to check — how many connections you have and whether they validated, whether email is on, whether the account is active.
- **One alert strip** for the whole page, instead of a success and error pair per section. With tabbed panes a per-section message could land on a pane you were not looking at.
- Denser cards and two-column form rows throughout, so each pane fits without scrolling.

### Fixes

- **The Profile page depended on having visited Overview first.** It loaded only its own stylesheet, while the page shell, status badges and button styles it uses live in the Overview stylesheet — so a session that went straight to Profile got an unstyled page. It now loads both, the way the Holdings and Balancer pages already did.
