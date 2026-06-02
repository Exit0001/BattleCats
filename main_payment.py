# main.py (อัปเดต) - เพิ่ม payment routes เข้าไปใน FastAPI

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os, shutil
import os as _os
from pathlib import Path
from datetime import datetime
from typing import Optional, List

from models import OrderRequest, OrderResponse, ItemSummary
from runner import BCSFERunner
from config import ITEM_MAP, AMOUNT_OPTIONS, COUNTRIES
from payment import (
    create_order, get_order, update_order_status,
    verify_slip, calculate_total, is_order_expired
)

app = FastAPI(title="BCSFE Order System")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

BACKUP_DIR = Path("saves_backup")
BACKUP_DIR.mkdir(exist_ok=True)
BCSFE_SAVE_PATH = Path.home() / "Documents" / "bcsfe" / "saves" / "SAVE_DATA"

def backup_save(transfer_code: str) -> str | None:
    try:
        if not BCSFE_SAVE_PATH.exists():
            return None
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = BACKUP_DIR / f"SAVE_{ts}_{(transfer_code or '')[:8]}"
        shutil.copy2(BCSFE_SAVE_PATH, dest)
        print(f"[BACKUP] ✅ → {dest}")
        return str(dest)
    except Exception as e:
        print(f"[BACKUP] ❌ {e}")
        return None

# ══════════════════════════════════════════
# PAYMENT MODELS
# ══════════════════════════════════════════

class CreateOrderPaymentRequest(BaseModel):
    """ขั้นแรก: ลูกค้าส่งข้อมูล → ได้ QR กลับมา"""
    transfer_code:     str
    confirmation_code: str
    country:           str = "1"
    items:             List[dict]

class CreateOrderPaymentResponse(BaseModel):
    order_id:   str
    amount:     int
    qr_base64:  str
    expires_at: str

class OrderStatusResponse(BaseModel):
    order_id: str
    status:   str
    amount:   int

# ══════════════════════════════════════════
# PAYMENT ROUTES
# ══════════════════════════════════════════

@app.post("/api/payment/create", response_model=CreateOrderPaymentResponse)
async def payment_create(req: CreateOrderPaymentRequest):
    """
    ขั้นที่ 1: สร้าง order + QR PromptPay
    ลูกค้าส่ง items มาก่อน → ได้ QR กลับไปสแกนจ่าย
    """
    if not req.items:
        raise HTTPException(400, "ต้องเลือก item อย่างน้อย 1 ชิ้น")

    for item in req.items:
        if item["key"] not in ITEM_MAP:
            raise HTTPException(400, f"ไม่รู้จัก item: {item['key']}")

    order = create_order(
        transfer_code=req.transfer_code,
        confirmation_code=req.confirmation_code,
        country=req.country,
        items=req.items,
    )

    return CreateOrderPaymentResponse(
        order_id=order["order_id"],
        amount=order["amount"],
        qr_base64=order["qr_base64"],
        expires_at=order["expires_at"],
    )


@app.post("/api/payment/verify/{order_id}")
async def payment_verify(order_id: str, slip: UploadFile = File(...)):
    """
    ขั้นที่ 2: ลูกค้าอัปโหลดสลิป → เช็คกับ SlipOK → รัน BCSFE อัตโนมัติ
    """
    order = get_order(order_id)
    if not order:
        raise HTTPException(404, "ไม่พบ order นี้")

    if is_order_expired(order):
        raise HTTPException(400, "order หมดอายุแล้ว กรุณาสั่งใหม่")

    if order["status"] in ("paid", "done"):
        raise HTTPException(400, "order นี้ดำเนินการแล้ว")

    # อ่านไฟล์สลิป
    slip_bytes = await slip.read()

    # เช็คสลิปกับ SlipOK
    result = await verify_slip(slip_bytes, order_id)
    if not result["success"]:
        raise HTTPException(400, result["reason"])

    # ชำระแล้ว → รัน BCSFE
    print(f"\n[ORDER] 💰 order {order_id} ชำระแล้ว → รัน BCSFE")
    try:
        runner = BCSFERunner(
            transfer=order["transfer_code"],
            confirm=order["confirmation_code"],
            country=order["country"],
        )
        bcsfe_result = runner.run(order["items"])

        if bcsfe_result["success"]:
            codes = bcsfe_result.get("new_transfer_code", {})
            new_tc = codes.get("transfer") if isinstance(codes, dict) else codes
            new_cc = codes.get("confirmation") if isinstance(codes, dict) else None

            backup_save(new_tc or order["transfer_code"])
            update_order_status(order_id, "done", {
                "new_transfer_code":     new_tc,
                "new_confirmation_code": new_cc,
                "done_at":               datetime.now().isoformat(),
            })

            summary = [
                {"item": ITEM_MAP[i["key"]]["label"], "amount": i["amount"]}
                for i in order["items"] if i["key"] in ITEM_MAP
            ]

            return {
                "success":               True,
                "new_transfer_code":     new_tc,
                "new_confirmation_code": new_cc,
                "summary":               summary,
            }
        else:
            update_order_status(order_id, "bcsfe_failed", {"error": bcsfe_result["error"]})
            raise HTTPException(500, bcsfe_result["error"])

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"เกิดข้อผิดพลาด: {e}")


@app.get("/api/payment/status/{order_id}", response_model=OrderStatusResponse)
async def payment_status(order_id: str):
    """เช็ค status ของ order (สำหรับ polling)"""
    order = get_order(order_id)
    if not order:
        raise HTTPException(404, "ไม่พบ order")
    return OrderStatusResponse(
        order_id=order_id,
        status=order["status"],
        amount=order["amount"],
    )

# ══════════════════════════════════════════
# EXISTING ROUTES
# ══════════════════════════════════════════

@app.get("/api/items")
def get_items():
    return {"items": ITEM_MAP, "amounts": AMOUNT_OPTIONS,
            "countries": COUNTRIES, "prices": __import__("payment").ITEM_PRICE}

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/")
def root():
    return RedirectResponse(url="/static/bcsfe-order.html")

if __name__ == "__main__":
    import uvicorn
    print("🚀 BCSFE Order System เริ่มต้น...")
    uvicorn.run(app, host="0.0.0.0", port=8000)
