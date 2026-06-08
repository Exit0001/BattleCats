# models.py - Pydantic models สำหรับ request/response

from pydantic import BaseModel
from typing import Optional, List

class ItemRequest(BaseModel):
    """โมเดลสำหรับ item ที่ลูกค้าต้องการเพิ่ม"""
    key: str                    # "cat_food", "xp", ...
    amount: int                 # จำนวนที่ต้องการเพิ่ม
    sub_type: Optional[int] = None  # sub-type สำหรับ catseye (1-6) และ catfruit (1-29)
    cat_id: Optional[int] = None    # สำหรับ per-cat services (upgrade_cat, trueform_cat, ...)

class OrderRequest(BaseModel):
    """โมเดลสำหรับ order request จากลูกค้า"""
    transfer_code: str               # Transfer Code จากเกม
    confirmation_code: str           # Confirmation Code จากเกม
    country: str = "1"               # "1"=en, "2"=jp, "3"=kr, "4"=tw
    items: List[ItemRequest] = []    # รายการ item (ถ้ามี)
    cat_ids: Optional[List[int]] = None   # IDs แมวที่ต้องการปลดล็อค (ถ้ามี)
    cat_unlock_total: int = 0        # ราคาปลดล็อคแมวรวม (คำนวณจาก frontend)
    payment_method: str = "promptpay"  # "promptpay" หรือ "truemoney"

class ItemSummary(BaseModel):
    """สรุป item ที่แก้ไขไปแล้ว"""
    item: str       # ชื่อ item
    amount: int     # จำนวนที่เพิ่ม

class OrderResponse(BaseModel):
    """โมเดลสำหรับ order response"""
    success: bool                                        # สำเร็จหรือไม่
    new_transfer_code: Optional[str] = None             # Transfer Code ใหม่
    new_confirmation_code: Optional[str] = None         # Confirmation Code ใหม่
    error: Optional[str] = None                         # ข้อความ error (ถ้ามี)
    summary: Optional[List[ItemSummary]] = None         # สรุปสิ่งที่แก้ไข

class TestBCSFERequest(BaseModel):
    """โมเดลสำหรับทดสอบ BCSFE"""
    transfer_code: str          # Transfer Code จากเกม
    confirmation_code: str      # Confirmation Code จากเกม
    item: str                   # ประเภทของ (key)
    amount: int                 # จำนวนที่ต้องการเพิ่ม
    sub_type: Optional[int] = None  # sub-type (ถ้ามี)
    country: str = "1"          # "1"=en, "2"=jp, "3"=kr, "4"=tw

class RetryRequest(BaseModel):
    """กรอก transfer/confirmation code ใหม่สำหรับ bcsfe_failed order"""
    transfer_code: str
    confirmation_code: str

class VoucherRedeemRequest(BaseModel):
    """ส่งโค้ด/ลิงก์ซองอั่งเป่า TrueMoney เพื่อ verify การชำระเงิน"""
    voucher_code: str

class AllCatsRequest(BaseModel):
    """สำหรับ action ที่ทำกับทุกตัว (ไม่ต้องระบุ IDs)"""
    transfer_code: str
    confirmation_code: str
    country: str = "1"
    payment_method: str = "promptpay"

class UnlockPaymentRequest(BaseModel):
    """สร้าง order สำหรับปลดล็อคแมว"""
    transfer_code: str
    confirmation_code: str
    country: str = "1"
    cat_ids: List[int]
    total: int
    payment_method: str = "promptpay"

class CheckIDEntry(BaseModel):
    transfer_code: str
    confirmation_code: str

class CheckIDRequest(BaseModel):
    codes: List[CheckIDEntry]
    country: str = "1"

class DupeSaveRequest(BaseModel):
    transfer_code: str
    confirmation_code: str
    country: str = "1"
    count: int = 1              # จำนวนที่ต้องการ dupe (1-20)

class UnlockCharactersRequest(BaseModel):
    """โมเดลสำหรับปลดล็อคตัวละคร"""
    transfer_code: str          # Transfer Code จากเกม
    confirmation_code: str      # Confirmation Code จากเกม
    country: str = "1"          # "1"=en, "2"=jp, "3"=kr, "4"=tw
    cat_ids: List[int]          # รายการ ID ตัวละครที่ต้องการปลดล็อค