from flask import Blueprint, request
from helper.Security import token_required
from helper.ErrorHandler import handle_error, bad_request
from helper.Helper import success_response
from controllers.WatchlistDbContext import WatchlistDbContext

watchlist_bp = Blueprint('watchlist', __name__)


@watchlist_bp.route('/', methods=['GET'])
@token_required
def get_watchlist():
    try:
        items = WatchlistDbContext.get_by_user(request.user_id)
        return success_response(data=items)
    except Exception as e:
        return handle_error(e)


@watchlist_bp.route('/', methods=['POST'])
@token_required
def add_to_watchlist():
    try:
        body = request.get_json(silent=True) or {}
        symbol = (body.get('symbol') or '').strip().upper()
        if not symbol:
            return bad_request("Symbol is required")

        if WatchlistDbContext.exists(request.user_id, symbol):
            return bad_request("Symbol already in watchlist")

        new_id = WatchlistDbContext.add(request.user_id, symbol)
        return success_response(data={'id': new_id, 'symbol': symbol}, message="Added to watchlist")
    except Exception as e:
        return handle_error(e)


@watchlist_bp.route('/<path:symbol>', methods=['DELETE'])
@token_required
def remove_from_watchlist(symbol: str):
    try:
        symbol = symbol.strip().upper()
        deleted = WatchlistDbContext.delete(request.user_id, symbol)
        if not deleted:
            return bad_request("Symbol not found in watchlist")
        return success_response(message="Removed from watchlist")
    except Exception as e:
        return handle_error(e)
