# main.py - FastAPI server สำหรับ BCSFE order system

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
from models import OrderRequest, OrderResponse, ItemSummary, ItemRequest, TestBCSFERequest, UnlockCharactersRequest, RetryRequest, UnlockPaymentRequest, AllCatsRequest
from runner import BCSFERunner
from config import ITEM_MAP, AMOUNT_OPTIONS, COUNTRIES
from payment import (
    ITEM_PRICE,
    create_order as create_payment_order,
    create_unlock_order,
    get_order,
    is_order_expired,
    update_order_status,
    verify_slip,
    mark_slip_used,
)

# Import เพิ่มเติมสำหรับ /api/orders/list
from payment import ORDER_DB

# ── Cat image proxy — disk cache ──────────────────────────────
CAT_CACHE_DIR = Path("pictures/cats")
CAT_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# semaphore ป้องกัน fetch พร้อมกันมากเกิน
_fetch_sem = asyncio.Semaphore(8)

HEADERS = {"User-Agent": "BattleCatsShop/1.0 (image-proxy)"}

# URL patterns — Miraheze เท่านั้น (Fandom block hotlink 403)
# pattern 1: Gatyachara_{id:03d}_f.png  → cats ทั่วไป 836+ ตัว
# pattern 2: Uni{id}_s00.png            → Ancient Egg series และ special cats
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
    """สร้าง order — รองรับ items, cat_ids, หรือทั้งสองพร้อมกัน"""
    has_items  = bool(order.items)
    has_unlock = bool(order.cat_ids)

    if not has_items and not has_unlock:
        raise HTTPException(status_code=400, detail="ต้องเลือก item หรือแมวที่จะปลดล็อคอย่างน้อย 1 รายการ")

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
        cat_ids=order.cat_ids,
        cat_unlock_total=order.cat_unlock_total,
    )

    return {
        "order_id": payment_order["order_id"],
        "amount":   payment_order["amount"],
        "qr_base64": payment_order["qr_base64"],
        "expires_at": payment_order["expires_at"],
    }

@app.post("/api/payment/create-unlock")
async def payment_create_unlock(body: UnlockPaymentRequest):
    """สร้าง order ปลดล็อคแมว พร้อม QR PromptPay"""
    if not body.cat_ids:
        raise HTTPException(status_code=400, detail="ต้องเลือกแมวอย่างน้อย 1 ตัว")
    if body.total <= 0:
        raise HTTPException(status_code=400, detail="ยอดชำระต้องมากกว่า 0")

    order = create_unlock_order(
        transfer_code=body.transfer_code,
        confirmation_code=body.confirmation_code,
        country=body.country,
        cat_ids=body.cat_ids,
        amount=body.total,
    )
    return {
        "order_id":   order["order_id"],
        "amount":     order["amount"],
        "qr_base64":  order["qr_base64"],
        "expires_at": order["expires_at"],
    }


def _run_bcsfe_steps(order: dict, tc: str, cc: str) -> dict:
    """รัน BCSFE ทั้ง 2 steps (items → unlock) คืน {success, new_tc, new_cc, summary, error}"""
    has_items  = bool(order.get("items"))
    has_unlock = bool(order.get("cat_ids")) or order.get("order_type") == "unlock"
    cur_tc, cur_cc = tc, cc
    summary = []

    if has_items:
        runner = BCSFERunner(transfer=cur_tc, confirm=cur_cc, country=order["country"])
        result = runner.run(order["items"])
        if not result["success"]:
            return {"success": False, "error": result["error"]}
        codes = result["new_transfer_code"]
        cur_tc = codes.get("transfer") if isinstance(codes, dict) else codes
        cur_cc = codes.get("confirmation") if isinstance(codes, dict) else None
        summary += [{"item": ITEM_MAP[i["key"]]["label"], "amount": i["amount"]}
                    for i in order["items"] if i["key"] in ITEM_MAP]
        print(f"[BCSFE] ✅ Items done → tc={cur_tc}")

    if has_unlock:
        cat_ids = order.get("cat_ids") or []
        runner2 = BCSFERunner(transfer=cur_tc, confirm=cur_cc, country=order["country"])
        result2 = runner2.run_unlock_characters(cat_ids)
        if not result2["success"]:
            return {"success": False, "error": result2["error"]}
        codes2 = result2["new_transfer_code"]
        cur_tc = codes2.get("transfer") if isinstance(codes2, dict) else codes2
        cur_cc = codes2.get("confirmation") if isinstance(codes2, dict) else None
        summary.append({"item": f"ปลดล็อคแมว {len(cat_ids)} ตัว", "amount": len(cat_ids)})
        print(f"[BCSFE] ✅ Unlock done → tc={cur_tc}")

    return {"success": True, "new_tc": cur_tc, "new_cc": cur_cc, "summary": summary}


@app.post("/api/payment/verify/{order_id}")
async def payment_verify(order_id: str, slip: UploadFile = File(...)):
    """เช็คสลิป และ ถ้าผ่าน ให้รัน BCSFE ต่อ"""
    order = get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="ไม่พบ order นี้")

    if is_order_expired(order):
        raise HTTPException(status_code=400, detail="order หมดอายุแล้ว กรุณาสั่งใหม่")

    # bcsfe_failed = ชำระแล้วแต่ code ผิด → บอก frontend ให้แสดง retry form
    if order["status"] == "bcsfe_failed":
        return {"success": False, "bcsfe_failed": True,
                "error": "สลิปผ่านแล้วแต่ Code ไม่ถูกต้อง กรุณากรอก Code ใหม่"}

    if order["status"] in ("paid", "done", "retrying"):
        raise HTTPException(status_code=400, detail="order นี้ดำเนินการแล้ว")

    slip_bytes = await slip.read()
    slip_result = await verify_slip(slip_bytes, order_id)
    if not slip_result["success"]:
        raise HTTPException(status_code=400, detail=slip_result["reason"])

    transaction_id = slip_result.get("transaction_id", "")

    try:
        step_result = _run_bcsfe_steps(order, order["transfer_code"], order["confirmation_code"])

        if not step_result["success"]:
            update_order_status(order_id, "bcsfe_failed", {"error": step_result["error"]})
            return {"success": False, "bcsfe_failed": True, "error": step_result["error"]}

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
        raise HTTPException(status_code=404, detail="ไม่พบ order")
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

@app.post("/api/test/bcsfe/batch")
async def test_bcsfe_batch(request: OrderRequest):
    """
    ทดสอบเพิ่มของหลายรายการในครั้งเดียว — download ครั้งเดียว แก้ทุก item แล้ว upload ครั้งเดียว
    """
    try:
        transfer_code     = request.transfer_code.strip()
        confirmation_code = request.confirmation_code.strip()
        country           = request.country

        if not transfer_code or not confirmation_code:
            return {"success": False, "error": "Transfer Code และ Confirmation Code ห้ามว่าง"}
        if country not in COUNTRIES:
            return {"success": False, "error": f"Country ไม่ถูกต้อง: {country}"}
        if not request.items:
            return {"success": False, "error": "ไม่มี item ในรายการ"}

        items_list = []
        for item in request.items:
            if item.key not in ITEM_MAP:
                return {"success": False, "error": f"ไม่รู้จัก item: {item.key}"}
            cfg = ITEM_MAP[item.key]
            if item.amount <= 0 or item.amount > cfg["max"]:
                return {"success": False, "error": f"{cfg['label']} จำนวนไม่ถูกต้อง ({item.amount})"}
            entry = {"key": item.key, "amount": item.amount}
            if item.sub_type:
                entry["sub_type"] = item.sub_type
            items_list.append(entry)

        runner = BCSFERunner(transfer=transfer_code, confirm=confirmation_code, country=country)
        result = runner.run(items_list)

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
            return {"success": False, "error": result.get("error", "Unknown error")}

    except Exception as e:
        return {"success": False, "error": f"เกิดข้อผิดพลาด: {str(e)}"}


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
                    "new_confirmation_code": new_cc, "count": len(request.cat_ids), "log": result.get("log", [])}
        return {"success": False, "error": result.get("error", "Unknown error")}
    except Exception as e:
        return {"success": False, "error": f"เกิดข้อผิดพลาด: {e}"}


@app.post("/api/unlock/all")
async def unlock_all_characters(request: AllCatsRequest):
    """Unlock ทุกตัวละครในเกม"""
    try:
        if not request.transfer_code.strip() or not request.confirmation_code.strip():
            return {"success": False, "error": "Transfer/Confirmation Code ห้ามว่าง"}
        if request.country not in COUNTRIES:
            return {"success": False, "error": f"Country ไม่ถูกต้อง: {request.country}"}

        print(f"\n[UNLOCK-ALL] 🐱 unlock all cats")
        runner = BCSFERunner(transfer=request.transfer_code.strip(),
                             confirm=request.confirmation_code.strip(),
                             country=request.country)
        result = runner.run_unlock_all()
        if result["success"]:
            codes = result.get("new_transfer_code", {})
            new_tc = codes.get("transfer") if isinstance(codes, dict) else codes
            new_cc = codes.get("confirmation") if isinstance(codes, dict) else None
            backup_save(new_tc or request.transfer_code)
            return {"success": True, "new_transfer_code": new_tc,
                    "new_confirmation_code": new_cc, "count": result.get("count", 0), "log": result.get("log", [])}
        return {"success": False, "error": result.get("error", "Unknown error")}
    except Exception as e:
        return {"success": False, "error": f"เกิดข้อผิดพลาด: {e}"}


@app.post("/api/upgrade/all")
async def upgrade_all_characters(request: AllCatsRequest):
    """Upgrade base max ทุกตัวที่ unlock อยู่ในรหัส"""
    try:
        if not request.transfer_code.strip() or not request.confirmation_code.strip():
            return {"success": False, "error": "Transfer/Confirmation Code ห้ามว่าง"}
        if request.country not in COUNTRIES:
            return {"success": False, "error": f"Country ไม่ถูกต้อง: {request.country}"}

        print(f"\n[UPGRADE-ALL] ⬆️ upgrade all unlocked cats")
        runner = BCSFERunner(transfer=request.transfer_code.strip(),
                             confirm=request.confirmation_code.strip(),
                             country=request.country)
        result = runner.run_upgrade_all_characters()
        if result["success"]:
            codes = result.get("new_transfer_code", {})
            new_tc = codes.get("transfer") if isinstance(codes, dict) else codes
            new_cc = codes.get("confirmation") if isinstance(codes, dict) else None
            backup_save(new_tc or request.transfer_code)
            return {"success": True, "new_transfer_code": new_tc,
                    "new_confirmation_code": new_cc, "count": result.get("count", 0), "log": result.get("log", [])}
        return {"success": False, "error": result.get("error", "Unknown error")}
    except Exception as e:
        return {"success": False, "error": f"เกิดข้อผิดพลาด: {e}"}


@app.post("/api/trueform/all")
async def trueform_all_characters(request: AllCatsRequest):
    """True Form ทุกตัวที่ลูกค้ามีอยู่แล้ว"""
    try:
        if not request.transfer_code.strip() or not request.confirmation_code.strip():
            return {"success": False, "error": "Transfer/Confirmation Code ห้ามว่าง"}
        if request.country not in COUNTRIES:
            return {"success": False, "error": f"Country ไม่ถูกต้อง: {request.country}"}

        print(f"\n[TRUEFORM-ALL] ✨ true form all unlocked cats")
        runner = BCSFERunner(transfer=request.transfer_code.strip(),
                             confirm=request.confirmation_code.strip(),
                             country=request.country)
        result = runner.run_true_form_all()
        if result["success"]:
            codes = result.get("new_transfer_code", {})
            new_tc = codes.get("transfer") if isinstance(codes, dict) else codes
            new_cc = codes.get("confirmation") if isinstance(codes, dict) else None
            backup_save(new_tc or request.transfer_code)
            return {"success": True, "new_transfer_code": new_tc,
                    "new_confirmation_code": new_cc, "count": result.get("count", 0), "log": result.get("log", [])}
        return {"success": False, "error": result.get("error", "Unknown error")}
    except Exception as e:
        return {"success": False, "error": f"เกิดข้อผิดพลาด: {e}"}


@app.post("/api/ultraform/all")
async def ultraform_all_characters(request: AllCatsRequest):
    """Ultra Form ทุกตัวที่ลูกค้ามีอยู่แล้ว"""
    try:
        if not request.transfer_code.strip() or not request.confirmation_code.strip():
            return {"success": False, "error": "Transfer/Confirmation Code ห้ามว่าง"}
        if request.country not in COUNTRIES:
            return {"success": False, "error": f"Country ไม่ถูกต้อง: {request.country}"}

        print(f"\n[ULTRAFORM-ALL] 💥 ultra form all unlocked cats")
        runner = BCSFERunner(transfer=request.transfer_code.strip(),
                             confirm=request.confirmation_code.strip(),
                             country=request.country)
        result = runner.run_ultra_form_all()
        if result["success"]:
            codes = result.get("new_transfer_code", {})
            new_tc = codes.get("transfer") if isinstance(codes, dict) else codes
            new_cc = codes.get("confirmation") if isinstance(codes, dict) else None
            backup_save(new_tc or request.transfer_code)
            return {"success": True, "new_transfer_code": new_tc,
                    "new_confirmation_code": new_cc, "count": result.get("count", 0), "log": result.get("log", [])}
        return {"success": False, "error": result.get("error", "Unknown error")}
    except Exception as e:
        return {"success": False, "error": f"เกิดข้อผิดพลาด: {e}"}


@app.post("/api/talents/all")
async def talents_all_characters(request: AllCatsRequest):
    """Max Talents ทุกตัวที่ลูกค้ามีอยู่แล้ว"""
    try:
        if not request.transfer_code.strip() or not request.confirmation_code.strip():
            return {"success": False, "error": "Transfer/Confirmation Code ห้ามว่าง"}
        if request.country not in COUNTRIES:
            return {"success": False, "error": f"Country ไม่ถูกต้อง: {request.country}"}

        print(f"\n[TALENTS-ALL] 🌟 talents max all unlocked cats")
        runner = BCSFERunner(transfer=request.transfer_code.strip(),
                             confirm=request.confirmation_code.strip(),
                             country=request.country)
        result = runner.run_talents_max_all()
        if result["success"]:
            codes = result.get("new_transfer_code", {})
            new_tc = codes.get("transfer") if isinstance(codes, dict) else codes
            new_cc = codes.get("confirmation") if isinstance(codes, dict) else None
            backup_save(new_tc or request.transfer_code)
            return {"success": True, "new_transfer_code": new_tc,
                    "new_confirmation_code": new_cc, "count": result.get("count", 0), "log": result.get("log", [])}
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
                    "new_confirmation_code": new_cc, "count": len(request.cat_ids), "log": result.get("log", [])}
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
                    "new_confirmation_code": new_cc, "count": len(request.cat_ids), "log": result.get("log", [])}
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
                    "new_confirmation_code": new_cc, "count": len(request.cat_ids), "log": result.get("log", [])}
        return {"success": False, "error": result.get("error", "Unknown error")}
    except Exception as e:
        return {"success": False, "error": f"เกิดข้อผิดพลาด: {e}"}


# ============= Utility Routes =============

@app.get("/api/cat-image/{cat_id}")
async def cat_image(cat_id: int):
    """เสิร์ฟรูปแมวจาก disk cache หรือ fetch จาก wiki แล้วบันทึก"""
    cache_path = CAT_CACHE_DIR / f"{cat_id}.png"

    # disk hit → เสิร์ฟทันที
    if cache_path.exists():
        return FileResponse(str(cache_path), media_type="image/png",
                            headers={"Cache-Control": "public, max-age=604800"})

    data = await _fetch_cat_image(cat_id)
    if data is None:
        raise HTTPException(status_code=404, detail="ไม่พบรูปแมว")

    return Response(data, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=604800"})


@app.get("/api/cat-image/prewarm")
async def prewarm_cat_images():
    """เริ่ม background pre-download รูปที่ยังไม่มีใน cache"""
    asyncio.create_task(_prewarm_all())
    cached = sum(1 for f in CAT_CACHE_DIR.glob("*.png"))
    return {"message": "กำลัง pre-download รูปแมวทั้งหมดใน background", "already_cached": cached}


async def _prewarm_all():
    missing = [i for i in range(861) if not (CAT_CACHE_DIR / f"{i}.png").exists()]
    if not missing:
        print("[CAT-IMG] ✅ Cache ครบทุกตัวแล้ว")
        return
    print(f"[CAT-IMG] 🔄 Pre-warming {len(missing)} รูปที่ยังไม่มี cache...")
    await asyncio.gather(*[_fetch_cat_image(i) for i in missing], return_exceptions=True)
    cached = sum(1 for f in CAT_CACHE_DIR.glob("*.png"))
    print(f"[CAT-IMG] ✅ Pre-warm เสร็จ — cached {cached}/861")


@app.post("/api/payment/retry/{order_id}")
async def payment_retry(order_id: str, body: RetryRequest):
    """ลองใหม่ด้วย Transfer/Confirmation Code ใหม่ สำหรับ order ที่ BCSFE ล้มเหลว"""
    order = get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="ไม่พบ order นี้")

    if order["status"] not in ("bcsfe_failed", "paid"):
        raise HTTPException(
            status_code=400,
            detail=f"ไม่สามารถลองใหม่ได้ สถานะปัจจุบัน: {order['status']}"
        )

    update_order_status(order_id, "retrying", {
        "transfer_code":     body.transfer_code,
        "confirmation_code": body.confirmation_code,
    })

    try:
        # ใช้ code ใหม่จาก retry form
        step_result = _run_bcsfe_steps(order, body.transfer_code, body.confirmation_code)

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
        raise HTTPException(status_code=500, detail=f"เกิดข้อผิดพลาด: {e}")


@app.get("/health")
def health_check():
    """ตรวจสอบสุขภาพ server"""
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

# Static files (CSS, JS, images) — ต้อง mount หลัง API routes
app.mount("/assets", StaticFiles(directory="assets"), name="assets")
app.mount("/pictures", StaticFiles(directory="pictures"), name="pictures")

@app.on_event("startup")
async def startup_prewarm():
    cached = sum(1 for _ in CAT_CACHE_DIR.glob("*.png"))
    print(f"[CAT-IMG] cache มีอยู่แล้ว {cached}/861 รูป")
    if cached < 861:
        asyncio.create_task(_prewarm_all())


# ============= Main =============

if __name__ == "__main__":
    import uvicorn
    print("🚀 BCSFE Order System เริ่มต้น...")
    print("📍 เปิดหน้าเว็บ: http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)