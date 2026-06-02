# 🚀 BCSFE Order System - Setup Guide

คู่มือติดตั้งและเริ่มต้นใช้งาน BCSFE Order System

---

## 📋 ข้อกำหนด

- **Python 3.8+** - [ดาวน์โหลด](https://www.python.org/downloads/)
- **pip** - (มาพร้อมกับ Python)
- **Internet Connection** - สำหรับเชื่อมต่อกับ BCSFE server

---

## 🪟 Windows

### วิธีที่ 1: ใช้ Batch Script (ง่ายที่สุด)

1. เปิด Command Prompt หรือ PowerShell ในโฟลเดอร์โปรเจกต์
2. รันคำสั่ง:
   ```bash
   run.bat
   ```
3. รอจนกว่า server เริ่มต้น แล้วเปิด browser ไปที่:
   ```
   orders.html
   ```

### วิธีที่ 2: Manual Setup

1. **สร้าง Virtual Environment**:
   ```bash
   python -m venv venv
   ```

2. **เปิดใช้ Virtual Environment**:
   ```bash
   venv\Scripts\activate.bat
   ```

3. **ติดตั้ง Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **รัน Server**:
   ```bash
   python main.py
   ```

5. **เปิด Browser**:
   ```
   orders.html
   ```

---

## 🐧 Linux / 🍎 macOS

### วิธีที่ 1: ใช้ Shell Script (ง่ายที่สุด)

1. เปิด Terminal ในโฟลเดอร์โปรเจกต์
2. ให้สิทธิ์ execute:
   ```bash
   chmod +x run.sh
   ```
3. รันสคริปต์:
   ```bash
   ./run.sh
   ```
4. เปิด browser ไปที่:
   ```
   orders.html
   ```

### วิธีที่ 2: Manual Setup

1. **สร้าง Virtual Environment**:
   ```bash
   python3 -m venv venv
   ```

2. **เปิดใช้ Virtual Environment**:
   ```bash
   source venv/bin/activate
   ```

3. **ติดตั้ง Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **รัน Server**:
   ```bash
   python main.py
   ```

5. **เปิด Browser**:
   ```
   orders.html
   ```

---

## ✅ ตรวจสอบการติดตั้ง

### 1. ตรวจสอบ Python
```bash
python --version
# ต้องได้ 3.8 ขึ้นไป
```

### 2. ตรวจสอบ BCSFE
```bash
python -m bcsfe --version
```

### 3. ตรวจสอบ FastAPI
```bash
python -c "import fastapi; print(fastapi.__version__)"
```

### 4. ทดสอบ Server
```bash
curl http://localhost:8000/health
# ต้องได้ {"status":"ok"}
```

---

## 🔍 Troubleshooting

### ❌ Python not found
**วิธีแก้**:
- ติดตั้ง Python 3.8+ จาก https://www.python.org/
- ตรวจสอบว่า Python ถูก add ใน PATH

### ❌ bcsfe not found
**วิธีแก้**:
```bash
pip install bcsfe --upgrade
```

### ❌ Port 8000 already in use
**วิธีแก้**:
- ปิด program อื่นที่ใช้ port 8000
- หรือเปลี่ยน port ใน main.py:
  ```python
  uvicorn.run(app, host="0.0.0.0", port=8001)
  ```

### ❌ Connection refused
**วิธีแก้**:
- ตรวจสอบว่า server กำลังรัน
- ลองเปิด http://localhost:8000/health
- ตรวจสอบ firewall settings

### ❌ CORS error
**วิธีแก้**:
- ตรวจสอบว่า frontend และ backend อยู่ URL เดียวกัน
- หรือ CORS middleware ถูกตั้งค่าแล้ว (ตรวจสอบ main.py)

---

## 🎯 First Run Checklist

- [ ] Python 3.8+ ติดตั้ง
- [ ] เปิดใช้ Virtual Environment
- [ ] ติดตั้ง requirements.txt
- [ ] ตรวจสอบ `python -m bcsfe --version`
- [ ] รัน `python main.py`
- [ ] เปิด browser ไป orders.html
- [ ] ทดสอบด้วย Transfer Code ทดสอบ (ถ้ามี)

---

## 📝 Advanced Configuration

### เปลี่ยน Port
แก้ไข `main.py`:
```python
uvicorn.run(app, host="0.0.0.0", port=YOUR_PORT)
```

### Enable Debug Mode
```bash
python main.py --debug
```

### ใช้ Gunicorn สำหรับ Production
```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:8000 main:app
```

### ดู API Documentation
เปิด: `http://localhost:8000/docs`

---

## 🔗 Links

- **BCSFE**: https://github.com/beinsezii/bcsfe
- **FastAPI**: https://fastapi.tiangolo.com/
- **Pexpect**: https://pexpect.readthedocs.io/

---

## 💬 Support

หากมีปัญหา:
1. ตรวจสอบ `logs/bcsfe_log_*.txt` ไฟล์
2. ดู API docs: http://localhost:8000/docs
3. ลองรัน `python -m bcsfe` ด้วยตนเอง

---

**Happy ordering! 🎉**
