"""The wallet import template, and parsing a filled-in one back.

Two halves of one contract, kept in one file so the columns the template writes
and the columns the importer accepts cannot drift apart.

The import is deliberately forgiving about *shape* and strict about *content*:
column order doesn't matter, headers are matched case- and punctuation-
insensitively with a set of aliases, and blank rows are skipped — but a row with
no address is reported rather than silently dropped, because a user who fills in
forty rows and imports thirty-eight needs to be told which two didn't make it
and why.
"""

from helper.Spreadsheet import write_xlsx


#: Canonical column key -> what the header may be written as.
#:
#: Aliases exist because people rename headers, translate them, or export from a
#: tool that already had its own names. "wallet", "name" and "nickname" for the
#: label; "public key" for the address (that is what Stellar and Solana call it).
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    'label':   ('label', 'name', 'wallet', 'walletname', 'nickname', 'description'),
    'address': ('address', 'walletaddress', 'publicaddress', 'publickey', 'account'),
    'chain':   ('chain', 'network', 'blockchain'),
    'asset':   ('asset', 'coin', 'currency', 'token', 'symbol'),
    'tag':     ('tag', 'memo', 'destinationtag', 'memotag', 'memoid'),
    'is_own':  ('isown', 'mine', 'ismine', 'isyours', 'ownedbyme', 'own', 'yours'),
    'notes':   ('notes', 'note', 'comment', 'comments'),
}

#: Header text -> canonical key, built once from the aliases above.
_HEADER_LOOKUP = {alias: key for key, aliases in COLUMN_ALIASES.items()
                  for alias in aliases}

#: The order columns appear in the template.
TEMPLATE_COLUMNS = ('label', 'address', 'chain', 'asset', 'tag', 'is_own', 'notes')

TEMPLATE_HEADERS = {
    'label': 'Label',
    'address': 'Address',
    'chain': 'Chain',
    'asset': 'Asset',
    'tag': 'Memo / Tag',
    'is_own': 'Is Mine',
    'notes': 'Notes',
}

TEMPLATE_WIDTHS = [22, 48, 14, 10, 16, 10, 34]

#: Values read as true / false for is_own. Anything unrecognised falls back to
#: true with a per-row warning, because "mine" is the overwhelmingly common case
#: and rejecting the row over an ambiguous yes/no would be unhelpful.
_TRUE_VALUES = {'yes', 'y', 'true', 't', '1', 'mine', 'own', 'self', 'x'}
_FALSE_VALUES = {'no', 'n', 'false', 'f', '0', 'not mine', 'notmine', 'other',
                 'external', 'someone else', 'third party'}

MAX_IMPORT_ROWS = 500

#: Marker the template writes into the Notes column of its own sample rows.
#: They are skipped on import, because the likeliest first-time mistake is
#: filling in rows below the examples and leaving the examples in place — which
#: would otherwise save four wallets nobody owns.
EXAMPLE_MARKER = 'example row'


def normalize_header(text: str) -> str:
    """Collapse a header to its comparison form: lowercase, letters only."""
    return ''.join(ch for ch in str(text or '').lower() if ch.isalnum())


def parse_is_own(value) -> tuple[bool, str | None]:
    """``(is_own, warning)``. Blank means mine, which is the common case."""
    text = str(value or '').strip().lower()
    if not text:
        return True, None
    if text in _TRUE_VALUES:
        return True, None
    if text in _FALSE_VALUES:
        return False, None
    return True, (f'"{value}" was not recognised as yes or no, so this wallet was '
                  f'treated as yours. Use yes or no.')


def build_template(examples: list[dict] | None = None) -> bytes:
    """The downloadable .xlsx template.

    Ships with example rows because an empty grid with seven headers leaves the
    format of each column to guesswork — particularly Is Mine, and the fact that
    a memo belongs in its own column rather than appended to the address. The
    examples are clearly marked as deletable.

    When *examples* is given (the user's already-saved wallets), those are used
    instead: exporting what exists makes the file a round-trip, so editing a
    dozen labels is a download, an edit and an import rather than a dozen dialog
    visits.
    """
    header = [TEMPLATE_HEADERS[c] for c in TEMPLATE_COLUMNS]

    if examples:
        rows = [header]
        for wallet in examples:
            rows.append([
                wallet.get('label') or '',
                wallet.get('address') or '',
                wallet.get('chain') or '',
                wallet.get('asset') or '',
                wallet.get('tag') or '',
                'yes' if wallet.get('is_own') else 'no',
                wallet.get('notes') or '',
            ])
    else:
        rows = [
            header,
            ['My Ledger', 'bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq',
             'Bitcoin', 'BTC', '', 'yes', 'EXAMPLE ROW - delete this'],
            ['MetaMask', '0x71C7656EC7ab88b098defB751B7401B5f6d8976F',
             'Ethereum', '', '', 'yes', 'EXAMPLE ROW - delete this'],
            ['Stellar wallet', 'GDQP2KPQGKIHYJGXNUIYOMHARUARCA7DJT5FO2FFOOKY3B2WSQHG4W37',
             'Stellar', 'XLM', '1234567890', 'yes',
             'EXAMPLE ROW - the memo goes in its own column, not on the address'],
            ["Landlord's wallet", '0x9f2C5B4d1eA83c7Bd6119cF8b7C4A1e0dD3F5b62',
             'Ethereum', 'USDC', '', 'no',
             'EXAMPLE ROW - someone else, so Is Mine is no'],
        ]

    instructions = [
        ['Importing wallets into Cyrus'],
        [''],
        ['Fill in one row per wallet on the "Wallets" sheet, then import the file'],
        ['from the Transfers page (Wallets -> Import from file).'],
        [''],
        ['Column', 'Required?', 'What it is'],
        ['Label', 'Required', 'A name you will recognise later, e.g. "My Ledger".'],
        ['Address', 'Required', 'The wallet address on its own. No memo, no amount, no label.'],
        ['Chain', 'Optional', 'Which network, e.g. Bitcoin, Ethereum, Stellar. For your reference.'],
        ['Asset', 'Optional', 'A coin, if the wallet only ever holds one, e.g. BTC.'],
        ['Memo / Tag', 'Optional', 'Stellar memo or XRP destination tag. Keep it out of the Address column.'],
        ['Is Mine', 'Optional', 'yes or no. Blank counts as yes.'],
        ['', '', 'Only wallets that are yours count as internal transfers between'],
        ['', '', 'your own accounts. Use no for someone else you want to recognise.'],
        ['Notes', 'Optional', 'Anything else you want to remember about it.'],
        [''],
        ['Good to know'],
        ['Column order does not matter, and extra columns are ignored.'],
        ['You can rename the headers to any reasonable synonym - "Name" works for Label,'],
        ['"Network" for Chain, "Memo" for Tag.'],
        ['An address already saved is skipped rather than duplicated, so re-importing'],
        ['the same file is safe.'],
        ['Addresses are matched case-insensitively, so the case you paste does not matter.'],
        ['CSV works too if you would rather not use Excel.'],
        [''],
        ['What Cyrus does with these'],
        ['An exchange reports the address a transfer went to, but never who owns it.'],
        ['Labelling an address is what turns "withdrew 0.05 BTC to bc1q..." into'],
        ['"moved 0.05 BTC to My Ledger" - on every matching transfer, past and future.'],
    ]

    return write_xlsx([
        {'name': 'Wallets', 'rows': rows, 'widths': TEMPLATE_WIDTHS},
        {'name': 'Instructions', 'rows': instructions,
         'widths': [16, 12, 78], 'freeze_header': False},
    ])


def map_columns(header_row: list) -> tuple[dict[str, int], list[str]]:
    """``({canonical_key: column_index}, unrecognised_headers)``.

    First occurrence wins for a duplicated column, so a file with two "Notes"
    columns uses the leftmost rather than whichever happened to be last.
    """
    mapping: dict[str, int] = {}
    unknown: list[str] = []
    for index, cell in enumerate(header_row):
        text = str(cell or '').strip()
        if not text:
            continue
        key = _HEADER_LOOKUP.get(normalize_header(text))
        if key is None:
            unknown.append(text)
        elif key not in mapping:
            mapping[key] = index
    return mapping, unknown


def parse_rows(rows: list[list]) -> dict:
    """Turn sheet rows into wallet dicts plus per-row problems.

    Returns ``{'wallets', 'errors', 'warnings', 'unknown_columns', 'header_row'}``
    where each error carries the spreadsheet row number the user can actually go
    and look at — 1-based including the header, so it matches what Excel shows
    down the side.
    """
    # Skip leading blank rows: a template that has been edited often gains one.
    header_index = None
    for index, row in enumerate(rows):
        if any(str(cell or '').strip() for cell in row):
            header_index = index
            break
    if header_index is None:
        return {'wallets': [], 'errors': [{'row': None, 'message': 'The file is empty.'}],
                'warnings': [], 'unknown_columns': [], 'header_row': None}

    mapping, unknown = map_columns(rows[header_index])

    if 'address' not in mapping or 'label' not in mapping:
        missing = [name for name, key in (('Label', 'label'), ('Address', 'address'))
                   if key not in mapping]
        found = ', '.join(str(c).strip() for c in rows[header_index]
                          if str(c or '').strip()) or 'nothing'
        return {
            'wallets': [],
            'errors': [{'row': header_index + 1, 'message':
                        f'The first row must name the columns, and {" and ".join(missing)} '
                        f'{"is" if len(missing) == 1 else "are"} missing. '
                        f'Found: {found}. Download the template if you are unsure.'}],
            'warnings': [], 'unknown_columns': unknown, 'header_row': header_index + 1,
        }

    def cell(row: list, key: str) -> str:
        index = mapping.get(key)
        if index is None or index >= len(row):
            return ''
        return str(row[index] or '').strip()

    wallets: list[dict] = []
    errors: list[dict] = []
    warnings: list[dict] = []
    seen: dict[str, int] = {}

    for offset, row in enumerate(rows[header_index + 1:], start=header_index + 2):
        if not any(str(c or '').strip() for c in row):
            continue

        if len(wallets) >= MAX_IMPORT_ROWS:
            errors.append({'row': offset, 'message':
                           f'Stopped at {MAX_IMPORT_ROWS} wallets — split the file '
                           f'and import the rest separately.'})
            break

        label = cell(row, 'label')
        address = cell(row, 'address')
        notes = cell(row, 'notes')

        if notes.lower().startswith(EXAMPLE_MARKER):
            warnings.append({'row': offset, 'label': label,
                             'message': 'Skipped — this is one of the template\'s '
                                        'example rows. Delete those rows to silence this.'})
            continue

        if not address:
            errors.append({'row': offset, 'label': label,
                           'message': 'No address in this row.'})
            continue
        if not label:
            errors.append({'row': offset, 'address': address,
                           'message': 'No label in this row — give it a name you '
                                      'will recognise.'})
            continue

        # An address pasted with its memo appended is a silent never-matches, so
        # it's worth catching by shape.
        if ' ' in address:
            errors.append({'row': offset, 'label': label, 'address': address,
                           'message': 'That address contains a space. Paste the '
                                      'address on its own — a memo or tag goes in '
                                      'the Memo / Tag column.'})
            continue

        key = address.lower()
        if key in seen:
            errors.append({'row': offset, 'label': label, 'address': address,
                           'message': f'The same address is already on row {seen[key]} '
                                      f'of this file.'})
            continue
        seen[key] = offset

        is_own, warning = parse_is_own(cell(row, 'is_own'))
        if warning:
            warnings.append({'row': offset, 'label': label, 'message': warning})

        wallets.append({
            'row': offset,
            'label': label[:60],
            'address': address,
            'chain': cell(row, 'chain')[:32] or None,
            'asset': (cell(row, 'asset')[:16] or None),
            'tag': cell(row, 'tag')[:64] or None,
            'is_own': is_own,
            'notes': notes[:500] or None,
        })

    return {'wallets': wallets, 'errors': errors, 'warnings': warnings,
            'unknown_columns': unknown, 'header_row': header_index + 1}
