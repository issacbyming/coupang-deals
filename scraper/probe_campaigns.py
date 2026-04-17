"""
探測 Coupang 台灣有效的 campaign IDs。
掃描範圍：1-500。有效判斷：頁面至少包含 3 個商品卡片（li.baby-product）。
結果寫入 valid_campaigns.txt，供 coupang.py 更新。
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from playwright.async_api import async_playwright
try:
    from playwright_stealth import stealth_async
    HAS_STEALTH = True
except ImportError:
    HAS_STEALTH = False

BASE_URL = "https://www.tw.coupang.com/np/campaigns/{}"
HOMEPAGE = "https://www.tw.coupang.com/"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
HEADERS = {
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "sec-ch-ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
}

# 掃描範圍
ID_RANGE = range(1, 500)
PARALLELISM = 5  # Akamai 友善：低並行度


async def probe_one(context, cid: int) -> dict | None:
    """回傳 {id, count, sample} 或 None。"""
    page = await context.new_page()
    if HAS_STEALTH:
        await stealth_async(page)
    try:
        resp = await page.goto(BASE_URL.format(cid), wait_until="domcontentloaded", timeout=20000)
        if not resp or resp.status >= 400:
            return None
        await page.wait_for_timeout(1800)
        cards = await page.query_selector_all("li.baby-product")
        if len(cards) >= 3:
            title_el = await cards[0].query_selector("div.name")
            title = (await title_el.inner_text()).strip()[:30] if title_el else ""
            return {"id": cid, "count": len(cards), "sample": title}
        return None
    except Exception:
        return None
    finally:
        await page.close()


async def main():
    print(f"掃描範圍：{min(ID_RANGE)}-{max(ID_RANGE)}（共 {len(ID_RANGE)} 個），並行 {PARALLELISM}")
    valid = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=UA,
            locale="zh-TW",
            viewport={"width": 1280, "height": 900},
            extra_http_headers=HEADERS,
        )

        # 暖身：先訪問首頁，再訪問已知有效的 campaign，建立 Akamai session
        print("建立 session...")
        warm = await context.new_page()
        if HAS_STEALTH:
            await stealth_async(warm)
        try:
            await warm.goto(HOMEPAGE, wait_until="domcontentloaded", timeout=30000)
            await warm.wait_for_timeout(3000)
            await warm.goto(BASE_URL.format(82), wait_until="domcontentloaded", timeout=30000)
            await warm.wait_for_timeout(3000)
            cards = await warm.query_selector_all("li.baby-product")
            print(f"  暖身成功，campaign 82 有 {len(cards)} 件商品")
        except Exception as e:
            print(f"  暖身失敗：{e}")
        await warm.close()

        sem = asyncio.Semaphore(PARALLELISM)
        done = 0
        total = len(ID_RANGE)

        async def bounded(cid):
            nonlocal done
            async with sem:
                result = await probe_one(context, cid)
                done += 1
                if result:
                    print(f"  ✓ [{done}/{total}] {cid}: {result['count']} 件 — {result['sample']}")
                elif done % 25 == 0:
                    print(f"  ... 進度 {done}/{total}")
                return result

        results = await asyncio.gather(*(bounded(i) for i in ID_RANGE))
        valid_items = [r for r in results if r is not None]
        valid_items.sort(key=lambda x: x["id"])
        valid = [r["id"] for r in valid_items]

        await browser.close()

    print(f"\n=== 找到 {len(valid)} 個有效 campaigns ===")
    print(f"CAMPAIGN_IDS = {valid}")

    # 寫入檔案
    out = Path(__file__).parent / "valid_campaigns.txt"
    out.write_text(",".join(str(i) for i in valid), encoding="utf-8")
    print(f"已寫入：{out}")


if __name__ == "__main__":
    asyncio.run(main())
