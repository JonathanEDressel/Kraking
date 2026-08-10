"""Endpoints for the portfolio assistant.

Key management mirrors the SMTP app password on the Profile page: the key is
write-only from the client's point of view — it goes in encrypted and only ever
comes back as the boolean ``anthropic_key_set``.

``/ask`` deliberately takes nothing but a question and the visible conversation.
The portfolio itself is gathered server-side in ``helper/ai_assistant.py``, so a
compromised or buggy client can't feed the model fabricated balances.
"""

from flask import Blueprint, request
from helper.Security import token_required, active_required, encrypt_api_key
from helper.ErrorHandler import handle_error, bad_request, not_found
from helper.Helper import success_response
from helper import ai_assistant

ai_bp = Blueprint('ai', __name__)


@ai_bp.route('/status', methods=['GET'])
@token_required
def status():
    """Whether this user has a key on file, and which model it will call."""
    try:
        from controllers.UserDbContext import UserDbContext

        user = UserDbContext.get_user_by_id(request.user_id)
        if not user:
            return not_found("User not found")

        return success_response(data={
            'configured': bool(user.anthropic_key_encrypted),
            'model': ai_assistant.MODEL,
        })
    except Exception as e:
        return handle_error(e)


@ai_bp.route('/key', methods=['PUT'])
@token_required
def save_key():
    """Validate a key against Anthropic, then store it encrypted."""
    try:
        from controllers.UserDbContext import UserDbContext

        data = request.get_json() or {}
        api_key = (data.get('api_key') or '').strip()
        if not api_key:
            return bad_request("An API key is required")

        try:
            ai_assistant.verify_key(api_key)
        except ValueError as e:
            return bad_request(str(e))

        UserDbContext.update_anthropic_key(request.user_id, encrypt_api_key(api_key))
        return success_response(data={'configured': True},
                                message="API key saved and verified")
    except Exception as e:
        return handle_error(e)


@ai_bp.route('/key', methods=['DELETE'])
@token_required
def delete_key():
    try:
        from controllers.UserDbContext import UserDbContext

        UserDbContext.update_anthropic_key(request.user_id, None)
        ai_assistant.invalidate_snapshot(request.user_id)
        return success_response(data={'configured': False}, message="API key removed")
    except Exception as e:
        return handle_error(e)


def _auth_header() -> str:
    """The caller's own Authorization header, forwarded to the tool executor.

    Tools re-enter the app through its real routes (see helper/ai_tools.py), so
    they authenticate as this user and are bound by the same decorators. There
    is no service account and no way for the assistant to act as anyone else.
    """
    return request.headers.get('Authorization', '')


@ai_bp.route('/ask', methods=['POST'])
@token_required
@active_required
def ask():
    """Start a turn: answer a question, or propose actions for confirmation."""
    try:
        data = request.get_json() or {}

        # A fresh panel should see current numbers even if a question was asked
        # a minute ago; mid-conversation follow-ups reuse the cached snapshot.
        if data.get('refresh'):
            ai_assistant.invalidate_snapshot(request.user_id)

        try:
            result = ai_assistant.ask(
                request.user_id, data.get('question'), data.get('history'), _auth_header()
            )
        except ValueError as e:
            return bad_request(str(e))

        return success_response(data=result)
    except Exception as e:
        return handle_error(e)


@ai_bp.route('/confirm', methods=['POST'])
@token_required
@active_required
def confirm():
    """Approve or decline the actions a paused turn is waiting on.

    Nothing that changes state runs until this endpoint says so: ``/ask`` stops
    at the first write the model proposes and returns it for display.
    """
    try:
        data = request.get_json() or {}
        token = (data.get('token') or '').strip()
        if not token:
            return bad_request("A confirmation token is required")

        try:
            result = ai_assistant.resume(
                request.user_id, token, bool(data.get('approved')), _auth_header()
            )
        except ValueError as e:
            return bad_request(str(e))

        # Balances and orders have just changed underneath the cached snapshot.
        ai_assistant.invalidate_snapshot(request.user_id)
        return success_response(data=result)
    except Exception as e:
        return handle_error(e)
