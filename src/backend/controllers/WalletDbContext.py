"""Data access for user-declared crypto addresses.

These are the only way a transfer with one leg outside Cyrus can be attributed.
An exchange reports the address a withdrawal went to but never who owns it, so
"withdrew 0.05 BTC to bc1q…" only becomes "moved 0.05 BTC to my Ledger" once the
user has said that address is theirs.

``address_norm`` is the matching key and ``address`` is what the user typed —
see ``TransferMatch.normalize_address`` for why those have to be separate.
"""

from helper.Helper import (execute_query_all, execute_query_one, execute_insert,
                           execute_non_query, execute_scalar)
from helper.InitiateConnection import get_db_connection


class WalletDbContext:

    @staticmethod
    def list_wallets(user_id: int) -> list[dict]:
        """Wallets with a count of how many transfers currently point at each.

        The count is what lets the UI warn before a delete that would orphan
        attributions, and it is cheap enough to carry on the list.
        """
        return execute_query_all(
            '''SELECT w.id, w.label, w.address, w.address_norm, w.chain, w.asset,
                      w.tag, w.is_own, w.notes, w.created_at,
                      (SELECT COUNT(*) FROM transfer_history t
                        WHERE t.counterparty_wallet_id = w.id) AS transfer_count
               FROM user_wallets w
               WHERE w.user_id = ?
               ORDER BY w.is_own DESC, w.label COLLATE NOCASE''',
            (user_id,)
        )

    @staticmethod
    def get_wallet(user_id: int, wallet_id: int) -> dict | None:
        return execute_query_one(
            'SELECT * FROM user_wallets WHERE user_id = ? AND id = ?',
            (user_id, int(wallet_id))
        )

    @staticmethod
    def find_by_norm(user_id: int, address_norm: str) -> dict | None:
        return execute_query_one(
            'SELECT * FROM user_wallets WHERE user_id = ? AND address_norm = ?',
            (user_id, address_norm)
        )

    @staticmethod
    def create_wallet(user_id: int, label: str, address: str, address_norm: str,
                      chain: str | None = None, asset: str | None = None,
                      tag: str | None = None, is_own: bool = True,
                      notes: str | None = None) -> int:
        return execute_insert(
            '''INSERT INTO user_wallets
               (user_id, label, address, address_norm, chain, asset, tag, is_own, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (user_id, label, address, address_norm, chain, asset, tag,
             1 if is_own else 0, notes)
        )

    @staticmethod
    def update_wallet(user_id: int, wallet_id: int, label: str, address: str,
                      address_norm: str, chain: str | None, asset: str | None,
                      tag: str | None, is_own: bool, notes: str | None) -> bool:
        rows = execute_non_query(
            '''UPDATE user_wallets
               SET label = ?, address = ?, address_norm = ?, chain = ?,
                   asset = ?, tag = ?, is_own = ?, notes = ?
               WHERE user_id = ? AND id = ?''',
            (label, address, address_norm, chain, asset, tag, 1 if is_own else 0,
             notes, user_id, int(wallet_id))
        )
        return rows > 0

    @staticmethod
    def delete_wallet(user_id: int, wallet_id: int) -> bool:
        """Delete a wallet and detach it from any transfer that referenced it.

        Done in one transaction rather than relying on a foreign key: the
        ``counterparty_wallet_id`` column was added by ALTER TABLE, and SQLite
        cannot add a constraint that way, so nothing would cascade. A dangling id
        would leave transfers attributed to a wallet that no longer exists.
        """
        conn = get_db_connection()
        try:
            owned = conn.execute(
                'SELECT 1 FROM user_wallets WHERE user_id = ? AND id = ?',
                (user_id, int(wallet_id))
            ).fetchone()
            if not owned:
                return False

            conn.execute(
                '''UPDATE transfer_history
                   SET counterparty_wallet_id = NULL,
                       match_source = CASE WHEN match_source = 'wallet' THEN NULL
                                           ELSE match_source END,
                       is_internal = CASE WHEN match_source = 'wallet' THEN NULL
                                          ELSE is_internal END,
                       match_confidence = CASE WHEN match_source = 'wallet' THEN NULL
                                               ELSE match_confidence END
                   WHERE user_id = ? AND counterparty_wallet_id = ?''',
                (user_id, int(wallet_id))
            )
            conn.execute(
                'DELETE FROM user_wallets WHERE user_id = ? AND id = ?',
                (user_id, int(wallet_id))
            )
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def address_seen_in_history(user_id: int, address: str) -> bool:
        """True when this exact address already appears in the user's transfers.

        Used to waive the shape checks on an address that demonstrably came from
        an exchange. Compared case-insensitively so a user retyping what the
        suggestions list showed them still counts.
        """
        text = str(address or '').strip()
        if not text:
            return False
        row = execute_query_one(
            '''SELECT 1 FROM transfer_history
               WHERE user_id = ? AND LOWER(TRIM(address)) = LOWER(?)
               LIMIT 1''',
            (user_id, text)
        )
        return row is not None

    @staticmethod
    def count_wallets(user_id: int) -> int:
        return int(execute_scalar(
            'SELECT COUNT(*) FROM user_wallets WHERE user_id = ?', (user_id,)) or 0)

    @staticmethod
    def suggest_addresses(user_id: int, limit: int = 25) -> list[dict]:
        """Addresses seen in transfer history that aren't labelled yet.

        Turns wallet setup from "go and find your addresses" into picking from a
        list Cyrus already has, which is the difference between a feature people
        use and one they don't.
        """
        return execute_query_all(
            '''SELECT t.address,
                      MIN(t.network)          AS network,
                      GROUP_CONCAT(DISTINCT t.asset) AS assets,
                      COUNT(*)                AS uses,
                      MAX(t.occurred_at)      AS last_seen,
                      SUM(CASE WHEN t.kind = 'withdrawal' THEN 1 ELSE 0 END) AS withdrawals,
                      SUM(CASE WHEN t.kind = 'deposit'    THEN 1 ELSE 0 END) AS deposits
               FROM transfer_history t
               WHERE t.user_id = ?
                 AND t.address IS NOT NULL AND TRIM(t.address) <> ''
                 AND t.counterparty_wallet_id IS NULL
               GROUP BY t.address
               ORDER BY uses DESC, last_seen DESC
               LIMIT ?''',
            (user_id, int(limit))
        )
