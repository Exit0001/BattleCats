# payment.py - ระบบ QR PromptPay + เช็คสลิปด้วย EasySlip API

import qrcode
import qrcode.image.svg
import io
import base64
import json
import math
import re
import uuid
import httpx
from curl_cffi.requests import AsyncSession as CurlSession
from datetime import datetime, timedelta, timezone

TZ_THAI = timezone(timedelta(hours=7))
from pathlib import Path

# ══════════════════════════════════════════
# CONFIG — แก้ค่าตรงนี้
# ══════════════════════════════════════════

PROMPTPAY_ID   = "0634515901"            # เบอร์ / เลขบัตรปชช ที่รับเงิน
TRUEMONEY_ID   = "0634515901"       # TrueMoney Wallet phone number (แก้ถ้าต่างกัน)
EASYSLIP_API_KEY = "1c49e3f0-85f9-4718-b3f6-de74ec35fe30"  # API Key จาก easyslip.com
ORDER_DB       = Path("orders.json")
SLIP_DB        = Path("used_slips.json")
USER_ORDERS_DB = Path("user_orders.json")
ORDER_TIMEOUT  = 15  # นาที หมดอายุ

SUPABASE_URL = "https://jpzceuxeelnwthaitkcw.supabase.co"
SUPABASE_KEY = "sb_publishable_VhQvIEjYgaDy0eW1qaIkyw_cxb5eZly"

# ══════════════════════════════════════════
# PRICE MAP — ราคาต่อ item ตามแพ็กเกจ
# ══════════════════════════════════════════

ITEM_PRICE = {
    "cat_food": {
        10000: 10,
        20000: 19,
        30000: 25,
        45000: 35,
    },
    "xp": {
        99999999: 25,
    },
    "normal_ticket": {
        100: 10,
        500: 45,
        1000: 85,
        2999: 239,
    },
    "rare_ticket": {
        50: 15,
        100: 29,
        200: 50,
        299: 70,
    },
    "np": {
        100: 5,
        1000: 49,
        5000: 239,
        9999: 449,
    },
    "platinum_shard": {
        10: 30,
        30: 83,
        60: 160,
        99: 250,
    },
    "leadership": {
        100: 20,
        1000: 185,
        5000: 869,
        9999: 1639,
    },
    "catseye": {
        100: 20,
        500: 87,
        5000: 799,
        9999: 1559,
    },
    "catfruit": {
        100: 30,
        300: 85,
        500: 139,
        998: 269,
    },
    "battle_item": {
        100: 10,
        500: 43,
        5000: 399,
        9999: 769,
    },
    "catamins": {
        100: 20,
        500: 87,
        5000: 799,
        9999: 1559,
    },
    "legend_ticket": {
        1: 40,
        2: 74,
        3: 102,
        4: 125,
    },
    "lucky_ticket": {
        100: 10,
        500: 45,
        1000: 85,
        2999: 239,
    },
    # Per-cat services (price per 1 cat)
    "upgrade_cat":   {1: 15},
    "trueform_cat":  {1: 15},
    "ultraform_cat": {1: 20},
    "talents_cat":   {1: 20},
    # All-character packages — ราคาอยู่ใน ALL_PACKAGE_MAP ใน main.py แล้ว ห้ามซ้ำตรงนี้
}

# ══════════════════════════════════════════
# ORDER DB HELPERS
# ══════════════════════════════════════════

def _load_orders() -> dict:
    if ORDER_DB.exists():
        return json.loads(ORDER_DB.read_text(encoding="utf-8"))
    return {}

def _save_orders(data: dict):
    ORDER_DB.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def _add_user_order(username: str, order_id: str):
    if not username:
        return
    try:
        data = json.loads(USER_ORDERS_DB.read_text(encoding="utf-8")) if USER_ORDERS_DB.exists() else {}
        ids = data.get(username, [])
        if order_id not in ids:
            ids.insert(0, order_id)
        data[username] = ids[:50]
        USER_ORDERS_DB.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[USER_ORDERS] ⚠ {e}")

def _load_slips() -> list:
    if SLIP_DB.exists():
        return json.loads(SLIP_DB.read_text(encoding="utf-8"))
    return []

def _save_slips(data: list):
    SLIP_DB.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _supabase_upsert(order: dict):
    """Sync order to Supabase orders table (fail silently — local JSON is source of truth)"""
    try:
        payload = {k: v for k, v in order.items() if k != "qr_base64"}
        with httpx.Client(timeout=8) as client:
            resp = client.post(
                f"{SUPABASE_URL}/rest/v1/orders",
                headers={
                    "apikey": SUPABASE_KEY,
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                    "Content-Type": "application/json",
                    "Prefer": "resolution=merge-duplicates",
                },
                json=[payload],
            )
        if resp.status_code not in (200, 201):
            print(f"[SUPABASE] ⚠ upsert failed {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        print(f"[SUPABASE] ⚠ sync error: {e}")

# ══════════════════════════════════════════
# QR GENERATOR
# ══════════════════════════════════════════

def _promptpay_payload(phone: str, amount: float) -> str:
    """สร้าง PromptPay QR payload string ตามมาตรฐาน EMVCo"""
    phone = phone.replace("-", "").replace(" ", "")
    if phone.startswith("0"):
        phone = "66" + phone[1:]
    phone_padded = phone.zfill(13)

    def tlv(tag: str, value: str) -> str:
        return f"{tag}{len(value):02d}{value}"

    merchant_info = tlv("00", "A000000677010111") + tlv("01", phone_padded)
    amount_str = f"{amount:.2f}"

    payload = (
        tlv("00", "01") +
        tlv("01", "12") +
        tlv("29", merchant_info) +
        "5303764" +
        tlv("54", amount_str) +
        "5802TH"
    )

    # CRC-16 CCITT
    crc = 0xFFFF
    payload_with_tag = payload + "6304"
    for ch in payload_with_tag:
        crc ^= ord(ch) << 8
        for _ in range(8):
            crc = (crc << 1) ^ 0x1021 if crc & 0x8000 else crc << 1
        crc &= 0xFFFF

    return payload_with_tag + f"{crc:04X}"


def generate_qr_base64(amount: float) -> str:
    """
    สร้าง QR code PromptPay และคืนเป็น base64 PNG
    ใช้แสดงบนหน้าเว็บได้เลยด้วย <img src="data:image/png;base64,...">
    """
    payload = _promptpay_payload(PROMPTPAY_ID, amount)
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=2,
    )
    qr.add_data(payload.encode("utf-8"))  # force byte mode (PromptPay requires it)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()

# ══════════════════════════════════════════
# ORDER MANAGEMENT
# ══════════════════════════════════════════

def truemoney_fee(base_amount: int) -> int:
    """ค่าธรรมเนียม TrueWallet 2.9% สูงสุด 20 บาท (ปัดขึ้น)"""
    return min(math.ceil(base_amount * 0.029), 20)


def calculate_total(items: list[dict]) -> int:
    """
    คำนวณราคารวมจาก items
    items = [{"key": "cat_food", "amount": 10000}, ...]
    คืนราคาเป็น int (บาท)
    """
    total = 0
    for item in items:
        key = item["key"]
        amount = item.get("amount")
        price_table = ITEM_PRICE.get(key)
        if price_table is None:
            continue  # all-package items ข้าม (ราคาถูกรวมไว้ใน cat_unlock_total แล้ว)
        price = price_table.get(amount)
        if price is None:
            raise ValueError(f"ไม่พบราคาสำหรับ {key} จำนวน {amount}")
        total += price
    return total


def create_order(transfer_code: str, confirmation_code: str,
                 country: str, items: list[dict],
                 cat_ids: list | None = None,
                 cat_unlock_total: int = 0,
                 payment_method: str = "promptpay",
                 username: str | None = None) -> dict:
    """
    สร้าง order ใหม่ บันทึกลง DB และสร้าง QR
    คืน order object ที่มี order_id, amount, qr_base64
    """
    order_id    = str(uuid.uuid4())[:8].upper()
    base_amount = calculate_total(items) + cat_unlock_total
    fee         = truemoney_fee(base_amount) if payment_method == "truemoney" else 0
    amount      = base_amount + fee
    expires     = (datetime.now(TZ_THAI) + timedelta(minutes=ORDER_TIMEOUT)).isoformat()

    order = {
        "order_id":          order_id,
        "transfer_code":     transfer_code,
        "confirmation_code": confirmation_code,
        "country":           country,
        "items":             items,
        "cat_ids":           cat_ids or [],
        "base_amount":       base_amount,
        "truemoney_fee":     fee,
        "amount":            amount,
        "payment_method":    payment_method,
        "status":            "pending",
        "created_at":        datetime.now(TZ_THAI).isoformat(),
        "expires_at":        expires,
        "qr_base64":         generate_qr_base64(amount) if payment_method == "promptpay" else None,
        "username":          username or "",
    }

    orders = _load_orders()
    orders[order_id] = order
    _save_orders(orders)
    _supabase_upsert(order)
    _add_user_order(username or "", order_id)

    print(f"[ORDER] สร้าง order {order_id} ยอด {amount} บาท หมดอายุ {expires}")
    return order


def create_all_package_order(transfer_code: str, confirmation_code: str,
                             country: str, package_type: str, amount: int,
                             payment_method: str = "promptpay") -> dict:
    """สร้าง order สำหรับแพ็กเกจ All (unlock_all, trueform_all, ฯลฯ)"""
    order_id    = str(uuid.uuid4())[:8].upper()
    fee         = truemoney_fee(amount) if payment_method == "truemoney" else 0
    total       = amount + fee
    expires     = (datetime.now(TZ_THAI) + timedelta(minutes=ORDER_TIMEOUT)).isoformat()
    order = {
        "order_id":          order_id,
        "transfer_code":     transfer_code,
        "confirmation_code": confirmation_code,
        "country":           country,
        "items":             [],
        "cat_ids":           [],
        "package_type":      package_type,
        "base_amount":       amount,
        "truemoney_fee":     fee,
        "amount":            total,
        "payment_method":    payment_method,
        "status":            "pending",
        "created_at":        datetime.now(TZ_THAI).isoformat(),
        "expires_at":        expires,
        "qr_base64":         generate_qr_base64(amount) if payment_method == "promptpay" else None,
    }
    orders = _load_orders()
    orders[order_id] = order
    _save_orders(orders)
    _supabase_upsert(order)
    print(f"[ORDER] สร้าง all-package order {order_id} type={package_type} ยอด {amount} บาท")
    return order


def get_order(order_id: str) -> dict | None:
    """ดึง order จาก DB"""
    orders = _load_orders()
    return orders.get(order_id)


def update_order_status(order_id: str, status: str, extra: dict = {}):
    """อัปเดต status ของ order"""
    orders = _load_orders()
    if order_id in orders:
        orders[order_id]["status"] = status
        orders[order_id].update(extra)
        _save_orders(orders)
        _supabase_upsert(orders[order_id])


def is_order_expired(order: dict) -> bool:
    """เช็คว่า order หมดอายุแล้วหรือยัง"""
    expires = datetime.fromisoformat(order["expires_at"])
    return datetime.now(TZ_THAI) > expires

# ══════════════════════════════════════════
# EASYSLIP VERIFICATION
# ══════════════════════════════════════════

async def verify_slip(slip_image_bytes: bytes, order_id: str) -> dict:
    """
    ส่งสลิปไปเช็คกับ EasySlip API
    คืน {"success": True/False, "reason": "..."}
    """
    order = get_order(order_id)
    if not order:
        return {"success": False, "reason": "ไม่พบ order นี้"}

    if is_order_expired(order):
        update_order_status(order_id, "expired")
        return {"success": False, "reason": "order หมดอายุแล้ว กรุณาสั่งใหม่"}

    if order["status"] == "paid":
        return {"success": False, "reason": "order นี้ชำระแล้ว"}

    # ── ส่งสลิปไป EasySlip ──
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.easyslip.com/v2/verify/bank",
                headers={"Authorization": f"Bearer {EASYSLIP_API_KEY}"},
                files={"image": ("slip.jpg", slip_image_bytes, "image/jpeg")},
            )
        data = resp.json()
        print(f"[EASYSLIP] response: {json.dumps(data, ensure_ascii=False)}")
    except Exception as e:
        return {"success": False, "reason": f"เช็คสลิปไม่ได้: {e}"}

    # ── ตรวจผลลัพธ์ ──
    if not data.get("success"):
        msg = data.get("message") or "สลิปไม่ถูกต้อง"
        error_map = {
            "IMAGE_SIZE_TOO_LARGE": "ไฟล์สลิปใหญ่เกิน 4MB กรุณาบีบอัดรูปแล้วส่งใหม่",
            "INVALID_IMAGE_FORMAT": "รูปแบบไฟล์ไม่รองรับ กรุณาส่งเป็น JPG หรือ PNG",
            "SLIP_NOT_FOUND":       "ไม่พบ QR Code ในสลิป กรุณาส่งรูปให้ชัดขึ้น",
            "SLIP_PENDING":         "สลิปยังประมวลผลไม่เสร็จ กรุณารอสักครู่แล้วส่งใหม่",
        }
        friendly = error_map.get(msg, f"EasySlip: {msg}")
        return {"success": False, "reason": friendly}

    slip_data = data.get("data", {})

    # 1) เช็คยอดตรง (อนุญาต ±0 บาท)
    raw_slip = slip_data.get("rawSlip", {})
    received = float(raw_slip.get("amount", {}).get("amount", 0))
    expected = float(order["amount"])
    if abs(received - expected) > 0.01:
        return {"success": False, "reason": f"ยอดไม่ตรง คาดหวัง {expected:.2f} แต่ได้ {received:.2f} บาท"}

    # 2) เช็คสลิปซ้ำ
    transaction_id = raw_slip.get("transRef", "")
    used_slips = _load_slips()
    if transaction_id and transaction_id in used_slips:
        return {"success": False, "reason": "สลิปนี้ถูกใช้ไปแล้ว"}

    # 3) เช็ค isDuplicate จาก EasySlip
    if slip_data.get("isDuplicate"):
        return {"success": False, "reason": "สลิปนี้ถูกใช้ไปแล้ว (duplicate detected)"}

    # ── อัปเดต order เป็น paid (ยังไม่บันทึกสลิป รอให้ BCSFE สำเร็จก่อน) ──
    update_order_status(order_id, "paid", {
        "paid_at":        datetime.now(TZ_THAI).isoformat(),
        "transaction_id": transaction_id,
        "received":       received,
    })

    print(f"[EASYSLIP] ✅ order {order_id} ชำระแล้ว {received} บาท")
    return {"success": True, "reason": "ชำระเงินสำเร็จ", "transaction_id": transaction_id}

# ══════════════════════════════════════════
# TRUEMONEY ANGPAO (ซองอั่งเป่า) — verify ผ่าน redeem API ตรง
# ══════════════════════════════════════════

_ANGPAO_ERROR_MESSAGES = {
    "VOUCHER_EXPIRED":        "ซองอั่งเป่านี้หมดอายุแล้ว",
    "VOUCHER_NOT_FOUND":      "ไม่พบซองอั่งเป่านี้ ตรวจสอบโค้ด/ลิงก์อีกครั้ง",
    "VOUCHER_OUT_OF_STOCK":   "ซองอั่งเป่านี้ถูกใช้ไปแล้ว",
    "TARGET_USER_REDEEMED":   "ซองอั่งเป่านี้ถูกใช้ไปแล้ว",
    "CANNOT_GET_OWN_VOUCHER": "ไม่สามารถใช้ซองอั่งเป่าของตัวเองได้",
}


def _extract_voucher_hash(code_or_link: str) -> str:
    """ดึง voucher hash จาก angpao link (gift.truemoney.com/campaign/?v=xxxx) หรือโค้ดตรงๆ"""
    code_or_link = code_or_link.strip()
    m = re.search(r"[?&]v=([a-zA-Z0-9]+)", code_or_link)
    if m:
        return m.group(1)
    return code_or_link


async def redeem_truemoney_voucher(voucher_code: str, order_id: str) -> dict:
    """
    Redeem ซองอั่งเป่า TrueMoney เข้า wallet เรา แล้วเช็คยอดกับ order
    คืน {"success": True/False, "reason": "...", "transaction_id": "..."}
    """
    order = get_order(order_id)
    if not order:
        return {"success": False, "reason": "ไม่พบ order นี้"}

    if is_order_expired(order):
        update_order_status(order_id, "expired")
        return {"success": False, "reason": "order หมดอายุแล้ว กรุณาสั่งใหม่"}

    if order["status"] == "paid":
        return {"success": False, "reason": "order นี้ชำระแล้ว"}

    voucher_hash = _extract_voucher_hash(voucher_code)
    print(f"[ANGPAO] voucher_code={repr(voucher_code)} → hash={repr(voucher_hash)}")
    if not voucher_hash:
        return {"success": False, "reason": "กรุณากรอกโค้ด/ลิงก์ซองอั่งเป่า"}

    used_slips = _load_slips()
    if voucher_hash in used_slips:
        return {"success": False, "reason": "ซองอั่งเป่านี้ถูกใช้ไปแล้ว"}

    mobile = TRUEMONEY_ID.replace("-", "").replace(" ", "")
    print(f"[ANGPAO] calling redeem: hash={voucher_hash} mobile={mobile}")

    try:
        async with CurlSession(impersonate="chrome124") as client:
            resp = await client.post(
                f"https://gift.truemoney.com/campaign/vouchers/{voucher_hash}/redeem",
                json={"mobile": mobile, "voucher_hash": voucher_hash},
                headers={
                    "Content-Type": "application/json",
                    "Origin": "https://gift.truemoney.com",
                    "Referer": f"https://gift.truemoney.com/campaign/?v={voucher_hash}",
                },
            )
        print(f"[ANGPAO] status={resp.status_code} body={resp.text[:500]}")
        data = resp.json()
        print(f"[ANGPAO] response: {json.dumps(data, ensure_ascii=False)}")
    except Exception as e:
        return {"success": False, "reason": f"เช็คซองอั่งเป่าไม่ได้: {e}"}

    status_obj = data.get("status") or {}
    code = data.get("code") or status_obj.get("code") or ("SUCCESS" if data.get("success") else "")

    if code != "SUCCESS":
        msg = _ANGPAO_ERROR_MESSAGES.get(code) or data.get("message") or status_obj.get("message") or "ซองอั่งเป่าไม่ถูกต้อง"
        return {"success": False, "reason": msg}

    voucher_data = data.get("data") or {}
    voucher = voucher_data.get("my_ticket") or voucher_data.get("voucher") or {}
    amount_baht = voucher.get("amount_baht")
    if amount_baht is not None:
        received = float(amount_baht)
    else:
        received = float(data.get("amount", 0)) / 100  # satang → บาท

    expected = float(order["amount"])
    if abs(received - expected) > 0.01:
        return {"success": False, "reason": f"ยอดไม่ตรง คาดหวัง {expected:.2f} แต่ได้ {received:.2f} บาท"}

    update_order_status(order_id, "paid", {
        "paid_at":        datetime.now(TZ_THAI).isoformat(),
        "transaction_id": voucher_hash,
        "received":       received,
    })

    print(f"[ANGPAO] ✅ order {order_id} ชำระแล้ว {received} บาท")
    return {"success": True, "reason": "ชำระเงินสำเร็จ", "transaction_id": voucher_hash}


def create_unlock_order(transfer_code: str, confirmation_code: str,
                        country: str, cat_ids: list, amount: int,
                        payment_method: str = "promptpay") -> dict:
    """สร้าง order สำหรับปลดล็อคแมว พร้อม QR PromptPay"""
    order_id    = str(uuid.uuid4())[:8].upper()
    fee         = truemoney_fee(amount) if payment_method == "truemoney" else 0
    total       = amount + fee
    expires     = (datetime.now(TZ_THAI) + timedelta(minutes=ORDER_TIMEOUT)).isoformat()
    order = {
        "order_id":          order_id,
        "order_type":        "unlock",
        "transfer_code":     transfer_code,
        "confirmation_code": confirmation_code,
        "country":           country,
        "cat_ids":           cat_ids,
        "items":             [],
        "base_amount":       amount,
        "truemoney_fee":     fee,
        "amount":            total,
        "payment_method":    payment_method,
        "status":            "pending",
        "created_at":        datetime.now(TZ_THAI).isoformat(),
        "expires_at":        expires,
        "qr_base64":         generate_qr_base64(amount) if payment_method == "promptpay" else None,
    }
    orders = _load_orders()
    orders[order_id] = order
    _save_orders(orders)
    _supabase_upsert(order)
    print(f"[UNLOCK-ORDER] สร้าง order {order_id} แมว {len(cat_ids)} ตัว ยอด {amount} บาท")
    return order


def mark_slip_used(transaction_id: str):
    """บันทึก transaction ID หลัง BCSFE สำเร็จแล้ว"""
    if not transaction_id:
        return
    used_slips = _load_slips()
    if transaction_id not in used_slips:
        used_slips.append(transaction_id)
        _save_slips(used_slips)


# ══════════════════════════════════════════
# LOYALTY SYSTEM
# ══════════════════════════════════════════

def get_user_loyalty(username: str) -> dict:
    """ดึง loyalty data จาก profiles table"""
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.get(
                f"{SUPABASE_URL}/rest/v1/profiles",
                params={"username": f"eq.{username}", "select": "total_spent,loyalty_redeemed_cycles"},
                headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"},
            )
            data = resp.json()
            if data:
                return {
                    "total_spent": data[0].get("total_spent") or 0,
                    "loyalty_redeemed_cycles": data[0].get("loyalty_redeemed_cycles") or 0,
                }
    except Exception as e:
        print(f"[LOYALTY] get error: {e}")
    return {"total_spent": 0, "loyalty_redeemed_cycles": 0}


def update_user_loyalty_spent(username: str, amount: int):
    """เพิ่ม total_spent หลังชำระเงินสำเร็จ — ใช้ RPC increment (atomic)"""
    if not username or amount <= 0:
        return
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.post(
                f"{SUPABASE_URL}/rest/v1/rpc/increment_total_spent",
                headers={
                    "apikey": SUPABASE_KEY,
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                    "Content-Type": "application/json",
                },
                json={"p_username": username, "p_amount": amount},
            )
        if resp.status_code in (200, 204):
            print(f"[LOYALTY] ✅ {username}: total_spent +{amount}")
        else:
            print(f"[LOYALTY] ❌ RPC ล้มเหลว {resp.status_code}: {resp.text[:300]}")
    except Exception as e:
        print(f"[LOYALTY] update_spent error: {e}")


def add_loyalty_redeemed_cycles(username: str, count: int):
    """เพิ่ม loyalty_redeemed_cycles ครั้งเดียวหลาย cycle"""
    try:
        loyalty = get_user_loyalty(username)
        new_count = loyalty["loyalty_redeemed_cycles"] + count
        with httpx.Client(timeout=8) as client:
            client.patch(
                f"{SUPABASE_URL}/rest/v1/profiles",
                params={"username": f"eq.{username}"},
                headers={
                    "apikey": SUPABASE_KEY,
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                    "Content-Type": "application/json",
                },
                json={"loyalty_redeemed_cycles": new_count},
            )
        print(f"[LOYALTY] {username}: redeemed +{count} cycles → total #{new_count}")
    except Exception as e:
        print(f"[LOYALTY] add_cycles error: {e}")


def verify_loyalty_session(username: str, session_token: str) -> bool:
    """ตรวจสอบว่า session_token (password_hash) ตรงกับใน Supabase"""
    if not username or not session_token:
        return False
    try:
        with httpx.Client(timeout=6) as client:
            resp = client.get(
                f"{SUPABASE_URL}/rest/v1/profiles",
                params={
                    "username": f"eq.{username}",
                    "password_hash": f"eq.{session_token}",
                    "select": "username",
                    "limit": "1",
                },
                headers={
                    "apikey": SUPABASE_KEY,
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                },
            )
        data = resp.json() if resp.status_code == 200 else []
        return len(data) > 0
    except Exception as e:
        print(f"[AUTH] verify_session error: {e}")
        return False


def save_loyalty_redemption(username: str, cycles: int, new_tc: str, new_cc: str):
    """บันทึก redemption history ลง loyalty_redemptions"""
    try:
        with httpx.Client(timeout=8) as client:
            client.post(
                f"{SUPABASE_URL}/rest/v1/loyalty_redemptions",
                headers={
                    "apikey": SUPABASE_KEY,
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal",
                },
                json={
                    "username": username,
                    "cycles_redeemed": cycles,
                    "new_transfer_code": new_tc,
                    "new_confirmation_code": new_cc,
                },
            )
        print(f"[LOYALTY] {username}: saved redemption history ({cycles} cycles)")
    except Exception as e:
        print(f"[LOYALTY] save_redemption error: {e}")


def get_loyalty_redemptions(username: str) -> list:
    """ดึงประวัติการแลกของ user"""
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.get(
                f"{SUPABASE_URL}/rest/v1/loyalty_redemptions",
                params={
                    "username": f"eq.{username}",
                    "order": "redeemed_at.desc",
                    "limit": "20",
                },
                headers={
                    "apikey": SUPABASE_KEY,
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                },
            )
        return resp.json() if resp.status_code == 200 else []
    except Exception as e:
        print(f"[LOYALTY] get_redemptions error: {e}")
        return []


def increment_loyalty_redeemed(username: str):
    """เพิ่ม loyalty_redeemed_cycles หลัง redeem สำเร็จ"""
    try:
        loyalty = get_user_loyalty(username)
        new_count = loyalty["loyalty_redeemed_cycles"] + 1
        with httpx.Client(timeout=8) as client:
            client.patch(
                f"{SUPABASE_URL}/rest/v1/profiles",
                params={"username": f"eq.{username}"},
                headers={
                    "apikey": SUPABASE_KEY,
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                    "Content-Type": "application/json",
                },
                json={"loyalty_redeemed_cycles": new_count},
            )
        print(f"[LOYALTY] {username}: redeemed cycle #{new_count}")
    except Exception as e:
        print(f"[LOYALTY] increment error: {e}")


# ══════════════════════════════════════════
# CODE SHOP — ขายรหัส pre-made
# ══════════════════════════════════════════

def _sh(extra: dict | None = None) -> dict:
    """Supabase headers"""
    h = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    if extra:
        h.update(extra)
    return h


def verify_admin_session(username: str, session_token: str) -> bool:
    """ตรวจว่า user เป็น admin (is_admin = TRUE + password ถูกต้อง)"""
    if not username or not session_token:
        return False
    try:
        with httpx.Client(timeout=6) as client:
            resp = client.get(
                f"{SUPABASE_URL}/rest/v1/profiles",
                params={"username": f"eq.{username}", "password_hash": f"eq.{session_token}",
                        "is_admin": "eq.true", "select": "username", "limit": "1"},
                headers=_sh(),
            )
        return len(resp.json()) > 0 if resp.status_code == 200 else False
    except Exception as e:
        print(f"[ADMIN] verify error: {e}")
        return False


def _count_stock(product_id: str, status: str | None = None) -> int:
    params: dict = {"product_id": f"eq.{product_id}", "select": "id"}
    if status:
        params["status"] = f"eq.{status}"
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.get(
                f"{SUPABASE_URL}/rest/v1/code_stock",
                params=params,
                headers=_sh({"Prefer": "count=exact"}),
            )
        cr = resp.headers.get("content-range", "")
        if "/" in cr:
            t = cr.split("/")[1]
            if t.isdigit():
                return int(t)
        data = resp.json() if resp.status_code == 200 else []
        return len(data) if isinstance(data, list) else 0
    except:
        return 0


def get_code_products() -> list:
    """ดึงสินค้าที่ active พร้อม stock count (ลูกค้าเห็น)"""
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.get(
                f"{SUPABASE_URL}/rest/v1/code_products",
                params={"is_active": "eq.true", "order": "created_at.asc", "select": "*"},
                headers=_sh(),
            )
        products = resp.json() if resp.status_code == 200 else []
        for p in products:
            p["stock_count"] = _count_stock(p["id"], "available")
        return products
    except Exception as e:
        print(f"[CODE-SHOP] get_products error: {e}")
        return []


def get_all_code_products() -> list:
    """ดึงสินค้าทั้งหมด (admin view รวม inactive)"""
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.get(
                f"{SUPABASE_URL}/rest/v1/code_products",
                params={"order": "created_at.asc", "select": "*"},
                headers=_sh(),
            )
        products = resp.json() if resp.status_code == 200 else []
        for p in products:
            p["stock_available"] = _count_stock(p["id"], "available")
            p["stock_sold"] = _count_stock(p["id"], "sold")
        return products
    except Exception as e:
        print(f"[CODE-SHOP] get_all_products error: {e}")
        return []


def get_code_product(product_id: str) -> dict | None:
    """ดึงสินค้าเดี่ยว"""
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.get(
                f"{SUPABASE_URL}/rest/v1/code_products",
                params={"id": f"eq.{product_id}", "select": "*", "limit": "1"},
                headers=_sh(),
            )
        data = resp.json() if resp.status_code == 200 else []
        return data[0] if data else None
    except Exception as e:
        print(f"[CODE-SHOP] get_product error: {e}")
        return None


def get_available_stock(product_id: str) -> dict | None:
    """ดึง stock item ที่ available ตัวแรก"""
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.get(
                f"{SUPABASE_URL}/rest/v1/code_stock",
                params={"product_id": f"eq.{product_id}", "status": "eq.available",
                        "order": "created_at.asc", "limit": "1",
                        "select": "id,transfer_code,confirmation_code"},
                headers=_sh(),
            )
        data = resp.json() if resp.status_code == 200 else []
        return data[0] if data else None
    except Exception as e:
        print(f"[CODE-SHOP] get_available_stock error: {e}")
        return None


def reserve_stock(stock_id: str, username: str, order_id: str) -> bool:
    """จอง stock item ระหว่างรอชำระ (atomic: เฉพาะ available)"""
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.patch(
                f"{SUPABASE_URL}/rest/v1/code_stock",
                params={"id": f"eq.{stock_id}", "status": "eq.available"},
                headers=_sh({"Content-Type": "application/json", "Prefer": "return=minimal"}),
                json={"status": "reserved", "buyer_username": username, "order_id": order_id},
            )
        return resp.status_code in (200, 204)
    except Exception as e:
        print(f"[CODE-SHOP] reserve_stock error: {e}")
        return False


def mark_stock_sold(stock_id: str) -> bool:
    """mark stock เป็น sold"""
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.patch(
                f"{SUPABASE_URL}/rest/v1/code_stock",
                params={"id": f"eq.{stock_id}"},
                headers=_sh({"Content-Type": "application/json", "Prefer": "return=minimal"}),
                json={"status": "sold", "sold_at": datetime.now(TZ_THAI).isoformat()},
            )
        return resp.status_code in (200, 204)
    except Exception as e:
        print(f"[CODE-SHOP] mark_sold error: {e}")
        return False


def release_stock(stock_id: str) -> bool:
    """คืน stock เป็น available (order หมดอายุ/ยกเลิก)"""
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.patch(
                f"{SUPABASE_URL}/rest/v1/code_stock",
                params={"id": f"eq.{stock_id}"},
                headers=_sh({"Content-Type": "application/json", "Prefer": "return=minimal"}),
                json={"status": "available", "buyer_username": None, "order_id": None},
            )
        return resp.status_code in (200, 204)
    except Exception as e:
        print(f"[CODE-SHOP] release_stock error: {e}")
        return False


def get_stock_by_order(order_id: str) -> dict | None:
    """ดึง stock item ที่ reserved/sold สำหรับ order นี้"""
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.get(
                f"{SUPABASE_URL}/rest/v1/code_stock",
                params={"order_id": f"eq.{order_id}",
                        "select": "id,transfer_code,confirmation_code,status"},
                headers=_sh(),
            )
        data = resp.json() if resp.status_code == 200 else []
        return data[0] if data else None
    except Exception as e:
        print(f"[CODE-SHOP] get_stock_by_order error: {e}")
        return None


def add_code_product(name: str, description: str, images: list, price: int) -> dict | None:
    """admin: เพิ่มสินค้าใหม่"""
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.post(
                f"{SUPABASE_URL}/rest/v1/code_products",
                headers=_sh({"Content-Type": "application/json", "Prefer": "return=representation"}),
                json={"name": name, "description": description,
                      "images": images, "price": price, "is_active": True},
            )
        print(f"[CODE-SHOP] add_product status={resp.status_code} body={resp.text[:300]}")
        data = resp.json() if resp.status_code in (200, 201) else None
        return data[0] if isinstance(data, list) and data else None
    except Exception as e:
        print(f"[CODE-SHOP] add_product error: {e}")
        return None


def toggle_code_product(product_id: str, is_active: bool) -> bool:
    """admin: เปิด/ปิดการแสดงสินค้า"""
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.patch(
                f"{SUPABASE_URL}/rest/v1/code_products",
                params={"id": f"eq.{product_id}"},
                headers=_sh({"Content-Type": "application/json", "Prefer": "return=minimal"}),
                json={"is_active": is_active},
            )
        return resp.status_code in (200, 204)
    except Exception as e:
        print(f"[CODE-SHOP] toggle_product error: {e}")
        return False


def delete_code_product(product_id: str) -> bool:
    """admin: ลบสินค้า (stock ลบด้วย ON DELETE CASCADE)"""
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.delete(
                f"{SUPABASE_URL}/rest/v1/code_products",
                params={"id": f"eq.{product_id}"},
                headers=_sh(),
            )
        return resp.status_code in (200, 204)
    except Exception as e:
        print(f"[CODE-SHOP] delete_product error: {e}")
        return False


def add_code_stock(product_id: str, transfer_code: str, confirmation_code: str, inquiry_code: str | None = None) -> dict | None:
    """admin: เพิ่มรหัสเข้า stock"""
    try:
        payload = {"product_id": product_id, "transfer_code": transfer_code,
                   "confirmation_code": confirmation_code, "status": "available"}
        if inquiry_code:
            payload["inquiry_code"] = inquiry_code
        with httpx.Client(timeout=8) as client:
            resp = client.post(
                f"{SUPABASE_URL}/rest/v1/code_stock",
                headers=_sh({"Content-Type": "application/json", "Prefer": "return=representation"}),
                json=payload,
            )
        print(f"[CODE-SHOP] add_stock status={resp.status_code} body={resp.text[:200]}")
        data = resp.json() if resp.status_code in (200, 201) else None
        return data[0] if isinstance(data, list) and data else None
    except Exception as e:
        print(f"[CODE-SHOP] add_stock error: {e}")
        return None


def get_user_code_purchases(username: str) -> list:
    """ประวัติการซื้อ pre-made code ของ user (join code_products)"""
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.get(
                f"{SUPABASE_URL}/rest/v1/code_stock",
                params={
                    "buyer_username": f"eq.{username}",
                    "status": "eq.sold",
                    "select": "id,transfer_code,confirmation_code,sold_at,order_id,product_id,code_products(name,price)",
                    "order": "sold_at.desc",
                    "limit": "30",
                },
                headers=_sh(),
            )
        return resp.json() if resp.status_code == 200 else []
    except Exception as e:
        print(f"[CODE-SHOP] get_user_code_purchases error: {e}")
        return []


def delete_code_stock(stock_id: str) -> bool:
    """admin: ลบ stock item"""
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.delete(
                f"{SUPABASE_URL}/rest/v1/code_stock",
                params={"id": f"eq.{stock_id}"},
                headers=_sh(),
            )
        return resp.status_code in (200, 204)
    except Exception as e:
        print(f"[CODE-SHOP] delete_stock error: {e}")
        return False


def get_product_stock(product_id: str) -> list:
    """admin: ดู stock ทั้งหมดของสินค้า"""
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.get(
                f"{SUPABASE_URL}/rest/v1/code_stock",
                params={"product_id": f"eq.{product_id}", "order": "created_at.asc",
                        "select": "id,status,buyer_username,sold_at,created_at"},
                headers=_sh(),
            )
        return resp.json() if resp.status_code == 200 else []
    except Exception as e:
        print(f"[CODE-SHOP] get_product_stock error: {e}")
        return []


def create_code_shop_order(product_id: str, stock_id: str, username: str, price: int,
                           payment_method: str = "promptpay") -> dict:
    """สร้าง order สำหรับซื้อ pre-made code"""
    order_id = str(uuid.uuid4())[:8].upper()
    fee      = truemoney_fee(price) if payment_method == "truemoney" else 0
    amount   = price + fee
    expires  = (datetime.now(TZ_THAI) + timedelta(minutes=ORDER_TIMEOUT)).isoformat()
    order = {
        "order_id":       order_id,
        "order_type":     "code_shop",
        "product_id":     product_id,
        "stock_id":       stock_id,
        "username":       username,
        "base_amount":    price,
        "truemoney_fee":  fee,
        "amount":         amount,
        "payment_method": payment_method,
        "status":         "pending",
        "created_at":     datetime.now(TZ_THAI).isoformat(),
        "expires_at":     expires,
        "qr_base64":      generate_qr_base64(amount) if payment_method == "promptpay" else None,
    }
    orders = _load_orders()
    orders[order_id] = order
    _save_orders(orders)
    _add_user_order(username, order_id)
    print(f"[CODE-SHOP] สร้าง order {order_id} product={product_id} method={payment_method}")
    return order
