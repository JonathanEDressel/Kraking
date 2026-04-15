from helper.Helper import execute_query_all, execute_insert, execute_non_query, execute_query_one, get_db_connection


class WatchlistDbContext:

    @staticmethod
    def get_by_user(user_id: int) -> list[dict]:
        return execute_query_all(
            'SELECT id, user_id, symbol, sort_order, created_at FROM watched_cryptos WHERE user_id = ? ORDER BY sort_order ASC, created_at ASC',
            (user_id,)
        )

    @staticmethod
    def add(user_id: int, symbol: str) -> int:
        return execute_insert(
            'INSERT INTO watched_cryptos (user_id, symbol, sort_order) VALUES (?, ?, (SELECT COALESCE(MAX(sort_order), -1) + 1 FROM watched_cryptos WHERE user_id = ?))',
            (user_id, symbol, user_id)
        )

    @staticmethod
    def delete(user_id: int, symbol: str) -> bool:
        rows = execute_non_query(
            'DELETE FROM watched_cryptos WHERE user_id = ? AND symbol = ?',
            (user_id, symbol)
        )
        return rows > 0

    @staticmethod
    def exists(user_id: int, symbol: str) -> bool:
        row = execute_query_one(
            'SELECT 1 FROM watched_cryptos WHERE user_id = ? AND symbol = ?',
            (user_id, symbol)
        )
        return row is not None

    @staticmethod
    def update_order(user_id: int, ordered_symbols: list[str]) -> None:
        conn = get_db_connection()
        try:
            for idx, symbol in enumerate(ordered_symbols):
                conn.execute(
                    'UPDATE watched_cryptos SET sort_order = ? WHERE user_id = ? AND symbol = ?',
                    (idx, user_id, symbol)
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
