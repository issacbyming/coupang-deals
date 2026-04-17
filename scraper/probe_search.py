"""
探索 Coupang 台灣搜尋頁，驗證：
1. 搜尋 URL 的實際格式
2. 搜尋結果頁是否使用同一套 selector (li.baby-product)
3. 分頁處理方式
4. 幾個關鍵字實際命中的 ≤5折商品數

設計目的：如果可行，把搜尋整合進正式爬蟲，補抓散在各活動頁之外的商品。
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

from utils import parse_price, calc_ratio

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

# 測試的 URL pattern（Coupang 常見兩種）
URL_PATTERNS = [
    "https://www.tw.coupang.com/np/search?q={kw}",
    "https://www.tw.coupang.com/np/search?q={kw}&page=1",
    "https://www.tw.coupang.com/np/search?component=&q={kw}&channel=user",
]

# 測試的關鍵字
KEYWORDS = [
    "賣家優惠",
    "賣家特價",
    "限時特價",
    "5折",
    "半價",
    "出清",
    "清倉",
]


async def diagnose_one_pattern(context, pattern: str, kw: str):
    """診斷單一 URL pattern + 關鍵字組合。"""
    url = pattern.format(kw=kw)
    page = await context.new_page()
    if HAS_STEALTH:
        await stealth_async(page)
    try:
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=25000)
        status = resp.status if resp else "N/A"
        await page.wait_for_timeout(2500)
        # 捲動載入更多
        for _ in range(3):
            await page.evaluate("window.scrollBy(0, window.innerHeight*2)")
            await page.wait_for_timeout(500)

        title = (await page.title()).strip()[:50]
        # 測試各種 selector
        selectors = [
            "li.baby-product",
            "li.search-product",
            "[data-product-id]",
            "a[href*='/products/']",
        ]
        sel_counts = {}
        for sel in selectors:
            els = await page.query_selector_all(sel)
            sel_counts[sel] = len(els)

        # 嘗試用 li.baby-product 抽價格（如有）
        sample_count = 0
        under_5fold = 0
        sample_title = ""
        cards = await page.query_selector_all("li.baby-product")
        for i, card in enumerate(cards[:50]):
            try:
                sale_el = await card.query_selector("strong.price-value")
                orig_el = await card.query_selector("del")
                name_el = await card.query_selector("div.name")
                if sale_el and orig_el:
                    sp = parse_price((await sale_el.inner_text()).strip())
                    op = parse_price((await orig_el.inner_text()).strip())
                    if sp and op and op > sp:
                        ratio = calc_ratio(op, sp)
                        sample_count += 1
                        if ratio <= 0.5:
                            under_5fold += 1
                            if not sample_title and name_el:
                                sample_title = (await name_el.inner_text()).strip()[:30]
            except Exception:
                continue

        return {
            "pattern": pattern,
            "kw": kw,
            "url": url,
            "status": status,
            "title": title,
            "selectors": sel_counts,
            "has_price": sample_count,
            "under_5fold": under_5fold,
            "sample": sample_title,
        }
    except Exception as e:
        return {"pattern": pattern, "kw": kw, "error": str(e)[:80]}
    finally:
        await page.close()


async def probe_pagination(context, kw: str):
    """測試分頁是否用 ?page=N，最多到多少頁仍有資料。"""
    print(f"\n=== [分頁測試] 關鍵字：{kw} ===")
    for page_no in [1, 2, 3, 5, 10]:
        url = f"https://www.tw.coupang.com/np/search?q={kw}&page={page_no}"
        page = await context.new_page()
        if HAS_STEALTH:
            await stealth_async(page)
        try:
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(2000)
            cards = await page.query_selector_all("li.baby-product")
            print(f"  page={page_no}: status={resp.status if resp else 'N/A'}, cards={len(cards)}")
        except Exception as e:
            print(f"  page={page_no}: ERR {str(e)[:60]}")
        finally:
            await page.close()


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=UA,
            locale="zh-TW",
            viewport={"width": 1280, "height": 900},
        )

        # 暖身
        print("[warm] 建立 session...")
        warm = await context.new_page()
        if HAS_STEALTH:
            await stealth_async(warm)
        try:
            await warm.goto("https://www.tw.coupang.com/", wait_until="domcontentloaded", timeout=30000)
            await warm.wait_for_timeout(3000)
        except Exception:
            pass
        await warm.close()

        # Step 1: 逐一試每個 pattern × 關鍵字
        print("\n=== [Step 1] URL pattern × 關鍵字測試 ===")
        sem = asyncio.Semaphore(3)
        async def bounded(pattern, kw):
            async with sem:
                return await diagnose_one_pattern(context, pattern, kw)

        tasks = []
        for pattern in URL_PATTERNS:
            for kw in KEYWORDS:
                tasks.append(bounded(pattern, kw))
        results = await asyncio.gather(*tasks)

        # 彙整結果
        print("\n結果總表：")
        print(f"{'pattern':<55} {'kw':<10} {'status':<8} {'baby-product':<15} {'≤5折':<6} sample")
        print("-" * 130)
        best_pattern = None
        best_score = 0
        for r in results:
            if "error" in r:
                print(f"{r['pattern'][:55]:<55} {r['kw']:<10} ERR: {r['error']}")
                continue
            bp_count = r["selectors"].get("li.baby-product", 0)
            score = bp_count + r["under_5fold"] * 5  # 權重：≤5折較重要
            print(f"{r['pattern'][:55]:<55} {r['kw']:<10} {str(r['status']):<8} {bp_count:<15} {r['under_5fold']:<6} {r['sample']}")
            if score > best_score:
                best_score, best_pattern = score, r["pattern"]

        # Step 2: 對最佳 pattern + 最佳關鍵字做分頁測試
        print(f"\n=== [Step 2] 最佳 pattern：{best_pattern} ===")
        # 找命中最多的關鍵字
        best_kw = max(
            (r for r in results if r.get("pattern") == best_pattern and "error" not in r),
            key=lambda r: r["selectors"].get("li.baby-product", 0),
            default=None,
        )
        if best_kw:
            await probe_pagination(context, best_kw["kw"])

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
