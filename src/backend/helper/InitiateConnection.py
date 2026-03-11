import sqlite3
from flask import current_app


def get_db_connection():
    conn = sqlite3.connect(
        current_app.config['DATABASE_PATH'],
        check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    conn.execute('PRAGMA journal_mode = WAL')
    return conn
