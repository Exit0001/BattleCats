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

PROMPTPAY_ID   = "004999236376637"       # K PLUS e-Wallet ID (15 หลัก) ที่รับเงิน
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
        try:
            return json.loads(ORDER_DB.read_text(encoding="utf-8"))
        except Exception:
            # corrupted — backup and start fresh
            try:
                ORDER_DB.rename(str(ORDER_DB) + ".corrupt")
            except Exception:
                pass
            return {}
    return {}

def _save_orders(data: dict):
    tmp = ORDER_DB.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(ORDER_DB)

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

def _is_transaction_used(transaction_id: str) -> bool:
    """เช็ค Supabase ว่า transaction_id นี้ถูกใช้ไปแล้วหรือยัง (ป้องกัน slip ซ้ำแม้ BCSFE fail)"""
    if not transaction_id:
        return False
    try:
        with httpx.Client(timeout=5) as client:
            resp = client.get(
                f"{SUPABASE_URL}/rest/v1/orders",
                params={"transaction_id": f"eq.{transaction_id}", "select": "transaction_id", "limit": "1"},
                headers={
                    "apikey": SUPABASE_KEY,
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                },
            )
        data = resp.json() if resp.status_code == 200 else []
        return len(data) > 0
    except Exception:
        return False


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

def _promptpay_payload(target_id: str, amount: float) -> str:
    """สร้าง PromptPay QR payload string ตามมาตรฐาน EMVCo
    รองรับ 3 รูปแบบ: เบอร์โทร (subtag 01) / เลขบัตรประชาชน 13 หลัก (subtag 02) / e-Wallet ID 15 หลัก (subtag 03)"""
    target_id = target_id.replace("-", "").replace(" ", "")

    if len(target_id) == 15:
        id_type, id_value = "03", target_id
    elif len(target_id) == 13:
        id_type, id_value = "02", target_id
    else:
        if target_id.startswith("0"):
            target_id = "66" + target_id[1:]
        id_type, id_value = "01", target_id.zfill(13)

    def tlv(tag: str, value: str) -> str:
        return f"{tag}{len(value):02d}{value}"

    merchant_info = tlv("00", "A000000677010111") + tlv(id_type, id_value)
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
                             payment_method: str = "promptpay",
                             username: str = "") -> dict:
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
        "username":          username or "",
    }
    orders = _load_orders()
    orders[order_id] = order
    _save_orders(orders)
    _supabase_upsert(order)
    _add_user_order(username or "", order_id)
    print(f"[ORDER] สร้าง all-package order {order_id} type={package_type} ยอด {amount} บาท")
    return order


def _supabase_get_order(order_id: str) -> dict | None:
    """อ่าน order จาก Supabase (fallback เมื่อ local JSON หาไม่เจอ)"""
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.get(
                f"{SUPABASE_URL}/rest/v1/orders",
                headers={
                    "apikey": SUPABASE_KEY,
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                },
                params={"order_id": f"eq.{order_id}", "select": "*", "limit": "1"},
            )
        if resp.status_code == 200:
            rows = resp.json()
            if rows:
                order = rows[0]
                # sync กลับมาเก็บใน local JSON ด้วย
                orders = _load_orders()
                orders[order_id] = order
                _save_orders(orders)
                print(f"[SUPABASE] ✔ recovered order {order_id} from Supabase")
                return order
    except Exception as e:
        print(f"[SUPABASE] ⚠ get_order fallback error: {e}")
    return None


def get_order(order_id: str) -> dict | None:
    """ดึง order จาก DB (fallback ไป Supabase ถ้า local หาไม่เจอ)"""
    orders = _load_orders()
    order = orders.get(order_id)
    if order is None:
        order = _supabase_get_order(order_id)
    return order


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

    # 1) เช็คยอด — รับได้ถ้า received >= expected (ส่วนเกินเข้า wallet)
    raw_slip = slip_data.get("rawSlip", {})
    received = float(raw_slip.get("amount", {}).get("amount", 0))
    expected = float(order["amount"])
    if received < expected - 0.01:
        return {"success": False, "reason": f"ยอดไม่ตรง คาดหวัง {expected:.2f} แต่ได้ {received:.2f} บาท"}

    # 2) เช็คสลิปซ้ำ — ตรวจทั้ง local file และ Supabase orders
    transaction_id = raw_slip.get("transRef", "")
    used_slips = _load_slips()
    if transaction_id and (transaction_id in used_slips or _is_transaction_used(transaction_id)):
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

    surplus = max(0, int(received) - int(expected))
    print(f"[EASYSLIP] ✅ order {order_id} ชำระแล้ว {received} บาท" + (f" surplus ฿{surplus}" if surplus else ""))
    return {"success": True, "reason": "ชำระเงินสำเร็จ", "transaction_id": transaction_id, "surplus": surplus}

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
    if received < expected - 0.01:
        credited = max(0, int(received))
        username = order.get("username") if order else None
        if credited > 0 and username:
            credit_wallet(username, credited)
            remaining = int(expected) - credited
            print(f"[ANGPAO] ⚠ underpay order {order_id}: ได้ ฿{received:.2f} ต้องการ ฿{expected:.2f} → credit ฿{credited} to {username}")
            tw_needed = remaining
            while tw_needed - truemoney_fee(tw_needed) < remaining:
                tw_needed += 1
            return {
                "success":      False,
                "insufficient": True,
                "credited":     credited,
                "remaining":    remaining,
                "reason":       (
                    f"ซองอั่งเป่าของคุณมียอดไม่พอนะครับ 😅\n\n"
                    f"💸 ยอดที่ได้รับ: ฿{received:.2f} (หลังหักค่าธรรมเนียม TrueWallet 2.9%)\n"
                    f"💰 เราเก็บเงินส่วนนี้ไว้ในกระเป๋าเงินให้แล้ว: ฿{credited}\n"
                    f"❗ ยังขาดอีก: ฿{remaining}\n\n"
                    f"เติมเงินเพิ่มเข้ากระเป๋าเงินได้ 2 วิธีครับ\n"
                    f"🏦 PromptPay — โอน ฿{remaining} พอดี\n"
                    f"💚 TrueWallet — ส่งซอง ฿{tw_needed} (รวมค่าธรรมเนียม 2.9% แล้ว)\n\n"
                    f"แล้วกลับมากด \"ชำระส่วนที่เหลือด้วย wallet\" ได้เลยครับ"
                ),
            }
        return {"success": False, "reason": f"ยอดไม่ตรง คาดหวัง {expected:.2f} แต่ได้ {received:.2f} บาท"}

    surplus = max(0, int(received) - int(expected))
    update_order_status(order_id, "paid", {
        "paid_at":        datetime.now(TZ_THAI).isoformat(),
        "transaction_id": voucher_hash,
        "received":       received,
    })

    print(f"[ANGPAO] ✅ order {order_id} ชำระแล้ว {received} บาท" + (f" surplus ฿{surplus}" if surplus else ""))
    return {"success": True, "reason": "ชำระเงินสำเร็จ", "transaction_id": voucher_hash, "surplus": surplus}


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


def create_stages_order(transfer_code: str, confirmation_code: str,
                        country: str, stages_config: dict, amount: int,
                        payment_method: str = "promptpay",
                        username: str = "") -> dict:
    """สร้าง order สำหรับปลดล็อคด่าน"""
    order_id = str(uuid.uuid4())[:8].upper()
    fee      = truemoney_fee(amount) if payment_method == "truemoney" else 0
    total    = amount + fee
    expires  = (datetime.now(TZ_THAI) + timedelta(minutes=ORDER_TIMEOUT)).isoformat()
    order = {
        "order_id":          order_id,
        "order_type":        "stages",
        "transfer_code":     transfer_code,
        "confirmation_code": confirmation_code,
        "country":           country,
        "items":             [],
        "cat_ids":           [],
        "stages_config":     stages_config,
        "base_amount":       amount,
        "truemoney_fee":     fee,
        "amount":            total,
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
    print(f"[STAGES-ORDER] สร้าง order {order_id} config={stages_config} ยอด {amount} บาท")
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
    """ดึง loyalty data — total_spent คำนวณสดจากตาราง orders (กัน drift จาก RPC ที่อาจล้มเหลว)"""
    redeemed_cycles = 0
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.get(
                f"{SUPABASE_URL}/rest/v1/profiles",
                params={"username": f"eq.{username}", "select": "loyalty_redeemed_cycles"},
                headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"},
            )
            data = resp.json()
            if data:
                redeemed_cycles = data[0].get("loyalty_redeemed_cycles") or 0
    except Exception as e:
        print(f"[LOYALTY] get error: {e}")

    total_spent = 0
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.get(
                f"{SUPABASE_URL}/rest/v1/orders",
                params={"username": f"eq.{username}", "status": "eq.done", "select": "amount,base_amount"},
                headers=_sh(),
            )
            orders = resp.json() if resp.status_code == 200 else []
        total_spent = sum((o.get("base_amount") if o.get("base_amount") is not None else o.get("amount") or 0) for o in orders)
    except Exception as e:
        print(f"[LOYALTY] total_spent calc error: {e}")

    return {"total_spent": total_spent, "loyalty_redeemed_cycles": redeemed_cycles}


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


def _get_revenue_for_range(start: datetime, end: datetime) -> dict:
    """สรุปยอดรายได้ระหว่าง start-end (ไม่นับ order ของบัญชี admin) — ใช้ร่วมกันทั้งรายเดือน/รายวัน"""
    with httpx.Client(timeout=8) as client:
        admin_resp = client.get(
            f"{SUPABASE_URL}/rest/v1/profiles",
            params={"is_admin": "eq.true", "select": "username"},
            headers=_sh(),
        )
    admin_usernames = [p["username"] for p in admin_resp.json()] if admin_resp.status_code == 200 else []

    with httpx.Client(timeout=8) as client:
        resp = client.get(
            f"{SUPABASE_URL}/rest/v1/orders",
            params={
                "status": "eq.done",
                "created_at": [f"gte.{start.isoformat()}", f"lt.{end.isoformat()}"],
                "select": "order_id,amount,base_amount,order_type,username,created_at",
            },
            headers=_sh(),
        )
    all_orders = resp.json() if resp.status_code == 200 else []
    TEST_ACCOUNTS = {"test", "mod"}
    orders = [o for o in all_orders if o.get("username") and o.get("username") not in admin_usernames
              and o.get("username") not in TEST_ACCOUNTS
              and o.get("order_type") != "topup"]

    def _rev(o):
        return o.get("base_amount") if o.get("base_amount") is not None else (o.get("amount") or 0)

    total_revenue = sum(_rev(o) for o in orders)
    by_type: dict = {}
    for o in orders:
        t = o.get("order_type") or "unknown"
        by_type[t] = by_type.get(t, 0) + _rev(o)

    orders_sorted = sorted(orders, key=lambda o: o.get("created_at") or "")

    return {
        "total_revenue": total_revenue,
        "total_orders": len(orders),
        "by_type": by_type,
        "excluded_admins": admin_usernames,
        "excluded_no_username_count": len(all_orders) - len(orders) - sum(
            1 for o in all_orders if o.get("username") in admin_usernames
        ),
        "orders": orders_sorted,
    }


def get_monthly_revenue(year: int, month: int) -> dict:
    """admin: สรุปยอดรายได้ของเดือนนั้น (ไม่นับ order ของบัญชี admin)"""
    try:
        start = datetime(year, month, 1, tzinfo=TZ_THAI)
        end = datetime(year + 1, 1, 1, tzinfo=TZ_THAI) if month == 12 else datetime(year, month + 1, 1, tzinfo=TZ_THAI)
        return {"year": year, "month": month, **_get_revenue_for_range(start, end)}
    except Exception as e:
        print(f"[REVENUE] error: {e}")
        return {"year": year, "month": month, "total_revenue": 0, "total_orders": 0,
                "by_type": {}, "excluded_admins": [], "orders": [], "error": str(e)}


def get_daily_revenue(year: int, month: int, day: int) -> dict:
    """admin: สรุปยอดรายได้ของวันนั้น (ไม่นับ order ของบัญชี admin)"""
    try:
        start = datetime(year, month, day, tzinfo=TZ_THAI)
        end = start + timedelta(days=1)
        return {"year": year, "month": month, "day": day, **_get_revenue_for_range(start, end)}
    except Exception as e:
        print(f"[REVENUE] error: {e}")
        return {"year": year, "month": month, "day": day, "total_revenue": 0, "total_orders": 0,
                "by_type": {}, "excluded_admins": [], "orders": [], "error": str(e)}


def _get_cr_revenue_for_range(start: datetime, end: datetime) -> dict:
    TEST_ACCOUNTS = {"test", "mod"}
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.get(
                f"{SUPABASE_URL}/rest/v1/cr_orders",
                params={
                    "status": "eq.done",
                    "created_at": [f"gte.{start.isoformat()}", f"lt.{end.isoformat()}"],
                    "select": "order_id,amount,base_amount,quantity,payment_method,username,created_at,done_at",
                },
                headers=_sh(),
            )
        all_orders = resp.json() if resp.status_code == 200 else []
    except Exception as e:
        print(f"[CR-REVENUE] error: {e}")
        all_orders = []
    orders = [o for o in all_orders if o.get("username") and o.get("username") not in TEST_ACCOUNTS]
    def _rev(o):
        return o.get("base_amount") if o.get("base_amount") is not None else (o.get("amount") or 0)
    total = sum(_rev(o) for o in orders)
    by_method: dict = {}
    for o in orders:
        m = o.get("payment_method") or "unknown"
        by_method[m] = by_method.get(m, 0) + _rev(o)
    return {
        "total_revenue": total,
        "total_orders": len(orders),
        "by_method": by_method,
        "orders": sorted(orders, key=lambda o: o.get("created_at") or ""),
    }


def get_cr_monthly_revenue(year: int, month: int) -> dict:
    try:
        start = datetime(year, month, 1, tzinfo=TZ_THAI)
        end = datetime(year + 1, 1, 1, tzinfo=TZ_THAI) if month == 12 else datetime(year, month + 1, 1, tzinfo=TZ_THAI)
        return {"year": year, "month": month, **_get_cr_revenue_for_range(start, end)}
    except Exception as e:
        return {"year": year, "month": month, "total_revenue": 0, "total_orders": 0, "by_method": {}, "orders": [], "error": str(e)}


def get_cr_daily_revenue(year: int, month: int, day: int) -> dict:
    try:
        start = datetime(year, month, day, tzinfo=TZ_THAI)
        end = start + timedelta(days=1)
        return {"year": year, "month": month, "day": day, **_get_cr_revenue_for_range(start, end)}
    except Exception as e:
        return {"year": year, "month": month, "day": day, "total_revenue": 0, "total_orders": 0, "by_method": {}, "orders": [], "error": str(e)}


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


# ══════════════════════════════════════════
# WALLET
# ══════════════════════════════════════════

def get_wallet_balance(username: str) -> int:
    """ดึงยอด wallet (หน่วยบาท)"""
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.get(
                f"{SUPABASE_URL}/rest/v1/profiles",
                params={"username": f"eq.{username}", "select": "wallet_balance"},
                headers=_sh(),
            )
        data = resp.json() if resp.status_code == 200 else []
        return int(data[0].get("wallet_balance") or 0) if data else 0
    except Exception as e:
        print(f"[WALLET] get_balance error: {e}")
        return 0


def credit_wallet(username: str, amount: int) -> bool:
    """บวกเงินเข้า wallet (หน่วยบาท)"""
    if amount <= 0:
        return False
    try:
        current = get_wallet_balance(username)
        with httpx.Client(timeout=8) as client:
            resp = client.patch(
                f"{SUPABASE_URL}/rest/v1/profiles",
                params={"username": f"eq.{username}"},
                headers=_sh({"Content-Type": "application/json", "Prefer": "return=minimal"}),
                json={"wallet_balance": current + amount},
            )
        ok = resp.status_code in (200, 204)
        if ok:
            print(f"[WALLET] ✅ credit {username} +฿{amount} → ฿{current + amount}")
        return ok
    except Exception as e:
        print(f"[WALLET] credit error: {e}")
        return False


def deduct_wallet(username: str, amount: int) -> bool:
    """หักเงินออกจาก wallet แบบ atomic — คืน False ถ้ายอดไม่พอ"""
    if amount <= 0:
        return False
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.post(
                f"{SUPABASE_URL}/rest/v1/rpc/deduct_wallet_atomic",
                headers=_sh({"Content-Type": "application/json"}),
                json={"p_username": username, "p_amount": amount},
            )
        ok = resp.status_code == 200 and resp.json() is True
        if ok:
            print(f"[WALLET] ✅ deduct {username} -฿{amount} (atomic)")
        else:
            print(f"[WALLET] ❌ deduct {username} ฿{amount} — balance ไม่พอหรือ RPC error (status={resp.status_code})")
        return ok
    except Exception as e:
        print(f"[WALLET] deduct error: {e}")
        return False


def create_topup_order(username: str, amount: int, payment_method: str) -> dict:
    """สร้าง order เติม wallet (PromptPay เท่านั้น — TrueMoney ใช้ redeem_angpao_for_wallet แทน)"""
    order_id = str(uuid.uuid4())[:8].upper()
    expires  = (datetime.now(TZ_THAI) + timedelta(minutes=ORDER_TIMEOUT)).isoformat()
    order = {
        "order_id":       order_id,
        "order_type":     "topup",
        "username":       username,
        "base_amount":    amount,
        "truemoney_fee":  0,
        "amount":         amount,
        "payment_method": payment_method,
        "status":         "pending",
        "created_at":     datetime.now(TZ_THAI).isoformat(),
        "expires_at":     expires,
        "qr_base64":      generate_qr_base64(amount),
    }
    orders = _load_orders()
    orders[order_id] = order
    _save_orders(orders)
    _add_user_order(username, order_id)
    _supabase_upsert(order)
    print(f"[WALLET] สร้าง topup order {order_id} ฿{amount}")
    return order


async def redeem_angpao_for_wallet(voucher_code: str, username: str) -> dict:
    """Redeem ซองอั่งเป่าเพื่อเติม wallet โดยตรง (ไม่ต้องมี order)
    คืน {"success", "received", "fee", "credited", "transaction_id"}"""
    MIN_AMOUNT = 2  # ขั้นต่ำ 2 บาท (เพราะมีค่าธรรมเนียม 2.9%)

    voucher_hash = _extract_voucher_hash(voucher_code)
    if not voucher_hash:
        return {"success": False, "reason": "กรุณากรอกโค้ด/ลิงก์ซองอั่งเป่า"}

    used_slips = _load_slips()
    if voucher_hash in used_slips:
        return {"success": False, "reason": "ซองอั่งเป่านี้ถูกใช้ไปแล้ว"}

    mobile = TRUEMONEY_ID.replace("-", "").replace(" ", "")
    print(f"[WALLET] angpao redeem for {username}: hash={voucher_hash}")

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
        data = resp.json()
        print(f"[WALLET] angpao response: {json.dumps(data, ensure_ascii=False)[:300]}")
    except Exception as e:
        return {"success": False, "reason": f"เช็คซองอั่งเป่าไม่ได้: {e}"}

    status_obj = data.get("status") or {}
    code = data.get("code") or status_obj.get("code") or ("SUCCESS" if data.get("success") else "")

    if code != "SUCCESS":
        msg = _ANGPAO_ERROR_MESSAGES.get(code) or data.get("message") or status_obj.get("message") or "ซองอั่งเป่าไม่ถูกต้อง"
        return {"success": False, "reason": msg}

    voucher_data = data.get("data") or {}
    voucher_obj  = voucher_data.get("my_ticket") or voucher_data.get("voucher") or {}
    amount_baht  = voucher_obj.get("amount_baht")
    if amount_baht is not None:
        received = float(amount_baht)
    else:
        received = float(data.get("amount", 0)) / 100

    if received < MIN_AMOUNT:
        return {"success": False, "reason": f"ยอดขั้นต่ำ ฿{MIN_AMOUNT} (ซองนี้มีแค่ ฿{received:.2f})"}

    fee      = truemoney_fee(int(received))
    credited = int(received) - fee
    if credited < 1:
        return {"success": False, "reason": "ยอดหลังหักค่าธรรมเนียมน้อยเกินไป"}

    mark_slip_used(voucher_hash)
    print(f"[WALLET] ✅ angpao {username} ฿{received} fee={fee} → credit ฿{credited}")
    return {"success": True, "received": received, "fee": fee, "credited": credited, "transaction_id": voucher_hash}


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
    release_expired_reserved_stock(product_id)
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
    """จอง stock item ระหว่างรอชำระ (atomic: เฉพาะ available)
    ใช้ count=exact เพื่อตรวจว่า row ถูก update จริง ป้องกัน double-sell"""
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.patch(
                f"{SUPABASE_URL}/rest/v1/code_stock",
                params={"id": f"eq.{stock_id}", "status": "eq.available"},
                headers=_sh({"Content-Type": "application/json", "Prefer": "count=exact"}),
                json={"status": "reserved", "buyer_username": username, "order_id": order_id},
            )
        # content-range: 0-0/1 = updated 1 row, 0-0/0 or missing = 0 rows updated
        count_header = resp.headers.get("content-range", "")
        # format: "0-N/TOTAL" — ตรวจ TOTAL > 0
        if "/" in count_header:
            total = count_header.split("/")[-1]
            updated = int(total) if total.isdigit() else 0
        else:
            updated = 1 if resp.status_code in (200, 204) else 0
        print(f"[CODE-SHOP] reserve_stock {stock_id}: updated={updated}")
        return updated > 0
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


def add_code_product(name: str, description: str, images: list, price: int,
                      name_en: str = "", description_en: str = "") -> dict | None:
    """admin: เพิ่มสินค้าใหม่"""
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.post(
                f"{SUPABASE_URL}/rest/v1/code_products",
                headers=_sh({"Content-Type": "application/json", "Prefer": "return=representation"}),
                json={"name": name, "description": description,
                      "name_en": name_en, "description_en": description_en,
                      "images": images, "price": price, "is_active": True},
            )
        print(f"[CODE-SHOP] add_product status={resp.status_code} body={resp.text[:300]}")
        data = resp.json() if resp.status_code in (200, 201) else None
        return data[0] if isinstance(data, list) and data else None
    except Exception as e:
        print(f"[CODE-SHOP] add_product error: {e}")
        return None


def update_code_product(product_id: str, name: str, description: str, price: int,
                         name_en: str = "", description_en: str = "") -> bool:
    """admin: แก้ไขชื่อ/คำอธิบาย/ราคาสินค้า (ไทย+อังกฤษ)"""
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.patch(
                f"{SUPABASE_URL}/rest/v1/code_products",
                params={"id": f"eq.{product_id}"},
                headers=_sh({"Content-Type": "application/json", "Prefer": "return=minimal"}),
                json={"name": name, "description": description,
                      "name_en": name_en, "description_en": description_en, "price": price},
            )
        return resp.status_code in (200, 204)
    except Exception as e:
        print(f"[CODE-SHOP] update_product error: {e}")
        return False


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


def release_expired_reserved_stock(product_id: str | None = None) -> int:
    """คืน stock ที่ค้างสถานะ reserved ของ order ที่หมดอายุ/ถูกยกเลิกไปแล้ว แต่ไม่มีใครมา cancel/verify ซ้ำ
    (เช่นลูกค้าปิดหน้าทิ้งหลังสร้าง QR แล้วไม่กลับมาเลย — stock ค้าง reserved ตลอดไปไม่งั้น)"""
    released = 0
    try:
        params = {"status": "eq.reserved", "select": "id,order_id"}
        if product_id:
            params["product_id"] = f"eq.{product_id}"
        with httpx.Client(timeout=8) as client:
            resp = client.get(f"{SUPABASE_URL}/rest/v1/code_stock", params=params, headers=_sh())
        reserved = resp.json() if resp.status_code == 200 else []
        for item in reserved:
            order = get_order(item.get("order_id", ""))
            should_release = (
                order is None
                or order.get("status") in ("cancelled", "expired")
                or (order.get("status") not in ("done",) and is_order_expired(order))
            )
            if should_release and release_stock(item["id"]):
                released += 1
    except Exception as e:
        print(f"[CODE-SHOP] release_expired_reserved_stock error: {e}")
    return released


def get_product_stock(product_id: str) -> list:
    """admin: ดู stock ทั้งหมดของสินค้า"""
    release_expired_reserved_stock(product_id)
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


# ══════════════════════════════════════════
# COOKIE RUN PRO MAX — DB & ORDER FUNCTIONS
# ══════════════════════════════════════════

CR_ORDERS_DB = Path("cr_orders.json")


def _load_cr_orders() -> dict:
    if CR_ORDERS_DB.exists():
        return json.loads(CR_ORDERS_DB.read_text(encoding="utf-8"))
    return {}


def _save_cr_orders(data: dict):
    CR_ORDERS_DB.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _count_cr_stock(product_id: str, status: str | None = None) -> int:
    params: dict = {"product_id": f"eq.{product_id}", "select": "id"}
    if status:
        params["status"] = f"eq.{status}"
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.get(
                f"{SUPABASE_URL}/rest/v1/cr_stock",
                params=params,
                headers=_sh({"Prefer": "count=exact"}),
            )
        cr = resp.headers.get("content-range", "")
        if "/" in cr:
            t = cr.split("/")[1]
            return int(t) if t.isdigit() else 0
        return 0
    except Exception:
        return 0


def get_cr_products() -> list:
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.get(
                f"{SUPABASE_URL}/rest/v1/cr_products",
                params={"is_active": "eq.true", "order": "created_at.asc", "select": "*"},
                headers=_sh(),
            )
        products = resp.json() if resp.status_code == 200 else []
        for p in products:
            p["stock_count"] = _count_cr_stock(p["id"], "available")
        return products
    except Exception as e:
        print(f"[CR] get_products error: {e}")
        return []


def get_all_cr_products() -> list:
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.get(
                f"{SUPABASE_URL}/rest/v1/cr_products",
                params={"order": "created_at.asc", "select": "*"},
                headers=_sh(),
            )
        products = resp.json() if resp.status_code == 200 else []
        for p in products:
            p["stock_available"] = _count_cr_stock(p["id"], "available")
            p["stock_sold"] = _count_cr_stock(p["id"], "sold")
        return products
    except Exception as e:
        print(f"[CR] get_all_products error: {e}")
        return []


def get_cr_product(product_id: str) -> dict | None:
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.get(
                f"{SUPABASE_URL}/rest/v1/cr_products",
                params={"id": f"eq.{product_id}", "select": "*", "limit": "1"},
                headers=_sh(),
            )
        data = resp.json() if resp.status_code == 200 else []
        return data[0] if data else None
    except Exception as e:
        print(f"[CR] get_product error: {e}")
        return None


def get_cr_order(order_id: str) -> dict | None:
    return _load_cr_orders().get(order_id)


def _supabase_upsert_cr_order(order: dict):
    try:
        row = {
            "order_id":       order["order_id"],
            "product_id":     order.get("product_id"),
            "username":       order.get("username"),
            "amount":         order.get("amount", 0),
            "base_amount":    order.get("base_amount", 0),
            "quantity":       order.get("quantity", 1),
            "payment_method": order.get("payment_method"),
            "status":         order.get("status"),
            "created_at":     order.get("created_at"),
            "done_at":        order.get("done_at"),
        }
        with httpx.Client(timeout=6) as client:
            client.post(
                f"{SUPABASE_URL}/rest/v1/cr_orders",
                json=row,
                params={"on_conflict": "order_id"},
                headers={**_sh(), "Prefer": "resolution=merge-duplicates"},
            )
    except Exception as e:
        print(f"[CR] supabase upsert error: {e}")


def update_cr_order_status(order_id: str, status: str, extra: dict = {}):
    orders = _load_cr_orders()
    if order_id in orders:
        orders[order_id]["status"] = status
        orders[order_id].update(extra)
        _save_cr_orders(orders)
        _supabase_upsert_cr_order(orders[order_id])


def release_expired_reserved_cr_stock(product_id: str | None = None) -> int:
    released = 0
    try:
        params = {"status": "eq.reserved", "select": "id,order_id"}
        if product_id:
            params["product_id"] = f"eq.{product_id}"
        with httpx.Client(timeout=8) as client:
            resp = client.get(f"{SUPABASE_URL}/rest/v1/cr_stock", params=params, headers=_sh())
        reserved = resp.json() if resp.status_code == 200 else []
        for item in reserved:
            order = get_cr_order(item.get("order_id", ""))
            should_release = (
                order is None
                or order.get("status") in ("cancelled", "expired")
                or (order.get("status") not in ("done",) and is_order_expired(order))
            )
            if should_release and release_cr_stock(item["id"]):
                released += 1
    except Exception as e:
        print(f"[CR] release_expired_reserved_cr_stock error: {e}")
    return released


def get_available_cr_stock(product_id: str) -> dict | None:
    stocks = get_available_cr_stock_bulk(product_id, 1)
    return stocks[0] if stocks else None


def get_available_cr_stock_bulk(product_id: str, quantity: int) -> list:
    release_expired_reserved_cr_stock(product_id)
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.get(
                f"{SUPABASE_URL}/rest/v1/cr_stock",
                params={"product_id": f"eq.{product_id}", "status": "eq.available",
                        "order": "created_at.asc", "limit": str(quantity), "select": "id,license_key"},
                headers=_sh(),
            )
        return resp.json() if resp.status_code == 200 else []
    except Exception as e:
        print(f"[CR] get_available_cr_stock_bulk error: {e}")
        return []


def reserve_cr_stock_bulk(stock_ids: list, username: str, order_id: str) -> bool:
    if not stock_ids:
        return False
    try:
        ids_filter = "in.(" + ",".join(stock_ids) + ")"
        with httpx.Client(timeout=8) as client:
            resp = client.patch(
                f"{SUPABASE_URL}/rest/v1/cr_stock",
                params={"id": ids_filter, "status": "eq.available"},
                headers=_sh({"Content-Type": "application/json", "Prefer": "count=exact"}),
                json={"status": "reserved", "buyer_username": username, "order_id": order_id,
                      "reserved_at": datetime.now(TZ_THAI).isoformat()},
            )
        count_header = resp.headers.get("content-range", "")
        if "/" in count_header:
            total = count_header.split("/")[-1]
            updated = int(total) if total.isdigit() else 0
        else:
            updated = len(stock_ids) if resp.status_code in (200, 204) else 0
        return updated == len(stock_ids)
    except Exception as e:
        print(f"[CR] reserve_cr_stock_bulk error: {e}")
        return False


def reserve_cr_stock(stock_id: str, username: str, order_id: str) -> bool:
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.patch(
                f"{SUPABASE_URL}/rest/v1/cr_stock",
                params={"id": f"eq.{stock_id}", "status": "eq.available"},
                headers=_sh({"Content-Type": "application/json", "Prefer": "count=exact"}),
                json={"status": "reserved", "buyer_username": username, "order_id": order_id,
                      "reserved_at": datetime.now(TZ_THAI).isoformat()},
            )
        count_header = resp.headers.get("content-range", "")
        if "/" in count_header:
            total = count_header.split("/")[-1]
            updated = int(total) if total.isdigit() else 0
        else:
            updated = 1 if resp.status_code in (200, 204) else 0
        return updated > 0
    except Exception as e:
        print(f"[CR] reserve_cr_stock error: {e}")
        return False


def mark_cr_stock_sold_bulk(stock_ids: list) -> bool:
    if not stock_ids:
        return False
    try:
        ids_filter = "in.(" + ",".join(stock_ids) + ")"
        with httpx.Client(timeout=8) as client:
            resp = client.patch(
                f"{SUPABASE_URL}/rest/v1/cr_stock",
                params={"id": ids_filter},
                headers=_sh({"Content-Type": "application/json", "Prefer": "return=minimal"}),
                json={"status": "sold", "sold_at": datetime.now(TZ_THAI).isoformat()},
            )
        return resp.status_code in (200, 204)
    except Exception as e:
        print(f"[CR] mark_cr_stock_sold_bulk error: {e}")
        return False


def mark_cr_stock_sold(stock_id: str) -> bool:
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.patch(
                f"{SUPABASE_URL}/rest/v1/cr_stock",
                params={"id": f"eq.{stock_id}"},
                headers=_sh({"Content-Type": "application/json", "Prefer": "return=minimal"}),
                json={"status": "sold", "sold_at": datetime.now(TZ_THAI).isoformat()},
            )
        return resp.status_code in (200, 204)
    except Exception as e:
        print(f"[CR] mark_cr_stock_sold error: {e}")
        return False


def release_cr_stock_bulk(stock_ids: list) -> None:
    if not stock_ids:
        return
    try:
        ids_filter = "in.(" + ",".join(stock_ids) + ")"
        with httpx.Client(timeout=8) as client:
            client.patch(
                f"{SUPABASE_URL}/rest/v1/cr_stock",
                params={"id": ids_filter},
                headers=_sh({"Content-Type": "application/json", "Prefer": "return=minimal"}),
                json={"status": "available", "buyer_username": None, "order_id": None, "reserved_at": None},
            )
    except Exception as e:
        print(f"[CR] release_cr_stock_bulk error: {e}")


def release_cr_stock(stock_id: str) -> bool:
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.patch(
                f"{SUPABASE_URL}/rest/v1/cr_stock",
                params={"id": f"eq.{stock_id}"},
                headers=_sh({"Content-Type": "application/json", "Prefer": "return=minimal"}),
                json={"status": "available", "buyer_username": None, "order_id": None, "reserved_at": None},
            )
        return resp.status_code in (200, 204)
    except Exception as e:
        print(f"[CR] release_cr_stock error: {e}")
        return False


def get_cr_stock_by_order(order_id: str) -> dict | None:
    stocks = get_cr_stocks_by_order(order_id)
    return stocks[0] if stocks else None


def get_cr_stocks_by_order(order_id: str) -> list:
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.get(
                f"{SUPABASE_URL}/rest/v1/cr_stock",
                params={"order_id": f"eq.{order_id}", "select": "id,license_key,status"},
                headers=_sh(),
            )
        return resp.json() if resp.status_code == 200 else []
    except Exception as e:
        print(f"[CR] get_cr_stocks_by_order error: {e}")
        return []


def create_cr_order(product_id: str, stock_ids: list, username: str, price: int,
                    payment_method: str = "promptpay", quantity: int = 1) -> dict:
    order_id = str(uuid.uuid4())[:8].upper()
    base_price = price * quantity
    fee = truemoney_fee(base_price) if payment_method == "truemoney" else 0
    amount = base_price + fee
    expires = (datetime.now(TZ_THAI) + timedelta(minutes=ORDER_TIMEOUT)).isoformat()
    order = {
        "order_id":       order_id,
        "order_type":     "cr_shop",
        "product_id":     product_id,
        "stock_id":       stock_ids[0] if stock_ids else "",
        "stock_ids":      stock_ids,
        "quantity":       quantity,
        "username":       username,
        "base_amount":    base_price,
        "truemoney_fee":  fee,
        "amount":         amount,
        "payment_method": payment_method,
        "status":         "pending",
        "created_at":     datetime.now(TZ_THAI).isoformat(),
        "expires_at":     expires,
        "qr_base64":      generate_qr_base64(amount) if payment_method == "promptpay" else None,
    }
    orders = _load_cr_orders()
    orders[order_id] = order
    _save_cr_orders(orders)
    _add_user_order(username, order_id)
    _supabase_upsert_cr_order(order)
    print(f"[CR] สร้าง order {order_id} product={product_id} qty={quantity} method={payment_method}")
    return order


def get_user_cr_purchases(username: str) -> list:
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.get(
                f"{SUPABASE_URL}/rest/v1/cr_stock",
                params={
                    "buyer_username": f"eq.{username}",
                    "status": "eq.sold",
                    "select": "id,license_key,sold_at,order_id,product_id,cr_products(name,price,duration,license_type,download_url)",
                    "order": "sold_at.desc",
                    "limit": "30",
                },
                headers=_sh(),
            )
        return resp.json() if resp.status_code == 200 else []
    except Exception as e:
        print(f"[CR] get_user_cr_purchases error: {e}")
        return []


def add_cr_product(name: str, description: str, license_type: str, duration: str, price: int,
                   download_url: str = "", name_en: str = "", description_en: str = "") -> dict | None:
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.post(
                f"{SUPABASE_URL}/rest/v1/cr_products",
                headers=_sh({"Content-Type": "application/json", "Prefer": "return=representation"}),
                json={"name": name, "description": description, "name_en": name_en,
                      "description_en": description_en, "license_type": license_type,
                      "duration": duration, "price": price, "download_url": download_url,
                      "is_active": True},
            )
        data = resp.json() if resp.status_code in (200, 201) else None
        return data[0] if isinstance(data, list) and data else None
    except Exception as e:
        print(f"[CR] add_product error: {e}")
        return None


def update_cr_product(product_id: str, name: str, description: str, price: int,
                      download_url: str = "", name_en: str = "", description_en: str = "") -> bool:
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.patch(
                f"{SUPABASE_URL}/rest/v1/cr_products",
                params={"id": f"eq.{product_id}"},
                headers=_sh({"Content-Type": "application/json", "Prefer": "return=minimal"}),
                json={"name": name, "description": description, "name_en": name_en,
                      "description_en": description_en, "price": price, "download_url": download_url},
            )
        return resp.status_code in (200, 204)
    except Exception as e:
        print(f"[CR] update_product error: {e}")
        return False


def toggle_cr_product(product_id: str, is_active: bool) -> bool:
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.patch(
                f"{SUPABASE_URL}/rest/v1/cr_products",
                params={"id": f"eq.{product_id}"},
                headers=_sh({"Content-Type": "application/json", "Prefer": "return=minimal"}),
                json={"is_active": is_active},
            )
        return resp.status_code in (200, 204)
    except Exception as e:
        print(f"[CR] toggle_product error: {e}")
        return False


def delete_cr_product(product_id: str) -> bool:
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.delete(
                f"{SUPABASE_URL}/rest/v1/cr_products",
                params={"id": f"eq.{product_id}"},
                headers=_sh(),
            )
        return resp.status_code in (200, 204)
    except Exception as e:
        print(f"[CR] delete_product error: {e}")
        return False


def add_cr_stock(product_id: str, license_key: str) -> dict | None:
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.post(
                f"{SUPABASE_URL}/rest/v1/cr_stock",
                headers=_sh({"Content-Type": "application/json", "Prefer": "return=representation"}),
                json={"product_id": product_id, "license_key": license_key, "status": "available"},
            )
        data = resp.json() if resp.status_code in (200, 201) else None
        return data[0] if isinstance(data, list) and data else None
    except Exception as e:
        print(f"[CR] add_stock error: {e}")
        return None


def delete_cr_stock(stock_id: str) -> bool:
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.delete(
                f"{SUPABASE_URL}/rest/v1/cr_stock",
                params={"id": f"eq.{stock_id}"},
                headers=_sh(),
            )
        return resp.status_code in (200, 204)
    except Exception as e:
        print(f"[CR] delete_stock error: {e}")
        return False


def get_cr_product_stock(product_id: str) -> list:
    release_expired_reserved_cr_stock(product_id)
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.get(
                f"{SUPABASE_URL}/rest/v1/cr_stock",
                params={"product_id": f"eq.{product_id}", "order": "created_at.asc",
                        "select": "id,status,buyer_username,sold_at,created_at"},
                headers=_sh(),
            )
        return resp.json() if resp.status_code == 200 else []
    except Exception as e:
        print(f"[CR] get_cr_product_stock error: {e}")
        return []


async def verify_cr_slip(slip_image_bytes: bytes, order_id: str) -> dict:
    """verify สลิป PromptPay สำหรับ CR order"""
    order = get_cr_order(order_id)
    if not order:
        return {"success": False, "reason": "ไม่พบ order นี้"}
    if is_order_expired(order):
        update_cr_order_status(order_id, "expired")
        return {"success": False, "reason": "order หมดอายุแล้ว กรุณาสั่งใหม่"}
    if order["status"] == "paid":
        return {"success": False, "reason": "order นี้ชำระแล้ว"}

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.easyslip.com/v2/verify/bank",
                headers={"Authorization": f"Bearer {EASYSLIP_API_KEY}"},
                files={"image": ("slip.jpg", slip_image_bytes, "image/jpeg")},
            )
        data = resp.json()
        print(f"[CR-EASYSLIP] response: {json.dumps(data, ensure_ascii=False)}")
    except Exception as e:
        return {"success": False, "reason": f"เช็คสลิปไม่ได้: {e}"}

    if not data.get("success"):
        msg = data.get("message") or "สลิปไม่ถูกต้อง"
        error_map = {
            "IMAGE_SIZE_TOO_LARGE": "ไฟล์สลิปใหญ่เกิน 4MB กรุณาบีบอัดรูปแล้วส่งใหม่",
            "INVALID_IMAGE_FORMAT": "รูปแบบไฟล์ไม่รองรับ กรุณาส่งเป็น JPG หรือ PNG",
            "SLIP_NOT_FOUND":       "ไม่พบ QR Code ในสลิป กรุณาส่งรูปให้ชัดขึ้น",
            "SLIP_PENDING":         "สลิปยังประมวลผลไม่เสร็จ กรุณารอสักครู่แล้วส่งใหม่",
        }
        return {"success": False, "reason": error_map.get(msg, f"EasySlip: {msg}")}

    slip_data = data.get("data", {})
    raw_slip = slip_data.get("rawSlip", {})
    received = float(raw_slip.get("amount", {}).get("amount", 0))
    expected = float(order["amount"])
    if received < expected - 0.01:
        return {"success": False, "reason": f"ยอดไม่ตรง คาดหวัง {expected:.2f} แต่ได้ {received:.2f} บาท"}

    transaction_id = raw_slip.get("transRef", "")
    used_slips = _load_slips()
    if transaction_id and (transaction_id in used_slips or _is_transaction_used(transaction_id)):
        return {"success": False, "reason": "สลิปนี้ถูกใช้ไปแล้ว"}
    if slip_data.get("isDuplicate"):
        return {"success": False, "reason": "สลิปนี้ถูกใช้ไปแล้ว (duplicate detected)"}

    update_cr_order_status(order_id, "paid", {
        "paid_at": datetime.now(TZ_THAI).isoformat(),
        "transaction_id": transaction_id,
        "received": received,
    })
    print(f"[CR-EASYSLIP] ✅ order {order_id} ชำระแล้ว {received} บาท")
    return {"success": True, "reason": "ชำระเงินสำเร็จ", "transaction_id": transaction_id}


async def redeem_truemoney_voucher_cr(voucher_code: str, order_id: str) -> dict:
    """verify ซองอั่งเป่า TrueMoney สำหรับ CR order"""
    order = get_cr_order(order_id)
    if not order:
        return {"success": False, "reason": "ไม่พบ order นี้"}
    if is_order_expired(order):
        update_cr_order_status(order_id, "expired")
        return {"success": False, "reason": "order หมดอายุแล้ว กรุณาสั่งใหม่"}
    if order["status"] == "paid":
        return {"success": False, "reason": "order นี้ชำระแล้ว"}

    voucher_hash = _extract_voucher_hash(voucher_code)
    if not voucher_hash:
        return {"success": False, "reason": "กรุณากรอกโค้ด/ลิงก์ซองอั่งเป่า"}

    used_slips = _load_slips()
    if voucher_hash in used_slips:
        return {"success": False, "reason": "ซองอั่งเป่านี้ถูกใช้ไปแล้ว"}

    mobile = TRUEMONEY_ID.replace("-", "").replace(" ", "")
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
        data = resp.json()
        print(f"[CR-ANGPAO] response: {json.dumps(data, ensure_ascii=False)}")
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
    received = float(amount_baht) if amount_baht is not None else float(data.get("amount", 0)) / 100

    expected = float(order["amount"])
    if received < expected - 0.01:
        credited = max(0, int(received))
        username = order.get("username")
        if credited > 0 and username:
            credit_wallet(username, credited)
            remaining = int(expected) - credited
            tw_needed = remaining
            while tw_needed - truemoney_fee(tw_needed) < remaining:
                tw_needed += 1
            return {
                "success": False, "insufficient": True,
                "credited": credited, "remaining": remaining,
                "reason": (
                    f"ซองอั่งเป่าของคุณมียอดไม่พอนะครับ 😅\n\n"
                    f"💸 ยอดที่ได้รับ: ฿{received:.2f} (หลังหักค่าธรรมเนียม TrueWallet 2.9%)\n"
                    f"💰 เราเก็บเงินส่วนนี้ไว้ในกระเป๋าเงินให้แล้ว: ฿{credited}\n"
                    f"❗ ยังขาดอีก: ฿{remaining}\n\n"
                    f"เติมเงินเพิ่มเข้ากระเป๋าเงินได้ 2 วิธีครับ\n"
                    f"🏦 PromptPay — โอน ฿{remaining} พอดี\n"
                    f"💚 TrueWallet — ส่งซอง ฿{tw_needed} (รวมค่าธรรมเนียม 2.9% แล้ว)\n\n"
                    f"แล้วกลับมากด \"ชำระส่วนที่เหลือด้วย wallet\" ได้เลยครับ"
                ),
            }
        return {"success": False, "reason": f"ยอดไม่ตรง คาดหวัง {expected:.2f} แต่ได้ {received:.2f} บาท"}

    surplus = max(0, int(received) - int(expected))
    update_cr_order_status(order_id, "paid", {
        "paid_at": datetime.now(TZ_THAI).isoformat(),
        "transaction_id": voucher_hash,
        "received": received,
    })
    print(f"[CR-ANGPAO] ✅ order {order_id} ชำระแล้ว {received} บาท" + (f" surplus ฿{surplus}" if surplus else ""))
    return {"success": True, "reason": "ชำระเงินสำเร็จ", "transaction_id": voucher_hash, "surplus": surplus}
