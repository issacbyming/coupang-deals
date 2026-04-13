"""產生 Coupang 5折以下特賣靜態頁面，供 GitHub Pages 展示。"""
import sqlite3, datetime, json, re
from pathlib import Path

DB = Path(__file__).parent / "data" / "deals.db"
OUT = Path(__file__).parent / "index.html"
SEEN_FILE = Path(__file__).parent / "seen_urls.json"

# 分類關鍵字（依優先順序匹配，命中第一個就停）
# ⚠️ 順序非常重要：「具體詞在前、模糊詞在後」，食品飲料放最後（避免單字誤抓）
# 新增分類時請注意插入位置，否則可能造成誤判
CATEGORIES = [
    ("嬰幼兒", r"嬰兒|幼兒|寶寶|奶瓶|尿布|奶嘴|安撫奶|嬰幼|兒童|童餐|學步|幼童"),
    ("寵物", r"寵物|貓砂|狗糧|貓糧|貓罐|狗罐|犬用|貓用|飼料"),
    ("3C家電", r"MacBook|iPad|iPhone|手機|耳機|藍牙|喇叭|充電|滑鼠|鍵盤|螢幕|電視|平板|筆電|相機|路由器|延長線|USB|HDMI|風扇|電扇|吸塵器|除濕|空氣清淨|加濕|麥克風|廚餘處理機|印表機|藍光眼鏡|眼鏡框"),
    ("玩具圖書", r"LEGO|樂高|積木|玩具|公仔|模型|拼圖|桌遊|繪本|童書|文具|筆記本|畫筆|蠟筆|彩色筆|色鉛筆|音效書|有聲書|搖搖書|翻翻書|Pororo|波樂樂|小企鵝"),
    ("運動戶外", r"運動|健身|瑜珈|跑步|登山|露營|帳篷|睡袋|啞鈴|跳繩|籃球|足球|羽球|網球|游泳|泳衣|泳褲|護具|按摩|拉伸|滾筒|滑板|腳踏車|單車|彈力帶|沙灘球|蛇板|泳鏡|泳帽|高爾夫"),
    ("美妝保養", r"面膜|保養|化妝|口紅|彩妝|精華|乳液|洗面|潔顏|防曬|美容|香水|眼影|粉底|美白|身體乳|護髮|染髮|洗髮|護膚|爽膚|精油|去角質|蜜粉|粉餅|眉筆|護手霜|面霜|BB霜|腮紅|睫毛|卸妝|安瓶|乳霜|保濕"),
    ("個人清潔", r"洗衣|洗碗|清潔|衛生紙|抽取式|衛生|尿布|生理|衛生棉|刮鬍|牙刷|牙膏|牙線|肥皂|沐浴乳|沐浴|洗手|抗菌|消毒|柔軟精|芳香|除臭"),
    ("廚房用品", r"鍋|平底鍋|湯鍋|炒鍋|刀具|砧板|餐具|碗盤|筷|餐墊|烤盤|保鮮盒|保溫瓶|料理|烘焙|咖啡機|電鍋|微波|烤箱|濾網|瀝水|鍋鏟|刀叉"),
    ("服飾配件", r"上衣|T恤|襯衫|外套|褲|裙|洋裝|內衣|內褲|襪|帽|圍巾|手套|包包|皮帶|錢包|手錶|首飾|戒指|項鍊|耳環|鞋|眼鏡|髮夾|抓夾|髮圈|行李箱|後背包|腰包"),
    ("室內家居", r"枕|被|床|毯|窗簾|地毯|沙發|椅|桌|燈|收納|衣架|掛|架|櫃|地墊|門簾|裝飾|盆栽"),
    ("生活用品", r"垃圾袋|夾鏈袋|塑膠袋|雨衣|雨傘|長柄傘|自動傘|塑膠傘|手電筒|工具|膠帶|繩|刷|擦|拭|鈕扣|密封條|除蟎|防蟎"),
    ("食品飲料", r"咖啡|紅茶|綠茶|烏龍茶|奶茶|可樂|沙士|果汁|汽水|保久乳|牛乳|鮮乳|優酪|"
                r"啤酒|紅酒|白酒|泡麵|拉麵|科學麵|烏龍麵|杯麵|餅乾|巧克力|蛋捲|洋芋片|"
                r"玉米|海苔|起司|優格|豆漿|豆腐|米果|米粉|麥片|燕麥|橄欖油|麻油|醬油|"
                r"食鹽|奶粉|零食|沖泡|飲料|香腸|火腿|水餃|乾糧|薯片|堅果|蜂蜜|果凍|"
                r"果條|牛肉|純水|芭樂|草莓|葡萄|蘋果|濃湯|鮪魚|蛤蜊|豆乾|茶包|奶油|"
                r"花生|蒸蛋|即溶|沖調|機能飲|牛奶"),
]

CATEGORY_NAMES = [c[0] for c in CATEGORIES] + ["其他"]


def classify(title: str) -> str:
    """依序匹配 CATEGORIES 的 regex，回傳第一個命中的分類名稱。"""
    for name, pattern in CATEGORIES:
        if re.search(pattern, title):
            return name
    return "其他"


def get_deals(date):
    if not DB.exists():
        return []
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM deals WHERE date=? AND discount_ratio<=0.5 ORDER BY discount_ratio ASC",
        (date,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def load_seen() -> dict:
    """載入已見過的 URL 紀錄 {url_key: last_seen_date}。"""
    if SEEN_FILE.exists():
        try:
            return json.loads(SEEN_FILE.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_seen(seen: dict, current_urls: list[str], today: str):
    """更新已見過的 URL，清除 7 天前的舊紀錄。"""
    cutoff = (datetime.date.fromisoformat(today) - datetime.timedelta(days=7)).isoformat()
    # 更新當前商品
    for url in current_urls:
        seen[url] = today
    # 清除過期
    seen = {k: v for k, v in seen.items() if v >= cutoff}
    SEEN_FILE.write_text(json.dumps(seen, ensure_ascii=False), encoding="utf-8")


def detect_new(deals: list[dict], seen: dict, today: str) -> set:
    """回傳今天新出現的商品 URL（之前沒見過的）。"""
    yesterday = (datetime.date.fromisoformat(today) - datetime.timedelta(days=1)).isoformat()
    new_urls = set()
    for d in deals:
        url_key = d["url"].split("?")[0]
        last_seen = seen.get(url_key)
        # 新品 = 從沒見過，或上次出現在昨天之前（消失後回歸）
        if last_seen is None or last_seen < yesterday:
            new_urls.add(d["url"])
    return new_urls


def card(d, is_new=False):
    img = d["image_url"] or ""
    if img.startswith("//"):
        img = "https:" + img
    fold = round(d["discount_ratio"] * 10, 1)
    orig = (
        f'<s style="color:#bbb;font-size:11px">NT${int(d["original_price"]):,}</s>'
        if d["original_price"]
        else ""
    )
    saving_amt = round(d["original_price"] - d["sale_price"]) if d["original_price"] and d["sale_price"] else 0
    saving = (
        f'<span style="font-size:11px;color:#c2410c">省${saving_amt}</span>'
        if saving_amt > 0
        else ""
    )
    img_tag = (
        f'<img src="{img}" style="width:100%;height:100%;object-fit:contain;padding:8px" loading="lazy">'
        if img
        else "🛒"
    )
    new_badge = '<span style="position:absolute;bottom:7px;left:7px;background:#16a34a;color:#fff;font-size:10px;font-weight:700;padding:2px 8px;border-radius:99px">NEW</span>' if is_new else ""
    cat = classify(d["title"])
    return f"""<a class="deal-card" href="{d['url']}" target="_blank"
  data-category="{cat}"
  data-ratio="{d['discount_ratio']}"
  data-sale="{d['sale_price'] or 0}"
  data-orig="{d['original_price'] or 0}"
  data-new="{'true' if is_new else 'false'}"
  style="text-decoration:none;color:inherit;background:#fff;border-radius:12px;overflow:hidden;border:1px solid #eee;display:flex;flex-direction:column;box-shadow:0 1px 4px rgba(0,0,0,.06)">
  <div style="position:relative;aspect-ratio:1;background:#f9f9f9;overflow:hidden">{img_tag}
    <span style="position:absolute;top:7px;left:7px;background:#ef4444;color:#fff;font-size:11px;font-weight:700;padding:3px 8px;border-radius:99px">{fold}折</span>
    <span style="position:absolute;top:7px;right:7px;background:rgba(0,0,0,.55);color:#fff;font-size:10px;padding:2px 7px;border-radius:99px">{cat}</span>
    {new_badge}
  </div>
  <div style="padding:10px;display:flex;flex-direction:column;gap:5px;flex:1">
    <p style="font-size:13px;line-height:1.4;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden">{d['title']}</p>
    <div style="margin-top:auto;display:flex;align-items:flex-end;justify-content:space-between">
      <div><span style="font-size:16px;font-weight:700;color:#dc2626">NT${int(d['sale_price']):,}</span><br>{orig}</div>
      {saving}
    </div>
  </div>
</a>"""


today = datetime.date.today().isoformat()
deals = get_deals(today)

# 新品偵測
seen = load_seen()
new_urls = detect_new(deals, seen, today) if seen else set()  # 首次執行無舊資料，不標新品
new_count = len(new_urls)
cards_html = "".join(card(d, is_new=(d["url"] in new_urls)) for d in deals)
# 儲存本次 URL 供下次比對
save_seen(seen, [d["url"].split("?")[0] for d in deals], today)

min_fold = f"最低 {min(d['discount_ratio'] for d in deals)*10:.1f} 折起" if deals else ""

# 分類統計
cat_counts = {name: 0 for name in CATEGORY_NAMES}
for d in deals:
    cat_counts[classify(d["title"])] += 1

# 分類按鈕（顯示有商品的）
cat_buttons = [f'<button class="cat-btn active" data-cat="all">全部 <span class="n">{len(deals)}</span></button>']
if new_count > 0:
    cat_buttons.append(f'<button class="cat-btn cat-new" data-cat="new">今日新品 <span class="n">{new_count}</span></button>')
for name in CATEGORY_NAMES:
    if cat_counts[name] > 0:
        cat_buttons.append(f'<button class="cat-btn" data-cat="{name}">{name} <span class="n">{cat_counts[name]}</span></button>')
cat_buttons_html = "".join(cat_buttons)

empty = (
    """<div id="empty" style="text-align:center;padding:80px;color:#aaa;display:none">
  <p style="font-size:40px">🔍</p><p style="font-size:16px;margin:10px 0">這個分類下沒有商品</p>
</div>"""
    if deals
    else """<div style="text-align:center;padding:80px;color:#aaa">
  <p style="font-size:40px">🔍</p><p style="font-size:16px;margin:10px 0">今天還沒有資料，請稍後再來</p>
</div>"""
)

grid_html = (
    f'<div id="grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px">{cards_html}</div>{empty}'
    if deals
    else empty
)

html = f"""<!DOCTYPE html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Coupang 今日 5折以下特賣 {today}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#f5f5f5;color:#222}}
.controls{{background:#fff;border-bottom:1px solid #eee;padding:10px 20px;display:flex;flex-wrap:wrap;gap:8px;align-items:center;position:sticky;top:0;z-index:5}}
.controls .row1{{width:100%;display:flex;align-items:center;gap:12px}}
.controls h1{{font-size:17px;font-weight:700}}
.controls .sub{{font-size:12px;color:#999}}
.controls .count-badge{{background:#fee2e2;color:#b91c1c;font-size:12px;font-weight:600;padding:2px 10px;border-radius:99px;margin-left:auto}}
.controls .min-fold{{font-size:12px;color:#aaa}}
.controls select{{font-size:13px;border:1px solid #ddd;border-radius:8px;padding:6px 10px;background:#fff;cursor:pointer}}
.controls input[type=search]{{font-size:13px;border:1px solid #ddd;border-radius:8px;padding:6px 12px;background:#fff;flex:1;max-width:220px;outline:none;transition:border-color .15s}}
.controls input[type=search]:focus{{border-color:#222}}
.cats{{width:100%;display:flex;flex-wrap:wrap;gap:6px;padding-top:4px}}
.cat-btn{{font-size:12px;padding:5px 11px;border-radius:99px;border:1px solid #ddd;background:#fff;cursor:pointer;color:#555;transition:all .15s}}
.cat-btn:hover{{border-color:#999}}
.cat-btn.active{{background:#222;color:#fff;border-color:#222}}
.cat-btn .n{{opacity:.6;font-size:11px;margin-left:3px}}
.cat-new{{border-color:#16a34a;color:#16a34a}}
.cat-new:hover{{border-color:#15803d}}
.cat-new.active{{background:#16a34a;color:#fff;border-color:#16a34a}}
main{{max-width:1100px;margin:0 auto;padding:16px}}
.deal-card{{transition:transform .15s,box-shadow .15s}}
.deal-card:hover{{transform:translateY(-2px);box-shadow:0 4px 16px rgba(0,0,0,.1)!important}}
footer{{text-align:center;padding:20px;font-size:12px;color:#ccc}}
</style>
</head><body>
<div class="controls">
  <div class="row1">
    <div><h1>Coupang 今日特賣</h1><p class="sub">5折以下優惠商品 · {today}</p></div>
    <span class="count-badge" id="visible-count">{len(deals)} 件優惠</span>
    <span class="min-fold">{min_fold}</span>
    <input type="search" id="search" placeholder="🔍 搜尋商品名稱...">
    <select id="sort">
      <option value="ratio-asc">折扣率 低→高</option>
      <option value="price-asc">售價 低→高</option>
      <option value="price-desc">售價 高→低</option>
    </select>
  </div>
  <div class="cats">{cat_buttons_html}</div>
</div>
<main>
  {grid_html}
</main>
<footer>資料來源：Coupang 台灣 · 最後更新：{datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}</footer>
<script>
(function() {{
  const grid = document.getElementById('grid');
  if (!grid) return;
  const cards = Array.from(grid.querySelectorAll('.deal-card'));
  const empty = document.getElementById('empty');
  const countBadge = document.getElementById('visible-count');
  const sortSel = document.getElementById('sort');
  const searchInput = document.getElementById('search');
  const catBtns = Array.from(document.querySelectorAll('.cat-btn'));

  cards.forEach(c => {{ c._searchText = c.textContent.toLowerCase(); }});

  let curCat = 'all';
  let curSort = 'ratio-asc';
  let curSearch = '';

  function apply() {{
    const q = curSearch.toLowerCase();
    let visible = cards.filter(c => {{
      if (curCat === 'new') {{ if (c.dataset.new !== 'true') return false; }}
      else if (curCat !== 'all' && c.dataset.category !== curCat) return false;
      if (q && !c._searchText.includes(q)) return false;
      return true;
    }});

    const sorters = {{
      'ratio-asc': (a, b) => parseFloat(a.dataset.ratio) - parseFloat(b.dataset.ratio),
      'price-asc': (a, b) => parseFloat(a.dataset.sale) - parseFloat(b.dataset.sale),
      'price-desc': (a, b) => parseFloat(b.dataset.sale) - parseFloat(a.dataset.sale),
    }};
    visible.sort(sorters[curSort]);

    cards.forEach(c => c.style.display = 'none');
    visible.forEach(c => {{ c.style.display = ''; grid.appendChild(c); }});

    countBadge.textContent = visible.length + ' 件優惠';
    if (empty) {{
      empty.style.display = visible.length === 0 ? '' : 'none';
      if (visible.length === 0 && q) {{
        const p = empty.querySelector('p:nth-child(2)');
        if (p) p.textContent = '找不到符合「' + curSearch + '」的商品';
      }}
    }}
  }}

  catBtns.forEach(btn => btn.addEventListener('click', () => {{
    catBtns.forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    curCat = btn.dataset.cat;
    apply();
  }}));

  sortSel.addEventListener('change', () => {{ curSort = sortSel.value; apply(); }});

  if (searchInput) {{
    searchInput.addEventListener('input', () => {{
      curSearch = searchInput.value.trim();
      apply();
    }});
  }}
}})();
</script>
</body></html>"""

OUT.write_text(html, encoding="utf-8")
print(f"✓ 已產生：{OUT}")
print(f"  共 {len(deals)} 筆 5折以下商品")
print(f"  分類分布：{', '.join(f'{k}({v})' for k, v in cat_counts.items() if v > 0)}")

# 唯一歸屬驗證
_total = sum(cat_counts.values())
assert _total == len(deals), f"分類總和 {_total} ≠ 商品數 {len(deals)}，唯一歸屬失效"
_other_pct = cat_counts["其他"] / len(deals) * 100 if deals else 0
print(f"✓ 唯一歸屬驗證通過：{_total} 件 = 各分類總和；「其他」佔比 {_other_pct:.1f}%")
