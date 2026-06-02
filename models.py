# models.py - Pydantic models สำหรับ request/response

from pydantic import BaseModel
from typing import Optional, List

class ItemRequest(BaseModel):
    """โมเดลสำหรับ item ที่ลูกค้าต้องการเพิ่ม"""
    key: str                    # "cat_food", "xp", ...
    amount: int                 # จำนวนที่ต้องการเพิ่ม
    sub_type: Optional[int] = None  # sub-type สำหรับ catseye (1-6) และ catfruit (1-29)

class OrderRequest(BaseModel):
    """โมเดลสำหรับ order request จากลูกค้า"""
    transfer_code: str          # Transfer Code จากเกม
    confirmation_code: str      # Confirmation Code จากเกม
    country: str = "1"          # "1"=en, "2"=jp, "3"=kr, "4"=tw
    items: List[ItemRequest]    # รายการ item ที่ต้องการ

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