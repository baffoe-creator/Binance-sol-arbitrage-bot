import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path("data/cache/state.db")

def init_state_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS bot_state (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        held_asset TEXT, held_qty REAL, in_flight INTEGER, updated_at TEXT
    )""")
    conn.execute("INSERT OR IGNORE INTO bot_state (id, held_asset, held_qty, in_flight) VALUES (1, NULL, 0, 0)")
    conn.commit()
    conn.close()

@contextmanager
def atomic_cycle_state():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE bot_state SET in_flight = 1")
    conn.commit()
    try:
        yield conn
        conn.execute("UPDATE bot_state SET in_flight = 0, held_asset = NULL, held_qty = 0")
        conn.commit()
    except Exception:
        conn.commit()
        raise
    finally:
        conn.close()

def check_recovery_needed() -> bool:
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT in_flight FROM bot_state WHERE id = 1").fetchone()
    conn.close()
    return bool(row and row[0])