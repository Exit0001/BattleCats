# payment.py - ระบบ QR PromptPay + เช็คสลิปด้วย SlipOK API

import qrcode
import qrcode.image.svg
import io
import base64
import json
import uuid
import httpx
from datetime import datetime, timedelta
from pathlib import Path

# ══════════════════════════════════════════
# CONFIG — แก้ค่าตรงนี้
# ══════════════════════════════════════════

PROMPTPAY_ID   = "0634515901"            # เบอร์ / เลขบัตรปชช ที่รับเงิน
TRUEMONEY_ID   = "0634515901"       # TrueMoney Wallet phone number (แก้ถ้าต่างกัน)
SLIPOK_API_KEY = "SLIPOKR9NYYUU"  # API Key จาก slipok.com
ORDER_DB       = Path("orders.json")
SLIP_DB        = Path("used_slips.json")
ORDER_TIMEOUT  = 15  # นาที หมดอายุ

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
    # All-character packages (fixed price, amount=1)
    "upgrade_all":   {1: 200},
    "unlock_all":    {1: 200},
    "trueform_all":  {1: 100},
    "ultraform_all": {1: 100},
    "talents_all":   {1: 150},
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

def _load_slips() -> list:
    if SLIP_DB.exists():
        return json.loads(SLIP_DB.read_text(encoding="utf-8"))
    return []

def _save_slips(data: list):
    SLIP_DB.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

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
            raise ValueError(f"ไม่พบราคาสินค้า: {key}")
        price = price_table.get(amount)
        if price is None:
            raise ValueError(f"ไม่พบราคาสำหรับ {key} จำนวน {amount}")
        total += price
    return total


def create_order(transfer_code: str, confirmation_code: str,
                 country: str, items: list[dict],
                 cat_ids: list | None = None,
                 cat_unlock_total: int = 0,
                 payment_method: str = "promptpay") -> dict:
    """
    สร้าง order ใหม่ บันทึกลง DB และสร้าง QR
    คืน order object ที่มี order_id, amount, qr_base64
    """
    order_id = str(uuid.uuid4())[:8].upper()
    amount   = calculate_total(items) + cat_unlock_total  # รวมราคาปลดล็อคแมวด้วย
    expires  = (datetime.now() + timedelta(minutes=ORDER_TIMEOUT)).isoformat()

    order = {
        "order_id":          order_id,
        "transfer_code":     transfer_code,
        "confirmation_code": confirmation_code,
        "country":           country,
        "items":             items,
        "cat_ids":           cat_ids or [],
        "amount":            amount,
        "payment_method":    payment_method,
        "status":            "pending",
        "created_at":        datetime.now().isoformat(),
        "expires_at":        expires,
        "qr_base64":         generate_qr_base64(amount) if payment_method == "promptpay" else None,
    }

    orders = _load_orders()
    orders[order_id] = order
    _save_orders(orders)

    print(f"[ORDER] สร้าง order {order_id} ยอด {amount} บาท หมดอายุ {expires}")
    return order


def create_all_package_order(transfer_code: str, confirmation_code: str,
                             country: str, package_type: str, amount: int,
                             payment_method: str = "promptpay") -> dict:
    """สร้าง order สำหรับแพ็กเกจ All (unlock_all, trueform_all, ฯลฯ)"""
    order_id = str(uuid.uuid4())[:8].upper()
    expires  = (datetime.now() + timedelta(minutes=ORDER_TIMEOUT)).isoformat()
    order = {
        "order_id":          order_id,
        "transfer_code":     transfer_code,
        "confirmation_code": confirmation_code,
        "country":           country,
        "items":             [],
        "cat_ids":           [],
        "package_type":      package_type,
        "amount":            amount,
        "payment_method":    payment_method,
        "status":            "pending",
        "created_at":        datetime.now().isoformat(),
        "expires_at":        expires,
        "qr_base64":         generate_qr_base64(amount) if payment_method == "promptpay" else None,
    }
    orders = _load_orders()
    orders[order_id] = order
    _save_orders(orders)
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


def is_order_expired(order: dict) -> bool:
    """เช็คว่า order หมดอายุแล้วหรือยัง"""
    expires = datetime.fromisoformat(order["expires_at"])
    return datetime.now() > expires

# ══════════════════════════════════════════
# SLIPOK VERIFICATION
# ══════════════════════════════════════════

async def verify_slip(slip_image_bytes: bytes, order_id: str) -> dict:
    """
    ส่งสลิปไปเช็คกับ SlipOK API
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

    # ── ส่งสลิปไป SlipOK ──
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.slipok.com/api/line/apikey/67138",
                headers={"x-authorization": SLIPOK_API_KEY},
                files={"files": ("slip.jpg", slip_image_bytes, "image/jpeg")},
                data={"log": "true"},
            )
        data = resp.json()
        print(f"[SLIPOK] response: {json.dumps(data, ensure_ascii=False)}")
    except Exception as e:
        return {"success": False, "reason": f"เช็คสลิปไม่ได้: {e}"}

    # ── ตรวจผลลัพธ์ ──
    if not data.get("success"):
        msg = data.get("message") or data.get("code") or "สลิปไม่ถูกต้อง"
        # SlipOK ขัดข้องชั่วคราว (ไม่หักโควต้า) → ให้ลูกค้าส่งใหม่ภายหลัง
        if "ขัดข้องชั่วคราว" in msg or "ขณะนี้" in msg:
            return {"success": False, "reason": "ระบบตรวจสลิปขัดข้องชั่วคราว กรุณาลองส่งสลิปอีกครั้งใน 15 นาที (ไม่เสียโควต้า)"}
        return {"success": False, "reason": f"SlipOK: {msg}"}

    slip_data = data.get("data", {})

    # 1) เช็คยอดตรง (อนุญาต ±0 บาท)
    received = float(slip_data.get("amount", 0))
    expected = float(order["amount"])
    if abs(received - expected) > 0.01:
        return {"success": False, "reason": f"ยอดไม่ตรง คาดหวัง {expected:.2f} แต่ได้ {received:.2f} บาท"}

    # 2) เช็คสลิปซ้ำ
    transaction_id = slip_data.get("transRef") or slip_data.get("transId") or ""
    used_slips = _load_slips()
    if transaction_id and transaction_id in used_slips:
        return {"success": False, "reason": "สลิปนี้ถูกใช้ไปแล้ว"}

    # ── อัปเดต order เป็น paid (ยังไม่บันทึกสลิป รอให้ BCSFE สำเร็จก่อน) ──
    received = float(slip_data.get("amount", order["amount"]))

    update_order_status(order_id, "paid", {
        "paid_at":        datetime.now().isoformat(),
        "transaction_id": transaction_id,
        "received":       received,
    })

    print(f"[SLIPOK] ✅ order {order_id} ชำระแล้ว {received} บาท")
    return {"success": True, "reason": "ชำระเงินสำเร็จ", "transaction_id": transaction_id}


def create_unlock_order(transfer_code: str, confirmation_code: str,
                        country: str, cat_ids: list, amount: int,
                        payment_method: str = "promptpay") -> dict:
    """สร้าง order สำหรับปลดล็อคแมว พร้อม QR PromptPay"""
    order_id = str(uuid.uuid4())[:8].upper()
    expires  = (datetime.now() + timedelta(minutes=ORDER_TIMEOUT)).isoformat()
    order = {
        "order_id":          order_id,
        "order_type":        "unlock",
        "transfer_code":     transfer_code,
        "confirmation_code": confirmation_code,
        "country":           country,
        "cat_ids":           cat_ids,
        "items":             [],
        "amount":            amount,
        "payment_method":    payment_method,
        "status":            "pending",
        "created_at":        datetime.now().isoformat(),
        "expires_at":        expires,
        "qr_base64":         generate_qr_base64(amount) if payment_method == "promptpay" else None,
    }
    orders = _load_orders()
    orders[order_id] = order
    _save_orders(orders)
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