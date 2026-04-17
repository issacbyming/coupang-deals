"""
診斷「列表頁價格 vs 點進詳細頁價格」的差異。
給定一組商品 URL，訪問詳細頁擷取實際酷澎售價，印出對比。

使用：修改 TEST_URLS，push 後用 GitHub Actions 手動觸發 diagnose workflow 執行。
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

from utils import parse_price

# 使用者回報「點進去價錢不一樣」的樣本 URL
TEST_URLS = [
    "https://www.tw.coupang.com/vp/products/474348095750165?itemId=474348095733781&vendorItemId=474348095782924&sourceType=CAMPAIGN&campaignId=272&categoryId=0",
    "https://www.tw.coupang.com/vp/products/21006566087623?itemId=21017110507695&vendorItemId=21081961211845&sourceType=CAMPAIGN&campaignId=427&categoryId=0",
    "https://www.tw.coupang.com/vp/products/577979692269568?itemId=577979692318721&vendorItemId=577979688124423&sourceType=CAMPAIGN&campaignId=281&categoryId=0",
]

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"


async def inspect_detail(context, url: str):
    page = await context.new_page()
    if HAS_STEALTH:
        await stealth_async(page)
    try:
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=25000)
        await page.wait_for_timeout(2500)
        title = (await page.title()).strip()[:60]
        status = resp.status if resp else "N/A"

        # 擷取多個可能的價格 selector，全部列出對比
        selectors = {
            "div.sales-price-amount": None,
            ".sales-price .price-amount": None,
            ".prod-sale-price .price-amount": None,
            "strong.price-value": None,
            "[class*='sales-price']": None,
            "[class*='total-price']": None,
        }
        for sel in selectors:
            el = await page.query_selector(sel)
            if el:
                try:
                    text = (await el.inner_text()).strip()[:40]
                    selectors[sel] = text
                except Exception:
                    selectors[sel] = "(error)"

        # 抓 PDP 上的商品名稱
        name = ""
        for sel in ["h1.prod-buy-header__title", "h2.prod-buy-header__title", "h1", "[class*='prod-name']"]:
            el = await page.query_selector(sel)
            if el:
                try:
                    name = (await el.inner_text()).strip()[:50]
                    break
                except Exception:
                    pass

        print(f"\n──── {url[:80]}...")
        print(f"  status : {status}")
        print(f"  title  : {title}")
        print(f"  name   : {name}")
        for sel, text in selectors.items():
            print(f"  {sel:<38} : {text}")
    except Exception as e:
        print(f"  ERROR: {e}")
    finally:
        await page.close()


async def main():
    print(f"診斷 {len(TEST_URLS)} 個 URL 的詳細頁價格來源...")
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
        warm = await context.new_page()
        if HAS_STEALTH:
            await stealth_async(warm)
        try:
            await warm.goto("https://www.tw.coupang.com/", wait_until="domcontentloaded", timeout=30000)
            await warm.wait_for_timeout(3000)
        except Exception:
            pass
        await warm.close()

        for url in TEST_URLS:
            await inspect_detail(context, url)

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
