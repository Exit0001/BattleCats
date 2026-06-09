# main.py - FastAPI server เธชเธณเธซเธฃเธฑเธ BCSFE order system
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')


from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
import os
import httpx
import asyncio
import shutil
from pathlib import Path
from datetime import datetime
from models import OrderRequest, OrderResponse, ItemSummary, ItemRequest, TestBCSFERequest, UnlockCharactersRequest, RetryRequest, UnlockPaymentRequest, AllCatsRequest, VoucherRedeemRequest, DupeSaveRequest, CheckIDRequest
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
)

ALL_PACKAGE_MAP = {
    "upgrade_all":   {"label": "Upgrade Max All",  "price": 200, "runner": "run_upgrade_all_characters"},
    "unlock_all":    {"label": "Unlock All",        "price": 200, "runner": "run_unlock_all"},
    "trueform_all":  {"label": "True Form All",     "price": 100, "runner": "run_true_form_all"},
    "ultraform_all": {"label": "Ultra Form All",    "price": 100, "runner": "run_ultra_form_all"},
    "talents_all":   {"label": "Max Talents All",   "price": 150, "runner": "run_talents_max_all"},
}

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


async def run_bcsfe(fn, *args, **kwargs):
    """เธฃเธฑเธ BCSFE operation เธ เธฒเธขเนเธ•เน lock โ€” เธเนเธญเธเธเธฑเธ concurrent SAVE_DATA conflict"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: fn(*args, **kwargs))

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============= API Routes =============

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
        if item.key not in ITEM_MAP:
            raise HTTPException(status_code=400, detail=f"เนเธกเนเธฃเธนเนเธเธฑเธ item: {item.key}")
        if item.amount <= 0:
            raise HTTPException(status_code=400, detail=f"เธเธณเธเธงเธ {item.key} เธ•เนเธญเธเธกเธฒเธเธเธงเนเธฒ 0")
        if item.amount > ITEM_MAP[item.key]["max"]:
            raise HTTPException(status_code=400, detail=f"{ITEM_MAP[item.key]['label']} เน€เธเธดเธเธเธณเธเธงเธเธชเธนเธเธชเธธเธ” ({ITEM_MAP[item.key]['max']})")

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
        cat_unlock_total=order.cat_unlock_total,
        payment_method=order.payment_method,
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

    return {"success": True, "new_tc": cur_tc, "new_cc": cur_cc, "summary": summary}


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
    if order["status"] == "done":
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
        batch_log.write(f"เวลา      : {_dt.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
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
    missing = [i for i in range(861) if not (CAT_CACHE_DIR / f"{i}.png").exists()]
    if not missing:
        print("[CAT-IMG] โ… Cache เธเธฃเธเธ—เธธเธเธ•เธฑเธงเนเธฅเนเธง")
        return
    print(f"[CAT-IMG] ๐” Pre-warming {len(missing)} เธฃเธนเธเธ—เธตเนเธขเธฑเธเนเธกเนเธกเธต cache...")
    await asyncio.gather(*[_fetch_cat_image(i) for i in missing], return_exceptions=True)
    cached = sum(1 for f in CAT_CACHE_DIR.glob("*.png"))
    print(f"[CAT-IMG] โ… Pre-warm เน€เธชเธฃเนเธ โ€” cached {cached}/861")


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
app.mount("/assets", StaticFiles(directory="assets"), name="assets")
app.mount("/pictures", StaticFiles(directory="pictures"), name="pictures")

@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse("favicon.ico", media_type="image/x-icon")

# โ”€โ”€ serve HTML pages เธเนเธฒเธ http:// เน€เธเธทเนเธญเธซเธฅเธตเธเน€เธฅเธตเนเธขเธ file:// security errors โ”€โ”€
_HTML_PAGES = ["index","shop","characters","stages","orders","admin","login",
                "orders_manager","test_no_payment"]

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




