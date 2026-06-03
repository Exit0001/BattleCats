# main.py - FastAPI server สำหรับ BCSFE order system

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
import os
import shutil
from pathlib import Path
from datetime import datetime
from models import OrderRequest, OrderResponse, ItemSummary, ItemRequest, TestBCSFERequest, UnlockCharactersRequest
from runner import BCSFERunner
from config import ITEM_MAP, AMOUNT_OPTIONS, COUNTRIES
from payment import (
    ITEM_PRICE,
    create_order as create_payment_order,
    get_order,
    is_order_expired,
    update_order_status,
    verify_slip,
)

# Import เพิ่มเติมสำหรับ /api/orders/list
from payment import ORDER_DB

# โฟลเดอร์เก็บ backup save files
BACKUP_DIR = Path("saves_backup")
BACKUP_DIR.mkdir(exist_ok=True)

# path ที่ bcsfe บันทึก SAVE_DATA ไว้
BCSFE_SAVE_PATH = Path.home() / "Documents" / "bcsfe" / "saves" / "SAVE_DATA"

def backup_save(transfer_code: str) -> str | None:
    """
    copy SAVE_DATA จาก bcsfe ไปเก็บใน saves_backup/
    ตั้งชื่อไฟล์ตาม timestamp + transfer code
    คืน path ที่บันทึก หรือ None ถ้าไม่พบไฟล์
    """
    try:
        if not BCSFE_SAVE_PATH.exists():
            print(f"[BACKUP] ⚠️ ไม่พบ SAVE_DATA ที่ {BCSFE_SAVE_PATH}")
            return None

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"SAVE_{timestamp}_{transfer_code[:8]}"
        dest = BACKUP_DIR / filename

        shutil.copy2(BCSFE_SAVE_PATH, dest)
        print(f"[BACKUP] ✅ บันทึก save → {dest}")
        return str(dest)
    except Exception as e:
        print(f"[BACKUP] ❌ backup ล้มเหลว: {e}")
        return None

# สร้าง FastAPI app
app = FastAPI(title="BCSFE Order System")

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
    ส่งข้อมูล ITEM_MAP, AMOUNT_OPTIONS, COUNTRIES และราคาสินค้า
    """
    return {
        "items": ITEM_MAP,
        "amounts": AMOUNT_OPTIONS,
        "countries": COUNTRIES,
        "prices": ITEM_PRICE,
    }

@app.post("/api/payment/create")
async def payment_create(order: OrderRequest):
    """สร้าง order สำหรับการชำระด้วย QR และเก็บข้อมูลไว้ใน DB"""
    if not order.items or len(order.items) == 0:
        raise HTTPException(status_code=400, detail="ต้องเลือก item อย่างน้อย 1 ชิ้น")

    if order.country not in COUNTRIES:
        raise HTTPException(status_code=400, detail=f"Country ไม่ถูกต้อง: {order.country}")

    for item in order.items:
        if item.key not in ITEM_MAP:
            raise HTTPException(status_code=400, detail=f"ไม่รู้จัก item: {item.key}")
        if item.amount <= 0:
            raise HTTPException(status_code=400, detail=f"จำนวน {item.key} ต้องมากกว่า 0")
        if item.amount > ITEM_MAP[item.key]["max"]:
            raise HTTPException(status_code=400, detail=f"{ITEM_MAP[item.key]['label']} เกินจำนวนสูงสุด ({ITEM_MAP[item.key]['max']})")

    payment_order = create_payment_order(
        transfer_code=order.transfer_code,
        confirmation_code=order.confirmation_code,
        country=order.country,
        items=[{"key": item.key, "amount": item.amount} for item in order.items],
    )

    return {
        "order_id": payment_order["order_id"],
        "amount": payment_order["amount"],
        "qr_base64": payment_order["qr_base64"],
        "expires_at": payment_order["expires_at"],
    }

@app.post("/api/payment/verify/{order_id}")
async def payment_verify(order_id: str, slip: UploadFile = File(...)):
    """เช็คสลิป และ ถ้าผ่าน ให้รัน BCSFE ต่อ"""
    order = get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="ไม่พบ order นี้")

    if is_order_expired(order):
        raise HTTPException(status_code=400, detail="order หมดอายุแล้ว กรุณาสั่งใหม่")

    if order["status"] in ("paid", "done"):
        raise HTTPException(status_code=400, detail="order นี้ดำเนินการแล้ว")

    slip_bytes = await slip.read()
    slip_result = await verify_slip(slip_bytes, order_id)
    if not slip_result["success"]:
        raise HTTPException(status_code=400, detail=slip_result["reason"])

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
                "new_transfer_code": new_tc,
                "new_confirmation_code": new_cc,
                "done_at": datetime.now().isoformat(),
            })

            summary = [
                {"item": ITEM_MAP[i["key"]]["label"], "amount": i["amount"]}
                for i in order["items"] if i["key"] in ITEM_MAP
            ]

            return {
                "success": True,
                "new_transfer_code": new_tc,
                "new_confirmation_code": new_cc,
                "summary": summary,
            }

        update_order_status(order_id, "bcsfe_failed", {"error": bcsfe_result["error"]})
        raise HTTPException(status_code=500, detail=bcsfe_result["error"])

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"เกิดข้อผิดพลาด: {e}")

@app.get("/api/payment/status/{order_id}")
def payment_status(order_id: str):
    order = get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="ไม่พบ order")
    return {
        "order_id": order_id,
        "status": order["status"],
        "amount": order["amount"],
        "expires_at": order["expires_at"],
    }

@app.post("/api/order", response_model=OrderResponse)
async def place_order(order: OrderRequest):
    """
    รับ order จากลูกค้า → รัน BCSFE → ส่ง Transfer Code ใหม่กลับ
    """
    
    # ===== Validation =====
    if not order.transfer_code or not order.confirmation_code:
        raise HTTPException(
            status_code=400,
            detail="Transfer Code และ Confirmation Code ห้ามว่าง"
        )
    
    if not order.items or len(order.items) == 0:
        raise HTTPException(
            status_code=400,
            detail="ต้องเลือก item อย่างน้อย 1 ชิ้น"
        )
    
    # Validate แต่ละ item
    for item in order.items:
        if item.key not in ITEM_MAP:
            raise HTTPException(
                status_code=400,
                detail=f"ไม่รู้จัก item: {item.key}"
            )
        
        cfg = ITEM_MAP[item.key]
        if item.amount <= 0:
            raise HTTPException(
                status_code=400,
                detail=f"จำนวน {item.key} ต้องมากกว่า 0"
            )
        
        if item.amount > cfg["max"]:
            raise HTTPException(
                status_code=400,
                detail=f"{cfg['label']} เกินจำนวนสูงสุด ({cfg['max']})"
            )
    
    # Validate country
    if order.country not in COUNTRIES:
        raise HTTPException(
            status_code=400,
            detail=f"Country ไม่ถูกต้อง: {order.country}"
        )
    
    # ===== รัน BCSFE =====
    try:
        print(f"\n{'='*60}")
        print(f"[ORDER] เริ่มต้น order ใหม่")
        print(f"  Transfer Code: {order.transfer_code[:8]}...")
        print(f"  Country: {COUNTRIES[order.country]}")
        print(f"  Items: {len(order.items)} รายการ")
        print(f"{'='*60}\n")
        
        runner = BCSFERunner(
            transfer=order.transfer_code,
            confirm=order.confirmation_code,
            country=order.country,
        )
        
        # แปลง items เป็น list[dict]
        items_list = [{"key": i.key, "amount": i.amount} for i in order.items]
        
        # รัน
        result = runner.run(items_list)
        
        if result["success"]:
            # สร้าง summary
            summary = [
                ItemSummary(
                    item=ITEM_MAP[i.key]["label"],
                    amount=i.amount
                )
                for i in order.items
            ]
            
            print(f"\n[ORDER] ✅ สำเร็จ!")

            # บันทึก SAVE_DATA อัตโนมัติหลัง order สำเร็จ
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
            print(f"\n[ORDER] ❌ ล้มเหลว: {result['error']}")
            raise HTTPException(
                status_code=500,
                detail=result["error"]
            )
    
    except HTTPException:
        raise
    except Exception as e:
        error_msg = f"เกิดข้อผิดพลาด: {str(e)}"
        print(f"\n[ORDER] ❌ {error_msg}")
        raise HTTPException(status_code=500, detail=error_msg)

# ============= TEST ROUTES =============

@app.get("/api/orders/list")
def list_orders():
    """ดึง orders ทั้งหมด"""
    try:
        orders_dict = {}
        
        # ลอง load จาก orders.json ตรง
        if ORDER_DB.exists():
            import json
            with open(ORDER_DB, 'r', encoding='utf-8') as f:
                try:
                    orders_dict = json.load(f)
                except:
                    pass
        
        # Filter เฉพาะ top 20 orders ล่าสุด
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
    ทดสอบการเพิ่มของเข้าเกมผ่าน BCSFE โดยไม่ต้องผ่านระบบการจ่ายเงิน
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
                "error": "Transfer Code และ Confirmation Code ห้ามว่าง"
            }
        
        if not item_key or item_key not in ITEM_MAP:
            return {
                "success": False,
                "error": f"ไม่รู้จัก item: {item_key}"
            }
        
        if amount <= 0:
            return {
                "success": False,
                "error": f"จำนวนต้องมากกว่า 0"
            }
        
        cfg = ITEM_MAP[item_key]
        if amount > cfg["max"]:
            return {
                "success": False,
                "error": f"{cfg['label']} เกินจำนวนสูงสุด ({cfg['max']})"
            }
        
        if country not in COUNTRIES:
            return {
                "success": False,
                "error": f"Country ไม่ถูกต้อง: {country}"
            }
        
        print(f"\n{'='*60}")
        print(f"[TEST-BCSFE] 🧪 ทดสอบการเพิ่มของ")
        print(f"  Transfer Code: {transfer_code[:8]}...")
        print(f"  Item: {cfg['label']} x{amount}")
        print(f"  Country: {COUNTRIES[country]}")
        print(f"{'='*60}\n")
        
        # สร้าง items list
        items_list = [{"key": item_key, "amount": amount}]
        if sub_type:
            items_list[0]["sub_type"] = sub_type
        
        # รัน BCSFE
        runner = BCSFERunner(
            transfer=transfer_code,
            confirm=confirmation_code,
            country=country,
        )
        
        result = runner.run(items_list)
        
        if result["success"]:
            codes = result.get("new_transfer_code", {})
            new_tc = codes.get("transfer") if isinstance(codes, dict) else codes
            new_cc = codes.get("confirmation") if isinstance(codes, dict) else None
            
            # บันทึก SAVE_DATA
            backup_save(new_tc or transfer_code)
            
            # สร้าง summary
            summary = [
                {
                    "item": cfg["label"],
                    "amount": amount
                }
            ]
            
            print(f"[TEST-BCSFE] ✅ สำเร็จ!")
            
            return {
                "success": True,
                "new_transfer_code": new_tc,
                "new_confirmation_code": new_cc,
                "summary": summary,
            }
        else:
            print(f"[TEST-BCSFE] ❌ ล้มเหลว: {result['error']}")
            return {
                "success": False,
                "error": result.get("error", "Unknown error")
            }
    
    except Exception as e:
        error_msg = f"เกิดข้อผิดพลาด: {str(e)}"
        print(f"[TEST-BCSFE] ❌ {error_msg}")
        return {
            "success": False,
            "error": error_msg
        }

@app.post("/api/unlock/characters")
async def unlock_characters(request: UnlockCharactersRequest):
    """ปลดล็อคตัวละครตาม cat_ids ผ่าน BCSFE"""
    try:
        transfer_code     = request.transfer_code.strip()
        confirmation_code = request.confirmation_code.strip()
        country           = request.country
        cat_ids           = request.cat_ids

        if not transfer_code or not confirmation_code:
            return {"success": False, "error": "Transfer Code และ Confirmation Code ห้ามว่าง"}
        if not cat_ids:
            return {"success": False, "error": "ต้องระบุ cat_ids อย่างน้อย 1 ตัว"}
        if country not in COUNTRIES:
            return {"success": False, "error": f"Country ไม่ถูกต้อง: {country}"}

        print(f"\n{'='*60}")
        print(f"[UNLOCK-CHARS] 🐱 ปลดล็อค {len(cat_ids)} ตัวละคร")
        print(f"  Transfer Code: {transfer_code[:8]}...")
        print(f"  Country: {COUNTRIES[country]}")
        print(f"  IDs: {str(cat_ids[:10])}{'...' if len(cat_ids) > 10 else ''}")
        print(f"{'='*60}\n")

        runner = BCSFERunner(
            transfer=transfer_code,
            confirm=confirmation_code,
            country=country,
        )
        result = runner.run_unlock_characters(cat_ids)

        if result["success"]:
            codes = result.get("new_transfer_code", {})
            new_tc = codes.get("transfer") if isinstance(codes, dict) else codes
            new_cc = codes.get("confirmation") if isinstance(codes, dict) else None
            backup_save(new_tc or transfer_code)
            print(f"[UNLOCK-CHARS] ✅ สำเร็จ!")
            return {
                "success": True,
                "new_transfer_code": new_tc,
                "new_confirmation_code": new_cc,
                "unlocked_count": len(cat_ids),
            }
        else:
            print(f"[UNLOCK-CHARS] ❌ ล้มเหลว: {result['error']}")
            return {"success": False, "error": result.get("error", "Unknown error")}

    except Exception as e:
        error_msg = f"เกิดข้อผิดพลาด: {str(e)}"
        print(f"[UNLOCK-CHARS] ❌ {error_msg}")
        return {"success": False, "error": error_msg}

@app.post("/api/upgrade/characters")
async def upgrade_characters(request: UnlockCharactersRequest):
    """อัพเกรดตัวละครถึง max level"""
    try:
        if not request.transfer_code.strip() or not request.confirmation_code.strip():
            return {"success": False, "error": "Transfer/Confirmation Code ห้ามว่าง"}
        if not request.cat_ids:
            return {"success": False, "error": "ต้องระบุ cat_ids อย่างน้อย 1 ตัว"}
        if request.country not in COUNTRIES:
            return {"success": False, "error": f"Country ไม่ถูกต้อง: {request.country}"}

        print(f"\n[UPGRADE-CHARS] ⬆️ upgrade {len(request.cat_ids)} ตัวละคร")
        runner = BCSFERunner(transfer=request.transfer_code.strip(),
                             confirm=request.confirmation_code.strip(),
                             country=request.country)
        result = runner.run_upgrade_characters(request.cat_ids)
        if result["success"]:
            codes = result.get("new_transfer_code", {})
            new_tc = codes.get("transfer") if isinstance(codes, dict) else codes
            new_cc = codes.get("confirmation") if isinstance(codes, dict) else None
            backup_save(new_tc or request.transfer_code)
            return {"success": True, "new_transfer_code": new_tc,
                    "new_confirmation_code": new_cc, "count": len(request.cat_ids)}
        return {"success": False, "error": result.get("error", "Unknown error")}
    except Exception as e:
        return {"success": False, "error": f"เกิดข้อผิดพลาด: {e}"}


@app.post("/api/trueform/characters")
async def trueform_characters(request: UnlockCharactersRequest):
    """True Form ตัวละคร"""
    try:
        if not request.transfer_code.strip() or not request.confirmation_code.strip():
            return {"success": False, "error": "Transfer/Confirmation Code ห้ามว่าง"}
        if not request.cat_ids:
            return {"success": False, "error": "ต้องระบุ cat_ids อย่างน้อย 1 ตัว"}
        if request.country not in COUNTRIES:
            return {"success": False, "error": f"Country ไม่ถูกต้อง: {request.country}"}

        print(f"\n[TRUEFORM-CHARS] ✨ true form {len(request.cat_ids)} ตัวละคร")
        runner = BCSFERunner(transfer=request.transfer_code.strip(),
                             confirm=request.confirmation_code.strip(),
                             country=request.country)
        result = runner.run_true_form_characters(request.cat_ids)
        if result["success"]:
            codes = result.get("new_transfer_code", {})
            new_tc = codes.get("transfer") if isinstance(codes, dict) else codes
            new_cc = codes.get("confirmation") if isinstance(codes, dict) else None
            backup_save(new_tc or request.transfer_code)
            return {"success": True, "new_transfer_code": new_tc,
                    "new_confirmation_code": new_cc, "count": len(request.cat_ids)}
        return {"success": False, "error": result.get("error", "Unknown error")}
    except Exception as e:
        return {"success": False, "error": f"เกิดข้อผิดพลาด: {e}"}


@app.post("/api/ultraform/characters")
async def ultraform_characters(request: UnlockCharactersRequest):
    """Ultra Form ตัวละคร (4th Form)"""
    try:
        if not request.transfer_code.strip() or not request.confirmation_code.strip():
            return {"success": False, "error": "Transfer/Confirmation Code ห้ามว่าง"}
        if not request.cat_ids:
            return {"success": False, "error": "ต้องระบุ cat_ids อย่างน้อย 1 ตัว"}
        if request.country not in COUNTRIES:
            return {"success": False, "error": f"Country ไม่ถูกต้อง: {request.country}"}

        print(f"\n[ULTRAFORM-CHARS] 💥 ultra form {len(request.cat_ids)} ตัวละคร")
        runner = BCSFERunner(transfer=request.transfer_code.strip(),
                             confirm=request.confirmation_code.strip(),
                             country=request.country)
        result = runner.run_ultra_form_characters(request.cat_ids)
        if result["success"]:
            codes = result.get("new_transfer_code", {})
            new_tc = codes.get("transfer") if isinstance(codes, dict) else codes
            new_cc = codes.get("confirmation") if isinstance(codes, dict) else None
            backup_save(new_tc or request.transfer_code)
            return {"success": True, "new_transfer_code": new_tc,
                    "new_confirmation_code": new_cc, "count": len(request.cat_ids)}
        return {"success": False, "error": result.get("error", "Unknown error")}
    except Exception as e:
        return {"success": False, "error": f"เกิดข้อผิดพลาด: {e}"}


@app.post("/api/talents/characters")
async def talents_characters(request: UnlockCharactersRequest):
    """Max Talents ตัวละคร"""
    try:
        if not request.transfer_code.strip() or not request.confirmation_code.strip():
            return {"success": False, "error": "Transfer/Confirmation Code ห้ามว่าง"}
        if not request.cat_ids:
            return {"success": False, "error": "ต้องระบุ cat_ids อย่างน้อย 1 ตัว"}
        if request.country not in COUNTRIES:
            return {"success": False, "error": f"Country ไม่ถูกต้อง: {request.country}"}

        print(f"\n[TALENTS-CHARS] 🌟 talents max {len(request.cat_ids)} ตัวละคร")
        runner = BCSFERunner(transfer=request.transfer_code.strip(),
                             confirm=request.confirmation_code.strip(),
                             country=request.country)
        result = runner.run_talents_max_characters(request.cat_ids)
        if result["success"]:
            codes = result.get("new_transfer_code", {})
            new_tc = codes.get("transfer") if isinstance(codes, dict) else codes
            new_cc = codes.get("confirmation") if isinstance(codes, dict) else None
            backup_save(new_tc or request.transfer_code)
            return {"success": True, "new_transfer_code": new_tc,
                    "new_confirmation_code": new_cc, "count": len(request.cat_ids)}
        return {"success": False, "error": result.get("error", "Unknown error")}
    except Exception as e:
        return {"success": False, "error": f"เกิดข้อผิดพลาด: {e}"}


# ============= Utility Routes =============

@app.get("/health")
def health_check():
    """ตรวจสอบสุขภาพ server"""
    return {"status": "ok"}

@app.get("/")
def root():
    """ตรวจสอบว่า server ทำงานอยู่"""
    return {"status": "ok", "message": "BCSFE Order System is running"}

# ============= Main =============

if __name__ == "__main__":
    import uvicorn
    print("🚀 BCSFE Order System เริ่มต้น...")
    print("📍 เปิด http://localhost:8000/docs")
    uvicorn.run(app, host="0.0.0.0", port=8000)