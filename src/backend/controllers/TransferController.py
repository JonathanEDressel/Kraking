"""HTTP surface for exchange transfer history.

Reads and writes are strictly separated. ``GET /`` and ``GET /status`` never
touch an exchange — they serve whatever the last sync persisted, so opening the
page is a couple of indexed queries regardless of how much history exists. Only
``POST /sync`` talks to an exchange, and it does one bounded slice of work per
call (see ``helper/TransferSync.py``) so the request always returns promptly
even when years of backfill remain.
"""

import time

from flask import Blueprint, request

from controllers.ExchangeConnectionDbContext import ExchangeConnectionDbContext
from controllers.TransferDbContext import TransferDbContext
from helper.ErrorHandler import handle_error, bad_request, not_found
from helper.Helper import success_response
from helper.Security import token_required, active_required
from helper.ExchangeRegistry import get_connection_row, supports_transfer_history

transfer_bp = Blueprint('transfers', __name__)

KINDS = ('deposit', 'withdrawal')

MAX_PAGE_SIZE = 500
DEFAULT_PAGE_SIZE = 100


def _clamp_int(value, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _optional_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _owned_conn_id(user_id: int, raw):
    """``(conn_id, error_response)``. A blank/``all`` value means every connection.

    Ownership is re-checked here rather than trusted from the query string —
    otherwise ``?conn_id=`` would read another user's transfer history.
    """
    if raw is None or str(raw).strip() == '' or str(raw).lower() == 'all':
        return None, None
    try:
        conn_id = int(raw)
    except (TypeError, ValueError):
        return None, bad_request('conn_id must be an integer')
    if not get_connection_row(user_id, conn_id):
        return None, not_found('Exchange connection not found')
    return conn_id, None


def _target_state(rows_by_kind: dict, kind: str, exchange_name: str,
                  now: int) -> dict:
    """Render one (connection, kind) sync-state row for the API."""
    if not supports_transfer_history(exchange_name):
        return {'state': 'unsupported', 'progress_pct': 0}

    state = rows_by_kind.get(kind)
    if not state or not state.get('synced_through'):
        return {'state': 'not_started', 'progress_pct': 0}

    if state.get('disabled'):
        return {
            'state': 'disabled',
            'progress_pct': 0,
            'disabled_reason': state.get('disabled_reason'),
        }

    epoch = int(state.get('history_epoch') or 0)
    synced_through = int(state.get('synced_through') or 0)
    complete = bool(state.get('backfill_complete'))

    span = max(now - epoch, 1)
    progress = 100 if complete else max(0, min(100, int((synced_through - epoch) / span * 100)))

    last_ok = state.get('last_sync_ok_at')
    return {
        # 'error' only when nothing is in flight — a transient failure part-way
        # through a backfill is still progress, not a dead end.
        'state': 'error' if (state.get('last_error') and not complete and progress == 0)
                 else ('idle' if complete else 'backfilling'),
        'progress_pct': progress,
        'synced_through': synced_through,
        'backfill_complete': complete,
        'last_sync_ok_at': last_ok,
        # Computed server-side: the client's clock cannot be trusted to agree.
        'age_seconds': (now - int(last_ok)) if last_ok else None,
        'last_error': state.get('last_error'),
    }


def _build_status(user_id: int) -> dict:
    """Per-connection sync status for the whole user."""
    now = int(time.time())
    rows = TransferDbContext.get_sync_states_by_user(user_id)

    connections: dict[int, dict] = {}
    for row in rows:
        conn_id = row['exchange_connection_id']
        entry = connections.get(conn_id)
        if entry is None:
            exchange_name = row['exchange_name']
            entry = connections[conn_id] = {
                'connection_id': conn_id,
                'exchange': exchange_name,
                'label': row.get('label'),
                'supported': supports_transfer_history(exchange_name),
                '_by_kind': {},
            }
        if row.get('kind'):
            entry['_by_kind'][row['kind']] = row

    out = []
    any_pending = False
    for entry in connections.values():
        by_kind = entry.pop('_by_kind')
        entry['kinds'] = {
            kind: _target_state(by_kind, kind, entry['exchange'], now)
            for kind in KINDS
        }
        if any(k['state'] in ('not_started', 'backfilling')
               for k in entry['kinds'].values()):
            any_pending = True
        out.append(entry)

    return {'connections': out, 'any_pending': any_pending}


@transfer_bp.route('/', methods=['GET'])
@token_required
@active_required
def list_transfers():
    try:
        user_id = request.user_id
        conn_id, err = _owned_conn_id(user_id, request.args.get('conn_id'))
        if err:
            return err

        kind = (request.args.get('kind') or '').strip().lower() or None
        if kind and kind not in KINDS:
            return bad_request("kind must be 'deposit' or 'withdrawal'")

        asset = (request.args.get('asset') or '').strip().upper() or None
        status = (request.args.get('status') or '').strip().lower() or None
        since_ts = _optional_int(request.args.get('from'))
        until_ts = _optional_int(request.args.get('to'))
        limit = _clamp_int(request.args.get('limit'), DEFAULT_PAGE_SIZE, 1, MAX_PAGE_SIZE)
        offset = _clamp_int(request.args.get('offset'), 0, 0, 10_000_000)

        filters = dict(conn_id=conn_id, kind=kind, asset=asset, status=status,
                       since_ts=since_ts, until_ts=until_ts)
        items = TransferDbContext.list_transfers(user_id, limit=limit, offset=offset,
                                                 **filters)
        total = TransferDbContext.count_transfers(user_id, **filters)

        # The sync block rides along so the page renders in one round-trip and
        # still knows whether to show a "syncing" affordance.
        return success_response(data={
            'items': items,
            'total': total,
            'limit': limit,
            'offset': offset,
            'sync': _build_status(user_id),
        })
    except Exception as e:
        return handle_error(e)


@transfer_bp.route('/status', methods=['GET'])
@token_required
@active_required
def sync_status():
    try:
        return success_response(data=_build_status(request.user_id))
    except Exception as e:
        return handle_error(e)


@transfer_bp.route('/sync', methods=['POST'])
@token_required
@active_required
def run_sync():
    """Run one bounded slice of sync and report progress.

    ``complete: false`` is the normal case mid-backfill, not an error — the
    caller loops until it flips. A connection already syncing in another request
    reports ``already_running`` rather than starting a second, competing walk
    against the same API key.
    """
    try:
        from helper.TransferSync import sync_connection

        user_id = request.user_id
        body = request.get_json(silent=True) or {}
        conn_id, err = _owned_conn_id(user_id, body.get('conn_id'))
        if err:
            return err

        if conn_id is not None:
            targets = [conn_id]
        else:
            targets = [
                c['id'] for c in
                ExchangeConnectionDbContext.get_validated_connections_by_user(user_id)
                if supports_transfer_history(c['exchange_name'])
            ]

        complete, new_rows, already_running = True, 0, False
        for target in targets:
            result = sync_connection(user_id, target)
            new_rows += result.get('new_rows', 0)
            if result.get('already_running'):
                already_running = True
            if not result.get('complete', True):
                complete = False

        # New rows can complete a pairing whose other half was already stored,
        # so re-match whenever anything landed. Best-effort: the transfers are
        # saved either way, and matching is derived data that the next run
        # rebuilds from scratch.
        match = None
        if new_rows:
            try:
                from helper.TransferMatch import match_user_transfers
                match = match_user_transfers(user_id)
            except Exception as e:
                print(f"[TRANSFERS] match after sync failed: {e}")

        return success_response(data={
            'complete': complete,
            'new_rows': new_rows,
            'already_running': already_running,
            'match': match,
            'sync': _build_status(user_id),
        })
    except Exception as e:
        return handle_error(e)


@transfer_bp.route('/assets', methods=['GET'])
@token_required
@active_required
def transfer_assets():
    try:
        return success_response(data=TransferDbContext.get_distinct_assets(request.user_id))
    except Exception as e:
        return handle_error(e)


# ---------------------------------------------------------------------------
# Movement timeline
# ---------------------------------------------------------------------------

def _endpoint(kind: str, leg: dict, side: str) -> dict:
    """Describe one end of a hop.

    ``side`` is 'exchange' for the venue this leg belongs to, or 'counterparty'
    for whatever sits at the other end. An unresolved counterparty is reported
    as ``unknown`` with the raw address, never guessed at — an unlabelled
    address genuinely could be anyone, including the user.
    """
    if side == 'exchange':
        return {
            'type': 'exchange',
            'label': leg.get('connection_label') or leg['exchange_name'],
            'exchange': leg['exchange_name'],
            'connection_id': leg['exchange_connection_id'],
        }
    if leg.get('wallet_label'):
        return {
            'type': 'wallet',
            'label': leg['wallet_label'],
            'wallet_id': leg['counterparty_wallet_id'],
            'is_own': bool(leg.get('wallet_is_own')),
            'address': leg.get('address'),
        }
    return {
        'type': 'unknown',
        'label': 'Unknown wallet' if leg.get('address') else 'Unknown source',
        'address': leg.get('address'),
    }


def _hop(occurred_at: int, asset: str, amount: str, amount_num, source: dict,
         destination: dict, legs: list[int], **extra) -> dict:
    hop = {
        'occurred_at': occurred_at,
        'asset': asset,
        'amount': amount,
        'amount_num': amount_num,
        'from': source,
        'to': destination,
        'legs': legs,
    }
    hop.update(extra)
    return hop


def _build_flow(legs: list[dict]) -> list[dict]:
    """Collapse legs into date-ordered movements.

    A matched pair is ONE movement with two ends, not two events — that
    collapsing is the whole point of the view. Everything else is a single-ended
    movement whose far end is either a labelled wallet or honestly unknown.
    """
    by_id = {l['id']: l for l in legs}
    consumed: set[int] = set()
    hops: list[dict] = []

    for leg in legs:
        if leg['id'] in consumed:
            continue

        partner_id = leg['internal_match_id']
        partner = by_id.get(partner_id) if partner_id else None
        confirmed = partner is not None and leg['match_source'] in (
            'txid', 'heuristic', 'user', 'wallet')

        # A confirmed pair between two connections: one hop, venue to venue.
        if partner is not None and confirmed and leg['match_source'] != 'wallet':
            consumed.add(leg['id'])
            consumed.add(partner['id'])
            out_leg = leg if leg['kind'] == 'withdrawal' else partner
            in_leg = partner if leg['kind'] == 'withdrawal' else leg
            fee = None
            try:
                fee = round(float(out_leg['amount_num']) - float(in_leg['amount_num']), 12)
            except (TypeError, ValueError):
                fee = None
            hops.append(_hop(
                out_leg['occurred_at'], out_leg['asset'], out_leg['amount'],
                out_leg['amount_num'],
                _endpoint('withdrawal', out_leg, 'exchange'),
                _endpoint('deposit', in_leg, 'exchange'),
                [out_leg['id'], in_leg['id']],
                kind='internal',
                received=in_leg['amount'],
                received_num=in_leg['amount_num'],
                network_fee=fee,
                arrived_at=in_leg['occurred_at'],
                match_source=leg['match_source'],
                confidence=leg['match_confidence'],
                locked=bool(leg['match_locked']),
                status=in_leg['status'] or out_leg['status'],
            ))
            continue

        # An unresolved suggestion: shown as a single-ended movement, with the
        # proposed counterpart attached so the UI can offer confirm/reject. It is
        # deliberately NOT drawn as a completed hop — that would present a guess
        # as a fact.
        # Attached to the WITHDRAWAL leg only. Both legs of a suggested pair
        # point at each other, so offering it from each side would ask the same
        # question twice and let one answer leave the other stranded. The
        # outbound side is the natural place to ask "did this end up there?".
        suggestion = None
        if (partner is not None and leg['match_source'] == 'suggested'
                and leg['kind'] == 'withdrawal'):
            other = partner
            suggestion = {
                'transfer_id': other['id'],
                'exchange': other.get('connection_label') or other['exchange_name'],
                'kind': other['kind'],
                'amount': other['amount'],
                'asset': other['asset'],
                'occurred_at': other['occurred_at'],
                'confidence': leg['match_confidence'],
                'withdrawal_id': leg['id'] if leg['kind'] == 'withdrawal' else other['id'],
                'deposit_id': other['id'] if leg['kind'] == 'withdrawal' else leg['id'],
            }

        consumed.add(leg['id'])
        venue = _endpoint(leg['kind'], leg, 'exchange')
        counterparty = _endpoint(leg['kind'], leg, 'counterparty')
        outbound = leg['kind'] == 'withdrawal'
        hops.append(_hop(
            leg['occurred_at'], leg['asset'], leg['amount'], leg['amount_num'],
            venue if outbound else counterparty,
            counterparty if outbound else venue,
            [leg['id']],
            kind='outbound' if outbound else 'inbound',
            match_source=leg['match_source'],
            confidence=leg['match_confidence'],
            locked=bool(leg['match_locked']),
            is_internal=leg['is_internal'],
            fee_amount=leg['fee_amount'],
            fee_currency=leg['fee_currency'],
            status=leg['status'],
            suggestion=suggestion,
        ))

    hops.sort(key=lambda h: (-(h['occurred_at'] or 0), h['asset']))
    return hops


@transfer_bp.route('/flow', methods=['GET'])
@token_required
@active_required
def transfer_flow():
    """Date-ordered movements: what left where, and where it landed."""
    try:
        asset = (request.args.get('asset') or '').strip().upper() or None
        since_ts = _optional_int(request.args.get('from'))

        legs = TransferDbContext.list_for_flow(request.user_id, since_ts, asset)
        hops = _build_flow(legs)

        counts = {'internal': 0, 'outbound': 0, 'inbound': 0,
                  'suggested': 0, 'unknown_counterparty': 0}
        for hop in hops:
            counts[hop['kind']] = counts.get(hop['kind'], 0) + 1
            if hop.get('suggestion'):
                counts['suggested'] += 1
            if hop['from']['type'] == 'unknown' or hop['to']['type'] == 'unknown':
                counts['unknown_counterparty'] += 1

        return success_response(data={
            'hops': hops,
            'counts': counts,
            'total_legs': len(legs),
        })
    except Exception as e:
        return handle_error(e)


@transfer_bp.route('/rematch', methods=['POST'])
@token_required
@active_required
def rematch():
    try:
        from helper.TransferMatch import match_user_transfers
        return success_response(data=match_user_transfers(request.user_id),
                                message='Transfers re-matched')
    except Exception as e:
        return handle_error(e)


def _pair_from_body(body: dict) -> tuple[int, int] | None:
    try:
        return int(body.get('withdrawal_id')), int(body.get('deposit_id'))
    except (TypeError, ValueError):
        return None


@transfer_bp.route('/match/confirm', methods=['POST'])
@token_required
@active_required
def confirm_match_route():
    try:
        from helper.TransferMatch import confirm_match
        pair = _pair_from_body(request.get_json(silent=True) or {})
        if not pair:
            return bad_request('withdrawal_id and deposit_id are required')
        if not confirm_match(request.user_id, *pair):
            return bad_request(
                'Those two transfers cannot be paired — a match needs one '
                'withdrawal and one deposit, both belonging to you.')
        return success_response(message='Match confirmed')
    except Exception as e:
        return handle_error(e)


@transfer_bp.route('/match/reject', methods=['POST'])
@token_required
@active_required
def reject_match_route():
    try:
        from helper.TransferMatch import reject_match
        pair = _pair_from_body(request.get_json(silent=True) or {})
        if not pair:
            return bad_request('withdrawal_id and deposit_id are required')
        reject_match(request.user_id, *pair)
        return success_response(message='Match rejected')
    except Exception as e:
        return handle_error(e)


@transfer_bp.route('/match/unlock', methods=['POST'])
@token_required
@active_required
def unlock_match_route():
    """Hand a manually-decided transfer back to automatic matching."""
    try:
        from helper.TransferMatch import unlock_match
        body = request.get_json(silent=True) or {}
        transfer_id = _optional_int(body.get('transfer_id'))
        if transfer_id is None:
            return bad_request('transfer_id is required')
        if not unlock_match(request.user_id, transfer_id):
            return not_found('Transfer not found')
        return success_response(message='Match unlocked')
    except Exception as e:
        return handle_error(e)
