"""
Coupang 台灣（tw.coupang.com）爬蟲
使用 Playwright 渲染 JavaScript，平行抓取多個 campaign 頁的 5折以下商品。
"""

import asyncio
import datetime
import re
from playwright.async_api import async_playwright, Page, BrowserContext, TimeoutError as PlaywrightTimeout
try:
    from playwright_stealth import stealth_async
    HAS_STEALTH = True
except ImportError:
    HAS_STEALTH = False

from utils import parse_price, calc_ratio

# 已驗證有效的 campaign IDs（從 probe_campaigns.py 掃描得出）
# 每個 campaign 對應一個促銷活動，商品有重疊但會涵蓋更廣
CAMPAIGN_IDS = [
    52, 54, 59, 60, 72, 74, 75, 76, 77, 82, 83, 84, 87,
    103, 104, 105, 107, 124, 125, 126, 127, 129, 131, 132,
    136, 137, 138, 139, 140, 141, 142, 143, 144, 145, 146,
    147, 148, 149, 150, 151, 152, 155, 156, 157, 158,
    160, 161, 162, 163, 164, 165, 166, 167, 168, 170,
    172, 173, 182, 183, 184, 185, 186, 187, 188, 189,
    190, 191, 192, 193, 194, 195, 196, 197, 198, 199,
]

CAMPAIGN_URLS = [f"https://www.tw.coupang.com/np/campaigns/{cid}" for cid in CAMPAIGN_IDS]

# 商品卡片 selector
PRODUCT_SELECTOR = "li.baby-product"

# 欄位 selector（campaign 列表頁）
TITLE_SEL = "div.name"
SALE_PRICE_SEL = "strong.price-value"
ORIG_PRICE_SEL = "del"
BADGE_SEL = "span[class*='discount-rate'], span[class*='rate'], span[class*='percent']"
DISCOUNT_LABEL_SEL = "span.instant-discount-text"

# 欄位 selector（商品詳細頁）
DETAIL_SALE_SEL = "div.sales-price-amount"
DETAIL_SALE_FALLBACK_SEL = ".sales-price .price-amount"

BASE_URL = "https://www.tw.coupang.com"

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
HEADERS = {
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "sec-ch-ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


class CoupangScraper:
    def __init__(self, headless: bool = True, max_items_per_page: int = 100, parallelism: int = 5):
        self.headless = headless
        self.max_items_per_page = max_items_per_page
        self.parallelism = parallelism

    async def fetch_deals(self) -> list[dict]:
        today = datetime.date.today().isoformat()
        now = datetime.datetime.utcnow().isoformat()

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=self.headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = await browser.new_context(
                user_agent=UA,
                viewport={"width": 1280, "height": 900},
                locale="zh-TW",
                extra_http_headers=HEADERS,
            )

            # 暖身：先訪問 campaigns/82 建立 session
            warm = await context.new_page()
            if HAS_STEALTH:
                await stealth_async(warm)
            try:
                await warm.goto("https://www.tw.coupang.com/np/campaigns/82", wait_until="domcontentloaded", timeout=30000)
                await warm.wait_for_timeout(2000)
            except Exception as e:
                print(f"[coupang] 暖身失敗：{e}")
            await warm.close()

            # 平行抓取每個 campaign
            all_results = []
            sem = asyncio.Semaphore(self.parallelism)

            async def scrape_one(url: str):
                async with sem:
                    page = await context.new_page()
                    if HAS_STEALTH:
                        await stealth_async(page)
                    try:
                        items = await self._scrape_page(page, url, today, now)
                        print(f"[coupang] {url.split('/')[-1]}: {len(items)} 筆")
                        all_results.extend(items)
                    except Exception as e:
                        print(f"[coupang] 失敗 {url}: {e}")
                    finally:
                        await page.close()

            await asyncio.gather(*(scrape_one(u) for u in CAMPAIGN_URLS))

            # 去重（以 url 為唯一鍵）
            seen = {}
            for item in all_results:
                key = item["url"].split("?")[0]  # 去掉 query string
                if key not in seen:
                    seen[key] = item
            deduped = list(seen.values())

            # 初步篩 5折以下（用 campaign 卡片價格）
            filtered = [d for d in deduped if d["discount_ratio"] is not None and d["discount_ratio"] <= 0.5]
            print(f"[coupang] 抓取總計 {len(all_results)} 筆，去重後 {len(deduped)} 筆，初步 5折以下 {len(filtered)} 筆")

            # ── 第二階段：對首購折扣商品，訪問詳細頁取酷澎售價 ──
            needs_detail = [d for d in filtered if d.get("discount_type") == "first_purchase"]
            no_detail = [d for d in filtered if d.get("discount_type") != "first_purchase"]

            if needs_detail:
                print(f"[coupang] 第二階段：{len(needs_detail)} 件首購商品需訪問詳細頁取酷澎售價")
                detail_sem = asyncio.Semaphore(10)
                detail_ok = 0
                detail_fail = 0

                async def fetch_detail(item):
                    nonlocal detail_ok, detail_fail
                    async with detail_sem:
                        page = await context.new_page()
                        if HAS_STEALTH:
                            await stealth_async(page)
                        try:
                            real_price = await self._scrape_detail_price(page, item["url"])
                            if real_price and item["original_price"] and item["original_price"] > real_price:
                                item["sale_price"] = real_price
                                item["discount_ratio"] = calc_ratio(item["original_price"], real_price)
                                detail_ok += 1
                            else:
                                detail_fail += 1
                        except Exception:
                            detail_fail += 1
                        finally:
                            await page.close()

                try:
                    await asyncio.wait_for(
                        asyncio.gather(*(fetch_detail(d) for d in needs_detail)),
                        timeout=300,  # 5 分鐘上限，避免拖垮整個流程
                    )
                except asyncio.TimeoutError:
                    print(f"[coupang] ⚠️ 詳細頁階段超時（5 分鐘），繼續使用已取得的結果")
                print(f"[coupang] 詳細頁結果：成功 {detail_ok}，失敗 {detail_fail}")

            # 最終合併 + 重新過濾（用酷澎售價）
            all_items = no_detail + needs_detail
            filtered = [d for d in all_items if d.get("discount_ratio") is not None and d["discount_ratio"] <= 0.5]
            print(f"[coupang] 最終篩選：{len(filtered)} 件 ≤5折商品（酷澎售價）")

            await browser.close()

        return filtered

    async def _scrape_page(self, page: Page, url: str, today: str, now: str) -> list[dict]:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2500)
        for _ in range(3):
            await page.evaluate("window.scrollBy(0, window.innerHeight*2)")
            await page.wait_for_timeout(500)

        cards = await page.query_selector_all(PRODUCT_SELECTOR)
        if not cards:
            return []

        results = []
        for card in cards[:self.max_items_per_page]:
            try:
                item = await self._parse_card(card, today, now)
                if item:
                    results.append(item)
            except Exception:
                continue
        return results

    async def _parse_card(self, card, today: str, now: str) -> dict | None:
        # URL
        link_el = await card.query_selector("a")
        if not link_el:
            return None
        href = await link_el.get_attribute("href")
        if not href:
            return None
        url = href if href.startswith("http") else BASE_URL + href

        # 標題
        title_el = await card.query_selector(TITLE_SEL)
        if not title_el:
            return None
        title = (await title_el.inner_text()).strip()
        if not title:
            return None

        # 圖片
        image_url = None
        img_el = await card.query_selector("img")
        if img_el:
            image_url = await img_el.get_attribute("src") or await img_el.get_attribute("data-src")

        # 售價
        sale_price = None
        sale_el = await card.query_selector(SALE_PRICE_SEL)
        if sale_el:
            sale_price = parse_price((await sale_el.inner_text()).strip())

        # 原價
        original_price = None
        orig_el = await card.query_selector(ORIG_PRICE_SEL)
        if orig_el:
            original_price = parse_price((await orig_el.inner_text()).strip())

        # 折扣率：優先以價格計算
        discount_ratio = None
        if sale_price and original_price and original_price > sale_price:
            discount_ratio = calc_ratio(original_price, sale_price)

        # fallback：徽章文字
        if discount_ratio is None:
            badge_el = await card.query_selector(BADGE_SEL)
            if badge_el:
                badge_text = (await badge_el.inner_text()).strip()
                discount_ratio = _parse_discount_ratio(badge_text)

        if discount_ratio is None:
            return None

        # 折扣類型：首購 / WOW / 一般
        discount_type = "regular"
        label_el = await card.query_selector(DISCOUNT_LABEL_SEL)
        if label_el:
            label_text = (await label_el.inner_text()).strip()
            if "首購" in label_text:
                discount_type = "first_purchase"
            elif "WOW" in label_text:
                discount_type = "wow"

        return {
            "title": title,
            "url": url,
            "image_url": image_url,
            "original_price": original_price,
            "sale_price": sale_price,
            "discount_ratio": discount_ratio,
            "discount_type": discount_type,
            "date": today,
            "fetched_at": now,
        }


    async def _scrape_detail_price(self, page: Page, url: str) -> float | None:
        """訪問商品詳細頁，擷取酷澎售價（sales-price-amount）。"""
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(2000)

            # 優先找 div.sales-price-amount
            el = await page.query_selector(DETAIL_SALE_SEL)
            if el:
                text = (await el.inner_text()).strip()
                price = parse_price(text)
                if price:
                    return price

            # fallback: .sales-price .price-amount
            el = await page.query_selector(DETAIL_SALE_FALLBACK_SEL)
            if el:
                text = (await el.inner_text()).strip()
                price = parse_price(text)
                if price:
                    return price

            return None
        except Exception:
            return None


def _parse_discount_ratio(text: str) -> float | None:
    """解析折扣率文字。"""
    if not text:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)折", text)
    if m:
        return round(float(m.group(1)) / 10.0, 4)
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    if m:
        pct = float(m.group(1))
        # Coupang 徽章「X%」實際是「省 X%」 → 剩餘 (100-X)%
        return round((100.0 - pct) / 100.0, 4)
    return None
