import sqlite3
import datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS deals (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    title          TEXT NOT NULL,
    url            TEXT NOT NULL UNIQUE,
    image_url      TEXT,
    original_price REAL,
    sale_price     REAL,
    discount_ratio REAL,
    date           TEXT,
    fetched_at     TEXT
);
"""


def init_db(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    conn.commit()
    return conn


def upsert_deal(conn: sqlite3.Connection, deal: dict) -> None:
    conn.execute(
        """
        INSERT INTO deals (title, url, image_url, original_price, sale_price, discount_ratio, date, fetched_at)
        VALUES (:title, :url, :image_url, :original_price, :sale_price, :discount_ratio, :date, :fetched_at)
        ON CONFLICT(url) DO UPDATE SET
            title = excluded.title,
            image_url = excluded.image_url,
            original_price = excluded.original_price,
            sale_price = excluded.sale_price,
            discount_ratio = excluded.discount_ratio,
            date = excluded.date,
            fetched_at = excluded.fetched_at
        """,
        deal,
    )
    conn.commit()


def get_deals(conn: sqlite3.Connection, date: str, max_ratio: float = 0.5) -> list:
    rows = conn.execute(
        "SELECT * FROM deals WHERE date = ? AND discount_ratio <= ? ORDER BY discount_ratio ASC",
        (date, max_ratio),
    ).fetchall()
    return [dict(r) for r in rows]


def clear_today(conn: sqlite3.Connection, date: str) -> None:
    """清除指定日期的所有商品，以便重新寫入最新結果。"""
    conn.execute("DELETE FROM deals WHERE date = ?", (date,))
    conn.commit()


def cleanup_old_deals(conn: sqlite3.Connection, keep_days: int = 7) -> None:
    cutoff = (datetime.date.today() - datetime.timedelta(days=keep_days)).isoformat()
    conn.execute("DELETE FROM deals WHERE date < ?", (cutoff,))
    conn.commit()
