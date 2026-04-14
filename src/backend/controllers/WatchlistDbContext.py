from helper.Helper import execute_query_all, execute_insert, execute_non_query, execute_query_one


class WatchlistDbContext:

    @staticmethod
    def get_by_user(user_id: int) -> list[dict]:
        return execute_query_all(
            'SELECT id, user_id, symbol, created_at FROM watched_cryptos WHERE user_id = ? ORDER BY created_at ASC',
            (user_id,)
        )

    @staticmethod
    def add(user_id: int, symbol: str) -> int:
        return execute_insert(
            'INSERT INTO watched_cryptos (user_id, symbol) VALUES (?, ?)',
            (user_id, symbol)
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
