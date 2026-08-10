"""HTTP surface for user-declared crypto addresses.

Every write re-runs the transfer matcher, because a wallet's whole purpose is to
change how existing transfers are attributed. Adding one and seeing the Transfers
page unchanged until some later sync would make the feature look broken.
"""

import base64
import binascii
import re

from flask import Blueprint, request

from controllers.WalletDbContext import WalletDbContext
from helper.ErrorHandler import handle_error, bad_request, not_found
from helper.Helper import success_response, created_response
from helper.Security import token_required, active_required
from helper.TransferMatch import match_user_transfers, normalize_address

wallet_bp = Blueprint('wallets', __name__)

MAX_LABEL = 60
MAX_NOTES = 500

#: Deliberately permissive. Addresses across the chains Cyrus sees take wildly
#: different forms — bech32 (bc1…), base58 (1…/3…/T…), 0x-hex, Stellar's 56-char
#: base32, Cosmos bech32 with an hrp prefix — and a strict per-chain validator
#: would be a large amount of code whose failure mode is rejecting a legitimate
#: address the user pasted correctly. This catches obvious rubbish (spaces,
#: punctuation, wrong length) and leaves correctness to the match: an address
#: that is wrong simply never matches anything.
_ADDRESS_RE = re.compile(r'^[A-Za-z0-9:_.-]{16,128}$')

#: A memo/tag is a separate field on chains that use one (XLM memo, XRP
#: destination tag). Pasting "address:memo" is a common mistake and produces an
#: address that silently never matches, so it's worth naming.
_TAGGED_HINT = re.compile(r'[:]')


def _clean_text(value, limit: int) -> str:
    return str(value or '').strip()[:limit]


def _validate_address(raw, user_id: int) -> tuple[str, str] | str:
    """``(display, normalized)`` or an error message.

    The shape checks exist to catch a mistyped or half-pasted address, so they
    are skipped for anything already present in the user's own transfer
    history: that string came from an exchange, it is real by definition, and
    whatever it looks like the user must be able to label it. Kraken in
    particular reports some funding entries by nickname rather than address, and
    refusing to label those would break the one-click path from the suggestions
    list — the main way anyone will actually add wallets.
    """
    address = str(raw or '').strip()
    if not address:
        return 'An address is required'

    normalized = normalize_address(address)
    if not normalized:
        return 'That address could not be read'

    if WalletDbContext.address_seen_in_history(user_id, address):
        return address, normalized

    if len(address) < 16:
        return 'That address looks too short to be valid'
    if len(address) > 128:
        return 'That address looks too long to be valid'
    if not _ADDRESS_RE.match(address):
        return ('That does not look like a crypto address. Paste just the '
                'address, with no spaces, label or amount.')
    return address, normalized


def _serialize(row: dict) -> dict:
    return {
        'id': row['id'],
        'label': row['label'],
        'address': row['address'],
        'chain': row.get('chain'),
        'asset': row.get('asset'),
        'tag': row.get('tag'),
        'is_own': bool(row['is_own']),
        'notes': row.get('notes'),
        'transfer_count': row.get('transfer_count', 0),
        'created_at': row.get('created_at'),
    }


def _payload(body: dict, user_id: int) -> tuple[dict, str | None]:
    label = _clean_text(body.get('label'), MAX_LABEL)
    if not label:
        return {}, 'A label is required — something you will recognise later'

    validated = _validate_address(body.get('address'), user_id)
    if isinstance(validated, str):
        return {}, validated
    address, address_norm = validated

    return {
        'label': label,
        'address': address,
        'address_norm': address_norm,
        'chain': _clean_text(body.get('chain'), 32) or None,
        'asset': (_clean_text(body.get('asset'), 16) or None),
        'tag': _clean_text(body.get('tag'), 64) or None,
        # Defaults to "mine", which is what almost every entry will be. Only an
        # own wallet makes a transfer internal, so the flag has to be explicit
        # rather than inferred.
        'is_own': bool(body.get('is_own', True)),
        'notes': _clean_text(body.get('notes'), MAX_NOTES) or None,
    }, None


@wallet_bp.route('/', methods=['GET'])
@token_required
@active_required
def list_wallets():
    try:
        rows = WalletDbContext.list_wallets(request.user_id)
        return success_response(data=[_serialize(r) for r in rows])
    except Exception as e:
        return handle_error(e)


@wallet_bp.route('/suggestions', methods=['GET'])
@token_required
@active_required
def suggestions():
    """Unlabelled addresses already present in the user's transfer history."""
    try:
        rows = WalletDbContext.suggest_addresses(request.user_id)
        return success_response(data=[{
            'address': r['address'],
            'network': r.get('network'),
            'assets': [a for a in (r.get('assets') or '').split(',') if a],
            'uses': r['uses'],
            'withdrawals': r['withdrawals'],
            'deposits': r['deposits'],
            'last_seen': r['last_seen'],
        } for r in rows])
    except Exception as e:
        return handle_error(e)


@wallet_bp.route('/', methods=['POST'])
@token_required
@active_required
def create_wallet():
    try:
        body = request.get_json(silent=True) or {}
        fields, error = _payload(body, request.user_id)
        if error:
            return bad_request(error)

        existing = WalletDbContext.find_by_norm(request.user_id, fields['address_norm'])
        if existing:
            return bad_request(
                f"That address is already saved as \"{existing['label']}\".")

        wallet_id = WalletDbContext.create_wallet(request.user_id, **fields)
        # Attribute existing transfers to the new wallet straight away.
        summary = match_user_transfers(request.user_id)
        row = WalletDbContext.get_wallet(request.user_id, wallet_id)
        return created_response(
            data={'wallet': _serialize(dict(row, transfer_count=0)), 'match': summary},
            message='Wallet saved')
    except Exception as e:
        return handle_error(e)


@wallet_bp.route('/<int:wallet_id>', methods=['PUT'])
@token_required
@active_required
def update_wallet(wallet_id):
    try:
        if not WalletDbContext.get_wallet(request.user_id, wallet_id):
            return not_found('Wallet not found')

        body = request.get_json(silent=True) or {}
        fields, error = _payload(body, request.user_id)
        if error:
            return bad_request(error)

        clash = WalletDbContext.find_by_norm(request.user_id, fields['address_norm'])
        if clash and clash['id'] != wallet_id:
            return bad_request(
                f"That address is already saved as \"{clash['label']}\".")

        WalletDbContext.update_wallet(request.user_id, wallet_id, **fields)
        summary = match_user_transfers(request.user_id)
        row = WalletDbContext.get_wallet(request.user_id, wallet_id)
        return success_response(data={'wallet': _serialize(row), 'match': summary},
                                message='Wallet updated')
    except Exception as e:
        return handle_error(e)


# ---------------------------------------------------------------------------
# Template download and bulk import
# ---------------------------------------------------------------------------

#: Ceiling on an uploaded file, before base64 expansion. A wallet list is a few
#: KB; anything at this size is a mistake or an attempt to exhaust memory, and
#: either way the parse would be pointless.
MAX_UPLOAD_BYTES = 4 * 1024 * 1024


@wallet_bp.route('/template', methods=['GET'])
@token_required
@active_required
def wallet_template():
    """The .xlsx import template, base64-encoded for the renderer to save.

    Base64 in JSON rather than a binary response: the renderer hands the bytes
    to Electron's native save dialog over IPC, which is how the app already
    saves the Robinhood key-generator script, and it gives the user a real
    "where do you want this" dialog rather than a silent drop into Downloads.

    ``?include_existing=1`` exports what is already saved instead of the example
    rows, which makes the template a round-trip: download, edit in bulk, import.
    """
    try:
        from helper.WalletImport import build_template

        include = (request.args.get('include_existing') or '').lower() in ('1', 'true', 'yes')
        existing = WalletDbContext.list_wallets(request.user_id) if include else []
        data = build_template(existing if existing else None)
        return success_response(data={
            'filename': 'cyrus-wallets.xlsx' if not existing else 'cyrus-wallets-export.xlsx',
            'content_base64': base64.b64encode(data).decode('ascii'),
            'bytes': len(data),
            'exported': len(existing),
        })
    except Exception as e:
        return handle_error(e)


@wallet_bp.route('/import', methods=['POST'])
@token_required
@active_required
def import_wallets():
    """Parse an uploaded wallet file and, unless previewing, save what is valid.

    Two-phase by design. ``preview: true`` parses and reports exactly what would
    happen — how many are new, which rows are already saved, which rows are
    broken and why — without writing anything. The user confirms, and the same
    endpoint runs again without the flag. Importing forty rows and discovering
    afterwards that six were malformed is a worse experience than being shown
    first, and the parse is cheap enough to do twice.

    Valid rows are saved even when others fail: a single typo on row 12 must not
    cost the user the other 39 rows they filled in correctly.
    """
    try:
        from helper.WalletImport import parse_rows
        from helper.Spreadsheet import read_table, SpreadsheetError

        body = request.get_json(silent=True) or {}
        raw = body.get('content_base64')
        if raw is None:
            return bad_request('No file was received.')
        if not str(raw):
            # An empty string means a file WAS picked and it had no content —
            # a different problem from nothing arriving, and worth saying so.
            return bad_request('That file is empty.')

        try:
            data = base64.b64decode(str(raw), validate=True)
        except (binascii.Error, ValueError):
            return bad_request('That file could not be read.')
        if not data:
            return bad_request('That file is empty.')
        if len(data) > MAX_UPLOAD_BYTES:
            return bad_request('That file is too large to be a wallet list.')

        filename = _clean_text(body.get('filename'), 200)
        preview = bool(body.get('preview'))

        try:
            rows = read_table(data, filename)
        except SpreadsheetError as e:
            return bad_request(str(e))

        parsed = parse_rows(rows)
        candidates = parsed['wallets']

        # Split against what is already saved before writing, so the report can
        # distinguish "already had this" from "just added it" — re-importing the
        # same file should read as a no-op, not as an error.
        to_create, duplicates = [], []
        for wallet in candidates:
            norm = normalize_address(wallet['address'])
            existing = WalletDbContext.find_by_norm(request.user_id, norm) if norm else None
            if existing:
                duplicates.append({'row': wallet['row'], 'label': wallet['label'],
                                   'address': wallet['address'],
                                   'existing_label': existing['label']})
            else:
                to_create.append(dict(wallet, address_norm=norm))

        created, failures = [], []
        if not preview:
            for wallet in to_create:
                try:
                    WalletDbContext.create_wallet(
                        request.user_id, label=wallet['label'], address=wallet['address'],
                        address_norm=wallet['address_norm'], chain=wallet['chain'],
                        asset=wallet['asset'], tag=wallet['tag'],
                        is_own=wallet['is_own'], notes=wallet['notes'])
                    created.append(wallet['label'])
                except Exception as e:
                    # One bad row must not abort the rest of the import.
                    failures.append({'row': wallet['row'], 'label': wallet['label'],
                                     'message': str(e)})

        match = None
        if created:
            match = match_user_transfers(request.user_id)

        return success_response(data={
            'preview': preview,
            'header_row': parsed['header_row'],
            'unknown_columns': parsed['unknown_columns'],
            'would_create': [
                {'row': w['row'], 'label': w['label'], 'address': w['address'],
                 'chain': w['chain'], 'is_own': w['is_own']}
                for w in to_create],
            'created': len(created),
            'duplicates': duplicates,
            'errors': parsed['errors'] + failures,
            'warnings': parsed['warnings'],
            'match': match,
        }, message='Preview ready' if preview else f'Imported {len(created)} wallets')
    except Exception as e:
        return handle_error(e)


@wallet_bp.route('/<int:wallet_id>', methods=['DELETE'])
@token_required
@active_required
def delete_wallet(wallet_id):
    try:
        if not WalletDbContext.delete_wallet(request.user_id, wallet_id):
            return not_found('Wallet not found')
        summary = match_user_transfers(request.user_id)
        return success_response(data={'match': summary}, message='Wallet removed')
    except Exception as e:
        return handle_error(e)
