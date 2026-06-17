# main.py - FastAPI server เธชเธณเธซเธฃเธฑเธ BCSFE order system
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')


from fastapi import FastAPI, HTTPException, UploadFile, File, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
import os
import httpx
import asyncio
import shutil
from pathlib import Path
from datetime import datetime
_BASE_DIR = Path(__file__).parent
import re as _re

# ── Cat unlock price table ─────────────────────────────────────────
_CAT_UNLOCK_PRICE = {"N": 5, "EX": 15, "RR": 20, "SR": 25, "UR": 39, "LR": 79}

def _load_cat_tiers() -> dict:
    try:
        text = (_BASE_DIR / "assets" / "characters_data.js").read_text(encoding="utf-8")
        m = _re.search(r'var catsData\s*=\s*\[(.*?)\];', text, _re.DOTALL)
        if not m:
            return {}
        return {int(i): t for i, t in _re.findall(r'\[(\d+),"(\w+)","[^"]*"\]', m.group(1))}
    except Exception:
        return {}

_CAT_TIER = _load_cat_tiers()

def _calc_cat_unlock_total(cat_ids: list) -> int:
    return sum(_CAT_UNLOCK_PRICE.get(_CAT_TIER.get(cid, ""), 20) for cid in (cat_ids or []))

# ── Stage price table (server-side, matches stages.html) ──────────
_STAGE_STORY_PRICES    = {"clear": 30, "treasure": 40, "zombie": 40}
_STAGE_LEGEND_PRICES   = {
    "sol": {1: 30, 2: 50, 3: 70, 4: 100},
    "ul":  {1: 30, 2: 50, 3: 70, 4: 100},
    "zl":  {1: 40, 2: 80},
}
_STAGE_AKU_UNLOCK   = 40
_STAGE_AKU_CHAPTERS = 100

def _story_group_count(chapters: list) -> int:
    groups = set()
    for ch in chapters:
        if 1 <= ch <= 3:   groups.add("eoc")
        elif 4 <= ch <= 6: groups.add("itf")
        elif 7 <= ch <= 9: groups.add("cotc")
    return len(groups)

def _calc_stages_price(cfg) -> int:
    total  = _story_group_count(cfg.story_chapters)    * _STAGE_STORY_PRICES["clear"]
    total += _story_group_count(cfg.treasure_chapters) * _STAGE_STORY_PRICES["treasure"]
    total += _story_group_count(cfg.zombie_chapters)   * _STAGE_STORY_PRICES["zombie"]
    for lt in cfg.legend_types:
        crown = cfg.legend_crowns.get(lt, cfg.max_crown)
        total += _STAGE_LEGEND_PRICES.get(lt, {}).get(crown, 0)
    if cfg.aku_unlock:   total += _STAGE_AKU_UNLOCK
    if cfg.aku_chapters: total += _STAGE_AKU_CHAPTERS
    return total

from models import OrderRequest, OrderResponse, ItemSummary, ItemRequest, TestBCSFERequest, UnlockCharactersRequest, RetryRequest, UnlockPaymentRequest, AllCatsRequest, VoucherRedeemRequest, DupeSaveRequest, CheckIDRequest, LoyaltyRedeemRequest, CodeShopBuyRequest, AdminProductRequest, AdminToggleRequest, AdminEditProductRequest, AdminStockRequest, ClearStoryChaptersRequest, ClearStoryAllRequest, ResetStoryChaptersRequest, ResetStoryAllRequest, SetTreasureChaptersRequest, SetTreasureAllRequest, ClearOutbreakChaptersRequest, ClearOutbreakAllRequest, AkuRequest, ClearLegendsRequest, StagesPaymentRequest
from runner import BCSFERunner
from config import ITEM_MAP, AMOUNT_OPTIONS, COUNTRIES
from payment import (
    ITEM_PRICE,
    TRUEMONEY_ID,
    create_order as create_payment_order,
    create_unlock_order,
    create_all_package_order,
    get_order,
    is_order_expired,
    update_order_status,
    verify_slip,
    redeem_truemoney_voucher,
    mark_slip_used,
    get_user_loyalty,
    update_user_loyalty_spent,
    increment_loyalty_redeemed,
    add_loyalty_redeemed_cycles,
    save_loyalty_redemption,
    get_loyalty_redemptions,
    verify_loyalty_session,
    verify_admin_session,
    get_code_products,
    get_all_code_products,
    get_code_product,
    get_available_stock,
    reserve_stock,
    mark_stock_sold,
    release_stock,
    get_stock_by_order,
    add_code_product,
    update_code_product,
    toggle_code_product,
    delete_code_product,
    add_code_stock,
    delete_code_stock,
    get_product_stock,
    create_stages_order,
    create_code_shop_order,
    get_user_code_purchases,
)

ALL_PACKAGE_MAP = {
    "upgrade_all":   {"label": "Upgrade Max All",  "price": 400, "runner": "run_upgrade_all_characters"},
    "unlock_all":    {"label": "Unlock All",        "price": 400, "runner": "run_unlock_all"},
    "trueform_all":  {"label": "True Form All",     "price": 200, "runner": "run_true_form_all"},
    "ultraform_all": {"label": "Ultra Form All",    "price": 200, "runner": "run_ultra_form_all"},
    "talents_all":   {"label": "Max Talents All",   "price": 300, "runner": "run_talents_max_all"},
    "crazed_all":    {"label": "Crazed All Cat",    "price": 70,  "runner": None},
    "manic_all":     {"label": "Manic All Cat",     "price": 125, "runner": None},
}

CRAZED_CAT_IDS = list(range(91, 100))  # 91-99

# Import เน€เธเธดเนเธกเน€เธ•เธดเธกเธชเธณเธซเธฃเธฑเธ /api/orders/list
from payment import ORDER_DB

# โ”€โ”€ Cat image proxy โ€” disk cache โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€
CAT_CACHE_DIR = Path("pictures/cats")
CAT_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# semaphore เธเนเธญเธเธเธฑเธ fetch เธเธฃเนเธญเธกเธเธฑเธเธกเธฒเธเน€เธเธดเธ
_fetch_sem = asyncio.Semaphore(8)

HEADERS = {"User-Agent": "BattleCatsShop/1.0 (image-proxy)"}

# URL patterns โ€” Miraheze เน€เธ—เนเธฒเธเธฑเนเธ (Fandom block hotlink 403)
# pattern 1: Gatyachara_{id:03d}_f.png  โ’ cats เธ—เธฑเนเธงเนเธ 836+ เธ•เธฑเธง
# pattern 2: Uni{id}_s00.png            โ’ Ancient Egg series เนเธฅเธฐ special cats
def _cat_img_urls(cat_id: int) -> list[str]:
    p3 = f"{cat_id:03d}"
    return [
        f"https://battlecats.miraheze.org/wiki/Special:FilePath/Gatyachara_{p3}_f.png",
        f"https://battlecats.miraheze.org/wiki/Special:FilePath/Uni{cat_id}_s00.png",
    ]


async def _fetch_cat_image(cat_id: int) -> bytes | None:
    cache_path = CAT_CACHE_DIR / f"{cat_id}.png"
    if cache_path.exists():
        return cache_path.read_bytes()

    async with _fetch_sem:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            for url in _cat_img_urls(cat_id):
                try:
                    r = await client.get(url, headers=HEADERS)
                    ct = r.headers.get("content-type", "")
                    if r.status_code == 200 and ct.startswith("image"):
                        cache_path.write_bytes(r.content)
                        return r.content
                except Exception:
                    continue
    return None


# เนเธเธฅเน€เธ”เธญเธฃเนเน€เธเนเธ backup save files
BACKUP_DIR = Path("saves_backup")
BACKUP_DIR.mkdir(exist_ok=True)

# path เธ—เธตเน bcsfe เธเธฑเธเธ—เธถเธ SAVE_DATA เนเธงเน
BCSFE_SAVE_PATH = Path.home() / "Documents" / "bcsfe" / "saves" / "SAVE_DATA"

def backup_save(transfer_code: str) -> str | None:
    """
    copy SAVE_DATA เธเธฒเธ bcsfe เนเธเน€เธเนเธเนเธ saves_backup/
    เธ•เธฑเนเธเธเธทเนเธญเนเธเธฅเนเธ•เธฒเธก timestamp + transfer code
    เธเธทเธ path เธ—เธตเนเธเธฑเธเธ—เธถเธ เธซเธฃเธทเธญ None เธ–เนเธฒเนเธกเนเธเธเนเธเธฅเน
    """
    try:
        if not BCSFE_SAVE_PATH.exists():
            print(f"[BACKUP] โ ๏ธ เนเธกเนเธเธ SAVE_DATA เธ—เธตเน {BCSFE_SAVE_PATH}")
            return None

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"SAVE_{timestamp}_{transfer_code[:8]}"
        dest = BACKUP_DIR / filename

        shutil.copy2(BCSFE_SAVE_PATH, dest)
        print(f"[BACKUP] โ… เธเธฑเธเธ—เธถเธ save โ’ {dest}")
        return str(dest)
    except Exception as e:
        print(f"[BACKUP] โ backup เธฅเนเธกเน€เธซเธฅเธง: {e}")
        return None

# เธชเธฃเนเธฒเธ FastAPI app
app = FastAPI(title="BCSFE Order System")

# BCSFE operations เธ•เนเธญเธเธฃเธฑเธเธ—เธตเธฅเธฐ 1 เน€เธ—เนเธฒเธเธฑเนเธ (SAVE_DATA เนเธเนเธฃเนเธงเธกเธเธฑเธ)
import asyncio


_bcsfe_lock = asyncio.Lock()


async def run_bcsfe(fn, *args, **kwargs):
    """เธฃเธฑเธ BCSFE operation เธ เธฒเธขเนเธ•เน lock โ€” เธเนเธญเธเธเธฑเธ concurrent SAVE_DATA conflict"""
    async with _bcsfe_lock:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: fn(*args, **kwargs))

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Cache-control middleware — browser cache static assets 1 day
from starlette.middleware.base import BaseHTTPMiddleware
class StaticCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        p = request.url.path
        if p.startswith("/assets/") or p.startswith("/pictures/"):
            response.headers["Cache-Control"] = "public, max-age=86400"
        return response
app.add_middleware(StaticCacheMiddleware)

RECAPTCHA_SECRET = "6LegGB8tAAAAAMv-xcbRjLIpImI_K9Kreu8c6icI"

# ============= API Routes =============

@app.get("/api/debug-paths")
def debug_paths():
    p = _BASE_DIR / "pictures" / "codeshop"
    files = sorted([f.name for f in p.iterdir()])[:5] if p.exists() else []
    return {
        "base_dir": str(_BASE_DIR),
        "pictures_exists": (_BASE_DIR / "pictures").exists(),
        "code_shop_exists": p.exists(),
        "sample_files": files,
    }

@app.post("/api/verify-recaptcha")
async def verify_recaptcha(body: dict):
    token = (body or {}).get("token", "")
    if not token:
        return {"success": False}
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://www.google.com/recaptcha/api/siteverify",
            data={"secret": RECAPTCHA_SECRET, "response": token},
        )
    result = r.json()
    ok = bool(result.get("success")) and float(result.get("score", 0)) >= 0.3
    return {"success": ok}

@app.get("/api/items")
def get_items():
    """
    เธชเนเธเธเนเธญเธกเธนเธฅ ITEM_MAP, AMOUNT_OPTIONS, COUNTRIES เนเธฅเธฐเธฃเธฒเธเธฒเธชเธดเธเธเนเธฒ
    """
    return {
        "items": ITEM_MAP,
        "amounts": AMOUNT_OPTIONS,
        "countries": COUNTRIES,
        "prices": ITEM_PRICE,
    }

@app.post("/api/payment/create")
async def payment_create(order: OrderRequest):
    """เธชเธฃเนเธฒเธ order โ€” เธฃเธญเธเธฃเธฑเธ items, cat_ids, เธซเธฃเธทเธญเธ—เธฑเนเธเธชเธญเธเธเธฃเนเธญเธกเธเธฑเธ"""
    has_items  = bool(order.items)
    has_unlock = bool(order.cat_ids)

    if not has_items and not has_unlock:
        raise HTTPException(status_code=400, detail="เธ•เนเธญเธเน€เธฅเธทเธญเธ item เธซเธฃเธทเธญเนเธกเธงเธ—เธตเนเธเธฐเธเธฅเธ”เธฅเนเธญเธเธญเธขเนเธฒเธเธเนเธญเธข 1 เธฃเธฒเธขเธเธฒเธฃ")

    if order.country not in COUNTRIES:
        raise HTTPException(status_code=400, detail=f"Country เนเธกเนเธ–เธนเธเธ•เนเธญเธ: {order.country}")

    for item in order.items:
        if item.key in ALL_PACKAGE_MAP:
            continue  # all-package items bypass ITEM_MAP validation
        if item.key not in ITEM_MAP:
            raise HTTPException(status_code=400, detail=f"เนเธกเนเธฃเธนเนเธเธฑเธ item: {item.key}")
        if item.amount <= 0:
            raise HTTPException(status_code=400, detail=f"เธเธณเธเธงเธ {item.key} เธ•เนเธญเธเธกเธฒเธเธเธงเนเธฒ 0")
        if item.amount > ITEM_MAP[item.key]["max"]:
            raise HTTPException(status_code=400, detail=f"{ITEM_MAP[item.key]['label']} เน€เธเธดเธเธเธณเธเธงเธเธชเธนเธเธชเธธเธ” ({ITEM_MAP[item.key]['max']})")

    # คำนวณราคา all-package items แยก แล้วรวมเข้า total
    pkg_extra = sum(
        ALL_PACKAGE_MAP[item.key]["price"]
        for item in order.items
        if item.key in ALL_PACKAGE_MAP
    )

    items_payload = []
    for item in order.items:
        d = {"key": item.key, "amount": item.amount}
        if item.cat_id is not None:
            d["cat_id"] = item.cat_id
        items_payload.append(d)

    payment_order = create_payment_order(
        transfer_code=order.transfer_code,
        confirmation_code=order.confirmation_code,
        country=order.country,
        items=items_payload,
        cat_ids=order.cat_ids,
        cat_unlock_total=_calc_cat_unlock_total(order.cat_ids) + pkg_extra,
        payment_method=order.payment_method,
        username=order.username or "",
    )

    resp = {
        "order_id":       payment_order["order_id"],
        "amount":         payment_order["amount"],
        "base_amount":    payment_order.get("base_amount", payment_order["amount"]),
        "truemoney_fee":  payment_order.get("truemoney_fee", 0),
        "qr_base64":      payment_order.get("qr_base64"),
        "expires_at":     payment_order["expires_at"],
        "payment_method": order.payment_method,
    }
    if order.payment_method == "truemoney":
        resp["truemoney_id"] = TRUEMONEY_ID
    return resp

@app.post("/api/payment/create-all-package/{package_type}")
async def payment_create_all_package(package_type: str, body: AllCatsRequest):
    """สร้าง order สำหรับแพ็กเกจ All (unlock_all, trueform_all, ฯลฯ) พร้อม QR"""
    if package_type not in ALL_PACKAGE_MAP:
        raise HTTPException(status_code=400, detail=f"ไม่รู้จัก package_type: {package_type}")
    price = ALL_PACKAGE_MAP[package_type]["price"]
    if price is None:
        raise HTTPException(status_code=400, detail="แพ็กเกจนี้ยังไม่เปิดขาย — กรุณาสอบถามเพิ่มเติม")
    if not body.transfer_code.strip() or not body.confirmation_code.strip():
        raise HTTPException(status_code=400, detail="กรุณากรอก Transfer Code และ Confirmation Code")
    if body.country not in COUNTRIES:
        raise HTTPException(status_code=400, detail=f"Country ไม่ถูกต้อง: {body.country}")
    order = create_all_package_order(
        transfer_code=body.transfer_code.strip(),
        confirmation_code=body.confirmation_code.strip(),
        country=body.country,
        package_type=package_type,
        amount=price,
        payment_method=body.payment_method,
    )
    resp = {"order_id": order["order_id"], "amount": order["amount"],
            "base_amount": order.get("base_amount", order["amount"]),
            "truemoney_fee": order.get("truemoney_fee", 0),
            "qr_base64": order.get("qr_base64"), "expires_at": order["expires_at"],
            "payment_method": body.payment_method}
    if body.payment_method == "truemoney":
        resp["truemoney_id"] = TRUEMONEY_ID
    return resp


@app.post("/api/payment/create-unlock")
async def payment_create_unlock(body: UnlockPaymentRequest):
    """เธชเธฃเนเธฒเธ order เธเธฅเธ”เธฅเนเธญเธเนเธกเธง เธเธฃเนเธญเธก QR PromptPay"""
    if not body.cat_ids:
        raise HTTPException(status_code=400, detail="เธ•เนเธญเธเน€เธฅเธทเธญเธเนเธกเธงเธญเธขเนเธฒเธเธเนเธญเธข 1 เธ•เธฑเธง")
    if body.total <= 0:
        raise HTTPException(status_code=400, detail="เธขเธญเธ”เธเธณเธฃเธฐเธ•เนเธญเธเธกเธฒเธเธเธงเนเธฒ 0")

    order = create_unlock_order(
        transfer_code=body.transfer_code,
        confirmation_code=body.confirmation_code,
        country=body.country,
        cat_ids=body.cat_ids,
        amount=body.total,
        payment_method=body.payment_method,
    )
    resp = {
        "order_id":       order["order_id"],
        "amount":         order["amount"],
        "base_amount":    order.get("base_amount", order["amount"]),
        "truemoney_fee":  order.get("truemoney_fee", 0),
        "qr_base64":      order.get("qr_base64"),
        "expires_at":     order["expires_at"],
        "payment_method": body.payment_method,
    }
    if body.payment_method == "truemoney":
        resp["truemoney_id"] = TRUEMONEY_ID
    return resp


PER_CAT_RUNNER = {
    "upgrade_cat":   "run_upgrade_characters",
    "trueform_cat":  "run_true_form_characters",
    "ultraform_cat": "run_ultra_form_characters",
    "talents_cat":   "run_talents_max_characters",
}


def _run_bcsfe_steps(order: dict, tc: str, cc: str) -> dict:
    """Run BCSFE steps in strict order:
    items → unlock (cat/all) → upgrade (cat/all) → trueform (cat/all)
          → ultraform (cat/all) → talents (cat/all)
    """
    from collections import defaultdict

    all_pkg_keys    = set(ALL_PACKAGE_MAP.keys())
    per_cat_keys    = set(PER_CAT_RUNNER.keys())
    all_order_items = order.get("items") or []

    # ── Separate item categories ──
    regular_items = [i for i in all_order_items
                     if i["key"] not in all_pkg_keys and i["key"] not in per_cat_keys]
    per_cat_items = [i for i in all_order_items if i["key"] in per_cat_keys]
    all_pkg_items = [i for i in all_order_items if i["key"] in all_pkg_keys]

    # Group per-cat by service key
    per_cat_groups: dict[str, list[int]] = defaultdict(list)
    for item in per_cat_items:
        if item.get("cat_id") is not None:
            per_cat_groups[item["key"]].append(item["cat_id"])

    # All-package keys in this order (include legacy package_type field)
    all_pkg_set: set[str] = {i["key"] for i in all_pkg_items}
    if order.get("package_type") and order["package_type"] in ALL_PACKAGE_MAP:
        all_pkg_set.add(order["package_type"])

    cur_tc, cur_cc = tc, cc
    summary: list[dict] = []

    def _fail(r: dict) -> dict:
        """Propagate failure, carrying the latest TC the runner obtained (if any)."""
        err = {"success": False, "error": r["error"]}
        latest = r.get("latest_transfer_code")
        if latest:
            err["latest_tc"] = latest.get("transfer")
            err["latest_cc"] = latest.get("confirmation")
        return err

    def _upd(codes):
        nonlocal cur_tc, cur_cc
        if isinstance(codes, dict):
            cur_tc = codes.get("transfer", cur_tc)
            cur_cc = codes.get("confirmation", cur_cc)
        elif codes:
            cur_tc = codes
            cur_cc = None

    def _runner():
        return BCSFERunner(transfer=cur_tc, confirm=cur_cc, country=order["country"])

    def _call(method, *args):
        return getattr(_runner(), method)(*args)

    # ── Step 1: Regular items (cat food, XP, tickets …) ──
    if regular_items:
        r = _call("run", regular_items)
        if not r["success"]: return _fail(r)
        _upd(r["new_transfer_code"])
        summary += [{"item": ITEM_MAP[i["key"]]["label"], "amount": i["amount"]}
                    for i in regular_items if i["key"] in ITEM_MAP]
        print(f"[BCSFE] items done -> tc={cur_tc}")

    # ── Step 2: Unlock ──
    cat_ids = order.get("cat_ids") or []
    if cat_ids or order.get("order_type") == "unlock":
        r = _call("run_unlock_characters", cat_ids)
        if not r["success"]: return _fail(r)
        _upd(r["new_transfer_code"])
        summary.append({"item": f"ปลดล็อค {len(cat_ids)} ตัว", "amount": len(cat_ids)})
        print(f"[BCSFE] unlock_cat done -> tc={cur_tc}")

    if "unlock_all" in all_pkg_set:
        r = _call("run_unlock_all")
        if not r["success"]: return _fail(r)
        _upd(r["new_transfer_code"])
        summary.append({"item": "Unlock All", "amount": 1})
        print(f"[BCSFE] unlock_all done -> tc={cur_tc}")

    if "crazed_all" in all_pkg_set:
        r = _call("run_unlock_characters", CRAZED_CAT_IDS)
        if not r["success"]: return _fail(r)
        _upd(r["new_transfer_code"])
        summary.append({"item": "Crazed All Cat (Unlock #91-99)", "amount": 9})
        print(f"[BCSFE] crazed_all done -> tc={cur_tc}")

    # ── Step 3: Upgrade Max ──
    if "upgrade_cat" in per_cat_groups:
        ids = per_cat_groups["upgrade_cat"]
        r = _call("run_upgrade_characters", ids)
        if not r["success"]: return _fail(r)
        _upd(r["new_transfer_code"])
        summary.append({"item": f"Upgrade Max ({len(ids)} ตัว)", "amount": len(ids)})
        print(f"[BCSFE] upgrade_cat x{len(ids)} done -> tc={cur_tc}")

    if "upgrade_all" in all_pkg_set:
        r = _call("run_upgrade_all_characters")
        if not r["success"]: return _fail(r)
        _upd(r["new_transfer_code"])
        summary.append({"item": "Upgrade Max All", "amount": 1})
        print(f"[BCSFE] upgrade_all done -> tc={cur_tc}")

    # ── Step 4: True Form ──
    if "trueform_cat" in per_cat_groups:
        ids = per_cat_groups["trueform_cat"]
        r = _call("run_true_form_characters", ids)
        if not r["success"]: return _fail(r)
        _upd(r["new_transfer_code"])
        summary.append({"item": f"True Form ({len(ids)} ตัว)", "amount": len(ids)})
        print(f"[BCSFE] trueform_cat x{len(ids)} done -> tc={cur_tc}")

    if "trueform_all" in all_pkg_set:
        r = _call("run_true_form_all")
        if not r["success"]: return _fail(r)
        _upd(r["new_transfer_code"])
        summary.append({"item": "True Form All", "amount": 1})
        print(f"[BCSFE] trueform_all done -> tc={cur_tc}")

    if "manic_all" in all_pkg_set:
        r = _call("run_true_form_characters", CRAZED_CAT_IDS)
        if not r["success"]: return _fail(r)
        _upd(r["new_transfer_code"])
        summary.append({"item": "Manic All Cat (True Form #91-99)", "amount": 9})
        print(f"[BCSFE] manic_all done -> tc={cur_tc}")

    # ── Step 5: Ultra Form ──
    if "ultraform_cat" in per_cat_groups:
        ids = per_cat_groups["ultraform_cat"]
        r = _call("run_ultra_form_characters", ids)
        if not r["success"]: return _fail(r)
        _upd(r["new_transfer_code"])
        summary.append({"item": f"Ultra Form ({len(ids)} ตัว)", "amount": len(ids)})
        print(f"[BCSFE] ultraform_cat x{len(ids)} done -> tc={cur_tc}")

    if "ultraform_all" in all_pkg_set:
        r = _call("run_ultra_form_all")
        if not r["success"]: return _fail(r)
        _upd(r["new_transfer_code"])
        summary.append({"item": "Ultra Form All", "amount": 1})
        print(f"[BCSFE] ultraform_all done -> tc={cur_tc}")

    # ── Step 6: Talent Max ──
    if "talents_cat" in per_cat_groups:
        ids = per_cat_groups["talents_cat"]
        r = _call("run_talents_max_characters", ids)
        if not r["success"]: return _fail(r)
        _upd(r["new_transfer_code"])
        summary.append({"item": f"Talent Max ({len(ids)} ตัว)", "amount": len(ids)})
        print(f"[BCSFE] talents_cat x{len(ids)} done -> tc={cur_tc}")

    if "talents_all" in all_pkg_set:
        r = _call("run_talents_max_all")
        if not r["success"]: return _fail(r)
        _upd(r["new_transfer_code"])
        summary.append({"item": "Max Talents All", "amount": 1})
        print(f"[BCSFE] talents_all done -> tc={cur_tc}")

    # -- Step 7: Stage operations --
    stages_config = order.get("stages_config") or {}
    if stages_config:
        story_ch  = stages_config.get("story_chapters", [])
        treasure_ch = stages_config.get("treasure_chapters", [])
        zombie_ch = stages_config.get("zombie_chapters", [])
        legend_types = stages_config.get("legend_types", [])
        max_crown = stages_config.get("max_crown", 4)
        aku_unlock = stages_config.get("aku_unlock", False)
        aku_chapters = stages_config.get("aku_chapters", False)

        if story_ch:
            r = _call("run_clear_story_chapters", story_ch)
            if not r["success"]: return _fail(r)
            _upd(r["new_transfer_code"])
            ch_names = [f"Ch.{c}" for c in story_ch]
            summary.append({"item": "Clear Story: " + ", ".join(ch_names), "amount": len(story_ch)})
            print(f"[BCSFE] story_clear done -> tc={cur_tc}")

        if treasure_ch:
            r = _call("run_set_treasure_chapters", treasure_ch, 3)
            if not r["success"]: return _fail(r)
            _upd(r["new_transfer_code"])
            ch_names = [f"Ch.{c}" for c in treasure_ch]
            summary.append({"item": "Gold Treasure: " + ", ".join(ch_names), "amount": len(treasure_ch)})
            print(f"[BCSFE] treasure done -> tc={cur_tc}")

        if zombie_ch:
            r = _call("run_clear_outbreak_chapters", zombie_ch)
            if not r["success"]: return _fail(r)
            _upd(r["new_transfer_code"])
            ch_names = [f"Ch.{c}" for c in zombie_ch]
            summary.append({"item": "Zombie Clear: " + ", ".join(ch_names), "amount": len(zombie_ch)})
            print(f"[BCSFE] zombie done -> tc={cur_tc}")

        if legend_types:
            legend_crowns = stages_config.get("legend_crowns", {})
            if legend_crowns:
                for lt in legend_types:
                    crown = max(1, min(4, int(legend_crowns.get(lt, max_crown))))
                    r = _call("run_clear_legends", [lt], crown)
                    if not r["success"]: return _fail(r)
                    _upd(r["new_transfer_code"])
                    summary.append({"item": f"Legend {lt.upper()} {crown}crown", "amount": 1})
                    print(f"[BCSFE] legend {lt} {crown}crown done -> tc={cur_tc}")
            else:
                r = _call("run_clear_legends", legend_types, max_crown)
                if not r["success"]: return _fail(r)
                _upd(r["new_transfer_code"])
                summary.append({"item": f"Legend ({', '.join(legend_types).upper()}) {max_crown}crown", "amount": len(legend_types)})
                print(f"[BCSFE] legends done -> tc={cur_tc}")

        if aku_unlock or aku_chapters:
            r = _call("run_aku", aku_unlock, aku_chapters)
            if not r["success"]: return _fail(r)
            _upd(r["new_transfer_code"])
            if aku_unlock:   summary.append({"item": "Aku Realm Unlock", "amount": 1})
            if aku_chapters: summary.append({"item": "Aku Chapters Clear", "amount": 1})
            print(f"[BCSFE] aku done -> tc={cur_tc}")

    return {"success": True, "new_tc": cur_tc, "new_cc": cur_cc, "summary": summary}


@app.post("/api/payment/create-stages")
async def payment_create_stages(body: StagesPaymentRequest):
    """สร้าง order สำหรับปลดล็อคด่าน"""
    if not body.transfer_code.strip() or not body.confirmation_code.strip():
        raise HTTPException(status_code=400, detail="กรุณากรอก Transfer Code และ Confirmation Code")
    if body.country not in COUNTRIES:
        raise HTTPException(status_code=400, detail=f"Country ไม่ถูกต้อง: {body.country}")
    cfg = body.stages_config
    if not any([cfg.story_chapters, cfg.treasure_chapters, cfg.zombie_chapters,
                cfg.legend_types, cfg.aku_unlock, cfg.aku_chapters]):
        raise HTTPException(status_code=400, detail="กรุณาเลือกบริการอย่างน้อย 1 อย่าง")
    correct_amount = _calc_stages_price(cfg)
    if correct_amount <= 0:
        raise HTTPException(status_code=400, detail="ไม่พบราคาสำหรับบริการที่เลือก")

    order = create_stages_order(
        transfer_code=body.transfer_code.strip(),
        confirmation_code=body.confirmation_code.strip(),
        country=body.country,
        stages_config=cfg.dict(),
        amount=correct_amount,
        payment_method=body.payment_method,
        username=body.username or "",
    )
    resp = {
        "order_id":      order["order_id"],
        "amount":        order["amount"],
        "base_amount":   order.get("base_amount", order["amount"]),
        "truemoney_fee": order.get("truemoney_fee", 0),
        "qr_base64":     order.get("qr_base64"),
        "expires_at":    order["expires_at"],
        "payment_method": body.payment_method,
    }
    if body.payment_method == "truemoney":
        resp["truemoney_id"] = TRUEMONEY_ID
    return resp


@app.post("/api/payment/verify/{order_id}")
async def payment_verify(order_id: str, slip: UploadFile = File(...)):
    """เน€เธเนเธเธชเธฅเธดเธ เนเธฅเธฐ เธ–เนเธฒเธเนเธฒเธ เนเธซเนเธฃเธฑเธ BCSFE เธ•เนเธญ"""
    order = get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="เนเธกเนเธเธ order เธเธตเน")

    if is_order_expired(order):
        raise HTTPException(status_code=400, detail="order เธซเธกเธ”เธญเธฒเธขเธธเนเธฅเนเธง เธเธฃเธธเธ“เธฒเธชเธฑเนเธเนเธซเธกเน")

    # bcsfe_failed = เธเธณเธฃเธฐเนเธฅเนเธงเนเธ•เน code เธเธดเธ” โ’ เธเธญเธ frontend เนเธซเนเนเธชเธ”เธ retry form
    if order["status"] == "bcsfe_failed":
        return {"success": False, "bcsfe_failed": True,
                "error": "เธชเธฅเธดเธเธเนเธฒเธเนเธฅเนเธงเนเธ•เน Code เนเธกเนเธ–เธนเธเธ•เนเธญเธ เธเธฃเธธเธ“เธฒเธเธฃเธญเธ Code เนเธซเธกเน"}

    if order["status"] in ("paid", "done", "retrying"):
        raise HTTPException(status_code=400, detail="order เธเธตเนเธ”เธณเน€เธเธดเธเธเธฒเธฃเนเธฅเนเธง")

    slip_bytes = await slip.read()
    slip_result = await verify_slip(slip_bytes, order_id)
    if not slip_result["success"]:
        raise HTTPException(status_code=400, detail=slip_result["reason"])

    transaction_id = slip_result.get("transaction_id", "")

    try:
        step_result = await run_bcsfe(_run_bcsfe_steps, order, order["transfer_code"], order["confirmation_code"])

        if not step_result["success"]:
            latest_tc = step_result.get("latest_tc")
            latest_cc = step_result.get("latest_cc")
            update_order_status(order_id, "bcsfe_failed", {
                "error": step_result["error"],
                "latest_transfer_code":     latest_tc,
                "latest_confirmation_code": latest_cc,
            })
            return {
                "success": False, "bcsfe_failed": True,
                "error": step_result["error"],
                "latest_transfer_code":     latest_tc,
                "latest_confirmation_code": latest_cc,
            }

        new_tc, new_cc = step_result["new_tc"], step_result["new_cc"]
        mark_slip_used(transaction_id)
        backup_save(new_tc or order["transfer_code"])
        update_order_status(order_id, "done", {
            "new_transfer_code":     new_tc,
            "new_confirmation_code": new_cc,
            "done_at":               datetime.now().isoformat(),
        })
        if order.get("username"):
            update_user_loyalty_spent(order["username"], order.get("base_amount", order["amount"]))

        return {
            "success":               True,
            "new_transfer_code":     new_tc,
            "new_confirmation_code": new_cc,
            "summary":               step_result["summary"],
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"เน€เธเธดเธ”เธเนเธญเธเธดเธ”เธเธฅเธฒเธ”: {e}")

@app.post("/api/payment/verify-voucher/{order_id}")
async def payment_verify_voucher(order_id: str, body: VoucherRedeemRequest):
    """verify TrueMoney ด้วยโค้ดซองอั่งเป่า แล้วรัน BCSFE ต่อ"""
    order = get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="ไม่พบ order นี้")

    if is_order_expired(order):
        raise HTTPException(status_code=400, detail="order หมดอายุแล้ว กรุณาสั่งใหม่")

    if order["status"] == "bcsfe_failed":
        return {"success": False, "bcsfe_failed": True,
                "error": "สลิปแล้วแต่ Code ไม่ถูกต้อง กรุณากรอก Code ใหม่"}

    if order["status"] in ("paid", "done", "retrying"):
        raise HTTPException(status_code=400, detail="order นี้ดำเนินการแล้ว")

    voucher_result = await redeem_truemoney_voucher(body.voucher_code, order_id)
    if not voucher_result["success"]:
        raise HTTPException(status_code=400, detail=voucher_result["reason"])

    transaction_id = voucher_result.get("transaction_id", "")

    try:
        step_result = await run_bcsfe(_run_bcsfe_steps, order, order["transfer_code"], order["confirmation_code"])

        if not step_result["success"]:
            latest_tc = step_result.get("latest_tc")
            latest_cc = step_result.get("latest_cc")
            update_order_status(order_id, "bcsfe_failed", {
                "error": step_result["error"],
                "latest_transfer_code":     latest_tc,
                "latest_confirmation_code": latest_cc,
            })
            return {
                "success": False, "bcsfe_failed": True,
                "error": step_result["error"],
                "latest_transfer_code":     latest_tc,
                "latest_confirmation_code": latest_cc,
            }

        new_tc, new_cc = step_result["new_tc"], step_result["new_cc"]
        mark_slip_used(transaction_id)
        backup_save(new_tc or order["transfer_code"])
        update_order_status(order_id, "done", {
            "new_transfer_code":     new_tc,
            "new_confirmation_code": new_cc,
            "done_at":               datetime.now().isoformat(),
        })
        if order.get("username"):
            update_user_loyalty_spent(order["username"], order.get("base_amount", order["amount"]))

        return {
            "success":               True,
            "new_transfer_code":     new_tc,
            "new_confirmation_code": new_cc,
            "summary":               step_result["summary"],
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"เกิดข้อผิดพลาด: {e}")


# ══════════════════════════════════════════
# LOYALTY ENDPOINTS
# ══════════════════════════════════════════

@app.get("/api/loyalty/status")
def loyalty_status_endpoint(username: str):
    loyalty = get_user_loyalty(username)
    total_spent = loyalty["total_spent"]
    redeemed = loyalty["loyalty_redeemed_cycles"]
    total_cycles = total_spent // 200
    available = total_cycles - redeemed
    progress_baht = total_spent % 200
    return {
        "username":                 username,
        "total_spent":              total_spent,
        "loyalty_redeemed_cycles":  redeemed,
        "available_cycles":         available,
        "progress_baht":            progress_baht,
        "progress_pct":             round(progress_baht / 200 * 100, 1),
        "next_reward_at":           (redeemed + 1) * 200,
    }


@app.post("/api/loyalty/redeem")
async def loyalty_redeem(body: LoyaltyRedeemRequest):
    if not verify_loyalty_session(body.username, body.session_token):
        raise HTTPException(status_code=401, detail="session ไม่ถูกต้อง — กรุณาเข้าสู่ระบบใหม่")
    loyalty = get_user_loyalty(body.username)
    available = loyalty["total_spent"] // 200 - loyalty["loyalty_redeemed_cycles"]
    if available <= 0:
        raise HTTPException(status_code=400, detail="ยังไม่มีรอบที่พร้อม redeem (ซื้อครบ 200 บาทถึงจะแลกได้)")

    cycles = max(1, min(body.cycles, available))  # clamp: 1 ≤ cycles ≤ available
    items = [
        {"key": "normal_ticket", "amount": 100 * cycles},
        {"key": "leadership",    "amount": 30  * cycles},
        {"key": "rare_ticket",   "amount": 10  * cycles},
    ]
    runner = BCSFERunner(body.transfer_code, body.confirmation_code, body.country)
    result = runner.run(items)

    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "BCSFE error"))

    codes = result["new_transfer_code"]
    new_tc = codes.get("transfer") if isinstance(codes, dict) else codes
    new_cc = codes.get("confirmation") if isinstance(codes, dict) else None
    add_loyalty_redeemed_cycles(body.username, cycles)
    save_loyalty_redemption(body.username, cycles, new_tc or "", new_cc or "")
    return {
        "success":               True,
        "new_transfer_code":     new_tc,
        "new_confirmation_code": new_cc,
        "cycles_redeemed":       cycles,
        "cycles_remaining":      available - cycles,
        "customer_note":         result.get("customer_note", ""),
    }


@app.get("/api/loyalty/history/{username}")
async def loyalty_history(username: str):
    rows = get_loyalty_redemptions(username)
    return {"history": rows}


@app.get("/api/payment/status/{order_id}")
def payment_status(order_id: str):
    order = get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="เนเธกเนเธเธ order")
    resp = {
        "order_id":   order_id,
        "status":     order["status"],
        "amount":     order["amount"],
        "expires_at": order["expires_at"],
    }
    resp["order_type"] = order.get("order_type", "bcsfe")
    if order["status"] == "done":
        if order.get("order_type") == "code_shop":
            stock = get_stock_by_order(order_id)
            if stock:
                resp["new_transfer_code"]     = stock.get("transfer_code")
                resp["new_confirmation_code"] = stock.get("confirmation_code")
        else:
            resp["new_transfer_code"]     = order.get("new_transfer_code")
            resp["new_confirmation_code"] = order.get("new_confirmation_code")
    return resp

@app.post("/api/order", response_model=OrderResponse)
async def place_order(order: OrderRequest):
    """
    เธฃเธฑเธ order เธเธฒเธเธฅเธนเธเธเนเธฒ โ’ เธฃเธฑเธ BCSFE โ’ เธชเนเธ Transfer Code เนเธซเธกเนเธเธฅเธฑเธ
    """
    
    # ===== Validation =====
    if not order.transfer_code or not order.confirmation_code:
        raise HTTPException(
            status_code=400,
            detail="Transfer Code เนเธฅเธฐ Confirmation Code เธซเนเธฒเธกเธงเนเธฒเธ"
        )
    
    if not order.items or len(order.items) == 0:
        raise HTTPException(
            status_code=400,
            detail="เธ•เนเธญเธเน€เธฅเธทเธญเธ item เธญเธขเนเธฒเธเธเนเธญเธข 1 เธเธดเนเธ"
        )
    
    # Validate เนเธ•เนเธฅเธฐ item
    for item in order.items:
        if item.key in ALL_PACKAGE_MAP:
            continue  # all-package items bypass ITEM_MAP validation
        if item.key not in ITEM_MAP:
            raise HTTPException(
                status_code=400,
                detail=f"เนเธกเนเธฃเธนเนเธเธฑเธ item: {item.key}"
            )
        
        cfg = ITEM_MAP[item.key]
        if item.amount <= 0:
            raise HTTPException(
                status_code=400,
                detail=f"เธเธณเธเธงเธ {item.key} เธ•เนเธญเธเธกเธฒเธเธเธงเนเธฒ 0"
            )
        
        if item.amount > cfg["max"]:
            raise HTTPException(
                status_code=400,
                detail=f"{cfg['label']} เน€เธเธดเธเธเธณเธเธงเธเธชเธนเธเธชเธธเธ” ({cfg['max']})"
            )
    
    # Validate country
    if order.country not in COUNTRIES:
        raise HTTPException(
            status_code=400,
            detail=f"Country เนเธกเนเธ–เธนเธเธ•เนเธญเธ: {order.country}"
        )
    
    # ===== เธฃเธฑเธ BCSFE =====
    try:
        print(f"\n{'='*60}")
        print(f"[ORDER] เน€เธฃเธดเนเธกเธ•เนเธ order เนเธซเธกเน")
        print(f"  Transfer Code: {order.transfer_code[:8]}...")
        print(f"  Country: {COUNTRIES[order.country]}")
        print(f"  Items: {len(order.items)} เธฃเธฒเธขเธเธฒเธฃ")
        print(f"{'='*60}\n")
        
        runner = BCSFERunner(
            transfer=order.transfer_code,
            confirm=order.confirmation_code,
            country=order.country,
        )
        
        # เนเธเธฅเธ items เน€เธเนเธ list[dict]
        items_list = [{"key": i.key, "amount": i.amount} for i in order.items]
        
        # เธฃเธฑเธ
        result = await run_bcsfe(runner.run, items_list)
        
        if result["success"]:
            # เธชเธฃเนเธฒเธ summary
            summary = [
                ItemSummary(
                    item=ITEM_MAP[i.key]["label"],
                    amount=i.amount
                )
                for i in order.items
            ]
            
            print(f"\n[ORDER] โ… เธชเธณเน€เธฃเนเธ!")

            # เธเธฑเธเธ—เธถเธ SAVE_DATA เธญเธฑเธ•เนเธเธกเธฑเธ•เธดเธซเธฅเธฑเธ order เธชเธณเน€เธฃเนเธ
            codes = result.get("new_transfer_code", {})
            new_tc = codes.get("transfer") if isinstance(codes, dict) else codes
            backup_save(new_tc or order.transfer_code)

            return OrderResponse(
                success=True,
                new_transfer_code=new_tc,
                new_confirmation_code=codes.get("confirmation") if isinstance(codes, dict) else None,
                summary=summary,
            )
        else:
            print(f"\n[ORDER] โ เธฅเนเธกเน€เธซเธฅเธง: {result['error']}")
            raise HTTPException(
                status_code=500,
                detail=result["error"]
            )
    
    except HTTPException:
        raise
    except Exception as e:
        error_msg = f"เน€เธเธดเธ”เธเนเธญเธเธดเธ”เธเธฅเธฒเธ”: {str(e)}"
        print(f"\n[ORDER] โ {error_msg}")
        raise HTTPException(status_code=500, detail=error_msg)

# ============= TEST ROUTES =============

@app.get("/api/orders/list")
def list_orders():
    """เธ”เธถเธ orders เธ—เธฑเนเธเธซเธกเธ”"""
    try:
        orders_dict = {}
        
        # เธฅเธญเธ load เธเธฒเธ orders.json เธ•เธฃเธ
        if ORDER_DB.exists():
            import json
            with open(ORDER_DB, 'r', encoding='utf-8') as f:
                try:
                    orders_dict = json.load(f)
                except:
                    pass
        
        # Filter เน€เธเธเธฒเธฐ top 20 orders เธฅเนเธฒเธชเธธเธ”
        if orders_dict:
            items = list(orders_dict.items())
            items.sort(key=lambda x: x[1].get('created_at', ''), reverse=True)
            orders_dict = dict(items[:20])
        
        return {
            "success": True,
            "total": len(orders_dict),
            "orders": orders_dict
        }
    except Exception as e:
        print(f"[ERROR] list_orders: {e}")
        return {
            "success": False,
            "total": 0,
            "orders": {}
        }

@app.post("/api/payment/cancel/{order_id}")
def cancel_order(order_id: str):
    """ลูกค้ายกเลิก order เอง (ยังไม่ได้จ่าย)"""
    try:
        order = get_order(order_id)
        if not order:
            raise HTTPException(status_code=404, detail="ไม่พบ order")
        if order["status"] not in ("pending",):
            raise HTTPException(status_code=400, detail="ยกเลิกได้เฉพาะ order ที่ยังรอชำระเงินเท่านั้น")
        update_order_status(order_id, "cancelled", {})
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/orders/my/{username}")
def my_orders(username: str):
    """ดึง orders ของ user คนนั้น อ่านจาก user_orders.json"""
    try:
        import json
        from pathlib import Path
        user_orders_path = Path("user_orders.json")
        order_ids = []
        if user_orders_path.exists():
            data = json.loads(user_orders_path.read_text(encoding="utf-8"))
            order_ids = data.get(username, [])

        orders_dict = {}
        if ORDER_DB.exists():
            orders_dict = json.loads(ORDER_DB.read_text(encoding="utf-8"))

        result = []
        for oid in order_ids[:30]:
            if oid in orders_dict:
                o = dict(orders_dict[oid])
                o.pop("qr_base64", None)  # ไม่ส่ง QR base64 (ใหญ่เกิน)
                result.append(o)

        return {"success": True, "orders": result}
    except Exception as e:
        return {"success": False, "orders": []}

@app.post("/api/test/bcsfe")
async def test_bcsfe(request: TestBCSFERequest):
    """
    เธ—เธ”เธชเธญเธเธเธฒเธฃเน€เธเธดเนเธกเธเธญเธเน€เธเนเธฒเน€เธเธกเธเนเธฒเธ BCSFE เนเธ”เธขเนเธกเนเธ•เนเธญเธเธเนเธฒเธเธฃเธฐเธเธเธเธฒเธฃเธเนเธฒเธขเน€เธเธดเธ
    """
    try:
        transfer_code = request.transfer_code.strip()
        confirmation_code = request.confirmation_code.strip()
        item_key = request.item.strip()
        amount = request.amount
        sub_type = request.sub_type
        country = request.country
        
        # Validation
        if not transfer_code or not confirmation_code:
            return {
                "success": False,
                "error": "Transfer Code เนเธฅเธฐ Confirmation Code เธซเนเธฒเธกเธงเนเธฒเธ"
            }
        
        if not item_key or item_key not in ITEM_MAP:
            return {
                "success": False,
                "error": f"เนเธกเนเธฃเธนเนเธเธฑเธ item: {item_key}"
            }
        
        if amount <= 0:
            return {
                "success": False,
                "error": f"เธเธณเธเธงเธเธ•เนเธญเธเธกเธฒเธเธเธงเนเธฒ 0"
            }
        
        cfg = ITEM_MAP[item_key]
        if amount > cfg["max"]:
            return {
                "success": False,
                "error": f"{cfg['label']} เน€เธเธดเธเธเธณเธเธงเธเธชเธนเธเธชเธธเธ” ({cfg['max']})"
            }
        
        if country not in COUNTRIES:
            return {
                "success": False,
                "error": f"Country เนเธกเนเธ–เธนเธเธ•เนเธญเธ: {country}"
            }
        
        print(f"\n{'='*60}")
        print(f"[TEST-BCSFE] ๐งช เธ—เธ”เธชเธญเธเธเธฒเธฃเน€เธเธดเนเธกเธเธญเธ")
        print(f"  Transfer Code: {transfer_code[:8]}...")
        print(f"  Item: {cfg['label']} x{amount}")
        print(f"  Country: {COUNTRIES[country]}")
        print(f"{'='*60}\n")
        
        # เธชเธฃเนเธฒเธ items list
        items_list = [{"key": item_key, "amount": amount}]
        if sub_type:
            items_list[0]["sub_type"] = sub_type
        
        # เธฃเธฑเธ BCSFE
        runner = BCSFERunner(
            transfer=transfer_code,
            confirm=confirmation_code,
            country=country,
        )
        
        result = await run_bcsfe(runner.run, items_list)
        
        if result["success"]:
            codes = result.get("new_transfer_code", {})
            new_tc = codes.get("transfer") if isinstance(codes, dict) else codes
            new_cc = codes.get("confirmation") if isinstance(codes, dict) else None

            # เธเธฑเธเธ—เธถเธ SAVE_DATA
            backup_save(new_tc or transfer_code)

            # เธชเธฃเนเธฒเธ summary
            summary = [
                {
                    "item": cfg["label"],
                    "amount": amount
                }
            ]

            print(f"[TEST-BCSFE] โ… เธชเธณเน€เธฃเนเธ!")

            resp = {
                "success": True,
                "new_transfer_code": new_tc,
                "new_confirmation_code": new_cc,
                "summary": summary,
            }
            if result.get("customer_note"):
                resp["customer_note"] = result["customer_note"]
            return resp
        else:
            print(f"[TEST-BCSFE] โ เธฅเนเธกเน€เธซเธฅเธง: {result['error']}")
            latest = result.get("latest_transfer_code")
            return {
                "success": False,
                "error": result.get("error", "Unknown error"),
                "latest_transfer_code": latest,
            }

    except Exception as e:
        error_msg = f"เน€เธเธดเธ”เธเนเธญเธเธดเธ”เธเธฅเธฒเธ”: {str(e)}"
        print(f"[TEST-BCSFE] โ {error_msg}")
        return {
            "success": False,
            "error": error_msg
        }

@app.post("/api/test/bcsfe/batch")
async def test_bcsfe_batch(request: OrderRequest):
    """
    เธ—เธ”เธชเธญเธเน€เธเธดเนเธกเธเธญเธเธซเธฅเธฒเธขเธฃเธฒเธขเธเธฒเธฃเนเธเธเธฃเธฑเนเธเน€เธ”เธตเธขเธง โ€” download เธเธฃเธฑเนเธเน€เธ”เธตเธขเธง เนเธเนเธ—เธธเธ item เนเธฅเนเธง upload เธเธฃเธฑเนเธเน€เธ”เธตเธขเธง
    """
    try:
        transfer_code     = request.transfer_code.strip()
        confirmation_code = request.confirmation_code.strip()
        country           = request.country

        if not transfer_code or not confirmation_code:
            return {"success": False, "error": "Transfer Code เนเธฅเธฐ Confirmation Code เธซเนเธฒเธกเธงเนเธฒเธ"}
        if country not in COUNTRIES:
            return {"success": False, "error": f"Country เนเธกเนเธ–เธนเธเธ•เนเธญเธ: {country}"}
        if not request.items:
            return {"success": False, "error": "เนเธกเนเธกเธต item เนเธเธฃเธฒเธขเธเธฒเธฃ"}

        items_list = []
        for item in request.items:
            if item.key not in ITEM_MAP:
                return {"success": False, "error": f"เนเธกเนเธฃเธนเนเธเธฑเธ item: {item.key}"}
            cfg = ITEM_MAP[item.key]
            if item.amount <= 0 or item.amount > cfg["max"]:
                return {"success": False, "error": f"{cfg['label']} เธเธณเธเธงเธเนเธกเนเธ–เธนเธเธ•เนเธญเธ ({item.amount})"}
            entry = {"key": item.key, "amount": item.amount}
            if item.sub_type:
                entry["sub_type"] = item.sub_type
            items_list.append(entry)

        runner = BCSFERunner(transfer=transfer_code, confirm=confirmation_code, country=country)
        result = await run_bcsfe(runner.run, items_list)

        if result["success"]:
            codes  = result.get("new_transfer_code", {})
            new_tc = codes.get("transfer") if isinstance(codes, dict) else codes
            new_cc = codes.get("confirmation") if isinstance(codes, dict) else None
            backup_save(new_tc or transfer_code)
            summary = [{"item": ITEM_MAP[i["key"]]["label"], "amount": i["amount"]} for i in items_list]
            resp = {"success": True, "new_transfer_code": new_tc, "new_confirmation_code": new_cc, "summary": summary}
            if result.get("customer_note"):
                resp["customer_note"] = result["customer_note"]
            return resp
        else:
            latest = result.get("latest_transfer_code")
            return {"success": False, "error": result.get("error", "Unknown error"),
                    "latest_transfer_code": latest}

    except Exception as e:
        return {"success": False, "error": f"เน€เธเธดเธ”เธเนเธญเธเธดเธ”เธเธฅเธฒเธ”: {str(e)}"}


@app.post("/api/unlock/characters")
async def unlock_characters(request: UnlockCharactersRequest):
    """เธเธฅเธ”เธฅเนเธญเธเธ•เธฑเธงเธฅเธฐเธเธฃเธ•เธฒเธก cat_ids เธเนเธฒเธ BCSFE"""
    try:
        transfer_code     = request.transfer_code.strip()
        confirmation_code = request.confirmation_code.strip()
        country           = request.country
        cat_ids           = request.cat_ids

        if not transfer_code or not confirmation_code:
            return {"success": False, "error": "Transfer Code เนเธฅเธฐ Confirmation Code เธซเนเธฒเธกเธงเนเธฒเธ"}
        if not cat_ids:
            return {"success": False, "error": "เธ•เนเธญเธเธฃเธฐเธเธธ cat_ids เธญเธขเนเธฒเธเธเนเธญเธข 1 เธ•เธฑเธง"}
        if country not in COUNTRIES:
            return {"success": False, "error": f"Country เนเธกเนเธ–เธนเธเธ•เนเธญเธ: {country}"}

        print(f"\n{'='*60}")
        print(f"[UNLOCK-CHARS] ๐ฑ เธเธฅเธ”เธฅเนเธญเธ {len(cat_ids)} เธ•เธฑเธงเธฅเธฐเธเธฃ")
        print(f"  Transfer Code: {transfer_code[:8]}...")
        print(f"  Country: {COUNTRIES[country]}")
        print(f"  IDs: {str(cat_ids[:10])}{'...' if len(cat_ids) > 10 else ''}")
        print(f"{'='*60}\n")

        runner = BCSFERunner(
            transfer=transfer_code,
            confirm=confirmation_code,
            country=country,
        )
        result = await run_bcsfe(runner.run_unlock_characters, cat_ids)

        if result["success"]:
            codes = result.get("new_transfer_code", {})
            new_tc = codes.get("transfer") if isinstance(codes, dict) else codes
            new_cc = codes.get("confirmation") if isinstance(codes, dict) else None
            backup_save(new_tc or transfer_code)
            print(f"[UNLOCK-CHARS] โ… เธชเธณเน€เธฃเนเธ!")
            return {
                "success": True,
                "new_transfer_code": new_tc,
                "new_confirmation_code": new_cc,
                "unlocked_count": len(cat_ids),
            }
        else:
            print(f"[UNLOCK-CHARS] โ เธฅเนเธกเน€เธซเธฅเธง: {result['error']}")
            return {"success": False, "error": result.get("error", "Unknown error")}

    except Exception as e:
        error_msg = f"เน€เธเธดเธ”เธเนเธญเธเธดเธ”เธเธฅเธฒเธ”: {str(e)}"
        print(f"[UNLOCK-CHARS] โ {error_msg}")
        return {"success": False, "error": error_msg}

@app.post("/api/upgrade/characters")
async def upgrade_characters(request: UnlockCharactersRequest):
    """เธญเธฑเธเน€เธเธฃเธ”เธ•เธฑเธงเธฅเธฐเธเธฃเธ–เธถเธ max level"""
    try:
        if not request.transfer_code.strip() or not request.confirmation_code.strip():
            return {"success": False, "error": "Transfer/Confirmation Code เธซเนเธฒเธกเธงเนเธฒเธ"}
        if not request.cat_ids:
            return {"success": False, "error": "เธ•เนเธญเธเธฃเธฐเธเธธ cat_ids เธญเธขเนเธฒเธเธเนเธญเธข 1 เธ•เธฑเธง"}
        if request.country not in COUNTRIES:
            return {"success": False, "error": f"Country เนเธกเนเธ–เธนเธเธ•เนเธญเธ: {request.country}"}

        print(f"\n[UPGRADE-CHARS] โฌ๏ธ upgrade {len(request.cat_ids)} เธ•เธฑเธงเธฅเธฐเธเธฃ")
        runner = BCSFERunner(transfer=request.transfer_code.strip(),
                             confirm=request.confirmation_code.strip(),
                             country=request.country)
        result = await run_bcsfe(runner.run_upgrade_characters, request.cat_ids)
        if result["success"]:
            codes = result.get("new_transfer_code", {})
            new_tc = codes.get("transfer") if isinstance(codes, dict) else codes
            new_cc = codes.get("confirmation") if isinstance(codes, dict) else None
            backup_save(new_tc or request.transfer_code)
            return {"success": True, "new_transfer_code": new_tc,
                    "new_confirmation_code": new_cc, "count": len(request.cat_ids), "log": result.get("log", [])}
        return {"success": False, "error": result.get("error", "Unknown error")}
    except Exception as e:
        return {"success": False, "error": f"เน€เธเธดเธ”เธเนเธญเธเธดเธ”เธเธฅเธฒเธ”: {e}"}


@app.post("/api/unlock/all")
async def unlock_all_characters(request: AllCatsRequest):
    """Unlock เธ—เธธเธเธ•เธฑเธงเธฅเธฐเธเธฃเนเธเน€เธเธก"""
    try:
        if not request.transfer_code.strip() or not request.confirmation_code.strip():
            return {"success": False, "error": "Transfer/Confirmation Code เธซเนเธฒเธกเธงเนเธฒเธ"}
        if request.country not in COUNTRIES:
            return {"success": False, "error": f"Country เนเธกเนเธ–เธนเธเธ•เนเธญเธ: {request.country}"}

        print(f"\n[UNLOCK-ALL] ๐ฑ unlock all cats")
        runner = BCSFERunner(transfer=request.transfer_code.strip(),
                             confirm=request.confirmation_code.strip(),
                             country=request.country)
        result = await run_bcsfe(runner.run_unlock_all)
        if result["success"]:
            codes = result.get("new_transfer_code", {})
            new_tc = codes.get("transfer") if isinstance(codes, dict) else codes
            new_cc = codes.get("confirmation") if isinstance(codes, dict) else None
            backup_save(new_tc or request.transfer_code)
            return {"success": True, "new_transfer_code": new_tc,
                    "new_confirmation_code": new_cc, "count": result.get("count", 0), "log": result.get("log", [])}
        return {"success": False, "error": result.get("error", "Unknown error")}
    except Exception as e:
        return {"success": False, "error": f"เน€เธเธดเธ”เธเนเธญเธเธดเธ”เธเธฅเธฒเธ”: {e}"}


@app.post("/api/upgrade/all")
async def upgrade_all_characters(request: AllCatsRequest):
    """Upgrade base max เธ—เธธเธเธ•เธฑเธงเธ—เธตเน unlock เธญเธขเธนเนเนเธเธฃเธซเธฑเธช"""
    try:
        if not request.transfer_code.strip() or not request.confirmation_code.strip():
            return {"success": False, "error": "Transfer/Confirmation Code เธซเนเธฒเธกเธงเนเธฒเธ"}
        if request.country not in COUNTRIES:
            return {"success": False, "error": f"Country เนเธกเนเธ–เธนเธเธ•เนเธญเธ: {request.country}"}

        print(f"\n[UPGRADE-ALL] โฌ๏ธ upgrade all unlocked cats")
        runner = BCSFERunner(transfer=request.transfer_code.strip(),
                             confirm=request.confirmation_code.strip(),
                             country=request.country)
        result = await run_bcsfe(runner.run_upgrade_all_characters)
        if result["success"]:
            codes = result.get("new_transfer_code", {})
            new_tc = codes.get("transfer") if isinstance(codes, dict) else codes
            new_cc = codes.get("confirmation") if isinstance(codes, dict) else None
            backup_save(new_tc or request.transfer_code)
            return {"success": True, "new_transfer_code": new_tc,
                    "new_confirmation_code": new_cc, "count": result.get("count", 0), "log": result.get("log", [])}
        return {"success": False, "error": result.get("error", "Unknown error")}
    except Exception as e:
        return {"success": False, "error": f"เน€เธเธดเธ”เธเนเธญเธเธดเธ”เธเธฅเธฒเธ”: {e}"}


@app.post("/api/trueform/all")
async def trueform_all_characters(request: AllCatsRequest):
    """True Form เธ—เธธเธเธ•เธฑเธงเธ—เธตเนเธฅเธนเธเธเนเธฒเธกเธตเธญเธขเธนเนเนเธฅเนเธง"""
    try:
        if not request.transfer_code.strip() or not request.confirmation_code.strip():
            return {"success": False, "error": "Transfer/Confirmation Code เธซเนเธฒเธกเธงเนเธฒเธ"}
        if request.country not in COUNTRIES:
            return {"success": False, "error": f"Country เนเธกเนเธ–เธนเธเธ•เนเธญเธ: {request.country}"}

        print(f"\n[TRUEFORM-ALL] โจ true form all unlocked cats")
        runner = BCSFERunner(transfer=request.transfer_code.strip(),
                             confirm=request.confirmation_code.strip(),
                             country=request.country)
        result = await run_bcsfe(runner.run_true_form_all)
        if result["success"]:
            codes = result.get("new_transfer_code", {})
            new_tc = codes.get("transfer") if isinstance(codes, dict) else codes
            new_cc = codes.get("confirmation") if isinstance(codes, dict) else None
            backup_save(new_tc or request.transfer_code)
            return {"success": True, "new_transfer_code": new_tc,
                    "new_confirmation_code": new_cc, "count": result.get("count", 0), "log": result.get("log", [])}
        return {"success": False, "error": result.get("error", "Unknown error")}
    except Exception as e:
        return {"success": False, "error": f"เน€เธเธดเธ”เธเนเธญเธเธดเธ”เธเธฅเธฒเธ”: {e}"}


@app.post("/api/ultraform/all")
async def ultraform_all_characters(request: AllCatsRequest):
    """Ultra Form เธ—เธธเธเธ•เธฑเธงเธ—เธตเนเธฅเธนเธเธเนเธฒเธกเธตเธญเธขเธนเนเนเธฅเนเธง"""
    try:
        if not request.transfer_code.strip() or not request.confirmation_code.strip():
            return {"success": False, "error": "Transfer/Confirmation Code เธซเนเธฒเธกเธงเนเธฒเธ"}
        if request.country not in COUNTRIES:
            return {"success": False, "error": f"Country เนเธกเนเธ–เธนเธเธ•เนเธญเธ: {request.country}"}

        print(f"\n[ULTRAFORM-ALL] ๐’ฅ ultra form all unlocked cats")
        runner = BCSFERunner(transfer=request.transfer_code.strip(),
                             confirm=request.confirmation_code.strip(),
                             country=request.country)
        result = await run_bcsfe(runner.run_ultra_form_all)
        if result["success"]:
            codes = result.get("new_transfer_code", {})
            new_tc = codes.get("transfer") if isinstance(codes, dict) else codes
            new_cc = codes.get("confirmation") if isinstance(codes, dict) else None
            backup_save(new_tc or request.transfer_code)
            return {"success": True, "new_transfer_code": new_tc,
                    "new_confirmation_code": new_cc, "count": result.get("count", 0), "log": result.get("log", [])}
        return {"success": False, "error": result.get("error", "Unknown error")}
    except Exception as e:
        return {"success": False, "error": f"เน€เธเธดเธ”เธเนเธญเธเธดเธ”เธเธฅเธฒเธ”: {e}"}


@app.post("/api/talents/all")
async def talents_all_characters(request: AllCatsRequest):
    """Max Talents เธ—เธธเธเธ•เธฑเธงเธ—เธตเนเธฅเธนเธเธเนเธฒเธกเธตเธญเธขเธนเนเนเธฅเนเธง"""
    try:
        if not request.transfer_code.strip() or not request.confirmation_code.strip():
            return {"success": False, "error": "Transfer/Confirmation Code เธซเนเธฒเธกเธงเนเธฒเธ"}
        if request.country not in COUNTRIES:
            return {"success": False, "error": f"Country เนเธกเนเธ–เธนเธเธ•เนเธญเธ: {request.country}"}

        print(f"\n[TALENTS-ALL] ๐ talents max all unlocked cats")
        runner = BCSFERunner(transfer=request.transfer_code.strip(),
                             confirm=request.confirmation_code.strip(),
                             country=request.country)
        result = await run_bcsfe(runner.run_talents_max_all)
        if result["success"]:
            codes = result.get("new_transfer_code", {})
            new_tc = codes.get("transfer") if isinstance(codes, dict) else codes
            new_cc = codes.get("confirmation") if isinstance(codes, dict) else None
            backup_save(new_tc or request.transfer_code)
            return {"success": True, "new_transfer_code": new_tc,
                    "new_confirmation_code": new_cc, "count": result.get("count", 0), "log": result.get("log", [])}
        return {"success": False, "error": result.get("error", "Unknown error")}
    except Exception as e:
        return {"success": False, "error": f"เน€เธเธดเธ”เธเนเธญเธเธดเธ”เธเธฅเธฒเธ”: {e}"}






@app.post("/api/clear/story-chapters")
async def clear_story_chapters(request: ClearStoryChaptersRequest):
    """เคลียร์ด่าน Main Story ตาม chapter ที่ระบุ (1-9)"""
    try:
        if not request.transfer_code.strip() or not request.confirmation_code.strip():
            return {"success": False, "error": "Transfer/Confirmation Code ห้ามว่าง"}
        if request.country not in COUNTRIES:
            return {"success": False, "error": f"Country ไม่ถูกต้อง: {request.country}"}
        valid = [c for c in request.chapters if 1 <= c <= 9]
        if not valid:
            return {"success": False, "error": "chapters ต้องเป็นตัวเลข 1-9 อย่างน้อย 1 ตัว"}
        ca = max(1, min(request.clear_amount, 9999))
        print(f"\n[CLEAR-STORY] chapters={valid} x{ca}")
        runner = BCSFERunner(transfer=request.transfer_code.strip(),
                             confirm=request.confirmation_code.strip(),
                             country=request.country)
        result = await run_bcsfe(runner.run_clear_story_chapters, valid, ca)
        if result["success"]:
            codes = result.get("new_transfer_code", {})
            new_tc = codes.get("transfer") if isinstance(codes, dict) else codes
            new_cc = codes.get("confirmation") if isinstance(codes, dict) else None
            backup_save(new_tc or request.transfer_code)
            return {"success": True, "new_transfer_code": new_tc,
                    "new_confirmation_code": new_cc, "log": result.get("log", [])}
        return {"success": False, "error": result.get("error", "Unknown error")}
    except Exception as e:
        return {"success": False, "error": f"เกิดข้อผิดพลาด: {e}"}


@app.post("/api/clear/story-all")
async def clear_story_all(request: ClearStoryAllRequest):
    """เคลียร์ด่าน Main Story ทั้ง 9 chapters"""
    try:
        if not request.transfer_code.strip() or not request.confirmation_code.strip():
            return {"success": False, "error": "Transfer/Confirmation Code ห้ามว่าง"}
        if request.country not in COUNTRIES:
            return {"success": False, "error": f"Country ไม่ถูกต้อง: {request.country}"}
        ca = max(1, min(request.clear_amount, 9999))
        print(f"\n[CLEAR-STORY-ALL] all chapters x{ca}")
        runner = BCSFERunner(transfer=request.transfer_code.strip(),
                             confirm=request.confirmation_code.strip(),
                             country=request.country)
        result = await run_bcsfe(runner.run_clear_story_all, ca)
        if result["success"]:
            codes = result.get("new_transfer_code", {})
            new_tc = codes.get("transfer") if isinstance(codes, dict) else codes
            new_cc = codes.get("confirmation") if isinstance(codes, dict) else None
            backup_save(new_tc or request.transfer_code)
            return {"success": True, "new_transfer_code": new_tc,
                    "new_confirmation_code": new_cc, "log": result.get("log", [])}
        return {"success": False, "error": result.get("error", "Unknown error")}
    except Exception as e:
        return {"success": False, "error": f"เกิดข้อผิดพลาด: {e}"}

@app.post("/api/reset/story-chapters")
async def reset_story_chapters(request: ResetStoryChaptersRequest):
    """รีเซ็ตด่าน Main Story กลับเป็น 0 ตาม chapter ที่ระบุ"""
    try:
        if not request.transfer_code.strip() or not request.confirmation_code.strip():
            return {"success": False, "error": "Transfer/Confirmation Code ห้ามว่าง"}
        if request.country not in COUNTRIES:
            return {"success": False, "error": f"Country ไม่ถูกต้อง: {request.country}"}
        valid = [c for c in request.chapters if 1 <= c <= 9]
        if not valid:
            return {"success": False, "error": "chapters ต้องเป็นตัวเลข 1-9 อย่างน้อย 1 ตัว"}
        print(f"\n[RESET-STORY] chapters={valid}")
        runner = BCSFERunner(transfer=request.transfer_code.strip(),
                             confirm=request.confirmation_code.strip(),
                             country=request.country)
        result = await run_bcsfe(runner.run_reset_story_chapters, valid)
        if result["success"]:
            codes = result.get("new_transfer_code", {})
            new_tc = codes.get("transfer") if isinstance(codes, dict) else codes
            new_cc = codes.get("confirmation") if isinstance(codes, dict) else None
            backup_save(new_tc or request.transfer_code)
            return {"success": True, "new_transfer_code": new_tc,
                    "new_confirmation_code": new_cc, "log": result.get("log", [])}
        return {"success": False, "error": result.get("error", "Unknown error")}
    except Exception as e:
        return {"success": False, "error": f"เกิดข้อผิดพลาด: {e}"}


@app.post("/api/reset/story-all")
async def reset_story_all(request: ResetStoryAllRequest):
    """รีเซ็ตด่าน Main Story ทั้ง 9 chapters"""
    try:
        if not request.transfer_code.strip() or not request.confirmation_code.strip():
            return {"success": False, "error": "Transfer/Confirmation Code ห้ามว่าง"}
        if request.country not in COUNTRIES:
            return {"success": False, "error": f"Country ไม่ถูกต้อง: {request.country}"}
        print(f"\n[RESET-STORY-ALL] reset all chapters")
        runner = BCSFERunner(transfer=request.transfer_code.strip(),
                             confirm=request.confirmation_code.strip(),
                             country=request.country)
        result = await run_bcsfe(runner.run_reset_story_all)
        if result["success"]:
            codes = result.get("new_transfer_code", {})
            new_tc = codes.get("transfer") if isinstance(codes, dict) else codes
            new_cc = codes.get("confirmation") if isinstance(codes, dict) else None
            backup_save(new_tc or request.transfer_code)
            return {"success": True, "new_transfer_code": new_tc,
                    "new_confirmation_code": new_cc, "log": result.get("log", [])}
        return {"success": False, "error": result.get("error", "Unknown error")}
    except Exception as e:
        return {"success": False, "error": f"เกิดข้อผิดพลาด: {e}"}

@app.post("/api/treasure/story-chapters")
async def set_treasure_chapters(request: SetTreasureChaptersRequest):
    """ตั้งค่า treasure สำหรับ story chapters ที่ระบุ"""
    try:
        if not request.transfer_code.strip() or not request.confirmation_code.strip():
            return {"success": False, "error": "Transfer/Confirmation Code ห้ามว่าง"}
        if request.country not in COUNTRIES:
            return {"success": False, "error": f"Country ไม่ถูกต้อง: {request.country}"}
        invalid = [c for c in request.chapters if c not in range(1, 10)]
        if invalid:
            return {"success": False, "error": f"Chapter ไม่ถูกต้อง: {invalid} (ต้องเป็น 1-9)"}
        tv = max(0, min(3, request.treasure_value))
        print(f"\n[TREASURE-CHAPTERS] chapters={request.chapters} value={tv}")
        runner = BCSFERunner(transfer=request.transfer_code.strip(),
                             confirm=request.confirmation_code.strip(),
                             country=request.country)
        result = await run_bcsfe(runner.run_set_treasure_chapters, request.chapters, tv)
        if result["success"]:
            codes = result.get("new_transfer_code", {})
            new_tc = codes.get("transfer") if isinstance(codes, dict) else codes
            new_cc = codes.get("confirmation") if isinstance(codes, dict) else None
            backup_save(new_tc or request.transfer_code)
            return {"success": True, "new_transfer_code": new_tc,
                    "new_confirmation_code": new_cc, "log": result.get("log", [])}
        return {"success": False, "error": result.get("error", "Unknown error")}
    except Exception as e:
        return {"success": False, "error": f"เกิดข้อผิดพลาด: {e}"}

@app.post("/api/treasure/story-all")
async def set_treasure_all(request: SetTreasureAllRequest):
    """ตั้งค่า treasure ทุก chapter (1-9)"""
    try:
        if not request.transfer_code.strip() or not request.confirmation_code.strip():
            return {"success": False, "error": "Transfer/Confirmation Code ห้ามว่าง"}
        if request.country not in COUNTRIES:
            return {"success": False, "error": f"Country ไม่ถูกต้อง: {request.country}"}
        tv = max(0, min(3, request.treasure_value))
        print(f"\n[TREASURE-ALL] value={tv}")
        runner = BCSFERunner(transfer=request.transfer_code.strip(),
                             confirm=request.confirmation_code.strip(),
                             country=request.country)
        result = await run_bcsfe(runner.run_set_treasure_all, tv)
        if result["success"]:
            codes = result.get("new_transfer_code", {})
            new_tc = codes.get("transfer") if isinstance(codes, dict) else codes
            new_cc = codes.get("confirmation") if isinstance(codes, dict) else None
            backup_save(new_tc or request.transfer_code)
            return {"success": True, "new_transfer_code": new_tc,
                    "new_confirmation_code": new_cc, "log": result.get("log", [])}
        return {"success": False, "error": result.get("error", "Unknown error")}
    except Exception as e:
        return {"success": False, "error": f"เกิดข้อผิดพลาด: {e}"}

@app.post("/api/outbreak/story-chapters")
async def clear_outbreak_chapters(request: ClearOutbreakChaptersRequest):
    """เคลียร์ zombie/outbreak สำหรับ story chapters ที่ระบุ"""
    try:
        if not request.transfer_code.strip() or not request.confirmation_code.strip():
            return {"success": False, "error": "Transfer/Confirmation Code ห้ามว่าง"}
        if request.country not in COUNTRIES:
            return {"success": False, "error": f"Country ไม่ถูกต้อง: {request.country}"}
        invalid = [c for c in request.chapters if c not in range(1, 10)]
        if invalid:
            return {"success": False, "error": f"Chapter ไม่ถูกต้อง: {invalid} (ต้องเป็น 1-9)"}
        print(f"\n[OUTBREAK-CHAPTERS] chapters={request.chapters}")
        runner = BCSFERunner(transfer=request.transfer_code.strip(),
                             confirm=request.confirmation_code.strip(),
                             country=request.country)
        result = await run_bcsfe(runner.run_clear_outbreak_chapters, request.chapters)
        if result["success"]:
            codes = result.get("new_transfer_code", {})
            new_tc = codes.get("transfer") if isinstance(codes, dict) else codes
            new_cc = codes.get("confirmation") if isinstance(codes, dict) else None
            backup_save(new_tc or request.transfer_code)
            return {"success": True, "new_transfer_code": new_tc,
                    "new_confirmation_code": new_cc, "log": result.get("log", [])}
        return {"success": False, "error": result.get("error", "Unknown error")}
    except Exception as e:
        return {"success": False, "error": f"เกิดข้อผิดพลาด: {e}"}

@app.post("/api/outbreak/story-all")
async def clear_outbreak_all(request: ClearOutbreakAllRequest):
    """เคลียร์ zombie/outbreak ทุก chapter (1-9)"""
    try:
        if not request.transfer_code.strip() or not request.confirmation_code.strip():
            return {"success": False, "error": "Transfer/Confirmation Code ห้ามว่าง"}
        if request.country not in COUNTRIES:
            return {"success": False, "error": f"Country ไม่ถูกต้อง: {request.country}"}
        print(f"\n[OUTBREAK-ALL] clear all outbreaks")
        runner = BCSFERunner(transfer=request.transfer_code.strip(),
                             confirm=request.confirmation_code.strip(),
                             country=request.country)
        result = await run_bcsfe(runner.run_clear_outbreak_all)
        if result["success"]:
            codes = result.get("new_transfer_code", {})
            new_tc = codes.get("transfer") if isinstance(codes, dict) else codes
            new_cc = codes.get("confirmation") if isinstance(codes, dict) else None
            backup_save(new_tc or request.transfer_code)
            return {"success": True, "new_transfer_code": new_tc,
                    "new_confirmation_code": new_cc, "log": result.get("log", [])}
        return {"success": False, "error": result.get("error", "Unknown error")}
    except Exception as e:
        return {"success": False, "error": f"เกิดข้อผิดพลาด: {e}"}

@app.post("/api/aku")
async def aku_action(request: AkuRequest):
    """ปลดล็อค Aku Realm (#8) และ/หรือ เคลียร์ Aku Chapters (#11)"""
    try:
        if not request.transfer_code.strip() or not request.confirmation_code.strip():
            return {"success": False, "error": "Transfer/Confirmation Code ห้ามว่าง"}
        if request.country not in COUNTRIES:
            return {"success": False, "error": f"Country ไม่ถูกต้อง: {request.country}"}
        if not request.do_unlock and not request.do_chapters:
            return {"success": False, "error": "ต้องเลือกอย่างน้อย 1 action (do_unlock หรือ do_chapters)"}
        clear_amount = max(1, min(9999, request.clear_amount))
        print(f"\n[AKU] unlock={request.do_unlock} chapters={request.do_chapters} x{clear_amount}")
        runner = BCSFERunner(transfer=request.transfer_code.strip(),
                             confirm=request.confirmation_code.strip(),
                             country=request.country)
        result = await run_bcsfe(runner.run_aku, request.do_unlock, request.do_chapters, clear_amount)
        if result["success"]:
            codes = result.get("new_transfer_code", {})
            new_tc = codes.get("transfer") if isinstance(codes, dict) else codes
            new_cc = codes.get("confirmation") if isinstance(codes, dict) else None
            backup_save(new_tc or request.transfer_code)
            return {"success": True, "new_transfer_code": new_tc,
                    "new_confirmation_code": new_cc, "log": result.get("log", [])}
        return {"success": False, "error": result.get("error", "Unknown error")}
    except Exception as e:
        return {"success": False, "error": f"เกิดข้อผิดพลาด: {e}"}

@app.post("/api/legend/clear")
async def clear_legends(request: ClearLegendsRequest):
    """เคลียร์ Legend Stages (SoL/UL/ZL) ตาม legend_types ที่ระบุ พร้อม crown level"""
    try:
        if not request.transfer_code.strip() or not request.confirmation_code.strip():
            return {"success": False, "error": "Transfer/Confirmation Code ห้ามว่าง"}
        if request.country not in COUNTRIES:
            return {"success": False, "error": f"Country ไม่ถูกต้อง: {request.country}"}
        valid_types = {"sol", "ul", "zl"}
        invalid = [t for t in request.legend_types if t not in valid_types]
        if invalid:
            return {"success": False, "error": f"legend_types ไม่ถูกต้อง: {invalid} (ต้องเป็น sol, ul, zl)"}
        if not request.legend_types:
            return {"success": False, "error": "legend_types ห้ามว่าง"}
        max_crown = max(1, min(4, request.max_crown))
        clear_amount = max(1, min(9999, request.clear_amount))
        print(f"\n[LEGEND-CLEAR] types={request.legend_types} max_crown={max_crown} x{clear_amount}")
        runner = BCSFERunner(transfer=request.transfer_code.strip(),
                             confirm=request.confirmation_code.strip(),
                             country=request.country)
        result = await run_bcsfe(runner.run_clear_legends, request.legend_types, max_crown, clear_amount)
        if result["success"]:
            codes = result.get("new_transfer_code", {})
            new_tc = codes.get("transfer") if isinstance(codes, dict) else codes
            new_cc = codes.get("confirmation") if isinstance(codes, dict) else None
            backup_save(new_tc or request.transfer_code)
            return {"success": True, "new_transfer_code": new_tc,
                    "new_confirmation_code": new_cc, "log": result.get("log", [])}
        return {"success": False, "error": result.get("error", "Unknown error")}
    except Exception as e:
        return {"success": False, "error": f"เกิดข้อผิดพลาด: {e}"}

@app.post("/api/dupe/save")
async def dupe_save(request: DupeSaveRequest):
    """Dupe save N ครั้ง"""
    try:
        if not request.transfer_code.strip() or not request.confirmation_code.strip():
            return {"success": False, "error": "Transfer/Confirmation Code ห้ามว่าง"}
        if request.country not in COUNTRIES:
            return {"success": False, "error": f"Country ไม่ถูกต้อง: {request.country}"}
        count = max(1, min(100, request.count))
        runner = BCSFERunner(transfer=request.transfer_code.strip(),
                             confirm=request.confirmation_code.strip(),
                             country=request.country)
        result = await run_bcsfe(lambda: runner.run_dupe_save(count))
        if result["success"]:
            return {"success": True, "codes": result.get("codes", []), "count": result.get("count", 0)}
        return {"success": False, "error": result.get("error", "Unknown error")}
    except Exception as e:
        return {"success": False, "error": f"เกิดข้อผิดพลาด: {e}"}
@app.post("/api/check/id")
async def check_id(request: CheckIDRequest):
    """ตรวจสอบรหัสหลายชุด — download + re-upload (ไม่แก้ไข) → ได้ TC ใหม่"""
    if request.country not in COUNTRIES:
        return {"success": False, "error": f"Country ไม่ถูกต้อง: {request.country}"}
    if not request.codes:
        return {"success": False, "error": "ไม่มีรหัสให้ตรวจ"}

    from pathlib import Path
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    from datetime import datetime as _dt
    ts = _dt.now().strftime("%Y%m%d_%H%M%S")
    batch_log_path = log_dir / f"api_log_{ts}_checkID_x{len(request.codes)}.txt"

    results = []
    with open(batch_log_path, "w", encoding="utf-8") as batch_log:
        batch_log.write("=" * 60 + "\n")
        batch_log.write(f"เวลา      : {_dt.now(TZ_THAI).strftime('%Y-%m-%d %H:%M:%S')}\n")
        batch_log.write(f"CheckID Batch: {len(request.codes)} รหัส\n")
        batch_log.write("=" * 60 + "\n\n")
        batch_log.flush()

        for i, entry in enumerate(request.codes):
            tc = entry.transfer_code.strip()
            cc = entry.confirmation_code.strip()
            batch_log.write(f"── รหัสที่ {i+1}/{len(request.codes)} ──────────────────────────\n")
            batch_log.flush()
            if not tc or not cc:
                results.append({"original_tc": tc, "valid": False, "error": "TC/CC ว่าง"})
                batch_log.write("❌ TC/CC ว่าง\n\n")
                batch_log.flush()
                continue
            runner = BCSFERunner(transfer=tc, confirm=cc, country=request.country, shared_log=batch_log)
            result = await run_bcsfe(runner.run_check_id)
            if result["success"]:
                codes = result.get("new_transfer_code", {})
                new_tc = codes.get("transfer") if isinstance(codes, dict) else codes
                new_cc = codes.get("confirmation") if isinstance(codes, dict) else None
                results.append({
                    "original_tc": tc,
                    "valid": True,
                    "new_tc": new_tc,
                    "new_cc": new_cc,
                    "inquiry_code": result.get("inquiry_code", "?"),
                })
            else:
                results.append({"original_tc": tc, "valid": False, "error": result.get("error", "ไม่ทราบสาเหตุ")})
            import asyncio; await asyncio.sleep(2)

        ok_count  = sum(1 for r in results if r["valid"])
        err_count = len(results) - ok_count
        batch_log.write("\n" + "=" * 60 + "\n")
        batch_log.write(f"สรุป: ✅ {ok_count} ใช้ได้  |  ❌ {err_count} ไม่ได้\n")

    return {"success": True, "results": results, "ok": ok_count, "error_count": err_count}

@app.post("/api/trueform/characters")
async def trueform_characters(request: UnlockCharactersRequest):
    """True Form เธ•เธฑเธงเธฅเธฐเธเธฃ"""
    try:
        if not request.transfer_code.strip() or not request.confirmation_code.strip():
            return {"success": False, "error": "Transfer/Confirmation Code เธซเนเธฒเธกเธงเนเธฒเธ"}
        if not request.cat_ids:
            return {"success": False, "error": "เธ•เนเธญเธเธฃเธฐเธเธธ cat_ids เธญเธขเนเธฒเธเธเนเธญเธข 1 เธ•เธฑเธง"}
        if request.country not in COUNTRIES:
            return {"success": False, "error": f"Country เนเธกเนเธ–เธนเธเธ•เนเธญเธ: {request.country}"}

        print(f"\n[TRUEFORM-CHARS] โจ true form {len(request.cat_ids)} เธ•เธฑเธงเธฅเธฐเธเธฃ")
        runner = BCSFERunner(transfer=request.transfer_code.strip(),
                             confirm=request.confirmation_code.strip(),
                             country=request.country)
        result = await run_bcsfe(runner.run_true_form_characters, request.cat_ids)
        if result["success"]:
            codes = result.get("new_transfer_code", {})
            new_tc = codes.get("transfer") if isinstance(codes, dict) else codes
            new_cc = codes.get("confirmation") if isinstance(codes, dict) else None
            backup_save(new_tc or request.transfer_code)
            return {"success": True, "new_transfer_code": new_tc,
                    "new_confirmation_code": new_cc, "count": len(request.cat_ids), "log": result.get("log", [])}
        return {"success": False, "error": result.get("error", "Unknown error")}
    except Exception as e:
        return {"success": False, "error": f"เน€เธเธดเธ”เธเนเธญเธเธดเธ”เธเธฅเธฒเธ”: {e}"}


@app.post("/api/ultraform/characters")
async def ultraform_characters(request: UnlockCharactersRequest):
    """Ultra Form เธ•เธฑเธงเธฅเธฐเธเธฃ (4th Form)"""
    try:
        if not request.transfer_code.strip() or not request.confirmation_code.strip():
            return {"success": False, "error": "Transfer/Confirmation Code เธซเนเธฒเธกเธงเนเธฒเธ"}
        if not request.cat_ids:
            return {"success": False, "error": "เธ•เนเธญเธเธฃเธฐเธเธธ cat_ids เธญเธขเนเธฒเธเธเนเธญเธข 1 เธ•เธฑเธง"}
        if request.country not in COUNTRIES:
            return {"success": False, "error": f"Country เนเธกเนเธ–เธนเธเธ•เนเธญเธ: {request.country}"}

        print(f"\n[ULTRAFORM-CHARS] ๐’ฅ ultra form {len(request.cat_ids)} เธ•เธฑเธงเธฅเธฐเธเธฃ")
        runner = BCSFERunner(transfer=request.transfer_code.strip(),
                             confirm=request.confirmation_code.strip(),
                             country=request.country)
        result = await run_bcsfe(runner.run_ultra_form_characters, request.cat_ids)
        if result["success"]:
            codes = result.get("new_transfer_code", {})
            new_tc = codes.get("transfer") if isinstance(codes, dict) else codes
            new_cc = codes.get("confirmation") if isinstance(codes, dict) else None
            backup_save(new_tc or request.transfer_code)
            return {"success": True, "new_transfer_code": new_tc,
                    "new_confirmation_code": new_cc, "count": len(request.cat_ids), "log": result.get("log", [])}
        return {"success": False, "error": result.get("error", "Unknown error")}
    except Exception as e:
        return {"success": False, "error": f"เน€เธเธดเธ”เธเนเธญเธเธดเธ”เธเธฅเธฒเธ”: {e}"}


@app.post("/api/talents/characters")
async def talents_characters(request: UnlockCharactersRequest):
    """Max Talents เธ•เธฑเธงเธฅเธฐเธเธฃ"""
    try:
        if not request.transfer_code.strip() or not request.confirmation_code.strip():
            return {"success": False, "error": "Transfer/Confirmation Code เธซเนเธฒเธกเธงเนเธฒเธ"}
        if not request.cat_ids:
            return {"success": False, "error": "เธ•เนเธญเธเธฃเธฐเธเธธ cat_ids เธญเธขเนเธฒเธเธเนเธญเธข 1 เธ•เธฑเธง"}
        if request.country not in COUNTRIES:
            return {"success": False, "error": f"Country เนเธกเนเธ–เธนเธเธ•เนเธญเธ: {request.country}"}

        print(f"\n[TALENTS-CHARS] ๐ talents max {len(request.cat_ids)} เธ•เธฑเธงเธฅเธฐเธเธฃ")
        runner = BCSFERunner(transfer=request.transfer_code.strip(),
                             confirm=request.confirmation_code.strip(),
                             country=request.country)
        result = await run_bcsfe(runner.run_talents_max_characters, request.cat_ids)
        if result["success"]:
            codes = result.get("new_transfer_code", {})
            new_tc = codes.get("transfer") if isinstance(codes, dict) else codes
            new_cc = codes.get("confirmation") if isinstance(codes, dict) else None
            backup_save(new_tc or request.transfer_code)
            return {"success": True, "new_transfer_code": new_tc,
                    "new_confirmation_code": new_cc, "count": len(request.cat_ids), "log": result.get("log", [])}
        return {"success": False, "error": result.get("error", "Unknown error")}
    except Exception as e:
        return {"success": False, "error": f"เน€เธเธดเธ”เธเนเธญเธเธดเธ”เธเธฅเธฒเธ”: {e}"}


# ============= Utility Routes =============

@app.get("/api/cat-image/{cat_id}")
async def cat_image(cat_id: int):
    """เน€เธชเธดเธฃเนเธเธฃเธนเธเนเธกเธงเธเธฒเธ disk cache เธซเธฃเธทเธญ fetch เธเธฒเธ wiki เนเธฅเนเธงเธเธฑเธเธ—เธถเธ"""
    cache_path = CAT_CACHE_DIR / f"{cat_id}.png"

    # disk hit โ’ เน€เธชเธดเธฃเนเธเธ—เธฑเธเธ—เธต
    if cache_path.exists():
        return FileResponse(str(cache_path), media_type="image/png",
                            headers={"Cache-Control": "public, max-age=604800"})

    data = await _fetch_cat_image(cat_id)
    if data is None:
        raise HTTPException(status_code=404, detail="เนเธกเนเธเธเธฃเธนเธเนเธกเธง")

    return Response(data, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=604800"})


@app.get("/api/cat-image/prewarm")
async def prewarm_cat_images():
    """เน€เธฃเธดเนเธก background pre-download เธฃเธนเธเธ—เธตเนเธขเธฑเธเนเธกเนเธกเธตเนเธ cache"""
    asyncio.create_task(_prewarm_all())
    cached = sum(1 for f in CAT_CACHE_DIR.glob("*.png"))
    return {"message": "เธเธณเธฅเธฑเธ pre-download เธฃเธนเธเนเธกเธงเธ—เธฑเนเธเธซเธกเธ”เนเธ background", "already_cached": cached}


async def _prewarm_all():
    missing = [i for i in range(866) if not (CAT_CACHE_DIR / f"{i}.png").exists()]
    if not missing:
        print("[CAT-IMG] โ… Cache เธเธฃเธเธ—เธธเธเธ•เธฑเธงเนเธฅเนเธง")
        return
    print(f"[CAT-IMG] ๐” Pre-warming {len(missing)} เธฃเธนเธเธ—เธตเนเธขเธฑเธเนเธกเนเธกเธต cache...")
    await asyncio.gather(*[_fetch_cat_image(i) for i in missing], return_exceptions=True)
    cached = sum(1 for f in CAT_CACHE_DIR.glob("*.png"))
    print(f"[CAT-IMG] โ… Pre-warm เน€เธชเธฃเนเธ โ€” cached {cached}/866")


@app.post("/api/payment/retry/{order_id}")
async def payment_retry(order_id: str, body: RetryRequest):
    """เธฅเธญเธเนเธซเธกเนเธ”เนเธงเธข Transfer/Confirmation Code เนเธซเธกเน เธชเธณเธซเธฃเธฑเธ order เธ—เธตเน BCSFE เธฅเนเธกเน€เธซเธฅเธง"""
    order = get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="เนเธกเนเธเธ order เธเธตเน")

    if order["status"] not in ("bcsfe_failed", "paid"):
        raise HTTPException(
            status_code=400,
            detail=f"เนเธกเนเธชเธฒเธกเธฒเธฃเธ–เธฅเธญเธเนเธซเธกเนเนเธ”เน เธชเธ–เธฒเธเธฐเธเธฑเธเธเธธเธเธฑเธ: {order['status']}"
        )

    update_order_status(order_id, "retrying", {
        "transfer_code":     body.transfer_code,
        "confirmation_code": body.confirmation_code,
    })

    try:
        # เนเธเน code เนเธซเธกเนเธเธฒเธ retry form
        step_result = await run_bcsfe(_run_bcsfe_steps, order, body.transfer_code, body.confirmation_code)

        if not step_result["success"]:
            update_order_status(order_id, "bcsfe_failed", {"error": step_result["error"]})
            raise HTTPException(status_code=500, detail=step_result["error"])

        new_tc, new_cc = step_result["new_tc"], step_result["new_cc"]
        backup_save(new_tc or body.transfer_code)
        update_order_status(order_id, "done", {
            "new_transfer_code":     new_tc,
            "new_confirmation_code": new_cc,
            "done_at":               datetime.now().isoformat(),
        })
        return {"success": True, "new_transfer_code": new_tc, "new_confirmation_code": new_cc,
                "summary": step_result["summary"]}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"เน€เธเธดเธ”เธเนเธญเธเธดเธ”เธเธฅเธฒเธ”: {e}")


@app.get("/health")
def health_check():
    """เธ•เธฃเธงเธเธชเธญเธเธชเธธเธเธ เธฒเธ server"""
    return {"status": "ok"}

@app.get("/")
def root():
    return FileResponse("index.html")

@app.get("/{page}.html")
def serve_html(page: str):
    path = f"{page}.html"
    if Path(path).exists():
        return FileResponse(path)
    raise HTTPException(status_code=404, detail="Not found")

# Static files (CSS, JS, images) โ€” เธ•เนเธญเธ mount เธซเธฅเธฑเธ API routes
app.mount("/assets", StaticFiles(directory=str(_BASE_DIR / "assets")), name="assets")
app.mount("/pictures", StaticFiles(directory=str(_BASE_DIR / "pictures")), name="pictures")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse("favicon.ico", media_type="image/x-icon")

# โ”€โ”€ serve HTML pages เธเนเธฒเธ http:// เน€เธเธทเนเธญเธซเธฅเธตเธเน€เธฅเธตเนเธขเธ file:// security errors โ”€โ”€
_HTML_PAGES = ["index","shop","characters","stages","orders","admin","login",
                "orders_manager","test_no_payment","shop-codes"]

@app.get("/{page}.html")
async def serve_html(page: str):
    if page not in _HTML_PAGES:
        raise HTTPException(status_code=404)
    return FileResponse(f"{page}.html", media_type="text/html")

@app.on_event("startup")
async def startup_prewarm():
    cached = sum(1 for _ in CAT_CACHE_DIR.glob("*.png"))
    print(f"[CAT-IMG] cache เธกเธตเธญเธขเธนเนเนเธฅเนเธง {cached}/861 เธฃเธนเธ")
    if cached < 861:
        asyncio.create_task(_prewarm_all())


# ============= Main =============

# ══════════════════════════════════════════
# CODE SHOP ROUTES
# ══════════════════════════════════════════

@app.get("/api/code-shop/products")
def api_code_shop_products():
    return {"products": get_code_products()}


@app.post("/api/code-shop/buy")
async def api_code_shop_buy(body: CodeShopBuyRequest):
    if not verify_loyalty_session(body.username, body.session_token):
        raise HTTPException(status_code=401, detail="กรุณาเข้าสู่ระบบก่อนซื้อ")

    product = get_code_product(body.product_id)
    if not product or not product.get("is_active"):
        raise HTTPException(status_code=404, detail="ไม่พบสินค้า")

    stock = get_available_stock(body.product_id)
    if not stock:
        raise HTTPException(status_code=400, detail="สินค้าหมดสต๊อกแล้ว")

    order = create_code_shop_order(body.product_id, stock["id"], body.username, product["price"],
                                   body.payment_method)

    if not reserve_stock(stock["id"], body.username, order["order_id"]):
        update_order_status(order["order_id"], "cancelled")
        raise HTTPException(status_code=400, detail="สินค้าถูกจองโดยคนอื่นพอดี กรุณาลองใหม่")

    resp = {
        "order_id":      order["order_id"],
        "amount":        order["amount"],
        "base_amount":   order["base_amount"],
        "truemoney_fee": order.get("truemoney_fee", 0),
        "qr_base64":     order.get("qr_base64"),
        "expires_at":    order["expires_at"],
        "payment_method": order["payment_method"],
    }
    if order["payment_method"] == "truemoney":
        resp["truemoney_id"] = TRUEMONEY_ID
    return resp


@app.post("/api/code-shop/cancel/{order_id}")
def api_code_shop_cancel(order_id: str, username: str = Query(None)):
    order = get_order(order_id)
    if not order:
        return {"success": True}
    if order.get("order_type") != "code_shop":
        return {"success": True}
    if order.get("status") in ("done", "cancelled", "expired"):
        return {"success": True}
    stock_id = order.get("stock_id", "")
    if stock_id:
        release_stock(stock_id)
    update_order_status(order_id, "cancelled")
    print(f"[CODE-SHOP] ❌ order {order_id} ยกเลิกโดย {username}")
    return {"success": True}


@app.post("/api/code-shop/verify/{order_id}")
async def api_code_shop_verify(order_id: str, slip: UploadFile = File(...)):
    order = get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="ไม่พบ order นี้")
    if order.get("order_type") != "code_shop":
        raise HTTPException(status_code=400, detail="order type ไม่ถูกต้อง")

    stock_id = order.get("stock_id", "")

    if is_order_expired(order):
        if stock_id:
            release_stock(stock_id)
        update_order_status(order_id, "expired")
        raise HTTPException(status_code=400, detail="order หมดอายุแล้ว กรุณาซื้อใหม่")

    if order["status"] == "done":
        raise HTTPException(status_code=400, detail="order นี้ดำเนินการแล้ว")

    slip_bytes = await slip.read()
    slip_result = await verify_slip(slip_bytes, order_id)
    if not slip_result["success"]:
        raise HTTPException(status_code=400, detail=slip_result["reason"])

    transaction_id = slip_result.get("transaction_id", "")

    stock = get_stock_by_order(order_id)
    if not stock:
        raise HTTPException(status_code=500, detail="ไม่พบรหัสที่จอง กรุณาติดต่อ admin")

    mark_stock_sold(stock_id)
    mark_slip_used(transaction_id)
    update_order_status(order_id, "done", {
        "done_at":        datetime.now().isoformat(),
        "transaction_id": transaction_id,
    })

    print(f"[CODE-SHOP] ✅ order {order_id} ส่งรหัสให้ {order.get('username')}")
    return {
        "success":           True,
        "transfer_code":     stock["transfer_code"],
        "confirmation_code": stock["confirmation_code"],
    }


@app.post("/api/code-shop/verify-voucher/{order_id}")
async def api_code_shop_verify_voucher(order_id: str, body: VoucherRedeemRequest):
    """verify TrueWallet ซองอั่งเป่า สำหรับ code shop"""
    order = get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="ไม่พบ order นี้")
    if order.get("order_type") != "code_shop":
        raise HTTPException(status_code=400, detail="order type ไม่ถูกต้อง")
    if order.get("payment_method") != "truemoney":
        raise HTTPException(status_code=400, detail="order นี้ไม่ใช่ TrueWallet")

    stock_id = order.get("stock_id", "")

    if is_order_expired(order):
        if stock_id:
            release_stock(stock_id)
        update_order_status(order_id, "expired")
        raise HTTPException(status_code=400, detail="order หมดอายุแล้ว กรุณาซื้อใหม่")

    if order["status"] == "done":
        raise HTTPException(status_code=400, detail="order นี้ดำเนินการแล้ว")

    voucher_result = await redeem_truemoney_voucher(body.voucher_code, order_id)
    if not voucher_result["success"]:
        raise HTTPException(status_code=400, detail=voucher_result["reason"])

    transaction_id = voucher_result.get("transaction_id", "")

    # บันทึกก่อนว่าเงินเข้าแล้ว เผื่อ step ถัดไปพัง admin จะได้รู้
    update_order_status(order_id, "paid", {
        "transaction_id": transaction_id,
        "paid_at":        datetime.now().isoformat(),
    })
    print(f"[CODE-SHOP] 💰 TrueWallet paid order {order_id} txn={transaction_id}")

    stock = get_stock_by_order(order_id)
    if not stock:
        print(f"[CODE-SHOP] ❌ ไม่พบ stock สำหรับ order {order_id} — เงินเข้าแล้ว txn={transaction_id}")
        raise HTTPException(status_code=500, detail="ระบบมีปัญหา กรุณาติดต่อ admin พร้อมแจ้ง Order ID")

    mark_stock_sold(stock_id)
    update_order_status(order_id, "done", {
        "done_at":        datetime.now().isoformat(),
        "transaction_id": transaction_id,
    })

    print(f"[CODE-SHOP] ✅ TrueWallet order {order_id} ส่งรหัสให้ {order.get('username')}")
    return {
        "success":           True,
        "transfer_code":     stock["transfer_code"],
        "confirmation_code": stock["confirmation_code"],
    }


@app.get("/api/code-shop/my-purchases")
def api_my_purchases(username: str, session_token: str):
    if not verify_loyalty_session(username, session_token):
        raise HTTPException(status_code=401, detail="กรุณาเข้าสู่ระบบก่อน")
    purchases = get_user_code_purchases(username)
    return {"purchases": purchases}


# ── Admin routes ──

@app.get("/api/admin/code-shop/products")
def api_admin_products(username: str, session_token: str):
    if not verify_admin_session(username, session_token):
        raise HTTPException(status_code=403, detail="ไม่มีสิทธิ์ admin")
    return {"products": get_all_code_products()}


@app.post("/api/admin/code-shop/products")
def api_admin_add_product(body: AdminProductRequest):
    if not verify_admin_session(body.username, body.session_token):
        raise HTTPException(status_code=403, detail="ไม่มีสิทธิ์ admin")
    product = add_code_product(body.name, body.description, body.images, body.price,
                                body.name_en, body.description_en)
    if not product:
        raise HTTPException(status_code=500, detail="เพิ่มสินค้าไม่ได้")
    return {"success": True, "product": product}


@app.patch("/api/admin/code-shop/products/{product_id}")
def api_admin_toggle_product(product_id: str, body: AdminToggleRequest):
    if not verify_admin_session(body.username, body.session_token):
        raise HTTPException(status_code=403, detail="ไม่มีสิทธิ์ admin")
    toggle_code_product(product_id, body.is_active)
    return {"success": True}


@app.put("/api/admin/code-shop/products/{product_id}")
def api_admin_edit_product(product_id: str, body: AdminEditProductRequest):
    if not verify_admin_session(body.username, body.session_token):
        raise HTTPException(status_code=403, detail="ไม่มีสิทธิ์ admin")
    ok = update_code_product(product_id, body.name, body.description, body.price,
                              body.name_en, body.description_en)
    if not ok:
        raise HTTPException(status_code=500, detail="แก้ไขสินค้าไม่ได้")
    return {"success": True}


@app.delete("/api/admin/code-shop/products/{product_id}")
def api_admin_delete_product(product_id: str, username: str, session_token: str):
    if not verify_admin_session(username, session_token):
        raise HTTPException(status_code=403, detail="ไม่มีสิทธิ์ admin")
    delete_code_product(product_id)
    return {"success": True}


@app.get("/api/admin/code-shop/products/{product_id}/stock")
def api_admin_get_stock(product_id: str, username: str, session_token: str):
    if not verify_admin_session(username, session_token):
        raise HTTPException(status_code=403, detail="ไม่มีสิทธิ์ admin")
    return {"stock": get_product_stock(product_id)}


@app.post("/api/admin/code-shop/stock")
def api_admin_add_stock(body: AdminStockRequest):
    if not verify_admin_session(body.username, body.session_token):
        raise HTTPException(status_code=403, detail="ไม่มีสิทธิ์ admin")
    item = add_code_stock(body.product_id, body.transfer_code, body.confirmation_code, body.inquiry_code)
    if not item:
        raise HTTPException(status_code=500, detail="เพิ่ม stock ไม่ได้")
    return {"success": True, "stock": item}


@app.delete("/api/admin/code-shop/stock/{stock_id}")
def api_admin_delete_stock(stock_id: str, username: str, session_token: str):
    if not verify_admin_session(username, session_token):
        raise HTTPException(status_code=403, detail="ไม่มีสิทธิ์ admin")
    delete_code_stock(stock_id)
    return {"success": True}


@app.get("/api/admin/code-shop/images")
def api_admin_list_images(username: str, session_token: str):
    if not verify_admin_session(username, session_token):
        raise HTTPException(status_code=403, detail="ไม่มีสิทธิ์ admin")
    folder = _BASE_DIR / "pictures" / "codeshop"
    if not folder.exists():
        return {"images": []}
    try:
        exts = {".png", ".jpg", ".jpeg", ".webp"}
        names = []
        for f in folder.iterdir():
            try:
                name = f.name
                if Path(name).suffix.lower() in exts:
                    names.append(name)
            except Exception:
                pass
        return {"images": sorted(names)}
    except Exception:
        return {"images": []}


@app.get("/sitemap.xml")
def sitemap():
    from fastapi.responses import Response
    content = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://battlecatpromax.cloud/</loc></url>
  <url><loc>https://battlecatpromax.cloud/static/shop.html</loc></url>
  <url><loc>https://battlecatpromax.cloud/static/index.html</loc></url>
  <url><loc>https://battlecatpromax.cloud/static/characters.html</loc></url>
  <url><loc>https://battlecatpromax.cloud/static/stages.html</loc></url>
</urlset>"""
    return Response(content, media_type="application/xml")

if __name__ == "__main__":
    import uvicorn
    print("๐€ BCSFE Order System เน€เธฃเธดเนเธกเธ•เนเธ...")
    print("๐“ เน€เธเธดเธ”เธซเธเนเธฒเน€เธงเนเธ: http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)




