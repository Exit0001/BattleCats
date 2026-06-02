# BCSFE Order System

ระบบการสั่งซื้อไอเทม Battle Cats อัตโนมัติ โดยใช้ BCSFE (Battle Cats Save File Editor) 

## 🚀 การติดตั้งและรัน

### ขั้นตอนที่ 1: ติดตั้ง Python Dependencies

```bash
pip install -r requirements.txt
```

**ข้อมูล**:
- `fastapi` - Web framework
- `uvicorn` - ASGI server
- `pexpect` - Terminal automation
- `bcsfe` - Battle Cats Save File Editor
- `pydantic` - Data validation

### ขั้นตอนที่ 2: รัน Server

```bash
python main.py
```

หรือ:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### ขั้นตอนที่ 3: เปิดเบราว์เซอร์

ไปที่:
```
orders.html
```

---

## 📁 โครงสร้างไฟล์

```
project/
├── main.py              # FastAPI server
├── runner.py            # BCSFERunner (pexpect automation)
├── models.py            # Pydantic models
├── config.py            # ITEM_MAP, AMOUNT_OPTIONS
├── requirements.txt     # Python dependencies
├── orders.html          # Frontend order page
├── shop.html            # Shop storefront
├── assets/              # Static styles and scripts
└── logs/
    └── bcsfe_log_*.txt # Logs (created automatically)
```

---

## 🔄 วิธีการทำงาน

### ฝั่งลูกค้า (Browser)
1. ใส่ Transfer Code + Confirmation Code จากเกม
2. เลือกภาษา
3. เลือกไอเทมและจำนวนที่ต้องการ
4. กด Submit
5. รับ Transfer Code ใหม่

### ฝั่ง Backend (Server)
1. รับ request จากลูกค้า
2. Spawn `python -m bcsfe` ผ่าน pexpect
3. จำลองการกดปุ่มตามลำดับ:
   - Download save
   - Enter codes
   - Select country
   - Edit items
   - Upload & save
4. อ่าน Transfer Code ใหม่
5. ส่ง response กลับให้ลูกค้า

---

## ⚠️ ข้อควรระวัง

| เรื่อง | รายละเอียด |
|--------|-----------|
| **Transfer Code** | ใช้ได้ครั้งเดียว ต้องกด "Begin Data Transfer" ในเกมก่อนทุกครั้ง |
| **Cat Food** | มี ban risk ตามเตือนของ bcsfe — แจ้งลูกค้าก่อนสั่ง |
| **Rare Ticket** | ต้องใช้ route 6 (Trade) เพื่อหลีกเลี่ยง ban |
| **Timeout** | ตั้งค่าให้นานพอ (60 วิ) เผื่อ Ponos server ช้า |
| **Log File** | เก็บ `logs/bcsfe_log_*.txt` ไว้ debug |

---

## 🛠️ Development

### Run with auto-reload
```bash
uvicorn main:app --reload
```

### Check API docs
เปิด: `http://localhost:8000/docs`

### View logs
```bash
tail -f logs/bcsfe_log_*.txt
```

---

## 📦 API Endpoints

### GET `/api/items`
ส่ง ITEM_MAP, AMOUNT_OPTIONS, COUNTRIES

**Response**:
```json
{
  "items": {...},
  "amounts": {...},
  "countries": {...}
}
```

### POST `/api/order`
รับ order และประมวลผล

**Request**:
```json
{
  "transfer_code": "...",
  "confirmation_code": "...",
  "country": "1",
  "items": [
    {"key": "cat_food", "amount": 10000}
  ]
}
```

**Response**:
```json
{
  "success": true,
  "new_transfer_code": "...",
  "summary": [
    {"item": "Cat Food", "amount": 10000}
  ]
}
```

---

## ✅ Checklist ก่อน Deploy

- [ ] ติดตั้ง Python 3.8+
- [ ] ติดตั้ง BCSFE (`pip install bcsfe`)
- [ ] ทดสอบ `python -m bcsfe` รันได้ใน terminal
- [ ] ตั้ง timeout ให้พอ (60 วิ)
- [ ] เก็บ logs ไว้ debug
- [ ] แจ้งลูกค้าเกี่ยวกับ ban risk (especially Cat Food)

---

## 🐛 Troubleshooting

### `bcsfe not found`
```bash
python -m bcsfe --version
# ถ้าไม่มี ให้ install:
pip install bcsfe --upgrade
```

### Timeout error
- เพิ่ม timeout ใน runner.py
- ตรวจสอบ internet connection
- ลองรัน `python -m bcsfe` ด้วยตนเอง

### Transfer Code ใช้ไม่ได้
- Transfer Code ใช้ได้แค่ครั้งเดียว
- ต้องกด "Begin Data Transfer" ใน game ใหม่

---

## 📝 Notes

- ใช้ dark theme มี Battle Cats vibes
- Single page application (no routing needed)
- Real-time form validation
- Auto-retry on network failure (frontend)

---

**Created**: 2026
**License**: Private
