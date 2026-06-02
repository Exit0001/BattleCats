# runner.py - BCSFERunner (Windows Compatible)
# อ่าน output ทีละ character เพราะ bcsfe ไม่ขึ้น newline หลัง prompt

import os
import subprocess
import threading
import queue
import re
import time
from datetime import datetime
from config import ITEM_MAP

try:
    import pyautogui
    HAS_PYAUTOGUI = True
except ImportError:
    HAS_PYAUTOGUI = False


class BCSFERunner:
    SEND_DELAY = 0.5

    def __init__(self, transfer: str, confirm: str, country: str = "1"):
        self.transfer  = transfer
        self.confirm   = confirm
        self.country   = country
        self.log_file  = os.path.join("logs", f"bcsfe_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
        self.process   = None
        self._q        = queue.Queue()
        self._full_log = []
        self._buf      = ""

    def run(self, items: list) -> dict:
        try:
            os.makedirs(os.path.dirname(self.log_file), exist_ok=True)
            print(f"[BCSFE] ══ เริ่มต้น (log: {self.log_file}) ══")

            # ตั้ง PYTHONIOENCODING=utf-8 เพื่อให้ bcsfe แสดง Unicode ได้บน Windows
            import os as _os
            env = _os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONUTF8"] = "1"
            # ปิด tkinter GUI dialogs ของ bcsfe บน Windows
            # บังคับให้ใช้ text-based input แทน file dialog
            env["BCSFE_DISABLE_DIALOGS"] = "1"
            env["NO_COLOR"] = "1"

            self.process = subprocess.Popen(
                ["python", "-m", "bcsfe"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=0,
                env=env,
            )

            threading.Thread(
                target=self._reader_char,
                args=(self.process.stdout,),
                daemon=True,
            ).start()

            # thread ปิด tkinter dialog อัตโนมัติ
            # bcsfe บน Windows ขึ้น file dialog ตอน save → ต้องกด Enter ปิด
            if HAS_PYAUTOGUI:
                threading.Thread(
                    target=self._dialog_killer,
                    daemon=True,
                ).start()

            # Auto-answer BCSFE startup update prompts
            self._handle_update_prompts()

            self._wait_send("Input a number between", "1", "เมนูหลัก → Download save")
            self._wait_send("Enter Transfer Code", self.transfer, "Transfer Code")
            self._wait_send("Enter Confirmation Code", self.confirm, "Confirmation Code")

            # รอ country list ครบแล้วค่อยส่ง
            self._wait_new("4. tw", timeout=15)
            self._wait_new("Select country code", timeout=15)
            time.sleep(0.3)
            self._send(self.country, f"ภาษา → {self.country}")

            # ตรวจสอบว่า download สำเร็จ
            result = self._wait_any(
                ["Features:", "Failed to download", "debug info"],
                timeout=30,
            )

            if result == 1:
                self._send("n", "ปฏิเสธ debug info")
                self._kill()
                self._write_log()
                return {"success": False, "error": "❌ Transfer Code หรือ Confirmation Code ไม่ถูกต้อง หรือหมดอายุแล้ว กรุณากด 'Begin Data Transfer' ในเกมใหม่แล้วลองอีกครั้ง"}

            if result == 2:
                self._send("n", "ปฏิเสธ debug info")
                self._kill()
                self._write_log()
                return {"success": False, "error": "❌ Transfer Code หรือ Confirmation Code ไม่ถูกต้อง หรือหมดอายุแล้ว กรุณากด 'Begin Data Transfer' ในเกมใหม่แล้วลองอีกครั้ง"}

            print("[BCSFE] ✅ Download save สำเร็จ!")

            for item in items:
                self._edit_item(item)

            # ════ STEP 6: Save Management ════
            self._wait_send("Save Management", "1", "เข้า Save Management")

            # กด 3 → Upload to server ตรงๆ
            # bcsfe จะ save อัตโนมัติก่อน upload อยู่แล้ว
            # ไม่กด save แยก เพราะจะขึ้น file dialog บน Windows
            self._wait_send("Upload save file to server", "3", "Upload to server")

            # ถ้า bcsfe ถาม "Save save file?" (y/n) ก่อน upload → ตอบ y
            idx = self._wait_any(
                ["Getting account", "Save save file", "(y/n)"],
                timeout=15,
            )
            if idx in (1, 2):
                self._send("y", "ยืนยัน save ก่อน upload")

            codes = self._wait_for_codes(timeout=90)
            self._exit_bcsfe()
            self._write_log()

            if codes:
                print(f"[BCSFE] ✅ Transfer: {codes['transfer']} | Confirm: {codes['confirmation']}")
                return {"success": True, "new_transfer_code": codes}
            else:
                self._print_last_log()
                return {"success": False, "error": "ไม่พบ Transfer Code ใหม่ในผลลัพธ์"}

        except TimeoutError as e:
            self._kill()
            self._write_log()
            return {"success": False, "error": f"⏱️ Timeout: {e}"}
        except Exception as e:
            self._kill()
            self._write_log()
            return {"success": False, "error": f"❌ {e}"}

    def _edit_item(self, item: dict):
        cfg = ITEM_MAP.get(item["key"])
        if not cfg:
            raise ValueError(f"ไม่รู้จัก item key: {item['key']}")

        print(f"\n[BCSFE] ── {cfg['label']} +{item['amount']} ──")

        # catseye/catfruit ต้องวนลูป sub-type — ใช้ method แยก
        if cfg.get("sub_select"):
            self._edit_sub_loop(item, cfg)
            return

        # item ทั่วไป
        self._wait_send("Features:", "2", "Features menu → 2 (Items)")
        self._wait_send("Input:", str(cfg["menu_no"]),
                        f"Items → {cfg['menu_no']} ({cfg['label']})")

        if cfg.get("has_warning"):
            self._wait_send("Do you want to continue", "y", "ยืนยัน warning → y")

        # sub_enter: ต้องกดเลขเพิ่มหลัง menu_no ก่อนใส่ค่า
        # เช่น lucky_ticket: 2→21→กด 1 (Lucky Ticket) ก่อนใส่ค่า
        if cfg.get("sub_enter") is not None:
            self._wait_send("Input", str(cfg["sub_enter"]),
                            f"sub_enter → {cfg['sub_enter']}")

        max_val = cfg["max"]
        wait_prompt = cfg.get("custom_prompt") or "Enter a value for"
        self._wait_new_keep(wait_prompt, timeout=30)

        full = "".join(self._full_log)

        if cfg.get("no_add"):
            mx = re.findall(r'max value[\s:]+(\d+)', full, re.IGNORECASE)
            actual_max = int(mx[-1]) if mx else max_val
            new_val = min(item["amount"], actual_max)
            current = None
            print(f"[BCSFE]   💡 {cfg['label']}: set = {new_val} (max={actual_max}) [no_add]")
        else:
            matches = re.findall(r'current value[\s:]+(\d+)', full, re.IGNORECASE)
            current = int(matches[-1]) if matches else 0
            new_val = min(current + item["amount"], max_val)
            print(f"[BCSFE]   💡 {cfg['label']}: {current} + {item['amount']} = {new_val} (max={max_val})")

        self._send(str(new_val), f"ส่งค่า {new_val}")
        self._wait_any(["Successfully changed", "Features:", "cat storage", "You now need"], timeout=30)
        result_str = f"{current} → {new_val}" if current is not None else f"set {new_val}"
        print(f"[BCSFE] ✔ {cfg['label']} เสร็จ ({result_str})")

    def _edit_sub_loop(self, item: dict, cfg: dict):
        """
        catseye (1-6) และ catfruit (1-29)
        จาก log จริง: หลัง Successfully changed bcsfe กลับ Features menu ใหญ่
        ทุกรอบต้องกด 2 (Items) → menu_no ใหม่เสมอ
        """
        sub_range = cfg.get("sub_select", "1-6")
        max_sub = int(sub_range.split("-")[1])
        max_val = cfg["max"]

        print(f"[BCSFE] catseye/catfruit loop: sub 1..{max_sub} each +{item['amount']}")

        for i in range(1, max_sub + 1):
            print(f"[BCSFE]   🔁 รอบ {i}/{max_sub}")

            # ทุกรอบ: กด 2 (Items) ใหม่
            self._wait_send("Features:", "2", f"รอบ {i}: Features → 2 (Items)")

            # ทุกรอบ: กด menu_no (14/15) ใหม่
            self._wait_send("Input:", str(cfg["menu_no"]),
                            f"รอบ {i}: Items → {cfg['menu_no']} ({cfg['label']})")

            # ส่ง i (sub-type) — รอ "Input" ก่อน (bcsfe แสดง list แล้วรอ Input)
            self._wait_send("Input", str(i), f"รอบ {i}: เลือก sub-type {i}")

            # รอ "Enter a value for" แล้วอ่าน current
            self._wait_new_keep("Enter a value for", timeout=30)

            full = "".join(self._full_log)
            matches = re.findall(r'current value[\s:]+(\d+)', full, re.IGNORECASE)
            current = int(matches[-1]) if matches else 0
            new_val = min(current + item["amount"], max_val)

            print(f"[BCSFE]     💡 sub {i}: {current} + {item['amount']} = {new_val} (max={max_val})")
            self._send(str(new_val), f"ส่งค่า {new_val}")

            # รอยืนยันแล้ววนรอบถัดไป
            self._wait_any(["Successfully changed", "Features:"], timeout=30)
            print(f"[BCSFE]     ✔ sub {i} เสร็จ ({current} → {new_val})")

        print(f"[BCSFE] ✔ {cfg['label']} ครบ {max_sub} sub-types")


    def _wait_for_codes(self, timeout: int = 90):
        deadline = time.time() + timeout
        print("[BCSFE]   ⏳ รอ Transfer + Confirmation Code ใหม่...")

        transfer     = None
        confirmation = None

        while time.time() < deadline:
            try:
                chunk = self._q.get(timeout=1)
                self._buf += chunk

                mt = re.search(
                    r"Transfer\s+Code\s*:\s*([A-Za-z0-9\-_@#$%^&*.()\[\]]+)",
                    self._buf, re.IGNORECASE
                )
                if mt:
                    transfer = mt.group(1).strip()
                    print(f"[BCSFE]   ✓ Transfer Code: {transfer}")

                mc = re.search(
                    r"Confirmation\s+Code\s*:\s*([A-Za-z0-9\-_@#$%^&*.()\[\]]+)",
                    self._buf, re.IGNORECASE
                )
                if mc:
                    confirmation = mc.group(1).strip()
                    print(f"[BCSFE]   ✓ Confirmation Code: {confirmation}")

                if transfer and confirmation:
                    return {"transfer": transfer, "confirmation": confirmation}

            except queue.Empty:
                if self.process.poll() is not None:
                    full = "".join(self._full_log)
                    mt = re.search(r"Transfer\s+Code\s*:\s*(\S+)", full, re.IGNORECASE)
                    mc = re.search(r"Confirmation\s+Code\s*:\s*(\S+)", full, re.IGNORECASE)
                    if mt and mc:
                        return {"transfer": mt.group(1).strip(), "confirmation": mc.group(1).strip()}
                    raise TimeoutError("Process จบก่อนเจอ Transfer Code")

        raise TimeoutError(f"รอ Transfer Code เกิน {timeout}s")

    def _reader_char(self, stdout):
        chunk = ""
        while True:
            ch = stdout.read(1)
            if not ch:
                if chunk:
                    self._full_log.append(chunk)
                    self._q.put(chunk)
                break

            chunk += ch
            self._full_log.append(ch)

            if ch in (":", "\n") or len(chunk) >= 80:
                self._q.put(chunk)
                if "\n" in chunk:
                    print(f"  [OUT] {chunk.rstrip()}")
                chunk = ""

        stdout.close()

    def _send(self, text: str, label: str = ""):
        print(f"[BCSFE]   ➤ {label}: '{text[:60]}'")
        self.process.stdin.write(text + "\n")
        self.process.stdin.flush()
        time.sleep(self.SEND_DELAY)

    def _wait_send(self, wait_for: str, send: str, label: str = "", timeout: int = 60):
        self._wait_new(wait_for, timeout=timeout)
        self._send(send, label)

    def _handle_update_prompts(self, timeout: int = 5):
        """ตอบ prompt อัพเดตของ BCSFE อัตโนมัติ"""
        try:
            idx = self._wait_any([
                "Would you like to update",
                "Would you like to disable update messages",
            ], timeout=timeout)

            if idx == 0:
                self._send("n", "ตอบไม่อัพเดต")
                try:
                    self._wait_new("Would you like to disable update messages", timeout=timeout)
                    self._send("y", "ปิดข้อความอัพเดต")
                except TimeoutError:
                    pass
            elif idx == 1:
                self._send("y", "ปิดข้อความอัพเดต")
        except TimeoutError:
            return

    def _wait_new(self, keyword: str, timeout: int = 60):
        """รอ keyword แล้วตัด buffer ส่วนก่อนหน้าทิ้ง"""
        deadline = time.time() + timeout
        print(f"[BCSFE]   ⏳ รอ prompt: '{keyword}'")

        if keyword.lower() in self._buf.lower():
            print(f"[BCSFE]   ✓ พบ (buffer): '{keyword}'")
            idx = self._buf.lower().find(keyword.lower())
            self._buf = self._buf[idx + len(keyword):]
            return

        while time.time() < deadline:
            try:
                chunk = self._q.get(timeout=1)
                self._buf += chunk

                if keyword.lower() in self._buf.lower():
                    print(f"[BCSFE]   ✓ พบ: '{keyword}'")
                    idx = self._buf.lower().find(keyword.lower())
                    self._buf = self._buf[idx + len(keyword):]
                    return

                if len(self._buf) > 5000:
                    self._buf = self._buf[-2000:]

            except queue.Empty:
                if self.process.poll() is not None:
                    raise TimeoutError(
                        f"bcsfe จบก่อนเจอ '{keyword}'\n"
                        f"buffer ล่าสุด: {self._buf[-300:]}"
                    )

        raise TimeoutError(f"รอ '{keyword}' เกิน {timeout}s")

    def _wait_new_keep(self, keyword: str, timeout: int = 60):
        """
        รอ keyword เหมือน _wait_new แต่ไม่ตัด buffer
        ใช้ตอนต้องอ่านข้อมูลจาก buffer หลังเจอ keyword เช่น current value
        """
        deadline = time.time() + timeout
        print(f"[BCSFE]   ⏳ รอ prompt (keep buf): '{keyword}'")

        if keyword.lower() in self._buf.lower():
            print(f"[BCSFE]   ✓ พบ (buffer): '{keyword}'")
            return

        while time.time() < deadline:
            try:
                chunk = self._q.get(timeout=1)
                self._buf += chunk

                if keyword.lower() in self._buf.lower():
                    print(f"[BCSFE]   ✓ พบ: '{keyword}'")
                    return

                if len(self._buf) > 5000:
                    self._buf = self._buf[-2000:]

            except queue.Empty:
                if self.process.poll() is not None:
                    raise TimeoutError(
                        f"bcsfe จบก่อนเจอ '{keyword}'\n"
                        f"buffer ล่าสุด: {self._buf[-300:]}"
                    )

        raise TimeoutError(f"รอ '{keyword}' เกิน {timeout}s")

    def _wait_any(self, keywords: list, timeout: int = 30) -> int:
        deadline = time.time() + timeout

        for i, kw in enumerate(keywords):
            if kw.lower() in self._buf.lower():
                return i

        while time.time() < deadline:
            try:
                chunk = self._q.get(timeout=1)
                self._buf += chunk

                for i, kw in enumerate(keywords):
                    if kw.lower() in self._buf.lower():
                        return i

                if len(self._buf) > 5000:
                    self._buf = self._buf[-2000:]

            except queue.Empty:
                if self.process.poll() is not None:
                    raise TimeoutError(f"Process จบก่อนเจอ {keywords}")

        raise TimeoutError(f"รอ {keywords} เกิน {timeout}s")

    def _dialog_killer(self):
        """
        Thread รันตลอด session
        1. เจอ "Save save file" dialog → เปลี่ยนชื่อเป็น timestamp แล้วกด Save
        2. เจอ "Confirm Save As" (ถาม overwrite) → กด Yes
        """
        import time as _t
        if not HAS_PYAUTOGUI:
            return

        print("[BCSFE] 🤖 dialog_killer เริ่มทำงาน")
        while self.process and self.process.poll() is None:
            try:
                # ── ตรวจ Save dialog ──
                wins = pyautogui.getWindowsWithTitle("Save save file")
                if wins:
                    print("[BCSFE] 🤖 พบ 'Save save file' dialog → เปลี่ยนชื่อ + Save")
                    wins[0].activate()
                    _t.sleep(0.4)

                    # ใส่ชื่อไฟล์ใหม่เป็น timestamp
                    timestamp = datetime.now().strftime("SAVE_%Y%m%d_%H%M%S")
                    # triple-click เพื่อ select all ในช่อง filename แล้วพิมพ์ใหม่
                    pyautogui.hotkey("alt", "n")   # focus ที่ช่อง File name
                    _t.sleep(0.2)
                    pyautogui.hotkey("ctrl", "a")  # select all
                    _t.sleep(0.1)
                    pyautogui.write(timestamp, interval=0.03)
                    _t.sleep(0.2)
                    pyautogui.press("enter")       # กด Save
                    print(f"[BCSFE] 🤖 บันทึกเป็น {timestamp}")
                    _t.sleep(1)
                    continue

                # ── ตรวจ Confirm Save As (overwrite) ──
                confirm_wins = pyautogui.getWindowsWithTitle("Confirm Save As")
                if confirm_wins:
                    print("[BCSFE] 🤖 พบ 'Confirm Save As' → กด Yes")
                    confirm_wins[0].activate()
                    _t.sleep(0.3)
                    pyautogui.press("enter")  # Yes เป็น default button
                    print("[BCSFE] 🤖 กด Yes สำเร็จ")
                    _t.sleep(0.5)

            except Exception as e:
                pass
            _t.sleep(0.5)

    def _flush_buf(self):
        drained = 0
        while True:
            try:
                chunk = self._q.get_nowait()
                self._buf += chunk
                drained += 1
            except queue.Empty:
                break
        self._buf = ""
        if drained:
            print(f"[BCSFE]   🧹 flush buffer ({drained} chunks)")

    def _exit_bcsfe(self):
        try:
            self.process.stdin.write("12\n")
            self.process.stdin.flush()
        except Exception:
            pass
        try:
            self.process.wait(timeout=5)
        except Exception:
            self.process.kill()

    def _write_log(self):
        try:
            with open(self.log_file, "w", encoding="utf-8") as f:
                f.write("".join(self._full_log))
            print(f"[BCSFE] 📄 log → {self.log_file}")
        except Exception:
            pass

    def _kill(self):
        if self.process:
            try:
                self.process.kill()
            except Exception:
                pass

    def _print_last_log(self):
        last = "".join(self._full_log)
        print(f"[BCSFE] output ท้าย:\n{last[-600:]}")