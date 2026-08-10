"""Tools the assistant can call, and the executor that runs them.

**Every tool dispatches through Cyrus's own HTTP routes**, in-process, via
Flask's test client with the caller's own JWT forwarded. Nothing here
re-implements a validation rule, a balance check, or an error mapping.

That's a deliberate choice rather than a shortcut. ``ExchangeController``'s
create-order path re-reads the balance on every single call specifically so a
ladder can't overspend, snaps amounts to market precision, and maps a dozen
CCXT exception types onto messages a person can act on. ``AutomationController``
runs ~80 lines of interlocking rule validation. A second copy of any of that,
reachable only through the assistant, would drift from the copy the UI uses —
and the failure mode of drift here is a wrong order or an unguarded withdrawal
rule. Going over the loopback means the assistant is exactly as constrained as
the buttons, including ``@token_required`` and ``@active_required``, and gets
the same error strings to report back verbatim.

Read tools run as soon as the model asks for them. Write tools never execute
here: the loop in ``ai_assistant`` pauses and hands them to the user first.
"""

from flask import current_app

# Anything that creates, cancels, or otherwise changes state. Gated behind an
# explicit user confirmation; see ai_assistant._run_loop.
WRITE_TOOLS = {'cancel_order', 'create_limit_order', 'create_automation_rule'}


def is_write(tool_name: str) -> bool:
    return tool_name in WRITE_TOOLS


# Rule fields AutomationController reads with `.strip()`, so they must arrive as
# strings even when they hold a number.
_RULE_STRING_FIELDS = frozenset({
    'rule_name', 'trigger_type', 'action_type', 'trigger_order_id', 'trigger_pair',
    'trigger_side', 'trigger_asset', 'trigger_threshold', 'trigger_price_quote_asset',
    'action_asset', 'action_address_key', 'action_amount', 'action_amount_mode',
    'convert_to_asset',
})


# ---------------------------------------------------------------------------
# Definitions
# ---------------------------------------------------------------------------

def tool_definitions() -> list[dict]:
    """Schemas passed to the model. Descriptions say *when* to call, not just what."""
    return [
        {
            'name': 'list_connections',
            'description': (
                "List the user's exchange connections. Call this before any action that "
                "needs a connection_id, and whenever the user names an account in words "
                '("my Kraken account", "the trading one") so you can resolve it to an id. '
                'Returns each connection\'s id, exchange, label, whether its keys are '
                'validated, and whether that exchange supports crypto withdrawals.'
            ),
            'input_schema': {'type': 'object', 'properties': {}, 'required': []},
        },
        {
            'name': 'list_open_orders',
            'description': (
                'List the resting (placed but unfilled) orders on one connection. Call '
                'this before cancelling anything so you cancel by real order id rather '
                'than guessing, and to show the user what you found. Orders flagged '
                'synthetic:true cannot be cancelled through the API — say so instead of '
                'trying.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'connection_id': {'type': 'integer', 'description': 'From list_connections.'},
                },
                'required': ['connection_id'],
            },
        },
        {
            'name': 'list_withdrawal_addresses',
            'description': (
                'List the whitelisted withdrawal addresses on one connection. Required '
                'before creating any withdraw_crypto automation rule: the rule stores an '
                "address by its nickname_key, so a user's \"my Tangem wallet\" has to be "
                'resolved to a real key here first. Only Kraken exposes these; elsewhere '
                'the list comes back empty, which means a withdraw rule is not possible.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'connection_id': {'type': 'integer', 'description': 'From list_connections.'},
                },
                'required': ['connection_id'],
            },
        },
        {
            'name': 'list_automation_rules',
            'description': (
                "List the user's existing automation rules. Call this when they ask what "
                'is set up, and before creating a rule that might duplicate one.'
            ),
            'input_schema': {'type': 'object', 'properties': {}, 'required': []},
        },
        {
            'name': 'cancel_order',
            'description': (
                'Cancel ONE resting order. To cancel several, call this once per order in '
                'the same turn — each is confirmed and reported separately, so a failure '
                'on one does not lose the others. Always call list_open_orders first; '
                'never invent an order id.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'connection_id': {'type': 'integer'},
                    'order_id': {'type': 'string', 'description': 'Exact id from list_open_orders.'},
                    'symbol': {
                        'type': 'string',
                        'description': "The order's pair, e.g. BTC/USD. Required on every exchange except Kraken.",
                    },
                },
                'required': ['connection_id', 'order_id'],
            },
        },
        {
            'name': 'create_limit_order',
            'description': (
                'Place ONE limit order. Market orders are not available. The amount is in '
                'the base asset (for BTC/USD, an amount of 0.5 means 0.5 BTC) and the '
                'price is in the quote asset. The server re-reads the live balance and '
                'rejects the order if funds are short, so do not try to compute '
                'affordability yourself — just place it and report what comes back.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'connection_id': {'type': 'integer'},
                    'symbol': {'type': 'string', 'description': 'Market symbol, e.g. BTC/USD.'},
                    'side': {'type': 'string', 'enum': ['buy', 'sell']},
                    'amount': {'type': 'number', 'description': 'Quantity in the base asset.'},
                    'price': {'type': 'number', 'description': 'Limit price in the quote asset.'},
                    'post_only': {
                        'type': 'boolean',
                        'description': 'Reject rather than fill immediately if the price crosses the book.',
                    },
                },
                'required': ['connection_id', 'symbol', 'side', 'amount', 'price'],
            },
        },
        {
            'name': 'create_automation_rule',
            'description': (
                'Create an automation rule: a trigger the background worker watches for, '
                'and an action it runs when the trigger fires.\n\n'
                'Triggers — balance_threshold (an asset balance reaches a level), '
                'price_threshold (an asset price reaches a level), order_filled (a '
                'specific resting order fills).\n'
                'Actions — withdraw_crypto (send to a whitelisted address; Kraken only, '
                'and needs action_address_key from list_withdrawal_addresses), '
                'convert_crypto (swap one asset for another on the exchange).\n\n'
                'Constraints the server enforces: price_threshold must pair with '
                'convert_crypto and its action_asset must equal its trigger_asset; '
                'order_filled needs trigger_order_id; convert needs convert_to_asset '
                'different from action_asset. Portfolio allocation caps are NOT created '
                'here — those live on the Balancer page; say so if asked.\n\n'
                'Resolve connection ids and address keys with the list_* tools before '
                'calling this, and give the rule a short descriptive name.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'rule_name': {'type': 'string', 'description': 'Short human label, e.g. "BTC over 3 to Tangem".'},
                    'trigger_type': {
                        'type': 'string',
                        'enum': ['balance_threshold', 'price_threshold', 'order_filled'],
                    },
                    'action_type': {'type': 'string', 'enum': ['withdraw_crypto', 'convert_crypto']},
                    'trigger_exchange_id': {'type': 'integer', 'description': 'Connection the trigger watches.'},
                    'action_exchange_id': {'type': 'integer', 'description': 'Connection the action runs on.'},
                    'trigger_asset': {'type': 'string', 'description': 'Asset watched. Required for balance/price triggers.'},
                    'trigger_threshold': {'type': 'string', 'description': 'Level as a number in a string, e.g. "3".'},
                    'trigger_price_quote_asset': {'type': 'string', 'description': 'Quote asset for price_threshold, e.g. USD.'},
                    'trigger_order_id': {'type': 'string', 'description': 'Required for order_filled.'},
                    'trigger_pair': {'type': 'string'},
                    'trigger_side': {'type': 'string', 'enum': ['buy', 'sell']},
                    'action_asset': {'type': 'string', 'description': 'Asset withdrawn, or converted from.'},
                    'action_address_key': {'type': 'string', 'description': 'nickname_key from list_withdrawal_addresses. Withdraw only.'},
                    'convert_to_asset': {'type': 'string', 'description': 'Target asset. Convert only.'},
                    'action_amount': {'type': 'string', 'description': 'Amount as a number in a string. Omit for balance_threshold withdrawals, which send the balance.'},
                    'action_amount_mode': {'type': 'string', 'enum': ['all', 'percent', 'fixed']},
                    'use_filled_amount': {'type': 'boolean', 'description': 'order_filled withdrawals: send exactly what filled.'},
                    'cooldown_minutes': {'type': 'integer', 'description': 'Minimum gap between firings. Defaults to 1440 (a day).'},
                    'max_executions': {'type': 'integer', 'description': 'Stop after this many firings. Omit for unlimited.'},
                },
                'required': ['rule_name', 'trigger_type', 'action_type',
                             'trigger_exchange_id', 'action_exchange_id'],
            },
        },
    ]


# ---------------------------------------------------------------------------
# In-process loopback
# ---------------------------------------------------------------------------

def _call(method: str, path: str, auth_header: str, body: dict | None = None) -> dict:
    """Dispatch one request through the app's own routing, as the same user.

    Returns ``{'ok': True, 'data': ...}`` or ``{'ok': False, 'error': str}``,
    where the error is whatever the real endpoint told the real UI.
    """
    try:
        client = current_app.test_client()
        response = client.open(
            path, method=method,
            headers={'Authorization': auth_header},
            json=body if body is not None else None,
        )
    except Exception as e:
        return {'ok': False, 'error': f"Cyrus could not run that request: {e}"}

    payload = response.get_json(silent=True)
    if payload is None:
        return {'ok': False, 'error': f"Unexpected response from {path} ({response.status_code})"}

    if response.status_code >= 400 or not payload.get('success', True):
        return {'ok': False, 'error': payload.get('result') or f"Request failed ({response.status_code})"}

    return {'ok': True, 'data': payload.get('data')}


def _int(args: dict, key: str):
    try:
        return int(args.get(key))
    except (TypeError, ValueError):
        return None


def execute(tool_name: str, args: dict, auth_header: str) -> dict:
    """Run one tool. Never raises — a failure is a result the model reports on."""
    args = args or {}

    if tool_name == 'list_connections':
        from helper.ExchangeRegistry import SUPPORTED_EXCHANGES
        result = _call('GET', '/api/exchanges/connections', auth_header)
        if not result['ok']:
            return result
        trimmed = []
        for c in result['data'] or []:
            meta = SUPPORTED_EXCHANGES.get(c.get('exchange_name'), {})
            trimmed.append({
                'connection_id': c.get('id'),
                'exchange': c.get('exchange_name'),
                'exchange_name': meta.get('name', c.get('exchange_name')),
                'label': c.get('label'),
                'is_validated': bool(c.get('is_validated')),
                'is_sandbox': bool(c.get('is_sandbox')),
                'supports_withdraw': bool(meta.get('supports_withdraw', False)),
            })
        return {'ok': True, 'data': trimmed}

    if tool_name == 'list_open_orders':
        conn = _int(args, 'connection_id')
        if conn is None:
            return {'ok': False, 'error': 'connection_id is required'}
        return _call('GET', f'/api/exchange/{conn}/open-orders', auth_header)

    if tool_name == 'list_withdrawal_addresses':
        conn = _int(args, 'connection_id')
        if conn is None:
            return {'ok': False, 'error': 'connection_id is required'}
        result = _call('GET', f'/api/exchange/{conn}/withdrawal-addresses', auth_header)
        if result['ok'] and not result['data']:
            # An empty list is the answer, but on its own it reads like a glitch.
            return {'ok': True, 'data': [], 'note': (
                'No whitelisted withdrawal addresses are available on this connection. '
                'Only Kraken exposes them, and they must be whitelisted on the exchange '
                'first. A withdraw_crypto rule cannot be created without one.')}
        return result

    if tool_name == 'list_automation_rules':
        return _call('GET', '/api/automation/rules', auth_header)

    if tool_name == 'cancel_order':
        conn = _int(args, 'connection_id')
        if conn is None:
            return {'ok': False, 'error': 'connection_id is required'}
        body = {'order_id': str(args.get('order_id') or '').strip()}
        if args.get('symbol'):
            body['symbol'] = str(args['symbol']).strip()
        return _call('POST', f'/api/exchange/{conn}/cancel-order', auth_header, body)

    if tool_name == 'create_limit_order':
        conn = _int(args, 'connection_id')
        if conn is None:
            return {'ok': False, 'error': 'connection_id is required'}
        body = {
            'type': 'limit',
            'symbol': args.get('symbol'),
            'side': args.get('side'),
            'amount': args.get('amount'),
            'price': args.get('price'),
            'post_only': bool(args.get('post_only', False)),
        }
        return _call('POST', f'/api/exchange/{conn}/create-order', auth_header, body)

    if tool_name == 'create_automation_rule':
        # Passed straight through: AutomationController owns every rule
        # constraint, and its rejection messages are what the user should see.
        # The only thing done here is a type coercion, not a validation — the
        # controller calls .strip() on these fields, so a model that sends
        # trigger_threshold as the number 3 rather than "3" would raise an
        # AttributeError and surface as a 500 instead of a usable message.
        body = {}
        for key, value in args.items():
            if value is None:
                continue
            body[key] = str(value) if key in _RULE_STRING_FIELDS else value
        return _call('POST', '/api/automation/rules', auth_header, body)

    return {'ok': False, 'error': f"Unknown tool '{tool_name}'"}


# ---------------------------------------------------------------------------
# Confirmation summaries
# ---------------------------------------------------------------------------

def summarize(tool_name: str, args: dict) -> dict:
    """A plain-language description of a pending write, built from the parsed
    arguments rather than the model's prose.

    This is what the user actually approves, so it has to come from the values
    that will really be sent. A summary written by the model could describe
    something other than what it is about to do.
    """
    args = args or {}

    if tool_name == 'cancel_order':
        pair = args.get('symbol') or 'order'
        return {
            'title': f"Cancel {pair}",
            'detail': f"Order {args.get('order_id')}",
            'danger': False,
        }

    if tool_name == 'create_limit_order':
        side = str(args.get('side') or '').upper()
        return {
            'title': f"{side} {args.get('amount')} {args.get('symbol')} @ {args.get('price')}",
            'detail': 'Limit order' + (', post-only' if args.get('post_only') else ''),
            'danger': True,
        }

    if tool_name == 'create_automation_rule':
        trigger = _describe_trigger(args)
        action = _describe_action(args)
        limits = []
        if args.get('cooldown_minutes'):
            limits.append(f"at most once every {args['cooldown_minutes']} min")
        if args.get('max_executions'):
            limits.append(f"max {args['max_executions']} times")
        detail = f"When {trigger}, {action}"
        if limits:
            detail += f" ({'; '.join(limits)})"
        return {
            'title': args.get('rule_name') or 'New automation rule',
            'detail': detail,
            # A withdraw rule moves funds off the exchange on its own schedule.
            'danger': args.get('action_type') == 'withdraw_crypto',
        }

    return {'title': tool_name, 'detail': '', 'danger': True}


def _describe_trigger(args: dict) -> str:
    trigger = args.get('trigger_type')
    if trigger == 'balance_threshold':
        return f"{args.get('trigger_asset')} balance reaches {args.get('trigger_threshold')}"
    if trigger == 'price_threshold':
        quote = args.get('trigger_price_quote_asset') or 'USD'
        return f"{args.get('trigger_asset')} price reaches {args.get('trigger_threshold')} {quote}"
    if trigger == 'order_filled':
        return f"order {args.get('trigger_order_id')} fills"
    return str(trigger)


def _describe_action(args: dict) -> str:
    if args.get('action_type') == 'withdraw_crypto':
        amount = 'the filled amount of' if args.get('use_filled_amount') else (args.get('action_amount') or 'the balance of')
        return f"withdraw {amount} {args.get('action_asset')} to \"{args.get('action_address_key')}\""

    mode = (args.get('action_amount_mode') or '').lower()
    if mode == 'percent':
        amount = f"{args.get('action_amount')}% of "
    elif mode == 'fixed' and args.get('action_amount'):
        amount = f"{args.get('action_amount')} "
    elif mode == 'all':
        amount = 'all '
    else:
        amount = ''
    return f"convert {amount}{args.get('action_asset')} to {args.get('convert_to_asset')}"
