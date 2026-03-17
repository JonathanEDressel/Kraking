from helper.Helper import execute_query_one, execute_query_all, execute_non_query, execute_insert


class ExchangeConnectionDbContext:

    @staticmethod
    def get_connections_by_user(user_id: int) -> list[dict]:
        return execute_query_all(
            'SELECT * FROM exchange_connections WHERE user_id = ? ORDER BY created_at',
            (user_id,)
        )

    @staticmethod
    def get_connection(connection_id: int, user_id: int) -> dict | None:
        return execute_query_one(
            'SELECT * FROM exchange_connections WHERE id = ? AND user_id = ?',
            (connection_id, user_id)
        )

    @staticmethod
    def create_connection(user_id: int, exchange_name: str, label: str,
                          api_key_encrypted: str, private_key_encrypted: str,
                          passphrase_encrypted: str | None = None,
                          is_sandbox: bool = False) -> int:
        return execute_insert(
            '''INSERT INTO exchange_connections
               (user_id, exchange_name, label, api_key_encrypted, private_key_encrypted, passphrase_encrypted, is_sandbox)
               VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (user_id, exchange_name, label, api_key_encrypted, private_key_encrypted, passphrase_encrypted, int(is_sandbox))
        )

    @staticmethod
    def update_connection_keys(connection_id: int, user_id: int,
                               api_key_encrypted: str, private_key_encrypted: str,
                               passphrase_encrypted: str | None = None) -> bool:
        execute_non_query(
            '''UPDATE exchange_connections
               SET api_key_encrypted = ?, private_key_encrypted = ?, passphrase_encrypted = ?,
                   is_validated = 0, keys_last_validated = NULL
               WHERE id = ? AND user_id = ?''',
            (api_key_encrypted, private_key_encrypted, passphrase_encrypted, connection_id, user_id)
        )
        return True

    @staticmethod
    def delete_connection(connection_id: int, user_id: int) -> bool:
        execute_non_query(
            'DELETE FROM exchange_connections WHERE id = ? AND user_id = ?',
            (connection_id, user_id)
        )
        return True

    @staticmethod
    def mark_validated(connection_id: int, user_id: int) -> bool:
        execute_non_query(
            '''UPDATE exchange_connections
               SET is_validated = 1, keys_last_validated = CURRENT_TIMESTAMP
               WHERE id = ? AND user_id = ?''',
            (connection_id, user_id)
        )
        return True

    @staticmethod
    def mark_invalid(connection_id: int, user_id: int) -> bool:
        execute_non_query(
            '''UPDATE exchange_connections
               SET is_validated = 0, keys_last_validated = CURRENT_TIMESTAMP
               WHERE id = ? AND user_id = ?''',
            (connection_id, user_id)
        )
        return True

    @staticmethod
    def count_active_rules_for_connection(connection_id: int) -> int:
        from helper.Helper import execute_scalar
        count = execute_scalar(
            '''SELECT COUNT(*) FROM automation_rules
               WHERE is_active = 1
                 AND (trigger_exchange_id = ? OR action_exchange_id = ?)''',
            (connection_id, connection_id)
        )
        return count or 0

    @staticmethod
    def get_validated_connections_by_user(user_id: int) -> list[dict]:
        return execute_query_all(
            'SELECT * FROM exchange_connections WHERE user_id = ? AND is_validated = 1',
            (user_id,)
        )
