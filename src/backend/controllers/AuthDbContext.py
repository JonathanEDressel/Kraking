from helper.Helper import execute_query_one, execute_insert, execute_non_query, execute_scalar
from models.UserModel import UserModel


class AuthDbContext:
    
    @staticmethod
    def get_user_by_username(username: str) -> UserModel:
        row = execute_query_one(
            'SELECT * FROM users WHERE username = ?',
            (username,)
        )
        return UserModel.from_row(row)
    
    @staticmethod
    def create_user(username: str, password_hash: str) -> UserModel:
        user_id = execute_insert(
            '''INSERT INTO users (username, password_hash)
               VALUES (?, ?)''',
            (username, password_hash)
        )
        
        row = execute_query_one(
            'SELECT * FROM users WHERE id = ?',
            (user_id,)
        )
        return UserModel.from_row(row)
    
    @staticmethod
    def update_last_login(user_id: int) -> None:
        execute_non_query(
            "UPDATE users SET last_login = datetime('now') WHERE id = ?",
            (user_id,)
        )
    
    @staticmethod
    def username_exists(username: str) -> bool:
        result = execute_scalar(
            'SELECT 1 FROM users WHERE username = ?',
            (username,)
        )
        return result is not None
