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
    fetched_at     TEXT,
    price_verified INTEGER DEFAULT 0
);
"""


def init_db(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    # 現有資料庫若缺欄位則補上（idempotent）
    try:
        conn.execute("ALTER TABLE deals ADD COLUMN price_verified INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # 欄位已存在
    conn.commit()
    return conn


def upsert_deal(conn: sqlite3.Connection, deal: dict) -> None:
    # 確保 price_verified 存在（True/False → 1/0）
    deal = dict(deal)
    deal["price_verified"] = 1 if deal.get("price_verified") else 0
    conn.execute(
        """
        INSERT INTO deals (title, url, image_url, original_price, sale_price, discount_ratio, date, fetched_at, price_verified)
        VALUES (:title, :url, :image_url, :original_price, :sale_price, :discount_ratio, :date, :fetched_at, :price_verified)
        ON CONFLICT(url) DO UPDATE SET
            title = excluded.title,
            image_url = excluded.image_url,
            original_price = excluded.original_price,
            sale_price = excluded.sale_price,
            discount_ratio = excluded.discount_ratio,
            date = excluded.date,
            fetched_at = excluded.fetched_at,
            price_verified = excluded.price_verified
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
