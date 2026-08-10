"""Work out where each transfer actually went, and where it came from.

An exchange tells you a withdrawal left and an address it went to. It does not
tell you who owns that address, and the exchange on the other end reports its
deposit as a separate, unrelated event. Joining the two halves back together is
what turns a list of transactions into a record of movement.

Three ways to do that, in descending order of how much they can be trusted:

  txid       Both legs carry the same on-chain hash. That is the same
             transaction seen from both ends — not an inference at all, so it
             is accepted outright.
  heuristic  No shared hash, but a withdrawal and a deposit of the same asset,
             close in time, with the deposit slightly smaller (the network fee).
             Scored, and only linked automatically when the score is high AND
             nothing else plausibly competes for either leg.
  wallet     The counterparty address matches one the user has labelled. This
             is the only thing that can resolve a transfer to self-custody,
             because there is no second leg anywhere in exchange data.

What none of these can do is tell you who owns an unknown address. A deposit
from an address we have never seen is genuinely ambiguous — it could be income
or it could be your own coins arriving — and it is reported as unresolved
rather than guessed at.
"""

import time

from helper.Helper import execute_query_all, execute_query_one
from helper.InitiateConnection import get_db_connection


# ---------------------------------------------------------------------------
# Tuning
# ---------------------------------------------------------------------------

#: Confidence at or above which a heuristic pair is linked without asking.
#: The user's stated bar: only auto-apply what we are ~95% sure of.
AUTO_LINK_CONFIDENCE = 0.95

#: Below this a candidate is not even worth showing as a suggestion.
SUGGEST_CONFIDENCE = 0.55

#: Most the deposit may fall short of the withdrawal and still be the same
#: movement. This is the fee allowance, and it is deliberately wide: a small
#: BTC transfer can lose several percent to fees, so a tight window would miss
#: exactly the transfers people most want tracked.
MAX_FEE_FRACTION = 0.05

#: Fee fraction treated as "no meaningful loss" — scores full marks.
#: Covers the overwhelming majority of real transfers.
TYPICAL_FEE_FRACTION = 0.01

#: A deposit slightly LARGER than the withdrawal is rounding, not a fee, and a
#: little of it is tolerable. Much more than this and the two are not the same
#: movement however close the timing.
MAX_OVERSHOOT_FRACTION = 0.005

#: Longest a transfer may take between leaving one venue and landing at another.
#: Bitcoin during congestion, and exchange-side manual review, are both slow.
MAX_GAP_SECONDS = 72 * 3600

#: Gap treated as immediate — scores full marks.
FAST_GAP_SECONDS = 3600

#: Exchanges timestamp when a transfer was *created*, and the two ends do not
#: agree to the second, so a deposit may appear marginally before its
#: withdrawal. Allow that much backwards before rejecting on ordering.
CLOCK_SKEW_SECONDS = 600

#: Ceiling applied when more than one candidate survives for a leg. Set below
#: AUTO_LINK_CONFIDENCE on purpose: an ambiguous pair must never link itself,
#: however good the individual numbers look.
AMBIGUOUS_CONFIDENCE_CAP = 0.90

#: Statuses that mean the transfer never happened, so it cannot be half of one.
DEAD_STATUSES = ('failed', 'canceled', 'cancelled')


def normalize_txid(txid) -> str | None:
    """Comparable form of an on-chain hash.

    Two exchanges reporting the same transaction routinely disagree on case and
    on the ``0x`` prefix. Comparing raw strings would miss every cross-exchange
    pair for that reason alone.
    """
    if not txid:
        return None
    value = str(txid).strip().lower()
    if value.startswith('0x'):
        value = value[2:]
    return value or None


def normalize_address(address) -> str | None:
    """Comparable form of a wallet address.

    Lowercased and 0x-stripped, the same as txids. This loses EVM checksum
    casing and is technically wrong for case-sensitive chains, where two
    addresses differing only in case are different addresses. In practice the
    risk of a false match is negligible next to the near-certainty of a user
    pasting an address whose case does not match what the exchange reported, so
    the display form is kept separately and only matching is normalised.
    """
    if not address:
        return None
    value = str(address).strip().lower()
    if value.startswith('0x'):
        value = value[2:]
    return value or None


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _taper(value: float, best: float, worst: float) -> float:
    """1.0 at *best*, 0.0 at *worst*, linear between, clamped outside."""
    if worst == best:
        return 1.0
    ratio = (value - best) / (worst - best)
    return max(0.0, min(1.0, 1.0 - ratio))


def score_pair(withdrawal: dict, deposit: dict) -> tuple[float, dict] | None:
    """Confidence that these two legs are one movement, or None if they can't be.

    Returns ``(confidence, detail)`` where detail explains the score — the UI
    shows it, because "87%" on its own is not something a user can sanity-check.

    The gates are hard requirements, not weighted factors. A different asset or
    a deposit that predates its withdrawal is not a weak match, it is not a
    match, and letting a strong time score paper over it would be wrong.
    """
    if withdrawal['asset'] != deposit['asset']:
        return None
    if withdrawal['exchange_connection_id'] == deposit['exchange_connection_id']:
        return None

    out_amount = float(withdrawal['amount_num'] or 0)
    in_amount = float(deposit['amount_num'] or 0)
    if out_amount <= 0 or in_amount <= 0:
        return None

    gap = int(deposit['occurred_at'] or 0) - int(withdrawal['occurred_at'] or 0)
    if gap < -CLOCK_SKEW_SECONDS or gap > MAX_GAP_SECONDS:
        return None

    # The deposit is the withdrawal minus fees, so it should be a little
    # smaller. Larger by more than rounding means these are different movements.
    shortfall = (out_amount - in_amount) / out_amount
    if shortfall > MAX_FEE_FRACTION:
        return None
    if shortfall < -MAX_OVERSHOOT_FRACTION:
        return None

    amount_score = _taper(max(0.0, shortfall), TYPICAL_FEE_FRACTION, MAX_FEE_FRACTION)
    time_score = _taper(max(0, gap), FAST_GAP_SECONDS, MAX_GAP_SECONDS)

    # Weighted toward the amount: a matching amount is far more distinctive than
    # proximity in time. Several transfers can happen in the same hour; two
    # unrelated ones agreeing to within a fee is much less likely.
    confidence = 0.70 * amount_score + 0.30 * time_score

    # Same network named on both legs is corroboration, and its absence is not
    # evidence either way (plenty of exchanges leave it null).
    out_net = (withdrawal.get('network') or '').strip().lower()
    in_net = (deposit.get('network') or '').strip().lower()
    if out_net and in_net and out_net == in_net:
        confidence = min(1.0, confidence + 0.03)

    return confidence, {
        'fee_fraction': round(max(0.0, shortfall), 6),
        'gap_seconds': max(0, gap),
        'amount_score': round(amount_score, 4),
        'time_score': round(time_score, 4),
    }


# ---------------------------------------------------------------------------
# The passes
# ---------------------------------------------------------------------------

def _load_legs(user_id: int) -> list[dict]:
    """Every transfer that could be half of a movement.

    Locked rows are loaded too — they are excluded from re-matching, but they
    still occupy their legs, so a locked pair must not have its partner stolen
    by a fresh suggestion.
    """
    placeholders = ', '.join('?' * len(DEAD_STATUSES))
    return execute_query_all(
        f'''SELECT id, exchange_connection_id, exchange_name, kind, asset,
                   amount_num, occurred_at, txid, address, network, status,
                   is_internal, internal_match_id, match_source,
                   match_confidence, match_locked
            FROM transfer_history
            WHERE user_id = ?
              AND (status IS NULL OR LOWER(status) NOT IN ({placeholders}))
            ORDER BY occurred_at''',
        (user_id, *DEAD_STATUSES)
    )


def _load_rejections(user_id: int) -> set[tuple[int, int]]:
    rows = execute_query_all(
        'SELECT withdrawal_id, deposit_id FROM transfer_match_rejections WHERE user_id = ?',
        (user_id,)
    )
    return {(r['withdrawal_id'], r['deposit_id']) for r in rows}


def _load_wallets(user_id: int) -> dict[str, dict]:
    rows = execute_query_all(
        'SELECT id, label, address, address_norm, is_own FROM user_wallets WHERE user_id = ?',
        (user_id,)
    )
    return {r['address_norm']: r for r in rows if r['address_norm']}


def _txid_pairs(legs: list[dict], rejected: set) -> list[dict]:
    """Pairs sharing an on-chain hash across two different connections."""
    by_hash: dict[str, list[dict]] = {}
    for leg in legs:
        h = normalize_txid(leg['txid'])
        if h:
            by_hash.setdefault(h, []).append(leg)

    pairs = []
    for group in by_hash.values():
        if len(group) < 2:
            continue
        withdrawals = [l for l in group if l['kind'] == 'withdrawal']
        deposits = [l for l in group if l['kind'] == 'deposit']
        for w in withdrawals:
            for d in deposits:
                if w['exchange_connection_id'] == d['exchange_connection_id']:
                    continue
                if (w['id'], d['id']) in rejected:
                    continue
                pairs.append({
                    'withdrawal': w, 'deposit': d,
                    'confidence': 1.0, 'source': 'txid',
                    'detail': {'txid': normalize_txid(w['txid'])},
                })
    return pairs


def _heuristic_pairs(legs: list[dict], rejected: set) -> list[dict]:
    """Scored candidates for legs with no shared hash.

    Ambiguity is measured across the whole candidate set before anything is
    linked: a pair is only unambiguous if neither of its legs has another
    plausible partner. That check cannot be made pair-by-pair, which is why
    scoring and capping happen in two separate sweeps here.
    """
    withdrawals = [l for l in legs if l['kind'] == 'withdrawal']
    deposits = [l for l in legs if l['kind'] == 'deposit']

    raw = []
    for w in withdrawals:
        for d in deposits:
            if (w['id'], d['id']) in rejected:
                continue
            scored = score_pair(w, d)
            if scored is None:
                continue
            confidence, detail = scored
            if confidence < SUGGEST_CONFIDENCE:
                continue
            raw.append({'withdrawal': w, 'deposit': d,
                        'confidence': confidence, 'source': 'heuristic',
                        'detail': detail})

    # How many plausible partners each leg has. Counted over everything that
    # cleared SUGGEST_CONFIDENCE, so a barely-plausible alternative is still
    # enough to make a pair ambiguous — which is the cautious reading, and the
    # right one when the output feeds a money question.
    contention: dict[int, int] = {}
    for pair in raw:
        for leg in (pair['withdrawal'], pair['deposit']):
            contention[leg['id']] = contention.get(leg['id'], 0) + 1

    for pair in raw:
        competing = max(contention[pair['withdrawal']['id']],
                        contention[pair['deposit']['id']])
        if competing > 1:
            pair['confidence'] = min(pair['confidence'], AMBIGUOUS_CONFIDENCE_CAP)
            pair['detail']['competing_candidates'] = competing
    return raw


def _assign(pairs: list[dict], locked_legs: set[int]) -> list[dict]:
    """Greedy one-to-one assignment, best score first.

    A transfer has exactly one counterpart, so once a leg is spoken for it is
    out. Greedy rather than optimal: it is predictable, explainable to a user
    looking at the result, and the cases where a global optimum would differ are
    precisely the ambiguous ones that get capped below auto-link anyway.
    """
    used = set(locked_legs)
    chosen = []
    for pair in sorted(pairs, key=lambda p: -p['confidence']):
        w_id, d_id = pair['withdrawal']['id'], pair['deposit']['id']
        if w_id in used or d_id in used:
            continue
        used.add(w_id)
        used.add(d_id)
        chosen.append(pair)
    return chosen


def match_user_transfers(user_id: int) -> dict:
    """Re-derive every match for *user_id*. Returns a summary of what changed.

    Idempotent and complete: unlocked matches are cleared and re-derived from
    scratch each run, so a deleted wallet or a newly synced transfer can revise
    an earlier conclusion instead of leaving a stale one behind. Rows the user
    has locked by confirming or clearing a match are never touched.
    """
    legs = _load_legs(user_id)
    if not legs:
        return {'linked': 0, 'suggested': 0, 'wallet_resolved': 0, 'unresolved': 0}

    rejected = _load_rejections(user_id)
    wallets = _load_wallets(user_id)
    by_id = {l['id']: l for l in legs}

    locked_legs = {l['id'] for l in legs if l['match_locked']}
    # A locked leg's partner is spoken for too, even if that partner isn't
    # itself locked — otherwise the matcher would hand it to someone else and
    # leave the locked row pointing at a leg that now claims a different match.
    for leg in legs:
        if leg['match_locked'] and leg['internal_match_id'] in by_id:
            locked_legs.add(leg['internal_match_id'])

    candidates = _txid_pairs(legs, rejected) + _heuristic_pairs(legs, rejected)
    chosen = _assign(candidates, locked_legs)

    linked = [p for p in chosen if p['confidence'] >= AUTO_LINK_CONFIDENCE]
    suggested = [p for p in chosen if p['confidence'] < AUTO_LINK_CONFIDENCE]

    # Wallet attribution for whatever is left with only one leg in our data.
    linked_ids = {p[side]['id'] for p in linked for side in ('withdrawal', 'deposit')}
    wallet_hits: dict[int, dict] = {}
    for leg in legs:
        if leg['id'] in linked_ids or leg['match_locked']:
            continue
        wallet = wallets.get(normalize_address(leg['address']))
        if wallet:
            wallet_hits[leg['id']] = wallet

    conn = get_db_connection()
    try:
        # Clear only what we are about to re-derive. Locked rows keep whatever
        # the user decided.
        conn.execute(
            '''UPDATE transfer_history
               SET is_internal = NULL, internal_match_id = NULL, match_source = NULL,
                   match_confidence = NULL, counterparty_wallet_id = NULL
               WHERE user_id = ? AND COALESCE(match_locked, 0) = 0''',
            (user_id,)
        )

        for pair in linked:
            w, d = pair['withdrawal'], pair['deposit']
            for leg, partner in ((w, d), (d, w)):
                conn.execute(
                    '''UPDATE transfer_history
                       SET is_internal = 1, internal_match_id = ?, match_source = ?,
                           match_confidence = ?
                       WHERE id = ? AND COALESCE(match_locked, 0) = 0''',
                    (partner['id'], pair['source'], round(pair['confidence'], 4), leg['id'])
                )

        # Suggestions are recorded but NOT marked internal: they are a question,
        # and a question must not read as an answer to anything downstream.
        for pair in suggested:
            w, d = pair['withdrawal'], pair['deposit']
            for leg, partner in ((w, d), (d, w)):
                conn.execute(
                    '''UPDATE transfer_history
                       SET internal_match_id = ?, match_source = 'suggested',
                           match_confidence = ?
                       WHERE id = ? AND COALESCE(match_locked, 0) = 0''',
                    (partner['id'], round(pair['confidence'], 4), leg['id'])
                )

        for leg_id, wallet in wallet_hits.items():
            conn.execute(
                '''UPDATE transfer_history
                   SET counterparty_wallet_id = ?, match_source = 'wallet',
                       match_confidence = 1.0, is_internal = ?
                   WHERE id = ? AND COALESCE(match_locked, 0) = 0''',
                (wallet['id'], 1 if wallet['is_own'] else 0, leg_id)
            )

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    resolved = linked_ids | set(wallet_hits)
    return {
        'linked': len(linked),
        'suggested': len(suggested),
        'wallet_resolved': len(wallet_hits),
        'unresolved': sum(1 for l in legs
                          if l['id'] not in resolved and not l['match_locked']),
        'matched_at': int(time.time()),
    }


# ---------------------------------------------------------------------------
# Manual overrides
# ---------------------------------------------------------------------------

def confirm_match(user_id: int, withdrawal_id: int, deposit_id: int) -> bool:
    """Accept a suggested pair as real, and lock it against re-derivation."""
    legs = execute_query_all(
        '''SELECT id, kind, exchange_connection_id FROM transfer_history
           WHERE user_id = ? AND id IN (?, ?)''',
        (user_id, withdrawal_id, deposit_id)
    )
    if len(legs) != 2:
        return False
    kinds = {l['kind'] for l in legs}
    if kinds != {'withdrawal', 'deposit'}:
        return False

    conn = get_db_connection()
    try:
        # Free anything either leg was previously tied to, or that row would be
        # left pointing at a leg which now claims a different partner.
        conn.execute(
            '''UPDATE transfer_history
               SET is_internal = NULL, internal_match_id = NULL, match_source = NULL,
                   match_confidence = NULL, match_locked = 0
               WHERE user_id = ? AND internal_match_id IN (?, ?) AND id NOT IN (?, ?)''',
            (user_id, withdrawal_id, deposit_id, withdrawal_id, deposit_id)
        )
        for leg_id, partner_id in ((withdrawal_id, deposit_id), (deposit_id, withdrawal_id)):
            conn.execute(
                '''UPDATE transfer_history
                   SET is_internal = 1, internal_match_id = ?, match_source = 'user',
                       match_confidence = 1.0, match_locked = 1
                   WHERE user_id = ? AND id = ?''',
                (partner_id, user_id, leg_id)
            )
        # A confirmation cancels any earlier rejection of the same pair.
        conn.execute(
            '''DELETE FROM transfer_match_rejections
               WHERE user_id = ? AND withdrawal_id = ? AND deposit_id = ?''',
            (user_id, withdrawal_id, deposit_id)
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def reject_match(user_id: int, withdrawal_id: int, deposit_id: int) -> bool:
    """Record that these two are not the same movement.

    The rejection is stored rather than just cleared, because the next match run
    would otherwise re-score the identical pair and suggest it again. The legs
    themselves are left unlocked so each can still match something else.
    """
    conn = get_db_connection()
    try:
        conn.execute(
            '''INSERT OR IGNORE INTO transfer_match_rejections
               (user_id, withdrawal_id, deposit_id) VALUES (?, ?, ?)''',
            (user_id, withdrawal_id, deposit_id)
        )
        conn.execute(
            '''UPDATE transfer_history
               SET is_internal = NULL, internal_match_id = NULL, match_source = NULL,
                   match_confidence = NULL, match_locked = 0
               WHERE user_id = ? AND id IN (?, ?)''',
            (user_id, withdrawal_id, deposit_id)
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def unlock_match(user_id: int, transfer_id: int) -> bool:
    """Hand a manually-set row back to the matcher."""
    row = execute_query_one(
        'SELECT internal_match_id FROM transfer_history WHERE user_id = ? AND id = ?',
        (user_id, transfer_id)
    )
    if not row:
        return False
    partner = row['internal_match_id']
    conn = get_db_connection()
    try:
        ids = [transfer_id] + ([partner] if partner else [])
        conn.execute(
            f'''UPDATE transfer_history SET match_locked = 0
                WHERE user_id = ? AND id IN ({', '.join('?' * len(ids))})''',
            (user_id, *ids)
        )
        conn.commit()
        return True
    finally:
        conn.close()
