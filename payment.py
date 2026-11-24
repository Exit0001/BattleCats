# payment.py - ระบบ QR PromptPay + เช็คสลิปด้วย EasySlip API

import qrcode
import qrcode.image.svg
import io
import base64
import json
import math
import re
import uuid
import asyncio
import time
import os
import threading
import httpx
from curl_cffi.requests import AsyncSession as CurlSession

# ── แก้ปัญหา SSL บนเครื่อง dev ที่ path มีภาษาไทย ──────────────────
# libcurl เป็นไลบรารี C อ่าน path ที่มีอักษรนอก ASCII ไม่ได้บน Windows
# ทำให้ curl_cffi โหลด cacert.pem ไม่สำเร็จ -> curl error 77
# แก้โดย copy ไฟล์ไป temp ที่เป็น ASCII ล้วน แล้วชี้ CURL_CA_BUNDLE ไปที่นั่น
# บน VPS path เป็น /battlecats/ (ASCII) เงื่อนไขนี้จะไม่ทำงาน ไม่กระทบ production
try:
    import os as _os, shutil as _shutil, tempfile as _tempfile, certifi as _certifi
    _ca = _certifi.where()
    if not _ca.isascii():
        _ca_ascii = _os.path.join(_tempfile.gettempdir(), "bc_cacert.pem")
        if not _os.path.exists(_ca_ascii):
            _shutil.copyfile(_ca, _ca_ascii)
        _os.environ.setdefault("CURL_CA_BUNDLE", _ca_ascii)
        print(f"[SSL] path certifi มีภาษาไทย -> ใช้ {_ca_ascii} แทน")
except Exception as _e:
    print(f"[SSL] ตั้ง CA bundle ไม่สำเร็จ: {_e}")
from datetime import datetime, timedelta, timezone

TZ_THAI = timezone(timedelta(hours=7))
from pathlib import Path

# ══════════════════════════════════════════
# CONFIG — แก้ค่าตรงนี้
# ══════════════════════════════════════════

PROMPTPAY_ID   = "004999236376637"       # K PLUS e-Wallet ID (15 หลัก) ที่รับเงิน
KBANK_ACCOUNT  = "2278616293"            # บัญชีกสิกรที่ผูกกับ PromptPay (EasySlip อาจ return เลขนี้แทน)
ALLOWED_RECEIVERS = {PROMPTPAY_ID, KBANK_ACCOUNT}  # receiver ที่รับได้
TRUEMONEY_ID   = "0634515901"       # TrueMoney Wallet phone number (แก้ถ้าต่างกัน)

# ── Proxy สำหรับเรียก TrueMoney (อั่งเป่า) ────────────────────────
# Cloudflare ของ TrueMoney บล็อก IP ศูนย์ข้อมูล (VPS) แต่ IP บ้าน (residential) ผ่านได้
# ใส่ residential proxy ไทยตรงนี้เพื่อให้ระบบอั่งเป่ากลับมาใช้งานได้
#   รูปแบบ : "http://user:pass@host:port"
#   ว่าง "" = ไม่ใช้ proxy (ยิงตรงจาก VPS -> จะโดน 403)
# IPRoyal residential (whitelist IP ของ VPS ไว้แล้ว จึงไม่ต้องใส่ user/pass)
#   IP ที่ whitelist : 187.77.156.253   |  ประเทศ : TH  |  order 81487917
#   ต้องใช้คู่กับ curl_cffi (impersonate) เท่านั้น — curl ธรรมดาจะโดน Cloudflare 403
# VPS ต้องยิงผ่าน proxy ไทย (IP datacenter โดน Cloudflare ของ TrueMoney บล็อก)
# เทสที่บ้าน: IP บ้านไม่อยู่ใน whitelist ของ IPRoyal จะได้ 407 -> สั่ง ANGPAO_PROXY="" ตอนเปิดเซิร์ฟเวอร์เพื่อไม่ใช้ proxy
ANGPAO_PROXY = os.getenv("ANGPAO_PROXY", "http://geo.iproyal.com:12321")

def _angpao_session_kwargs() -> dict:
    """ตัวเลือกที่ส่งให้ CurlSession — ใส่ proxy ถ้าตั้งค่าไว้"""
    kw = {"impersonate": "chrome136"}
    if ANGPAO_PROXY:
        kw["proxies"] = {"http": ANGPAO_PROXY, "https": ANGPAO_PROXY}
    return kw
EASYSLIP_API_KEY = "1c49e3f0-85f9-4718-b3f6-de74ec35fe30"  # API Key จาก easyslip.com

# ── Slip provider switch ──  "easyslip" | "slip2go"
SLIP_PROVIDER    = "slip2go"
SLIP2GO_API_KEY  = "yO1I5a+lTFR3j8WcEmS8t8A1IHyEXnv7hC0FgdZaNjs="
SLIP2GO_API_URL  = "https://connect.slip2go.com/api/verify-slip/qr-image/info"
ORDER_DB       = Path("orders.json")
SLIP_DB        = Path("used_slips.json")
USER_ORDERS_DB = Path("user_orders.json")
ORDER_TIMEOUT  = 15  # นาที หมดอายุ

SUPABASE_URL = "https://jpzceuxeelnwthaitkcw.supabase.co"
SUPABASE_KEY = "sb_publishable_VhQvIEjYgaDy0eW1qaIkyw_cxb5eZly"

# ══════════════════════════════════════════
# PROMOTION — ลดราคาทั้งร้านตามช่วงเวลา (ไม่รวม Cookie Run / เติมเงิน wallet)
# ══════════════════════════════════════════
# ⚠️ ถ้าแก้วัน/เปอร์เซ็นต์ ต้องแก้ใน assets/promo.js ให้ตรงกันด้วย (ใช้แสดงราคาบนหน้าเว็บ)
PROMO_START   = datetime(2026, 11, 1, 0, 0, tzinfo=TZ_THAI)   # เริ่ม 1 พ.ย. 2569 00:00
PROMO_END     = datetime(2026, 11, 11, 0, 0, tzinfo=TZ_THAI)  # จบ 10 พ.ย. 2569 23:59 (หมดตอน 11 พ.ย. 00:00)
PROMO_PERCENT = 25
# เทสใน local: ตั้ง PROMO_FORCE=1 ตอนเปิดเซิร์ฟเวอร์ = เปิดโปรทันทีไม่สนวันที่ (ห้ามตั้งบน VPS)
PROMO_FORCE   = os.getenv("PROMO_FORCE", "") == "1"
# เทสตั้งเวลาล่วงหน้าใน local: PROMO_TEST_START / PROMO_TEST_END = "2026-10-26T18:15:00+07:00" (ห้ามตั้งบน VPS)
if os.getenv("PROMO_TEST_START"):
    PROMO_START = datetime.fromisoformat(os.environ["PROMO_TEST_START"])
if os.getenv("PROMO_TEST_END"):
    PROMO_END = datetime.fromisoformat(os.environ["PROMO_TEST_END"])

def promo_active() -> bool:
    if PROMO_FORCE:
        return True
    return PROMO_START <= datetime.now(TZ_THAI) < PROMO_END

def promo_price(price: int) -> int:
    """ราคาหลังลด (คิดทีละชิ้น ปัดครึ่งขึ้น: 35→26, 39→29, 10→8, 15→11)
    ต้องตรงกับ BCPromo.price() ใน assets/promo.js"""
    if not price or not promo_active():
        return price
    return (int(price) * (100 - PROMO_PERCENT) + 50) // 100

def promo_info() -> dict:
    # ก่อนโปรเริ่ม ไม่บอกวัน/เปอร์เซ็นต์ (กันลูกค้ารู้ล่วงหน้าจาก /api/promo)
    if not promo_active():
        return {"active": False}
    return {"active": True, "percent": PROMO_PERCENT}
    # return {
    #     "active":  promo_active(),
    #     "percent": PROMO_PERCENT,
    #     "start":   PROMO_START.isoformat(),
    #     "end":     PROMO_END.isoformat(),
    # }

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
    "base_material": {
        30:  20,
        100: 49,
        500: 149,
        999: 249,
    },
    "talent_orb_s":       {1: 49, 5: 99, 10: 149, 30: 249},
    "talent_orb_a":       {1: 29, 5: 59, 10: 89, 30: 149},
    "gamatoto_level":     {50: 29, 80: 49, 100: 79, 130: 200},
    "gamatoto_lackey":    {10: 19},
    "gamatoto_underling": {10: 39},
    "gamatoto_assistant": {10: 69},
    "gamatoto_legend":    {10: 120},
    # Per-cat services (price per 1 cat)
    "upgrade_cat":      {1: 15},
    "upgrade_plus_cat": {1: 100},
    "trueform_cat":     {1: 15},
    "ultraform_cat":    {1: 20},
    "talents_cat":      {1: 20},
    # All-character packages — ราคาอยู่ใน ALL_PACKAGE_MAP ใน main.py แล้ว ห้ามซ้ำตรงนี้
}

# ══════════════════════════════════════════
# ORDER DB HELPERS
# ══════════════════════════════════════════

# lock กันอ่าน/เขียน orders.json ชนกัน — หน้าประวัติยิง /api/payment/status ~30 ออเดอร์พร้อมกัน
# แต่ละ request ที่ fallback ไป Supabase จะ load+save ไฟล์นี้ ถ้าไม่ล็อค: tmp ชื่อเดียวกันถูกเขียนทับ/ย้ายชนกัน
# -> "No such file: orders.tmp -> orders.json" (ตอบ 404 = "ไม่ทราบสถานะ") และไฟล์พังจนถูก rename เป็น .corrupt
_ORDERS_LOCK = threading.RLock()

def _load_orders() -> dict:
    with _ORDERS_LOCK:
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
    with _ORDERS_LOCK:
        # tmp ชื่อไม่ซ้ำต่อครั้ง เผื่อมีคนเขียนนอก lock (เช่น process อื่น) จะได้ไม่ชนกัน
        tmp = ORDER_DB.with_name(f"{ORDER_DB.stem}.{os.getpid()}.{threading.get_ident()}.tmp")
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
        total += promo_price(price)
        # total += price
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
                # sync กลับมาเก็บใน local JSON ด้วย — ทำใน lock เดียวกันทั้ง load+save จะได้ไม่ทับกันเอง
                # และถ้าเขียนไฟล์ไม่สำเร็จก็ยังต้องคืน order ให้ผู้เรียก (ห้ามตอบ 404 ทั้งที่มีออเดอร์)
                try:
                    with _ORDERS_LOCK:
                        orders = _load_orders()
                        orders[order_id] = order
                        _save_orders(orders)
                    print(f"[SUPABASE] ✔ recovered order {order_id} from Supabase")
                except Exception as e:
                    print(f"[SUPABASE] ⚠ recovered {order_id} but local save failed: {e}")
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
    with _ORDERS_LOCK:
        orders = _load_orders()
        if order_id in orders:
            orders[order_id]["status"] = status
            orders[order_id].update(extra)
            _save_orders(orders)
            row = orders[order_id]
        else:
            row = None
    if row is not None:
        _supabase_upsert(row)


def is_order_expired(order: dict) -> bool:
    """เช็คว่า order หมดอายุแล้วหรือยัง"""
    expires = datetime.fromisoformat(order["expires_at"])
    return datetime.now(TZ_THAI) > expires

# ══════════════════════════════════════════
# SLIP VERIFICATION — รองรับ 2 provider (EasySlip / Slip2Go)
# ══════════════════════════════════════════
#
# ทั้ง 2 provider return "normalized dict" หน้าตาเดียวกัน เพื่อให้ verify_slip()
# ตรวจ security เหมือนเดิมโดยไม่ต้องแยก logic:
#
#   {"ok": bool, "reason": str,
#    "recv_name_th": str, "recv_name_en": str,
#    "recv_proxy_type": str, "recv_proxy_acct": str, "recv_bank_acct": str,
#    "amount": float, "trans_ref": str, "is_duplicate": bool}
#

# ต่อท้าย error ที่เป็น "อาการชั่วคราว" เท่านั้น (ลองใหม่แล้วผ่านได้)
# ห้ามใส่กับ error ที่สลิปผิดจริง เช่น โอนผิดบัญชี / สลิปซ้ำ / ยอดไม่ตรง
_RETRY_HINT = " — หากลองแล้วยังไม่ได้ ให้กดยกเลิก order นี้ แล้วทำรายการใหม่ (ใช้สลิปเดิมได้เลย)"

async def _call_easyslip(slip_image_bytes: bytes) -> dict:
    """เรียก EasySlip API แล้ว normalize ผลลัพธ์"""
    _ef, _em = _sniff_image(slip_image_bytes)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.easyslip.com/v2/verify/bank",
                headers={"Authorization": f"Bearer {EASYSLIP_API_KEY}"},
                files={"image": (_ef, slip_image_bytes, _em)},
                data={"matchAccount": "true"},
            )
        print(f"[EASYSLIP] status={resp.status_code} body={resp.text[:500]}")
        if resp.status_code in (502, 503, 504):
            return {"ok": False, "reason": "ระบบเช็คสลิปขัดข้องชั่วคราว (EasySlip server down) กรุณารอสักครู่แล้วลองใหม่" + _RETRY_HINT}
        if resp.status_code == 401:
            return {"ok": False, "reason": "EasySlip API Key หมดอายุหรือไม่ถูกต้อง กรุณาติดต่อแอดมิน"}
        try:
            data = resp.json()
        except Exception:
            return {"ok": False, "reason": f"EasySlip ตอบกลับผิดปกติ (status {resp.status_code}) กรุณาลองใหม่" + _RETRY_HINT}
        print(f"[EASYSLIP] response: {json.dumps(data, ensure_ascii=False)}")
    except Exception as e:
        reason = str(e) if str(e) else "เชื่อมต่อ EasySlip ไม่ได้ กรุณาลองใหม่อีกครั้ง"
        return {"ok": False, "reason": f"เช็คสลิปไม่ได้: {reason}" + _RETRY_HINT}

    if not data.get("success"):
        msg = data.get("message") or "สลิปไม่ถูกต้อง"
        error_map = {
            "IMAGE_SIZE_TOO_LARGE": "ไฟล์สลิปใหญ่เกิน 4MB กรุณาบีบอัดรูปแล้วส่งใหม่",
            "INVALID_IMAGE_FORMAT": "รูปแบบไฟล์ไม่รองรับ กรุณาส่งเป็น JPG หรือ PNG",
            "SLIP_NOT_FOUND":       "ไม่พบ QR Code ในสลิป กรุณาส่งรูปให้ชัดขึ้น",
            "SLIP_PENDING":         "สลิปยังประมวลผลไม่เสร็จ กรุณารอสักครู่แล้วส่งใหม่",
        }
        return {"ok": False, "reason": error_map.get(msg, f"EasySlip: {msg}")}

    slip_data = data.get("data", {})
    _raw      = slip_data.get("rawSlip", {})
    _recv_acc = _raw.get("receiver", {}).get("account", {})
    _proxy    = _recv_acc.get("proxy", {}) or {}
    _bank     = _recv_acc.get("bank",  {}) or {}
    _name_obj = _recv_acc.get("name",  {}) or {}

    return {
        "ok": True,
        "recv_name_th":    (_name_obj.get("th", "") or "").strip(),
        "recv_name_en":    (_name_obj.get("en", "") or "").strip(),
        "recv_proxy_type": _proxy.get("type", ""),
        "recv_proxy_acct": (_proxy.get("account", "") or "").replace("-", "").replace(" ", ""),
        "recv_bank_acct":  (_bank.get("account", "") or "").replace("-", "").replace(" ", ""),
        "amount":          float(_raw.get("amount", {}).get("amount", 0)),
        "trans_ref":       _raw.get("transRef", ""),
        "is_duplicate":    bool(slip_data.get("isDuplicate")),
    }


def _sniff_image(data: bytes):
    """
    เดาชนิดรูปจาก magic bytes → คืน (filename, mime)

    เดิม hardcode เป็น slip.jpg/image/jpeg เสมอ ทำให้ตอนลูกค้าอัปโหลด PNG
    เราไปบอก API ว่าเป็น JPEG ซึ่งอาจทำให้ฝั่งเขา error ได้
    """
    if data[:8] == bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]):
        return ("slip.png", "image/png")
    if data[:3] == bytes([0xFF, 0xD8, 0xFF]):
        return ("slip.jpg", "image/jpeg")
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ("slip.webp", "image/webp")
    return ("slip.jpg", "image/jpeg")   # fallback เดิม


SLIP2GO_LOG = Path("logs") / "slip2go.log"

def _slip2go_log(line: str):
    """บันทึกทุก response ของ Slip2Go ลงไฟล์ — ใช้เป็นหลักฐานส่ง support"""
    try:
        SLIP2GO_LOG.parent.mkdir(exist_ok=True)
        ts = datetime.now(TZ_THAI).strftime("%Y-%m-%d %H:%M:%S")
        with io.open(SLIP2GO_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {line}\n")
    except Exception:
        pass


async def _call_slip2go(slip_image_bytes: bytes) -> dict:
    """
    เรียก Slip2Go API (endpoint แบบส่งรูป) แล้ว normalize ผลลัพธ์

    Slip2Go ตอบ 5xx เป็นช่วงๆ (intermittent) → retry เองเงียบๆ ก่อน
    ลูกค้าจะไม่เห็น error ถ้าลองซ้ำแล้วผ่าน
    """
    # จากข้อมูลจริง (เก็บ 1 ชม. 31 ส.ค. 69): Slip2Go 502 เป็นช่วงๆ uptime ~86%
    # ช่วงที่ล่มมักหายภายใน ~30 วิ → backoff ต้องกว้างพอจะข้ามช่วงนั้น
    #   ปกติตอบ ~300ms | ตอน 502 ก็ตอบเร็ว (~280ms) → เวลาส่วนใหญ่คือ backoff ไม่ใช่ timeout
    #   เคส 502 ล้วน  : 0.3*5 + 30 ≈ 31 วิ
    #   เคสค้างจริง   : ตัดที่ _DEADLINE
    _ATTEMPTS = 5
    _TIMEOUT  = 10
    _BACKOFF  = (2.0, 5.0, 8.0, 15.0)   # รวม 30 วิ — ครอบคลุมช่วง 502 ที่เคยเจอ (26 วิ)
    _DEADLINE = 55                       # เพดานรวม กันลูกค้ารอเป็นนาที

    _fname, _mime = _sniff_image(slip_image_bytes)
    _t_start = time.monotonic()
    resp = None
    last_err = None
    for attempt in range(1, _ATTEMPTS + 1):
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    SLIP2GO_API_URL,
                    headers={"Authorization": f"Bearer {SLIP2GO_API_KEY}"},
                    files={"file": (_fname, slip_image_bytes, _mime)},
                )
            print(f"[SLIP2GO] attempt {attempt}/{_ATTEMPTS} status={resp.status_code} body={resp.text[:500]}")
            _slip2go_log(f"attempt {attempt}/{_ATTEMPTS} HTTP {resp.status_code} | {resp.text[:400]}")
            if resp.status_code < 500:
                # 200502 = "Bank error" — Slip2Go ยืนยันว่าเป็นฝั่งธนาคารขัดข้อง
                # สลิปยังไม่ทันถึงขั้นตอนตรวจ, ให้รอแล้วลองใหม่, และ "ไม่หักโทเคน"
                # → ถือเป็น transient ต้อง retry (มาพร้อม HTTP 200 เลยหลุด check ข้างบน)
                if '"200502"' not in resp.text:
                    break      # ได้คำตอบจริง (สำเร็จ หรือ error ที่ retry ไปก็ไม่ช่วย)
                last_err = "code 200502 (Bank error)"
            else:
                last_err = f"HTTP {resp.status_code}"
        except Exception as e:
            resp = None
            last_err = f"{type(e).__name__}: {e}"
            print(f"[SLIP2GO] attempt {attempt}/{_ATTEMPTS} ❌ {last_err}")
            _slip2go_log(f"attempt {attempt}/{_ATTEMPTS} EXCEPTION | {last_err}")

        if attempt < _ATTEMPTS:
            delay = _BACKOFF[attempt - 1]
            elapsed = time.monotonic() - _t_start
            if elapsed + delay > _DEADLINE:
                print(f"[SLIP2GO] ถึง deadline {_DEADLINE}s แล้ว หยุด retry")
                _slip2go_log(f"หยุด retry ที่ attempt {attempt}/{_ATTEMPTS} (deadline {_DEADLINE}s)")
                break
            print(f"[SLIP2GO] retry ใน {delay}s... (ผ่านไป {elapsed:.1f}s)")
            await asyncio.sleep(delay)

    # ครบทุกรอบแล้วยังไม่ได้คำตอบ
    if resp is None:
        return {"ok": False, "reason": f"เชื่อมต่อ Slip2Go ไม่ได้ ({last_err}) ลองแล้ว {_ATTEMPTS} ครั้ง" + _RETRY_HINT}
    if resp.status_code >= 500:
        return {"ok": False, "reason": f"ระบบเช็คสลิปขัดข้องชั่วคราว (Slip2Go {resp.status_code}) ลองแล้ว {_ATTEMPTS} ครั้ง" + _RETRY_HINT}
    if resp.status_code in (401, 403):
        return {"ok": False, "reason": "Slip2Go API Key ไม่ถูกต้อง/ไม่มีสิทธิ์ กรุณาติดต่อแอดมิน"}
    try:
        data = resp.json()
    except Exception:
        return {"ok": False, "reason": f"Slip2Go ตอบกลับผิดปกติ (status {resp.status_code}) กรุณาลองใหม่" + _RETRY_HINT}
    print(f"[SLIP2GO] response: {json.dumps(data, ensure_ascii=False)}")

    code = str(data.get("code", ""))
    if code != "200000":
        msg = data.get("message") or "สลิปไม่ถูกต้อง"
        error_map = {
            "401001": "Slip2Go: Token ไม่ถูกต้อง กรุณาติดต่อแอดมิน",
            "401002": "Slip2Go: ไม่พบร้านค้า (Shop not found) กรุณาติดต่อแอดมิน",
            "400002": "ไฟล์สลิปไม่ถูกต้อง กรุณาส่งเป็น JPG หรือ PNG ที่ชัดเจน",
            "200500": "ไม่ใช่สลิปโอนเงินที่ถูกต้อง กรุณาส่งรูปสลิปจริงที่เห็น QR ชัดเจน",  # Slip is fraud
            "404000": "ไม่พบข้อมูลสลิปนี้ในระบบธนาคาร กรุณาตรวจสอบสลิปอีกครั้ง",
            # Slip2Go support ยืนยัน: ธนาคารส่งข้อมูลช้า ครั้งแรกเลยหาไม่เจอ ให้รอ 5-10 นาที
            "200404": "ธนาคารยังส่งข้อมูลมาไม่ถึงระบบตรวจสอบ — เงินของคุณไม่หาย ไม่ต้องโอนใหม่ กรุณารอ 5-10 นาที แล้วส่งสลิปใบเดิมอีกครั้ง" + _RETRY_HINT,
            "200502": "ธนาคารขัดข้องชั่วคราว (ไม่ใช่ปัญหาที่สลิปของคุณ) ลองแล้ว 3 ครั้ง กรุณารอ 1-2 นาทีแล้วลองใหม่" + _RETRY_HINT,
        }
        return {"ok": False, "reason": error_map.get(code, f"Slip2Go [{code}]: {msg}")}

    d         = data.get("data", {}) or {}
    _recv     = d.get("receiver", {}) or {}
    _recv_acc = _recv.get("account", {}) or {}
    _proxy    = _recv_acc.get("proxy", {}) or {}
    _bank     = _recv_acc.get("bank",  {}) or {}
    # Slip2Go ส่งชื่อมาช่องเดียว และอาจเป็น "ไทย" หรือ "อังกฤษ" ก็ได้ แล้วแต่ธนาคาร
    #   PromptPay/e-wallet → "Mr. Sorawit T"   |  โอนบัญชีธนาคาร → "นาย สรวิชญ์ ท"
    # → ใส่ทั้ง 2 ช่อง เพื่อให้ verify_slip() เช็คได้ทั้งไทยและอังกฤษ
    _name     = (_recv_acc.get("name", "") or "").strip()

    return {
        "ok": True,
        "recv_name_th":    _name,
        "recv_name_en":    _name,
        "recv_proxy_type": _proxy.get("type", ""),
        "recv_proxy_acct": (_proxy.get("account", "") or "").replace("-", "").replace(" ", ""),
        "recv_bank_acct":  (_bank.get("account", "") or "").replace("-", "").replace(" ", ""),
        "amount":          float(d.get("amount", 0) or 0),
        "trans_ref":       d.get("transRef", "") or "",
        "is_duplicate":    False,   # Slip2Go ไม่มี field นี้ — ใช้ used_slips + Supabase แทน
    }


async def verify_slip(slip_image_bytes: bytes, order_id: str) -> dict:
    """
    ส่งสลิปไปเช็คกับ slip provider ที่เลือกไว้ (SLIP_PROVIDER)
    คืน {"success": True/False, "reason": "..."}
    """
    order = get_order(order_id)
    if not order:
        return {"success": False, "reason": "ไม่พบ order นี้"}

    if is_order_expired(order):
        update_order_status(order_id, "expired")
        return {"success": False, "reason": "order หมดอายุแล้ว กรุณากดยกเลิก แล้วทำรายการใหม่ (ใส่สลิปเดิมได้เลย)"}

    if order["status"] == "paid":
        return {"success": False, "reason": "order นี้ชำระแล้ว"}

    # ── ส่งสลิปไป provider ที่เลือกไว้ ──
    if SLIP_PROVIDER == "slip2go":
        _r = await _call_slip2go(slip_image_bytes)
    else:
        _r = await _call_easyslip(slip_image_bytes)

    _TAG = SLIP_PROVIDER.upper()
    if not _r.get("ok"):
        return {"success": False, "reason": _r.get("reason", "เช็คสลิปไม่สำเร็จ")}

    # 0) เช็ค receiver — ต้องโอนเข้าบัญชีร้านเราเท่านั้น
    _proxy_type   = _r["recv_proxy_type"]
    _proxy_acct   = _r["recv_proxy_acct"]
    _bank_acct    = _r["recv_bank_acct"]
    _recv_name_th = _r["recv_name_th"]
    _recv_name_en = _r["recv_name_en"]
    print(f"[{_TAG}] receiver: th={_recv_name_th!r} proxy_type={_proxy_type!r} acct={(_proxy_acct or _bank_acct)!r}")

    # ── ชั้น 1: BILLERID = ร้านค้า/บริการ (LINE MAN, ค่าไฟ ฯลฯ) ──
    if _proxy_type == "BILLERID":
        print(f"[{_TAG}] ❌ BILLERID receiver: {_recv_name_th!r}")
        return {"success": False, "reason": "สลิปนี้โอนเข้าบัญชีอื่น ไม่ใช่บัญชีร้านค้า กรุณาโอนเข้า PromptPay ของร้านเท่านั้น"}

    # ── ชั้น 2: digit groups — ทุกชุดเลขต้องอยู่ในเลขบัญชีเรา ──
    _acct_src = _proxy_acct or _bank_acct
    if _acct_src:
        _digit_groups = re.findall(r'\d{2,}', _acct_src)
        _our_accounts = [PROMPTPAY_ID, KBANK_ACCOUNT]
        if _digit_groups:
            _all_match = all(any(g in acct for acct in _our_accounts) for g in _digit_groups)
            print(f"[{_TAG}] receiver digit groups: {_digit_groups} → match={_all_match}")
            if not _all_match:
                print(f"[{_TAG}] ❌ account digit mismatch: {_digit_groups}")
                return {"success": False, "reason": "สลิปนี้โอนเข้าบัญชีอื่น ไม่ใช่บัญชีร้านค้า กรุณาโอนเข้า PromptPay ของร้านเท่านั้น"}

    # ── ชั้น 3: เช็คชื่อผู้รับเงิน ──
    _TITLES = ("นาย", "นาง", "นางสาว", "ด.ช.", "ด.ญ.", "Mr.", "Mrs.", "Miss", "MR.", "MRS.")
    def _strip_title(s: str) -> str:
        s = s.strip()
        for t in _TITLES:
            if s.startswith(t):
                return s[len(t):].strip()
        return s

    OWNER_NAME_TH = "สรวิชญ์ ทองอินทร์"
    OWNER_NAME_EN = "sorawit thongin"

    _name_th_clean = _strip_title(_recv_name_th)
    _name_en_clean = _strip_title(_recv_name_en).lower()
    if _recv_name_th or _recv_name_en:  # มีชื่อมาให้เช็ค
        # EasySlip ตัดชื่อกลางคัน + บางธนาคารส่งนามสกุลขึ้นก่อน
        # → เช็คแค่ว่าชื่อจริงหรือนามสกุลปรากฏอยู่ในข้อความที่ได้รับ
        _name_ok = (
            ("สรวิชญ์" in _name_th_clean or "ทองอินทร์" in _name_th_clean) or
            ("sorawit" in _name_en_clean or "thongin" in _name_en_clean)
        )
        if not _name_ok:
            print(f"[{_TAG}] ❌ wrong receiver name: th={_name_th_clean!r} en={_name_en_clean!r}")
            return {"success": False, "reason": "สลิปนี้โอนเข้าบัญชีอื่น ไม่ใช่บัญชีร้านค้า กรุณาโอนเข้า PromptPay ของร้านเท่านั้น"}

    # ── fallback: ถ้าไม่มี receiver info เลย → reject ──
    _has_account_info = bool(_proxy_type or _proxy_acct or _bank_acct)
    _has_name_info    = bool(_recv_name_th or _recv_name_en)
    if not _has_account_info and not _has_name_info:
        print(f"[{_TAG}] ❌ no receiver info at all — reject")
        return {"success": False, "reason": "ไม่สามารถยืนยันบัญชีผู้รับได้ กรุณาติดต่อแอดมิน"}

    # 1) เช็คยอด — รับได้ถ้า received >= expected (ส่วนเกินเข้า wallet)
    received = _r["amount"]
    expected = float(order["amount"])
    if received < expected - 0.01:
        return {"success": False, "reason": f"ยอดไม่ตรง คาดหวัง {expected:.2f} แต่ได้ {received:.2f} บาท"}

    # 2) เช็คสลิปซ้ำ — ตรวจทั้ง local file และ Supabase orders
    transaction_id = _r["trans_ref"]
    used_slips = _load_slips()
    if transaction_id and (transaction_id in used_slips or _is_transaction_used(transaction_id)):
        return {"success": False, "reason": "สลิปนี้ถูกใช้ไปแล้ว"}

    # 3) เช็ค isDuplicate จาก provider (EasySlip มี field นี้ / Slip2Go ไม่มี)
    if _r["is_duplicate"]:
        return {"success": False, "reason": "สลิปนี้ถูกใช้ไปแล้ว (duplicate detected)"}

    # ── อัปเดต order เป็น paid (ยังไม่บันทึกสลิป รอให้ BCSFE สำเร็จก่อน) ──
    update_order_status(order_id, "paid", {
        "paid_at":        datetime.now(TZ_THAI).isoformat(),
        "transaction_id": transaction_id,
        "received":       received,
    })

    surplus = max(0, int(received) - int(expected))
    print(f"[{_TAG}] ✅ order {order_id} ชำระแล้ว {received} บาท" + (f" surplus ฿{surplus}" if surplus else ""))
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


# ── กู้ซองที่ "เปิดเข้าเบอร์ร้านแล้ว แต่ระบบไม่ได้บันทึก" ────────────────────
# เคสจริง 22/9/2026: ยิงไป TrueMoney เปิดซองสำเร็จ แต่คำตอบขากลับหาย (timeout/proxy)
# ระบบถือว่าล้มเหลว ลูกค้าส่งซ้ำได้ VOUCHER_OUT_OF_STOCK -> เงินเข้าร้านแต่ลูกค้าไม่ได้ยอด
#
# กันใช้ซ้ำด้วย 4 ด่าน:
#   1. voucher_hash ต้องไม่อยู่ใน used_slips (ซองที่เคยได้ยอดแล้วจะไม่ผ่านด่านนี้ตลอดไป)
#   2. ผู้รับซองต้องเป็นเบอร์ร้านเท่านั้น (เทียบกับเลขที่ TrueMoney ปิดบังไว้ 063-xxx-5901)
#   3. เปิดซองไม่เกิน _ANGPAO_RECOVER_WINDOW_SEC (กันขุดลิงก์เก่ามายิง)
#   4. ผู้เรียกต้อง mark_slip_used() ทันทีก่อนให้ยอด
_ANGPAO_RECOVER_CODES = {"VOUCHER_OUT_OF_STOCK", "TARGET_USER_REDEEMED"}
_ANGPAO_RECOVER_WINDOW_SEC = 24 * 3600


def _mobile_matches_shop(masked: str) -> bool:
    """เทียบเบอร์ที่ TrueMoney ปิดบัง เช่น '063-xxx-5901' กับเบอร์ร้าน '0634515901'"""
    shop = re.sub(r"\D", "", TRUEMONEY_ID)
    digits = re.sub(r"[^0-9x]", "", (masked or "").lower())
    if not digits or len(digits) != len(shop):
        return False
    return all(d == "x" or d == s for d, s in zip(digits, shop))


def _angpao_recover_amount(data: dict, code: str) -> float | None:
    """ซองถูกเปิดเข้าเบอร์ร้านไปแล้วเมื่อเร็วๆ นี้หรือไม่ — คืนยอดเงิน ถ้าใช่"""
    if code not in _ANGPAO_RECOVER_CODES:
        return None
    vdata = data.get("data") or {}
    voucher = vdata.get("voucher") or {}
    if voucher.get("status") != "redeemed":
        return None
    now_ms = time.time() * 1000
    for t in (vdata.get("tickets") or []):
        if not _mobile_matches_shop(t.get("mobile")):
            continue
        upd = t.get("update_date")
        if not isinstance(upd, (int, float)) or (now_ms - upd) > _ANGPAO_RECOVER_WINDOW_SEC * 1000:
            continue
        amt = t.get("amount_baht") or voucher.get("redeemed_amount_baht") or voucher.get("amount_baht")
        try:
            amt = float(amt)
        except (TypeError, ValueError):
            continue
        if amt > 0:
            print(f"[ANGPAO] 🔁 กู้ซองที่เปิดเข้าเบอร์ร้านแล้ว ฿{amt} (เปิดเมื่อ {int((now_ms - upd) / 1000)} วินาทีก่อน)")
            return amt
    return None


async def _angpao_redeem_call(voucher_hash: str) -> dict:
    """ยิงเปิดซอง 1 ครั้ง — คืน dict ของ TrueMoney (โยน exception ถ้าติดต่อไม่ได้)"""
    mobile = TRUEMONEY_ID.replace("-", "").replace(" ", "")
    async with CurlSession(**_angpao_session_kwargs()) as client:
        resp = await client.post(
            f"https://gift.truemoney.com/campaign/vouchers/{voucher_hash}/redeem",
            json={"mobile": mobile, "voucher_hash": voucher_hash},
            headers={
                "Content-Type": "application/json",
                "Origin": "https://gift.truemoney.com",
                "Referer": f"https://gift.truemoney.com/campaign/?v={voucher_hash}",
            },
        )
    return resp.json()


async def _angpao_redeem_with_retry(voucher_hash: str, tag: str) -> dict:
    """ยิงเปิดซอง ถ้าคำตอบหาย (timeout/เน็ตสะดุด) ให้ยิงซ้ำอีกครั้ง
    รอบสองซองจะถูกเปิดไปแล้ว -> ได้ VOUCHER_OUT_OF_STOCK ที่มีข้อมูลให้ _angpao_recover_amount กู้ต่อได้"""
    try:
        return await _angpao_redeem_call(voucher_hash)
    except Exception as e:
        print(f"[{tag}] ⚠ ยิงเปิดซองรอบแรกไม่สำเร็จ ({e}) — ยิงซ้ำเพื่อเช็คว่าซองถูกเปิดไปแล้วหรือยัง")
        await asyncio.sleep(2)
        return await _angpao_redeem_call(voucher_hash)


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
        return {"success": False, "reason": "order หมดอายุแล้ว กรุณากดยกเลิก แล้วทำรายการใหม่ (ใส่สลิปเดิมได้เลย)"}

    if order["status"] == "paid":
        return {"success": False, "reason": "order นี้ชำระแล้ว"}

    voucher_hash = _extract_voucher_hash(voucher_code)
    print(f"[ANGPAO] voucher_code={repr(voucher_code)} → hash={repr(voucher_hash)}")
    if not voucher_hash:
        return {"success": False, "reason": "กรุณากรอกโค้ด/ลิงก์ซองอั่งเป่า"}

    used_slips = _load_slips()
    if voucher_hash in used_slips:
        return {"success": False, "reason": "ซองอั่งเป่านี้ถูกใช้ไปแล้ว"}

    print(f"[ANGPAO] calling redeem: hash={voucher_hash} mobile={TRUEMONEY_ID}")

    try:
        data = await _angpao_redeem_with_retry(voucher_hash, "ANGPAO")
        print(f"[ANGPAO] response: {json.dumps(data, ensure_ascii=False)}")
    except Exception as e:
        return {"success": False, "reason": f"เช็คซองอั่งเป่าไม่ได้: {e}"}

    status_obj = data.get("status") or {}
    code = data.get("code") or status_obj.get("code") or ("SUCCESS" if data.get("success") else "")

    recovered = None
    if code != "SUCCESS":
        # ซองอาจถูกเปิดเข้าเบอร์ร้านไปแล้วจากรอบที่คำตอบหาย — ถ้าใช่ ให้ถือว่าจ่ายแล้ว
        recovered = _angpao_recover_amount(data, code)
        if recovered is None:
            msg = _ANGPAO_ERROR_MESSAGES.get(code) or data.get("message") or status_obj.get("message") or "ซองอั่งเป่าไม่ถูกต้อง"
            return {"success": False, "reason": msg}

    # จดรหัสซองทันทีที่ TrueMoney ยืนยันว่าเปิดซองแล้ว (เงินเข้าร้านแล้ว)
    # เดิมจดหลัง BCSFE สำเร็จเท่านั้น -> ถ้าลูกค้ากรอกรหัสเกมผิด ซองไม่ถูกจด
    #    เอาซองเดิมไปเติมกระเป๋า/จ่ายออเดอร์อื่นได้เงินซ้ำ (ตัวกู้ซองจะมองว่าเปิดเข้าเบอร์ร้านแล้ว)
    mark_slip_used(voucher_hash)

    if recovered is not None:
        received = recovered
    else:
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
    r200 = r500 = r1000 = 0
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.get(
                f"{SUPABASE_URL}/rest/v1/profiles",
                params={
                    "username": f"eq.{username}",
                    "select": "loyalty_redeemed_cycles,loyalty_redeemed_tier200,loyalty_redeemed_tier500,loyalty_redeemed_tier1000",
                },
                headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"},
            )
            data = resp.json()
            if data:
                r200  = data[0].get("loyalty_redeemed_tier200")  or 0
                r500  = data[0].get("loyalty_redeemed_tier500")  or 0
                r1000 = data[0].get("loyalty_redeemed_tier1000") or 0
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

    return {
        "total_spent": total_spent,
        "loyalty_redeemed_cycles": r200,  # backward compat
        "redeemed_tier200":  r200,
        "redeemed_tier500":  r500,
        "redeemed_tier1000": r1000,
    }


def add_loyalty_redeemed_tier(username: str, tier: int, count: int):
    """เพิ่ม loyalty_redeemed_tierXXX ตาม tier ที่ระบุ (200/500/1000)"""
    col = f"loyalty_redeemed_tier{tier}"
    try:
        loyalty = get_user_loyalty(username)
        current  = loyalty.get(f"redeemed_tier{tier}", 0)
        new_count = current + count
        with httpx.Client(timeout=8) as client:
            client.patch(
                f"{SUPABASE_URL}/rest/v1/profiles",
                params={"username": f"eq.{username}"},
                headers={
                    "apikey": SUPABASE_KEY,
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                    "Content-Type": "application/json",
                },
                json={col: new_count},
            )
        print(f"[LOYALTY] {username}: tier{tier} +{count} → total #{new_count}")
    except Exception as e:
        print(f"[LOYALTY] add_loyalty_redeemed_tier error: {e}")


# def add_loyalty_redeemed_cycles(username: str, count: int):
#     """[DEPRECATED] ใช้ add_loyalty_redeemed_tier แทน"""
#     add_loyalty_redeemed_tier(username, 200, count)


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


def save_loyalty_redemption(username: str, cycles: int, new_tc: str, new_cc: str,
                            original_transfer_code: str = "", country: str = "en",
                            tier: int = 200):
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
                    "original_transfer_code": original_transfer_code,
                    "country": country,
                    "tier": tier,
                },
            )
        print(f"[LOYALTY] {username}: saved redemption history (tier{tier} × {cycles})")
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


def get_loyalty_redemption_by_id(redemption_id: str) -> dict | None:
    """ดึง loyalty redemption record เดียวตาม id"""
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.get(
                f"{SUPABASE_URL}/rest/v1/loyalty_redemptions",
                params={"id": f"eq.{redemption_id}", "limit": "1"},
                headers={
                    "apikey": SUPABASE_KEY,
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                },
            )
        data = resp.json() if resp.status_code == 200 else []
        return data[0] if data else None
    except Exception as e:
        print(f"[LOYALTY] get_redemption_by_id error: {e}")
        return None


def update_loyalty_redemption_tc(redemption_id: str, new_tc: str, new_cc: str):
    """อัพเดท TC/CC ใน loyalty_redemptions หลัง retry สำเร็จ"""
    try:
        with httpx.Client(timeout=8) as client:
            client.patch(
                f"{SUPABASE_URL}/rest/v1/loyalty_redemptions",
                params={"id": f"eq.{redemption_id}"},
                headers={
                    "apikey": SUPABASE_KEY,
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal",
                },
                json={
                    "new_transfer_code": new_tc,
                    "new_confirmation_code": new_cc,
                },
            )
        print(f"[LOYALTY] redemption {redemption_id}: updated TC → {new_tc}")
    except Exception as e:
        print(f"[LOYALTY] update_redemption_tc error: {e}")


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


def _supabase_get_all(client, table: str, params: dict, page: int = 1000) -> list:
    """ดึงทุกแถวแบบแบ่งหน้า — Supabase ตอบสูงสุด 1000 แถวต่อครั้ง
    (เดิมดึงครั้งเดียว วันที่ออเดอร์เกิน 1000 ยอดขายจะถูกตัดเหลือแค่ช่วงเช้า-บ่าย)"""
    rows, offset = [], 0
    while True:
        r = client.get(
            f"{SUPABASE_URL}/rest/v1/{table}",
            params={**params, "order": "created_at.asc", "limit": str(page), "offset": str(offset)},
            headers=_sh(),
        )
        if r.status_code != 200:
            # ลองซ้ำ 2 ครั้ง ถ้ายังไม่ได้ให้ error ไปเลย — ห้ามคืนข้อมูลครึ่งๆ
            # (เดิม break เงียบๆ -> ยอดขายวันนั้นขึ้น 0 บาทหรือขาดไปโดยไม่มีใครรู้)
            for _wait in (0.5, 1.5):
                time.sleep(_wait)
                r = client.get(
                    f"{SUPABASE_URL}/rest/v1/{table}",
                    params={**params, "order": "created_at.asc", "limit": str(page), "offset": str(offset)},
                    headers=_sh(),
                )
                if r.status_code == 200:
                    break
            if r.status_code != 200:
                raise RuntimeError(f"Supabase {table} HTTP {r.status_code}")
        chunk = r.json()
        rows.extend(chunk)
        if len(chunk) < page:
            break
        offset += page
    return rows


def _fetch_revenue_rows(start: datetime, end: datetime) -> tuple:
    """ดึงออเดอร์ที่ใช้คิดยอด (ไม่รวม topup) + รายชื่อ admin — error ให้ raise ไม่คืนข้อมูลครึ่งๆ"""
    with httpx.Client(timeout=8) as client:
        admin_resp = client.get(
            f"{SUPABASE_URL}/rest/v1/profiles",
            params={"is_admin": "eq.true", "select": "username"},
            headers=_sh(),
        )
    if admin_resp.status_code != 200:
        # ถ้าดึงรายชื่อ admin ไม่ได้ ยอดของ admin จะถูกนับรวมไปด้วย — ให้ error แทน
        raise RuntimeError(f"Supabase profiles HTTP {admin_resp.status_code}")
    admin_usernames = [p["username"] for p in admin_resp.json()]

    with httpx.Client(timeout=15) as client:
        all_orders = _supabase_get_all(client, "orders", {
            "status": "eq.done",
            "created_at": [f"gte.{start.isoformat()}", f"lt.{end.isoformat()}"],
            # ไม่ดึงออเดอร์เติมเงิน (topup) ตั้งแต่ต้น — ต้องรวม order_type ที่เป็น null ด้วย
            # (ออเดอร์เก่าหลายตัวไม่มี order_type ถ้าใช้ neq อย่างเดียว postgres จะตัดพวกนี้ทิ้ง)
            "or": "(order_type.is.null,order_type.neq.topup)",
            "select": "order_id,amount,base_amount,order_type,payment_method,username,created_at",
        })
    # --- โค้ดเดิม (ดึงครั้งเดียว โดนตัดที่ 1000 แถว) ---
    # with httpx.Client(timeout=8) as client:
    #     resp = client.get(f"{SUPABASE_URL}/rest/v1/orders", params={...}, headers=_sh())
    # all_orders = resp.json() if resp.status_code == 200 else []
    return all_orders, admin_usernames


def _summarize_revenue(all_orders: list, admin_usernames: list, include_orders: bool = True) -> dict:
    """สรุปยอดจากรายการออเดอร์ที่ดึงมาแล้ว (ไม่นับ admin / บัญชีทดสอบ / topup / ไม่มี username)"""
    TEST_ACCOUNTS = {"test", "mod"}
    orders = [o for o in all_orders if o.get("username") and o.get("username") not in admin_usernames
              and o.get("username") not in TEST_ACCOUNTS
              and o.get("order_type") != "topup"]

    def _rev(o):
        return o.get("base_amount") if o.get("base_amount") is not None else (o.get("amount") or 0)

    total_revenue = sum(_rev(o) for o in orders)
    by_type: dict = {}
    by_method: dict = {}
    by_method_count: dict = {}
    for o in orders:
        t = o.get("order_type") or "unknown"
        by_type[t] = by_type.get(t, 0) + _rev(o)
        m = o.get("payment_method") or "unknown"
        by_method[m] = by_method.get(m, 0) + _rev(o)
        by_method_count[m] = by_method_count.get(m, 0) + 1

    orders_sorted = sorted(orders, key=lambda o: o.get("created_at") or "")

    return {
        "total_revenue": total_revenue,
        "total_orders": len(orders),
        "by_type": by_type,
        "by_method": by_method,
        "by_method_count": by_method_count,
        "excluded_admins": admin_usernames,
        # นับเฉพาะออเดอร์ที่ไม่มี username จริงๆ
        # (สูตรเดิม = ทั้งหมด − ที่นับ − admin ทำให้ topup/บัญชีทดสอบถูกนับเป็น "ไม่มี username" ไปด้วย)
        "excluded_no_username_count": sum(1 for o in all_orders if not o.get("username")),
        # "excluded_no_username_count": len(all_orders) - len(orders) - sum(
        #     1 for o in all_orders if o.get("username") in admin_usernames
        # ),
        "orders": orders_sorted if include_orders else [],
    }


def _get_revenue_for_range(start: datetime, end: datetime) -> dict:
    """สรุปยอดรายได้ระหว่าง start-end (ไม่นับ order ของบัญชี admin) — ใช้ร่วมกันทั้งรายเดือน/รายวัน"""
    all_orders, admin_usernames = _fetch_revenue_rows(start, end)
    return _summarize_revenue(all_orders, admin_usernames)


def get_revenue_days(year: int, month: int, day: int, days: int, include_orders: bool = False) -> dict:
    """สรุปยอดรายวันหลายวันติดกันจากการดึงข้อมูล "ครั้งเดียว"
    (เดิมหน้าเว็บยิง /revenue/daily ทีละวันพร้อมกัน 30 request -> Cloudflare 429 -> บางวันขึ้น 0 บาท)"""
    start = datetime(year, month, day, tzinfo=TZ_THAI)
    end = start + timedelta(days=days)
    all_orders, admin_usernames = _fetch_revenue_rows(start, end)
    buckets: dict = {}
    for o in all_orders:
        try:
            k = datetime.fromisoformat(o["created_at"]).astimezone(TZ_THAI).strftime("%Y-%m-%d")
        except Exception:
            continue
        buckets.setdefault(k, []).append(o)
    out = []
    for i in range(days):
        d = start + timedelta(days=i)
        k = d.strftime("%Y-%m-%d")
        out.append({"year": d.year, "month": d.month, "day": d.day,
                    **_summarize_revenue(buckets.get(k, []), admin_usernames, include_orders)})
    return {"days": out}


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
        with httpx.Client(timeout=15) as client:
            all_orders = _supabase_get_all(client, "cr_orders", {
                "status": "eq.done",
                "created_at": [f"gte.{start.isoformat()}", f"lt.{end.isoformat()}"],
                "select": "order_id,amount,base_amount,quantity,payment_method,username,created_at,done_at",
            })
        # --- โค้ดเดิม (ดึงครั้งเดียว โดนตัดที่ 1000 แถว) ---
        # resp = client.get(f"{SUPABASE_URL}/rest/v1/cr_orders", params={...}, headers=_sh())
        # all_orders = resp.json() if resp.status_code == 200 else []
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


PENDING_CREDITS_FILE = Path("logs") / "pending_credits.jsonl"


def _record_pending_credit(username: str, amount: int, reason: str):
    """จดไว้ให้แอดมินเติมมือ เมื่อเติมเงินอัตโนมัติไม่สำเร็จ (เงินลูกค้าต้องไม่หายเงียบ)"""
    try:
        PENDING_CREDITS_FILE.parent.mkdir(exist_ok=True)
        with open(PENDING_CREDITS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps({"time": datetime.now(TZ_THAI).isoformat(), "username": username,
                                "amount": amount, "reason": reason}, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[WALLET] ⚠ บันทึก pending credit ไม่ได้: {e}")
    print(f"[WALLET] 🚨 PENDING CREDIT {username} +฿{amount} — ต้องเติมมือ ({reason})")


def credit_wallet(username: str, amount: int) -> bool:
    """บวกเงินเข้า wallet (หน่วยบาท) — แบบปลอดภัย

    เดิม: อ่านยอดไม่ได้ -> ถือว่ายอดเป็น 0 -> เขียนทับ = ยอดเดิมลูกค้าหาย
          และถ้า Supabase timeout เงินไม่เข้าแต่ไม่มีใครรู้ (เคส Noh 15/10/2026)
    ใหม่: - อ่านยอดไม่ได้ = ไม่เขียน (ลองใหม่)
          - เขียนแบบมีเงื่อนไข wallet_balance=ยอดที่อ่านมา กันมีรายการอื่นแทรกแล้วทับกัน
          - ลองซ้ำ 4 ครั้ง ถ้ายังไม่ได้ จดลง logs/pending_credits.jsonl ให้แอดมินเติมมือ"""
    if amount <= 0:
        return False
    last_err = ""
    for attempt in range(4):
        if attempt:
            time.sleep(1.5 * attempt)
        try:
            with httpx.Client(timeout=12) as client:
                r = client.get(
                    f"{SUPABASE_URL}/rest/v1/profiles",
                    params={"username": f"eq.{username}", "select": "wallet_balance"},
                    headers=_sh(),
                )
                if r.status_code != 200 or not r.json():
                    last_err = f"อ่านยอดไม่ได้ HTTP {r.status_code}"
                    continue
                current = int(r.json()[0].get("wallet_balance") or 0)
                try:
                    resp = client.patch(
                        f"{SUPABASE_URL}/rest/v1/profiles",
                        params={"username": f"eq.{username}", "wallet_balance": f"eq.{current}"},
                        headers=_sh({"Content-Type": "application/json", "Prefer": "return=representation"}),
                        json={"wallet_balance": current + amount},
                    )
                except Exception as e:
                    # ส่งคำสั่งเขียนไปแล้วแต่ไม่รู้ผล (เขียนสำเร็จแต่คำตอบหายก็ได้)
                    # ห้ามลองซ้ำ — ไม่งั้นลูกค้าได้เงิน 2 เท่า ให้แอดมินเช็คยอดก่อนเติมมือ
                    _record_pending_credit(username, amount,
                        f"ไม่รู้ผลการเขียน ({e}) — ยอดก่อนเติม ฿{current} เช็คก่อน ถ้าเป็น ฿{current + amount} แล้วไม่ต้องเติม")
                    return False
            if resp.status_code in (200, 204) and resp.json():
                print(f"[WALLET] ✅ credit {username} +฿{amount} → ฿{current + amount}")
                return True
            last_err = f"เขียนไม่สำเร็จ HTTP {resp.status_code} (ยอดอาจเปลี่ยนระหว่างทาง)"
        except Exception as e:
            last_err = str(e)
            print(f"[WALLET] credit error (ครั้งที่ {attempt + 1}): {e}")
    _record_pending_credit(username, amount, last_err)
    return False
    # --- โค้ดเดิม ---
    # try:
    #     current = get_wallet_balance(username)
    #     with httpx.Client(timeout=8) as client:
    #         resp = client.patch(f"{SUPABASE_URL}/rest/v1/profiles",
    #             params={"username": f"eq.{username}"}, headers=..., json={"wallet_balance": current + amount})
    #     ...


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

    print(f"[WALLET] angpao redeem for {username}: hash={voucher_hash}")

    try:
        data = await _angpao_redeem_with_retry(voucher_hash, "WALLET")
        print(f"[WALLET] angpao response: {json.dumps(data, ensure_ascii=False)[:300]}")
    except Exception as e:
        return {"success": False, "reason": f"เช็คซองอั่งเป่าไม่ได้: {e}"}

    status_obj = data.get("status") or {}
    code = data.get("code") or status_obj.get("code") or ("SUCCESS" if data.get("success") else "")

    recovered = None
    if code != "SUCCESS":
        # ซองอาจถูกเปิดเข้าเบอร์ร้านไปแล้วจากรอบที่คำตอบหาย — ถ้าใช่ ให้เติมเงินให้ลูกค้า
        recovered = _angpao_recover_amount(data, code)
        if recovered is None:
            msg = _ANGPAO_ERROR_MESSAGES.get(code) or data.get("message") or status_obj.get("message") or "ซองอั่งเป่าไม่ถูกต้อง"
            return {"success": False, "reason": msg}

    if recovered is not None:
        received = recovered
    else:
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
        return {"success": False, "reason": "order หมดอายุแล้ว กรุณากดยกเลิก แล้วทำรายการใหม่ (ใส่สลิปเดิมได้เลย)"}
    if order["status"] == "paid":
        return {"success": False, "reason": "order นี้ชำระแล้ว"}

    # ใช้ provider เดียวกับ verify_slip() (SLIP_PROVIDER)
    if SLIP_PROVIDER == "slip2go":
        _r = await _call_slip2go(slip_image_bytes)
    else:
        _r = await _call_easyslip(slip_image_bytes)

    _TAG = "CR-" + SLIP_PROVIDER.upper()
    if not _r.get("ok"):
        return {"success": False, "reason": _r.get("reason", "เช็คสลิปไม่สำเร็จ")}

    received = _r["amount"]
    expected = float(order["amount"])
    if received < expected - 0.01:
        return {"success": False, "reason": f"ยอดไม่ตรง คาดหวัง {expected:.2f} แต่ได้ {received:.2f} บาท"}

    transaction_id = _r["trans_ref"]
    used_slips = _load_slips()
    if transaction_id and (transaction_id in used_slips or _is_transaction_used(transaction_id)):
        return {"success": False, "reason": "สลิปนี้ถูกใช้ไปแล้ว"}
    if _r["is_duplicate"]:
        return {"success": False, "reason": "สลิปนี้ถูกใช้ไปแล้ว (duplicate detected)"}

    update_cr_order_status(order_id, "paid", {
        "paid_at": datetime.now(TZ_THAI).isoformat(),
        "transaction_id": transaction_id,
        "received": received,
    })
    print(f"[{_TAG}] ✅ order {order_id} ชำระแล้ว {received} บาท")
    return {"success": True, "reason": "ชำระเงินสำเร็จ", "transaction_id": transaction_id}


async def redeem_truemoney_voucher_cr(voucher_code: str, order_id: str) -> dict:
    """verify ซองอั่งเป่า TrueMoney สำหรับ CR order"""
    order = get_cr_order(order_id)
    if not order:
        return {"success": False, "reason": "ไม่พบ order นี้"}
    if is_order_expired(order):
        update_cr_order_status(order_id, "expired")
        return {"success": False, "reason": "order หมดอายุแล้ว กรุณากดยกเลิก แล้วทำรายการใหม่ (ใส่สลิปเดิมได้เลย)"}
    if order["status"] == "paid":
        return {"success": False, "reason": "order นี้ชำระแล้ว"}

    voucher_hash = _extract_voucher_hash(voucher_code)
    if not voucher_hash:
        return {"success": False, "reason": "กรุณากรอกโค้ด/ลิงก์ซองอั่งเป่า"}

    used_slips = _load_slips()
    if voucher_hash in used_slips:
        return {"success": False, "reason": "ซองอั่งเป่านี้ถูกใช้ไปแล้ว"}

    try:
        data = await _angpao_redeem_with_retry(voucher_hash, "CR-ANGPAO")
        print(f"[CR-ANGPAO] response: {json.dumps(data, ensure_ascii=False)}")
    except Exception as e:
        return {"success": False, "reason": f"เช็คซองอั่งเป่าไม่ได้: {e}"}

    status_obj = data.get("status") or {}
    code = data.get("code") or status_obj.get("code") or ("SUCCESS" if data.get("success") else "")
    recovered = None
    if code != "SUCCESS":
        # ซองอาจถูกเปิดเข้าเบอร์ร้านไปแล้วจากรอบที่คำตอบหาย — ถ้าใช่ ให้ถือว่าจ่ายแล้ว
        recovered = _angpao_recover_amount(data, code)
        if recovered is None:
            msg = _ANGPAO_ERROR_MESSAGES.get(code) or data.get("message") or status_obj.get("message") or "ซองอั่งเป่าไม่ถูกต้อง"
            return {"success": False, "reason": msg}

    # จดรหัสซองทันทีที่ TrueMoney ยืนยันว่าเปิดซองแล้ว (เงินเข้าร้านแล้ว)
    # เดิมจดหลัง BCSFE สำเร็จเท่านั้น -> ถ้าลูกค้ากรอกรหัสเกมผิด ซองไม่ถูกจด
    #    เอาซองเดิมไปเติมกระเป๋า/จ่ายออเดอร์อื่นได้เงินซ้ำ (ตัวกู้ซองจะมองว่าเปิดเข้าเบอร์ร้านแล้ว)
    mark_slip_used(voucher_hash)

    if recovered is not None:
        received = recovered
    else:
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
