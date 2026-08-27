# Unban Tool Skill

ใช้เมื่อต้องการแก้ไข/เพิ่มฟีเจอร์ระบบ Unban Account

---

## ไฟล์ที่เกี่ยวข้อง

| ไฟล์ | หน้าที่ |
|------|---------|
| `unban.html` | Admin UI — login gate + ค้น username + แสดงผล |
| `main.py` | `POST /api/admin/unban/run` endpoint |
| `runner.py` | `run_unban_from_backup(vps_save_bytes)` method |
| `models.py` | `UnbanRequest` model |

---

## Flow ทั้งหมด

```
Admin พิมพ์ username
    ↓
searchAll() — query Supabase พร้อมกัน 2 tables:
    • orders          → order_id, transfer_code, status, amount
    • loyalty_redemptions → original_transfer_code, new_transfer_code, cycles
    ↓
Admin กดเลือก row
    • Orders row    → selectByOrderId()  → ใส่ order_id ใน form
    • Loyalty row   → selectByTC()       → ใส่ transfer_code โดยตรงใน hidden input
    ↓
Admin กด Unban Account
    ↓
POST /api/admin/unban/run
    • ถ้ามี transfer_code → ใช้ตรงเลย (จาก loyalty)
    • ถ้ามี order_id      → query orders table ดึง transfer_code
    ↓
ค้นไฟล์ใน saves_backup/SAVE_*_{tc[:8]}
    ↓
อ่าน bytes → core.SaveFile(core.Data(bytes), cc=cc)
    ↓
create_new_account() → get_codes()
    ↓
Return: new_tc, new_cc, inquiry_before, inquiry_after, backup_used
```

---

## Backup File Format

```
/battlecats/saves_backup/SAVE_{YYYYMMDD}_{HHMMSS}_{TC_FIRST_8}
```

- `TC_FIRST_8` = **8 ตัวแรก** ของ transfer_code (ไม่ใช่ 9)
- สร้างโดย `runner.py → _backup()` ทุกครั้งที่ทำ operation
- ลบอัตโนมัติเมื่อ server restart ถ้าเก่ากว่า 30 วัน (`_cleanup_old_files()` ใน main.py)

---

## UnbanRequest Model (`models.py`)

```python
class UnbanRequest(BaseModel):
    order_id: str = ""           # ใส่ order_id → ดึง TC จาก orders table
    transfer_code: str = ""      # หรือใส่ TC โดยตรง (จาก loyalty_redemptions)
    country: str = "1"
    username: str = ""           # admin username (สำหรับ verify_admin_session)
    session_token: str = ""      # password_hash
```

---

## Endpoint (`main.py`)

```python
@app.post("/api/admin/unban/run")
async def admin_unban_run(request: UnbanRequest):
    # 1. verify_admin_session
    # 2. ถ้ามี transfer_code ใช้ตรง / ถ้ามี order_id ดึงจาก Supabase
    # 3. ค้น saves_backup/ ด้วย glob pattern: SAVE_*_{tc[:8]}
    # 4. open(backup_path, "rb").read() → save_bytes
    # 5. BCSFERunner.run_unban_from_backup(save_bytes)
    # 6. return new_tc, new_cc, inquiry_before, inquiry_after, backup_used
```

---

## Runner Method (`runner.py`)

```python
def run_unban_from_backup(self, vps_save_bytes: bytes) -> dict:
    # core.SaveFile(core.Data(bytes), cc=cc) — โหลดจาก bytes
    # create_new_account()  → Inquiry Code ใหม่ (= unban)
    # get_codes()           → TC ใหม่ + CC ใหม่
    # return inquiry_before, inquiry_after เพื่อยืนยันว่า unban จริง
```

> ถ้า `inquiry_before == inquiry_after` → unban อาจไม่สำเร็จ

---

## Auth

- ใช้ `verify_admin_session(username, session_token)` — เหมือน admin panel อื่น
- Frontend เก็บ session ใน `sessionStorage` (`bc_unban_user`, `bc_unban_hash`)
- hash = `btoa(unescape(encodeURIComponent(password)))`

---

## จุดที่ต้องระวังเมื่อแก้

| จุด | หมายเหตุ |
|-----|---------|
| TC prefix | ใช้ `tc[:8]` เสมอ (8 ตัวแรก ไม่ใช่ 9) |
| Glob pattern | `SAVE_*_{tc[:8]}` — underscore หน้า prefix |
| Loyalty TC | ใช้ `original_transfer_code` ไม่ใช่ `new_transfer_code` |
| `confirm` ใน BCSFERunner | ใส่ `"00000000"` (dummy) เพราะไม่ได้ download จาก PONOS |
| `core.SaveFile(core.Data(bytes))` | bytes ต้องเป็น save data จริง ถ้าว่างเปล่าจะ error |

---

## Deploy

```powershell
$pass = ConvertTo-SecureString "SZ/(-6p-x/(yXXQW" -AsPlainText -Force
$cred = New-Object System.Management.Automation.PSCredential("root", $pass)
$base = "c:\Users\modpo\OneDrive\เดสก์ท็อป\btc\BattleCats"

foreach ($f in @("unban.html","main.py","runner.py","models.py")) {
    Set-SCPItem -ComputerName "187.77.156.253" -Credential $cred -Path "$base\$f" -Destination "/battlecats/" -Force -AcceptKey
}
$s = New-SSHSession -ComputerName "187.77.156.253" -Credential $cred -AcceptKey -Force
Invoke-SSHCommand -SSHSession $s -Command "systemctl restart battlecats"
Remove-SSHSession $s
```
