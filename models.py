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
    username: Optional[str] = None     # ชื่อผู้ใช้ (สำหรับ history lookup)

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
    country: str = ""   # ว่าง = ใช้เซิร์ฟเวอร์เดิมของ order / ใส่ "1"-"4" = เปลี่ยนเซิร์ฟเวอร์ (กรณีเลือกผิดตอนสั่ง)

class VoucherRedeemRequest(BaseModel):
    """ส่งโค้ด/ลิงก์ซองอั่งเป่า TrueMoney เพื่อ verify การชำระเงิน"""
    voucher_code: str

class AllCatsRequest(BaseModel):
    """สำหรับ action ที่ทำกับทุกตัว (ไม่ต้องระบุ IDs)"""
    transfer_code: str
    confirmation_code: str
    country: str = "1"
    payment_method: str = "promptpay"
    username: Optional[str] = None

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
    workers: int = 3            # checkID แบบไว: จำนวนที่ตรวจพร้อมกัน (1-8)

class DupeSaveRequest(BaseModel):
    transfer_code: str
    confirmation_code: str
    country: str = "1"
    count: int = 1              # จำนวนที่ต้องการ dupe (1-20)
    workers: int = 3            # dupe แบบไว: จำนวนที่ทำพร้อมกัน (1-8)
    playtime_min_h: float = 0   # dupe แบบไว: สุ่มเวลาเล่น (ชม.) ต่ำสุด — 0 = ไม่สุ่ม ใช้เวลาเดิมของเซฟ
    playtime_max_h: float = 0   # dupe แบบไว: สุ่มเวลาเล่น (ชม.) สูงสุด

class UnbanRequest(BaseModel):
    order_id: str = ""           # ใส่ order_id → ดึง TC จาก orders table
    transfer_code: str = ""      # หรือใส่ TC โดยตรง (จาก loyalty_redemptions)
    country: str = "1"
    username: str = ""
    session_token: str = ""

class RemoveCheetahUnbanRequest(BaseModel):
    transfer_code: str          # TC ของลูกค้า (download fresh)
    confirmation_code: str      # CC ของลูกค้า
    country: str = "1"
    username: str = ""          # admin username
    session_token: str = ""     # password_hash

class UnlockCharactersRequest(BaseModel):
    """โมเดลสำหรับปลดล็อคตัวละคร"""
    transfer_code: str          # Transfer Code จากเกม
    confirmation_code: str      # Confirmation Code จากเกม
    country: str = "1"          # "1"=en, "2"=jp, "3"=kr, "4"=tw
    cat_ids: List[int]          # รายการ ID ตัวละครที่ต้องการปลดล็อค

class LoyaltyRedeemRequest(BaseModel):
    """แลกของรางวัล loyalty (multi-tier: 200/500/1000)"""
    username: str
    transfer_code: str
    confirmation_code: str
    country: str = "1"
    cycles: int = 1
    tier: int = 200          # 200 / 500 / 1000
    session_token: str = ""  # password_hash จาก localStorage — ใช้ verify เจ้าของบัญชี


class CodeShopBuyRequest(BaseModel):
    """ซื้อ pre-made code"""
    product_id: str
    username: str
    session_token: str
    payment_method: str = "promptpay"


class AdminProductRequest(BaseModel):
    """admin: เพิ่มสินค้า"""
    name: str
    description: str = ""
    name_en: str = ""
    description_en: str = ""
    images: List[str] = []
    price: int = 200
    username: str
    session_token: str


class AdminToggleRequest(BaseModel):
    """admin: เปิด/ปิดสินค้า"""
    is_active: bool
    username: str
    session_token: str


class AdminEditProductRequest(BaseModel):
    """admin: แก้ไขชื่อ/คำอธิบาย/ราคาสินค้า (ไทย+อังกฤษ)"""
    name: str
    description: str = ""
    name_en: str = ""
    description_en: str = ""
    price: int = 200
    username: str
    session_token: str


class AdminStockRequest(BaseModel):
    """admin: เพิ่ม stock"""
    product_id: str
    transfer_code: str
    confirmation_code: str
    inquiry_code: Optional[str] = None
    username: str
    session_token: str


class ClearStoryChaptersRequest(BaseModel):
    """เคลียร์ด่าน Main Story ตาม chapter ที่ระบุ (1-9)"""
    transfer_code: str
    confirmation_code: str
    country: str = "1"
    chapters: List[int]   # รายการ chapter number 1-9
    clear_amount: int = 1


class ClearStoryAllRequest(BaseModel):
    """เคลียร์ด่าน Main Story ทั้ง 9 chapters"""
    transfer_code: str
    confirmation_code: str
    country: str = "1"
    clear_amount: int = 1


class ResetStoryChaptersRequest(BaseModel):
    """รีเซ็ตด่าน Main Story กลับเป็น 0 ตาม chapter ที่ระบุ"""
    transfer_code: str
    confirmation_code: str
    country: str = "1"
    chapters: List[int]


class ResetStoryAllRequest(BaseModel):
    """รีเซ็ตด่าน Main Story ทั้ง 9 chapters"""
    transfer_code: str
    confirmation_code: str
    country: str = "1"


class SetTreasureChaptersRequest(BaseModel):
    """ตั้งค่า treasure สำหรับ story chapters ที่ระบุ (1-9)"""
    transfer_code: str
    confirmation_code: str
    country: str = "1"
    chapters: List[int]
    treasure_value: int = 3  # 0=None, 1=Bronze, 2=Silver, 3=Gold


class SetTreasureAllRequest(BaseModel):
    """ตั้งค่า treasure สำหรับ story chapters ทั้ง 9"""
    transfer_code: str
    confirmation_code: str
    country: str = "1"
    treasure_value: int = 3


class ClearOutbreakChaptersRequest(BaseModel):
    """เคลียร์ zombie/outbreak สำหรับ story chapters ที่ระบุ (1-9)"""
    transfer_code: str
    confirmation_code: str
    country: str = "1"
    chapters: List[int]


class ClearOutbreakAllRequest(BaseModel):
    """เคลียร์ zombie/outbreak สำหรับ story chapters ทั้ง 9"""
    transfer_code: str
    confirmation_code: str
    country: str = "1"


class AkuRequest(BaseModel):
    """ปลดล็อค Aku Realm และ/หรือ เคลียร์ Aku Chapters"""
    transfer_code: str
    confirmation_code: str
    country: str = "1"
    do_unlock: bool = False    # Unlock Aku Realm (#8)
    do_chapters: bool = False  # Clear Aku Chapters (#11)
    clear_amount: int = 1


class ClearLegendsRequest(BaseModel):
    """เคลียร์ Legend Stages — SoL / UL / ZL พร้อมเลือก crown level"""
    transfer_code: str
    confirmation_code: str
    country: str = "1"
    legend_types: List[str]  # รายการของ "sol", "ul", "zl"
    max_crown: int = 4       # เคลียร์ crowns 1 ถึง max_crown (1-4)
    clear_amount: int = 1


class StagesConfig(BaseModel):
    """config สำหรับ stage operations"""
    story_chapters: List[int] = []       # chapters 1-9 ที่ต้องการ clear
    treasure_chapters: List[int] = []    # chapters 1-9 ที่ต้องการ gold treasure
    zombie_chapters: List[int] = []      # chapters 1-9 ที่ต้องการ clear zombie
    legend_types: List[str] = []         # "sol", "ul", "zl"
    max_crown: int = 4                   # fallback ถ้าไม่มี legend_crowns
    legend_crowns: dict = {}             # per-legend crown: {"sol":4,"ul":4,"zl":2}
    aku_unlock: bool = False
    aku_chapters: bool = False
    event_stage_ids: List[int] = []   # Normal Event Stages map IDs (type=1)


class StagesPaymentRequest(BaseModel):
    """สร้าง order สำหรับปลดล็อคด่าน"""
    transfer_code: str
    confirmation_code: str
    country: str = "1"
    payment_method: str = "promptpay"
    stages_config: StagesConfig
    amount: int
    username: Optional[str] = None


class WalletTopupRequest(BaseModel):
    """เติมเงิน wallet ผ่าน PromptPay"""
    username: str
    session_token: str
    amount: int


class WalletVoucherRequest(BaseModel):
    """เติมเงิน wallet ผ่านซองอั่งเป่า TrueMoney"""
    username: str
    session_token: str
    voucher_code: str


class WalletPayRequest(BaseModel):
    """จ่ายด้วย wallet balance"""
    username: str
    session_token: str


class CRBuyRequest(BaseModel):
    """ซื้อ CR license key"""
    product_id: str
    username: str
    session_token: str
    payment_method: str = "promptpay"
    quantity: int = 1


class CRAdminProductRequest(BaseModel):
    """admin: เพิ่มสินค้า CR"""
    name: str
    description: str = ""
    name_en: str = ""
    description_en: str = ""
    license_type: str = "single"
    duration: str = "permanent"
    price: int = 200
    download_url: str = ""
    username: str
    session_token: str


class CRAdminEditProductRequest(BaseModel):
    """admin: แก้ไขสินค้า CR"""
    name: str
    description: str = ""
    name_en: str = ""
    description_en: str = ""
    price: int = 200
    download_url: str = ""
    username: str
    session_token: str


class CRAdminStockRequest(BaseModel):
    """admin: เพิ่ม license key เข้า CR stock"""
    product_id: str
    license_key: str
    username: str
    session_token: str