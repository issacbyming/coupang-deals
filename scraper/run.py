"""
Coupang 台灣每日折扣商品抓取主入口。
由 GitHub Actions 定時觸發，或手動執行。
"""

import asyncio
import sys
from pathlib import Path

# 讓 import 找得到同層模組
sys.path.insert(0, str(Path(__file__).parent))

from coupang import CoupangScraper
from db import init_db, upsert_deal, cleanup_old_deals, clear_today

DB_PATH = str(Path(__file__).parent.parent / "data" / "deals.db")


async def main():
    print("=== Coupang 台灣折扣抓取開始 ===")

    conn = init_db(DB_PATH)
    scraper = CoupangScraper(headless=True)

    try:
        deals = await scraper.fetch_deals()
    except Exception as e:
        print(f"[ERROR] 爬蟲失敗：{e}", file=sys.stderr)
        conn.close()
        sys.exit(1)

    # 清除今天的舊資料，確保只保留最新結果
    import datetime
    clear_today(conn, datetime.date.today().isoformat())

    saved = 0
    for deal in deals:
        try:
            upsert_deal(conn, deal)
            saved += 1
        except Exception as e:
            print(f"[WARN] 儲存失敗：{deal.get('title', '')}：{e}", file=sys.stderr)

    cleanup_old_deals(conn, keep_days=7)
    conn.close()

    print(f"=== 完成：共儲存 {saved} 筆 5折以下商品 ===")


if __name__ == "__main__":
    asyncio.run(main())
