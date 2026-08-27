# runner.py - BCSFERunner using bcsfe 3.x Python API + CLI subprocess for lucky/rare ticket

from datetime import datetime, timezone, timedelta
TZ_THAI = timezone(timedelta(hours=7))
from pathlib import Path
import shutil
import subprocess
import re
import time
import uuid
from bcsfe import core
from bcsfe.core.game.catbase.cat import Talent as BCSFETalent
from bcsfe.core.game.map.outbreaks import Outbreak as BCOutbreak, Chapter as OutbreakChapter

from config import ITEM_MAP

import sys as _sys
BCSFE_CLI = [_sys.executable, "-m", "bcsfe"]
BCSFE_SAVES_DIR = Path(str(core.SaveFile.get_saves_path()))  # cross-platform (Windows/Linux)

COUNTRY_MAP = {"1": "en", "2": "jp", "3": "kr", "4": "tw"}
LOG_DIR = Path("logs")

# Story chapter mapping: user-facing number (1-9) → raw index in save_file.story.chapters
# Index 3 is unused/skipped by BCSFE (get_real_chapters skips it)
STORY_CHAPTER_MAP = {
    1: 0,  # Empire of Cats Ch.1
    2: 1,  # Empire of Cats Ch.2
    3: 2,  # Empire of Cats Ch.3
    4: 4,  # Into the Future Ch.1
    5: 5,  # Into the Future Ch.2
    6: 6,  # Into the Future Ch.3
    7: 7,  # Cats of the Cosmos Ch.1
    8: 8,  # Cats of the Cosmos Ch.2
    9: 9,  # Cats of the Cosmos Ch.3
}
STORY_CHAPTER_NAMES = {
    1: "Empire of Cats Ch.1",
    2: "Empire of Cats Ch.2",
    3: "Empire of Cats Ch.3",
    4: "Into the Future Ch.1",
    5: "Into the Future Ch.2",
    6: "Into the Future Ch.3",
    7: "Cats of the Cosmos Ch.1",
    8: "Cats of the Cosmos Ch.2",
    9: "Cats of the Cosmos Ch.3",
}
STORY_STAGES_PER_CHAPTER = 48  # stages 0–47 per chapter


class BCSFERunner:
    def __init__(self, transfer: str, confirm: str, country: str = "1", shared_log=None):
        self.transfer = transfer.strip()
        self.confirm  = confirm.strip()
        self.country  = country.strip()
        self._session_id  = uuid.uuid4().hex[:8]
        self._save_path   = BCSFE_SAVES_DIR / f"SAVE_DATA_{self._session_id}"
        self._cli_save_path = BCSFE_SAVES_DIR / f"SAVE_DATA_cli_{self._session_id}"
        if shared_log is not None:
            self._log_file  = shared_log
            self._owned_log = False
        else:
            LOG_DIR.mkdir(exist_ok=True)
            ts = datetime.now(TZ_THAI).strftime("%Y%m%d_%H%M%S")
            self._log_path = LOG_DIR / f"api_log_{ts}_{self.transfer[:8]}.txt"
            self._log_file = open(self._log_path, "w", encoding="utf-8")
            self._owned_log = True
        self._deferred_cli = []
        self._last_cli_output = ""
        self._latest_tc   = self.transfer
        self._latest_cc   = self.confirm
        self._download_done = False
        self._log(f"{'='*60}")
        self._log(f"เวลา      : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self._log(f"Transfer  : {self.transfer}")
        self._log(f"Confirm   : {self.confirm}")
        self._log(f"Country   : {COUNTRY_MAP.get(self.country, 'en')}")
        self._log(f"{'='*60}")

    def _log(self, msg: str):
        print(msg)
        self._log_file.write(msg + "\n")
        self._log_file.flush()

    def _close_log(self):
        if self._owned_log:
            self._log_file.close()

    def _error_result(self, e: Exception) -> dict:
        """Build error result. If download already succeeded, include latest TC so customer isn't stuck."""
        err = {"success": False, "error": str(e)}
        if self._download_done:
            err["latest_transfer_code"] = {
                "transfer":     self._latest_tc,
                "confirmation": self._latest_cc,
            }
        return err

    # ──────────────────────────────────────────────────
    # CLI subprocess helper (lucky_ticket / rare_ticket)
    # ──────────────────────────────────────────────────

    def _run_cli_item(self, transfer: str, confirm: str, key: str,
                      amount: int, current: int = 0, use_local: bool = False) -> dict:
        """
        รัน bcsfe CLI ด้วย communicate() — ส่ง inputs ทั้งหมดพร้อมกัน
        use_local=True → Load from SAVE_DATA (option 3) แทนการ download
        """
        import os
        cc_num = self.country

        if key == "lucky_ticket":
            value_to_send = min(current + amount, 2999)
            self._log(f"[CLI] Lucky Ticket: {current} + {amount} = {value_to_send}")
            nav = ["3", "21", "1", str(value_to_send)]
        else:
            # CLI rare_ticket ใช้ delta (บวกเพิ่ม) ไม่ใช่ absolute
            room = max(0, 299 - current)
            to_add = min(amount, room)
            self._log(f"[CLI] Rare Ticket: current={current}, room={room}, to_add={to_add}")
            if to_add <= 0:
                self._log(f"[CLI] Rare Ticket: เต็ม 299 แล้ว — ข้ามCLI")
                return {"success": True, "transfer": self._latest_tc, "confirmation": self._latest_cc}
            nav = ["3", "6", str(to_add)]

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"

        cli_path_str = str(self._cli_save_path)
        _backup_path = None

        if use_local:
            # backup ก่อนรัน CLI — BCSFE error-handling อาจเขียนทับ/corrupt cli_save_path
            _backup_path = BCSFE_SAVES_DIR / f"SAVE_DATA_backup_{self._session_id}"
            try:
                shutil.copy2(cli_path_str, str(_backup_path))
            except Exception as _be:
                self._log(f"[CLI] ⚠ backup ล้มเหลว: {_be}")
                _backup_path = None

            self._log(f"[CLI] โหลดจาก {cli_path_str} (--input-path)")
            inputs = "\n".join(nav + ["2", "n", "2", "2", "3", "12", "n"]) + "\n"
            result = self._cli_communicate(inputs, env, cli_args=["--input-path", cli_path_str])

            # ถ้า upload ล้มเหลว → retry ด้วย backup (clean file) + full nav (re-add tickets)
            if not result.get("success") and result.get("upload_failed"):
                self._log("[CLI] ⚠ Upload ล้มเหลว (rate limit) — รอ 15 วินาทีแล้ว retry ด้วย backup...")
                time.sleep(15)
                if _backup_path and _backup_path.exists():
                    self._log(f"[CLI] retry โหลดจาก backup: {_backup_path}")
                    result = self._cli_communicate(inputs, env,
                                                   cli_args=["--input-path", str(_backup_path)],
                                                   label="RETRY")
                    if not result.get("success"):
                        self._log(f"[CLI] ❌ Upload ล้มเหลวทั้งสองรอบ — เก็บ backup ไว้ให้แอดมิน")
                        self._log(f"[CLI] 📁 save ที่แก้แล้ว (มีของอยู่): {_backup_path}")
                        self._log(f"[CLI] 👨‍💼 TC ปัจจุบัน: {self._latest_tc} / {self._latest_cc}")
                        _backup_path = None  # ป้องกันไม่ให้ cleanup ลบไฟล์นี้
                else:
                    self._log("[CLI] ❌ ไม่มี backup — retry ไม่ได้")
                    result = {"success": False, "error": "Upload ล้มเหลวและไม่มี backup"}
        else:
            # Download: ส่ง unique path แทน "" → save ลง cli_save_path ของ session นี้
            inputs = "\n".join(["1", transfer, confirm, cc_num, cli_path_str] + nav + ["2", "2", "3"]) + "\n"
            result = self._cli_communicate(inputs, env)

        # ── Lucky Ticket: ตรวจ current value จาก CLI output แล้ว re-run ถ้าจำเป็น ──
        if key == "lucky_ticket" and result.get("success"):
            last_output = getattr(self, "_last_cli_output", "")
            m = re.search(r'current value[:\s]+(\d+)', last_output, re.IGNORECASE)
            if m:
                actual_current = int(m.group(1))
                correct_add = min(actual_current + amount, 2999)
                if correct_add != value_to_send:
                    self._log(f"[CLI] Lucky Ticket current จริง={actual_current} ≠ assumed={current} → re-run ด้วย {actual_current}+{amount}={correct_add}")
                    nav2 = ["3", "21", "1", str(correct_add)]
                    inputs2 = "\n".join(nav2 + ["2", "", "2", "2", "3", "12", "n"]) + "\n"
                    self._log("[CLI] รอ 15 วินาที (rate limit cooldown หลัง first run upload)...")
                    time.sleep(15)
                    rerun_result = self._cli_communicate(inputs2, env,
                                                        cli_args=["--input-path", str(self._cli_save_path)])
                    if not rerun_result.get("success"):
                        self._log("[CLI] Lucky Ticket re-run ครั้งแรกล้มเหลว — รอ 15s แล้ว retry...")
                        time.sleep(15)
                        rerun_result = self._cli_communicate(inputs2, env,
                                                            cli_args=["--input-path", str(self._cli_save_path)])
                    if rerun_result.get("success"):
                        result = rerun_result
                    else:
                        self._log("[CLI] Lucky Ticket re-run ล้มเหลว ทุก retry — restore backup (ของอื่นครบ ยกเว้น Lucky Ticket)")
                        if _backup_path and _backup_path.exists():
                            try:
                                time.sleep(15)
                                inputs_restore = "\n".join(["2", "3", "12", "n"]) + "\n"
                                restore_result = self._cli_communicate(inputs_restore, env,
                                                                      cli_args=["--input-path", str(_backup_path)])
                                if restore_result.get("success"):
                                    self._log(f"[CLI] Backup restore ✅ TC: {restore_result['transfer']} | Confirm: {restore_result['confirmation']}")
                                    result = restore_result
                                    _backup_path = None  # ป้องกัน cleanup ลบก่อนใช้
                                else:
                                    self._log("[CLI] Backup restore upload ล้มเหลว")
                            except Exception as _be:
                                self._log(f"[CLI] Backup restore error: {_be}")
                        else:
                            self._log("[CLI] ไม่มี backup file สำหรับ restore")

        # ── Rare Ticket: ตรวจ current value จาก CLI output แล้ว re-run ถ้าจำเป็น ──
        if key == "rare_ticket" and result.get("success"):
            last_output = getattr(self, "_last_cli_output", "")
            m = re.search(r'current value[:\s]+(\d+)', last_output, re.IGNORECASE)
            if m:
                actual_current = int(m.group(1))
                correct_add = min(amount, max(0, 299 - actual_current))
                if correct_add != to_add:
                    self._log(f"[CLI] Rare Ticket current จริง={actual_current} ≠ assumed={current} → re-run ด้วย to_add={correct_add}")
                    nav2 = ["3", "6", str(correct_add)]
                    inputs2 = "\n".join(nav2 + ["2", "", "2", "2", "3", "12", "n"]) + "\n"
                    result = self._cli_communicate(inputs2, env,
                                                   cli_args=["--input-path", str(self._cli_save_path)])
                else:
                    self._log(f"[CLI] Rare Ticket verified: actual_current={actual_current} ✓ to_add={correct_add}")

        if _backup_path:
            try:
                _backup_path.unlink(missing_ok=True)
            except Exception:
                pass

        return result

    def _cli_communicate(self, inputs: str, env: dict, label: str = "", cli_args: list = None) -> dict:
        """รัน CLI แล้ว parse transfer code"""
        lp = f"[{label}]" if label else "[CLI]"
        try:
            cmd = BCSFE_CLI + (cli_args or [])
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", env=env,
            )
            stdout, _ = proc.communicate(input=inputs, timeout=120)

            clean = re.sub(r'\x1b\[[0-9;]*[mGKH]', '', stdout)
            self._last_cli_output = clean  # เก็บไว้ให้ caller ตรวจสอบ
            for line in clean.splitlines():
                if line.strip():
                    self._log_file.write(f"  {lp} {line}\n")
            self._log_file.flush()

            tc_list = re.findall(r'Transfer Code[:\s]+([a-f0-9]{8,9})', clean)
            cc_list = re.findall(r'Confirmation Code[:\s]+(\d{4})', clean)

            if tc_list:
                new_tc = tc_list[-1]
                new_cc = cc_list[-1] if cc_list else None
                self._log(f"{lp} ✅ Transfer ใหม่: {new_tc} | Confirm ใหม่: {new_cc}")
                return {"success": True, "transfer": new_tc, "confirmation": new_cc}

            if "Failed to upload save file" in clean:
                return {"success": False, "upload_failed": True, "error": "Upload ล้มเหลว (rate limit)"}

            self._log(f"{lp} ❌ parse transfer code ไม่ได้")
            for line in clean.splitlines()[-15:]:
                self._log(f"  {line}")
            return {"success": False, "error": "parse transfer code ไม่ได้"}

        except subprocess.TimeoutExpired:
            proc.kill()
            self._log(f"{lp} ❌ timeout (120s)")
            return {"success": False, "error": "CLI timeout"}
        except Exception as e:
            self._log(f"{lp} ❌ {e}")
            return {"success": False, "error": str(e)}

    # ──────────────────────────────────────────────────
    # helpers
    # ──────────────────────────────────────────────────

    def _get_cc(self) -> core.CountryCode:
        code = COUNTRY_MAP.get(self.country, "en")
        return core.CountryCode.from_code(code)

    def _download_save(self, backup: bool = True):
        cc = self._get_cc()
        gv = core.GameVersion(120200)
        self._log(f"[BCSFE] ⬇  Downloading save (transfer={self.transfer[:6]}... cc={cc})")
        try:
            handler, _ = core.ServerHandler.from_codes(
                self.transfer, self.confirm, cc, gv, print=False, save_backup=backup
            )
        except Exception as e:
            self._log(f"[BCSFE] ❌ from_codes exception: {type(e).__name__}: {e}")
            raise
        if handler is None:
            raise RuntimeError(
                "❌ Transfer Code หรือ Confirmation Code ไม่ถูกต้อง หรือหมดอายุแล้ว "
                "กรุณากด 'Begin Data Transfer' ในเกมใหม่แล้วลองอีกครั้ง"
            )
        self._download_done = True
        self._log("[BCSFE] ✅ Download สำเร็จ")
        return handler.save_file

    def _upload_save(self, save_file, backup: bool = True) -> dict:
        # ใช้ unique path ของ session นี้ → parallel sessions ไม่ conflict
        bcsfe_path = core.SaveFile.get_saves_path().add(f"SAVE_DATA_{self._session_id}")
        save_file.to_file(bcsfe_path)
        self._log(f"[BCSFE] 💾 บันทึก save → {bcsfe_path}")

        if backup:
            self._backup(Path(bcsfe_path.to_str()))

        self._log("[BCSFE] ⬆  Uploading save...")
        result = core.ServerHandler(save_file).get_codes()

        # ลบ temp file หลัง upload
        try:
            Path(bcsfe_path.to_str()).unlink(missing_ok=True)
        except Exception:
            pass

        if result is None:
            raise RuntimeError("❌ Upload ล้มเหลว กรุณาลองใหม่")

        new_tc, new_cc = result
        self._latest_tc = new_tc
        self._latest_cc = new_cc
        self._log(f"[BCSFE] ✅ Transfer ใหม่: {new_tc} | Confirm ใหม่: {new_cc}")
        self._log(f"{'='*60}")
        return {"transfer": new_tc, "confirmation": new_cc}

    def _backup(self, src: Path = None):
        """Backup save file ของ session นี้"""
        try:
            if src is None:
                src = BCSFE_SAVES_DIR / f"SAVE_DATA_{self._session_id}"
            if not src.exists():
                return
            backup_dir = Path("saves_backup")
            backup_dir.mkdir(exist_ok=True)
            ts = datetime.now(TZ_THAI).strftime("%Y%m%d_%H%M%S")
            dest = backup_dir / f"SAVE_{ts}_{self.transfer[:8]}"
            shutil.copy2(src, dest)
            self._log(f"[BCSFE] 📁 Backup → {dest}")
        except Exception as e:
            self._log(f"[BCSFE] ⚠  Backup ล้มเหลว: {e}")

    # ──────────────────────────────────────────────────
    # item editors
    # ──────────────────────────────────────────────────

    def _read_lucky_ticket_current(self, save_file) -> int:
        try:
            tickets = save_file.lucky_tickets
            if tickets and len(tickets) > 0:
                return int(tickets[0])
        except Exception:
            pass
        return 0

    def _edit_item(self, save_file, item: dict):
        key    = item["key"]
        amount = item["amount"]
        cfg    = ITEM_MAP.get(key)
        if not cfg:
            raise ValueError(f"ไม่รู้จัก item key: {key}")

        max_val = cfg["max"]
        label   = cfg["label"]

        # ── array items (sub-type loop) ──
        if cfg.get("sub_select"):
            self._edit_array_item(save_file, key, amount, max_val, label)
            return

        # ── base_material: เพิ่มทุกชนิดพร้อมกัน ──
        if key == "base_material":
            MATERIAL_NAMES = [
                "Bricks","Feathers","Coal","Sprockets","Gold","Meteorite","Beast Bones","Ammonite",
                "Brick Z","Feathers Z","Coal Z","Sprockets Z","Gold Z","Meteorite Z","Beast Bones Z","Ammonite Z",
            ]
            mats = save_file.ototo.base_materials.materials
            for i, mat in enumerate(mats):
                old = mat.amount
                mat.amount = min(old + amount, max_val)
                name = MATERIAL_NAMES[i] if i < len(MATERIAL_NAMES) else f"Mat#{i}"
                self._log(f"[ITEM] {name}: {old} + {amount} → {mat.amount}")
            return

        # ── gamatoto_level: set XP ให้ตรงกับ level ที่เลือก ──
        if key == "gamatoto_level":
            import bcsfe.core as _bc
            gamatoto_levels = _bc.core_data.get_gamatoto_levels(save_file)
            old_xp = save_file.gamatoto.xp
            old_lv = gamatoto_levels.get_level_from_xp(old_xp)
            xp = gamatoto_levels.get_xp_from_level(amount)
            if xp is None:
                self._log(f"[ITEM] Gamatoto Level: ไม่พบ level {amount}")
                return
            save_file.gamatoto.xp = xp
            old_str = f"Lv{old_lv.level}" if old_lv else "?"
            self._log(f"[ITEM] Gamatoto Level: {old_str} → Lv{amount} (xp={xp})")
            return

        # ── gamatoto helpers: clear ทั้งหมดแล้วใส่ rarity ที่เลือก 10 ตัว ──
        GAMATOTO_RARITY = {
            "gamatoto_lackey":    1,
            "gamatoto_underling": 2,
            "gamatoto_assistant": 3,
            "gamatoto_legend":    4,
        }
        GAMATOTO_NAMES = {
            "gamatoto_lackey":    "Lackey",
            "gamatoto_underling": "Underling",
            "gamatoto_assistant": "Assistant",
            "gamatoto_legend":    "Legend",
        }
        if key in GAMATOTO_RARITY:
            import bcsfe.core as _bc
            import bcsfe.core.game.gamoto.gamatoto as _gam
            rarity   = GAMATOTO_RARITY[key]
            rname    = GAMATOTO_NAMES[key]
            members_data = _bc.GamatotoMembersName(save_file)
            members  = members_data.get_all_rarity(rarity) or []
            count    = min(amount, len(members))
            helpers  = [_gam.Helper(m.member_id) for m in members[:count]]
            old_count = len([h for h in save_file.gamatoto.helpers.helpers if h.is_valid()])
            save_file.gamatoto.helpers = _gam.Helpers(helpers)
            self._log(f"[ITEM] Gamatoto Helpers: ลบ {old_count} ตัวเดิม → เพิ่ม {count} {rname}")
            return

        # ── lucky_ticket / rare_ticket: deferred ไปรัน CLI หลัง upload ──
        if key in ("lucky_ticket", "rare_ticket"):
            cur = 0
            if key == "rare_ticket":
                cur = int(save_file.rare_tickets)
            elif key == "lucky_ticket":
                cur = self._read_lucky_ticket_current(save_file)
            self._deferred_cli.append({"key": key, "amount": amount, "label": label, "current": cur})
            self._log(f"[ITEM] {label}: defer → CLI (current={cur})")
            return

        # ── simple scalar items — ทุกตัว ADD เสมอ ──
        cur = self._get_scalar(save_file, key)
        new_val = min(cur + amount, max_val)
        self._set_scalar(save_file, key, new_val)
        self._log(f"[ITEM] {label}: {cur} → {new_val}  (+{new_val - cur})")

    def _get_scalar(self, sf, key: str) -> int:
        mapping = {
            "cat_food":      lambda: sf.catfood,
            "xp":            lambda: sf.xp,
            "normal_ticket": lambda: sf.normal_tickets,
            "rare_ticket":   lambda: sf.rare_tickets,
            "np":            lambda: sf.np,
            "platinum_shard":lambda: sf.platinum_shards,
            "leadership":    lambda: sf.leadership,
            "legend_ticket": lambda: sf.legend_tickets,
            "lucky_ticket":  lambda: sf.lucky_tickets[0] if sf.lucky_tickets else 0,
        }
        fn = mapping.get(key)
        if fn is None:
            raise ValueError(f"ไม่รู้จัก scalar key: {key}")
        return int(fn())

    def _set_scalar(self, sf, key: str, val: int):
        if   key == "cat_food":       sf.catfood          = val
        elif key == "xp":             sf.xp               = val
        elif key == "normal_ticket":  sf.normal_tickets   = val
        elif key == "rare_ticket":    sf.rare_tickets     = val
        elif key == "np":             sf.np               = val
        elif key == "platinum_shard": sf.platinum_shards  = val
        elif key == "leadership":     sf.leadership       = val
        elif key == "legend_ticket":  sf.legend_tickets   = val
        elif key == "lucky_ticket":
            lst = list(sf.lucky_tickets) if sf.lucky_tickets else [0]
            lst[0] = val
            sf.lucky_tickets = lst
        else:
            raise ValueError(f"ไม่รู้จัก scalar key: {key}")

    def _edit_array_item(self, sf, key: str, amount: int, max_val: int, label: str):
        sub_range  = ITEM_MAP[key].get("sub_select", "1-1")
        max_sub    = int(sub_range.split("-")[1])

        if key == "catseye":
            arr = list(sf.catseyes)
        elif key == "catfruit":
            arr = list(sf.catfruit)
        elif key == "catamins":
            arr = list(sf.catamins)
        elif key == "battle_item":
            arr = [item.amount for item in sf.battle_items.items]
        else:
            raise ValueError(f"ไม่รู้จัก array key: {key}")

        n = min(max_sub, len(arr))
        before = arr[:n].copy()
        for i in range(n):
            arr[i] = min(arr[i] + amount, max_val)

        if key == "catseye":
            sf.catseyes = arr
        elif key == "catfruit":
            sf.catfruit = arr
        elif key == "catamins":
            sf.catamins = arr
        elif key == "battle_item":
            for i in range(n):
                sf.battle_items.items[i].amount = arr[i]

        self._log(f"[ITEM] {label} ({n} types) +{amount} each:")
        for i in range(n):
            self._log(f"       type {i+1}: {before[i]} → {arr[i]}")

    # ──────────────────────────────────────────────────
    # public run methods
    # ──────────────────────────────────────────────────

    # ── TEST ONLY — ลบออกหลัง test เสร็จ ──────────────────────────
    # TEST_ERROR_STAGE = None   → ปกติ (ไม่ error)
    # TEST_ERROR_STAGE = "after_download"  → error หลัง download (ก่อน upload)
    # TEST_ERROR_STAGE = "after_upload"    → error หลัง upload (ได้ TC ใหม่แล้ว)
    TEST_ERROR_STAGE = None   # Test 1
    # ──────────────────────────────────────────────────────────────

    def run(self, items: list) -> dict:
        try:
            self._log(f"[OP] เพิ่มของ {len(items)} รายการ")
            core.core_data.init_data()
            save_file = self._download_save()

            if self.TEST_ERROR_STAGE == "after_download":
                raise Exception("🧪 TEST: error หลัง download (ก่อน upload) — ดู latest_transfer_code ใน response")

            for item in items:
                self._edit_item(save_file, item)

            # ── CLI deferred items (lucky_ticket / rare_ticket) ──
            # ถ้ามี CLI items → save ลง disk ให้ CLI upload ครั้งเดียว (ไม่ต้อง API upload ก่อน = ไม่มี rate limit)
            # ถ้าไม่มี CLI items → upload ผ่าน API ตามปกติ
            has_rare = False
            if self._deferred_cli:
                # save to disk — CLI จะ upload แทน (TC เดิมยังใช้ได้ถ้า CLI ล้มเหลว)
                try:
                    cli_bcsfe_path = core.SaveFile.get_saves_path().add(f"SAVE_DATA_cli_{self._session_id}")
                    save_file.to_file(cli_bcsfe_path)
                    self._cli_save_path = Path(str(cli_bcsfe_path))
                    self._log(f"[CLI] บันทึก save → {self._cli_save_path}")
                except Exception as e:
                    self._log(f"[CLI] ⚠ บันทึก CLI save ล้มเหลว: {e}")
                self._backup(self._cli_save_path)  # permanent backup สำหรับ admin

                # API upload ก่อน → ลูกค้ามี safety TC แม้ CLI จะล้มเหลว
                codes = self._upload_save(save_file)
                current_tc = codes["transfer"]
                current_cc = codes["confirmation"]
                self._latest_tc = current_tc
                self._latest_cc = current_cc

                # รอ PONOS rate limit cooldown ก่อนรัน CLI upload
                self._log("[CLI] รอ 15 วินาที (PONOS rate limit cooldown หลัง API upload)...")
                time.sleep(15)

                if self.TEST_ERROR_STAGE == "after_upload":
                    raise Exception("🧪 TEST: error ก่อน CLI (after_upload stage)")

                for deferred in self._deferred_cli:
                    key = deferred["key"]
                    r = self._run_cli_item(current_tc, current_cc, key, deferred["amount"], deferred.get("current", 0), use_local=True)
                    if r["success"]:
                        current_tc = r["transfer"]
                        current_cc = r["confirmation"]
                        self._latest_tc = current_tc
                        self._latest_cc = current_cc
                        if key == "rare_ticket":
                            has_rare = True
                    else:
                        self._log(f"[BCSFE] ⚠ {deferred['label']} CLI ล้มเหลว — ลูกค้าใช้ TC จาก API upload ได้: {current_tc}")
                try:
                    self._cli_save_path.unlink(missing_ok=True)
                except Exception:
                    pass
            else:
                # ── Python API items: upload ──
                codes = self._upload_save(save_file)
                current_tc = codes["transfer"]
                current_cc = codes["confirmation"]

                if self.TEST_ERROR_STAGE == "after_upload":
                    raise Exception("🧪 TEST: error หลัง upload (มี TC ใหม่แล้ว) — ดู latest_transfer_code ใน response")

            final_codes = {"transfer": current_tc, "confirmation": current_cc}
            self._log(f"{'='*60}")
            self._close_log()

            result = {"success": True, "new_transfer_code": final_codes}
            if has_rare:
                result["customer_note"] = "วิธีการใช้งาน: ให้ลูกค้ากดรับไอเทม นำเข้าตู้เย็น (Storage) กดใช้ทั้งหมด และทำการแลกบัตรทองได้เลยครับ"
            return result

        except Exception as e:
            self._log(f"[BCSFE] ❌ {e}")
            self._close_log()
            return self._error_result(e)

    def run_retry_fresh(self, cli_items: list, backup_path: "Path | None" = None) -> dict:
        """Retry: โหลด backup จากรอบแรกโดยตรง → CLI รันเหมือน purchase ปกติ (ไม่ download จาก PONOS)"""
        try:
            core.core_data.init_data()

            if not backup_path or not backup_path.exists():
                raise RuntimeError("ไม่พบ backup save — กรุณาติดต่อแอดมิน")

            # Copy backup → cli_save_path (ไม่ต้อง load ด้วย Python API)
            shutil.copy2(str(backup_path), str(self._cli_save_path))
            self._log(f"[RETRY] โหลด backup → {self._cli_save_path}")

            self._log("[RETRY] รอ 15 วินาที (PONOS rate limit cooldown)...")
            time.sleep(15)

            current_tc = self._latest_tc
            current_cc = self._latest_cc

            for item in cli_items:
                key    = item["key"]
                amount = item["amount"]

                # รันเหมือน purchase ปกติทุกอย่าง (re-run check อยู่ใน _run_cli_item แล้ว)
                r = self._run_cli_item(current_tc, current_cc, key, amount,
                                      current=0, use_local=True)
                if r.get("success"):
                    current_tc = r["transfer"]
                    current_cc = r["confirmation"]
                    self._latest_tc = current_tc
                    self._latest_cc = current_cc
                else:
                    self._log(f"[RETRY] ⚠ {key} CLI ล้มเหลว — TC: {current_tc}")

            try:
                self._cli_save_path.unlink(missing_ok=True)
            except Exception:
                pass

            self._close_log()
            return {"success": True, "transfer": current_tc, "confirmation": current_cc}

        except Exception as e:
            self._log(f"[RETRY] ❌ {e}")
            self._close_log()
            return {"success": False, "error": str(e)}

    def _find_cats(self, save_file, cat_ids: list):
        """หา Cat objects จาก IDs (ทุกตัว รวม locked) — ใช้สำหรับ unlock"""
        id_set = set(cat_ids)
        return [cat for cat in save_file.cats.cats if cat.id in id_set]

    def _find_owned_cats(self, save_file, cat_ids: list):
        """หา Cat objects เฉพาะตัวที่ unlocked จาก IDs — ใช้สำหรับ upgrade/form/talents"""
        id_set = set(cat_ids)
        return [cat for cat in save_file.cats.get_unlocked_cats() if cat.id in id_set]

    def run_unlock_characters(self, cat_ids: list) -> dict:
        try:
            self._log(f"[OP] Unlock Characters จำนวน {len(cat_ids)} ตัว")
            core.core_data.init_data()
            save_file = self._download_save()

            cats = self._find_cats(save_file, cat_ids)
            self._log(f"[BCSFE] พบ {len(cats)}/{len(cat_ids)} ตัวใน save")

            logs = []
            not_found = [i for i in cat_ids if not any(c.id == i for c in cats)]
            for cat in cats:
                cat.unlock(save_file)  # ใช้ BCSFE unlock() เหมือน CLI (ไม่แตะ unlocked_forms)
                logs.append(f"✔ #{cat.id} — unlocked")
                self._log(f"[CAT] ✔ #{cat.id} — unlocked")
            for i in not_found:
                logs.append(f"✘ #{i} — ไม่พบใน save")
                self._log(f"[CAT] ✘ #{i} — ไม่พบใน save")

            self._log(f"[BCSFE] Unlocked {len(cats)} cats")
            codes = self._upload_save(save_file)
            self._close_log()
            return {"success": True, "new_transfer_code": codes, "log": logs}

        except Exception as e:
            import traceback
            self._log(f"[BCSFE] ❌ {e}\n{traceback.format_exc()}")
            self._close_log()
            return self._error_result(e)

    @staticmethod
    def _set_base_max(cat, save_file) -> None:
        unit_buy = save_file.cats.read_unitbuy(save_file).get_unit_buy(cat.id)
        target_base = (unit_buy.max_upgrade_level_catseye - 1) if unit_buy else 29
        if cat.upgrade.base < target_base:
            cat.upgrade.base = target_base

    def run_upgrade_characters(self, cat_ids: list) -> dict:
        """Upgrade max level (with catseyes) ตาม IDs ที่ระบุ"""
        try:
            self._log(f"[OP] Upgrade Characters จำนวน {len(cat_ids)} ตัว")
            core.core_data.init_data()
            save_file = self._download_save()

            cats = self._find_owned_cats(save_file, cat_ids)
            logs = []
            not_found = [i for i in cat_ids if not any(c.id == i for c in cats)]
            for cat in cats:
                old_lv = cat.upgrade.base + 1
                old_plus = cat.upgrade.plus
                self._set_base_max(cat, save_file)
                cat.upgrade.plus = 0
                entry = f"✔ #{cat.id} — Lv{old_lv}+{old_plus} → Lv{cat.upgrade.base+1}+0"
                logs.append(entry)
                self._log(f"[CAT] {entry}")
            for i in not_found:
                logs.append(f"✘ #{i} — ไม่พบใน save")
                self._log(f"[CAT] ✘ #{i} — ไม่พบใน save")
            self._log(f"[BCSFE] Upgraded {len(cats)}/{len(cat_ids)} cats → max")

            codes = self._upload_save(save_file)
            self._close_log()
            return {"success": True, "new_transfer_code": codes, "log": logs}

        except Exception as e:
            self._log(f"[BCSFE] ❌ {e}")
            self._close_log()
            return self._error_result(e)

    def run_upgrade_plus_characters(self, cat_ids: list) -> dict:
        """Upgrade max level + max plus ตาม IDs ที่ระบุ"""
        try:
            self._log(f"[OP] Upgrade Max + Characters จำนวน {len(cat_ids)} ตัว")
            core.core_data.init_data()
            save_file = self._download_save()

            cats = self._find_owned_cats(save_file, cat_ids)
            logs = []
            not_found = [i for i in cat_ids if not any(c.id == i for c in cats)]
            for cat in cats:
                old_lv = cat.upgrade.base + 1
                old_plus = cat.upgrade.plus
                self._set_base_max(cat, save_file)
                power_up = core.PowerUpHelper(cat, save_file)
                max_plus = power_up.get_max_possible_plus()
                cat.upgrade.plus = max_plus
                entry = f"✔ #{cat.id} — Lv{old_lv}+{old_plus} → Lv{cat.upgrade.base+1}+{max_plus}"
                logs.append(entry)
                self._log(f"[CAT] {entry}")
            for i in not_found:
                logs.append(f"✘ #{i} — ไม่พบใน save")
                self._log(f"[CAT] ✘ #{i} — ไม่พบใน save")
            self._log(f"[BCSFE] Upgraded+Plus {len(cats)}/{len(cat_ids)} cats → max+max")

            codes = self._upload_save(save_file)
            self._close_log()
            return {"success": True, "new_transfer_code": codes, "log": logs}

        except Exception as e:
            self._log(f"[BCSFE] ❌ {e}")
            self._close_log()
            return self._error_result(e)

    def run_upgrade_all_characters(self) -> dict:
        """Upgrade max (with catseyes) ทุกตัวที่ unlock อยู่ใน save"""
        try:
            self._log("[OP] Upgrade ALL unlocked cats -> max")
            core.core_data.init_data()
            save_file = self._download_save()

            pic_book = save_file.cats.read_nyanko_picture_book(save_file)
            count = 0
            logs = []
            for cat in save_file.cats.cats:
                if cat.unlocked:
                    old_lv = cat.upgrade.base + 1
                    old_plus = cat.upgrade.plus
                    old_forms = cat.unlocked_forms
                    self._set_base_max(cat, save_file)
                    if cat.upgrade.base > 29 and cat.unlocked_forms < 3:
                        pic_book_cat = pic_book.get_cat(cat.id)
                        if pic_book_cat is not None and pic_book_cat.total_forms >= 3:
                            cat.true_form(save_file, set_current_form=True)
                    entry = f"✔ #{cat.id} — Lv{old_lv}+{old_plus} → Lv{cat.upgrade.base+1}+{cat.upgrade.plus} (forms: {old_forms}->{cat.unlocked_forms})"
                    logs.append(entry)
                    self._log(f"[CAT] {entry}")
                    count += 1
            self._log(f"[BCSFE] Upgraded all {count} unlocked cats -> max")

            codes = self._upload_save(save_file)
            self._close_log()
            return {"success": True, "new_transfer_code": codes, "count": count, "log": logs}

        except Exception as e:
            self._log(f"[BCSFE] ❌ {e}")
            self._close_log()
            return self._error_result(e)

    def run_true_form_characters(self, cat_ids: list) -> dict:
        try:
            self._log(f"[OP] True Form Characters จำนวน {len(cat_ids)} ตัว")
            core.core_data.init_data()
            save_file = self._download_save()

            cats = self._find_owned_cats(save_file, cat_ids)
            logs = []
            not_found = [i for i in cat_ids if not any(c.id == i for c in cats)]
            save_file.cats.true_form_cats(save_file, cats)
            for cat in cats:
                logs.append(f"✔ #{cat.id} — True Form applied")
                self._log(f"[CAT] ✔ #{cat.id} — True Form applied")
            for i in not_found:
                logs.append(f"✘ #{i} — ไม่พบใน save")
                self._log(f"[CAT] ✘ #{i} — ไม่พบใน save")
            self._log(f"[BCSFE] True Form {len(cats)}/{len(cat_ids)} cats")

            codes = self._upload_save(save_file)
            self._close_log()
            return {"success": True, "new_transfer_code": codes, "log": logs}

        except Exception as e:
            self._log(f"[BCSFE] ❌ {e}")
            self._close_log()
            return self._error_result(e)

    def run_ultra_form_characters(self, cat_ids: list) -> dict:
        """Ultra Form ตาม IDs — ส่งตรงเข้า fourth_form_cats() ไม่เช็ค True Form ก่อน
        (เหมือน CLI ที่ ultra form ได้ทันทีโดยไม่ต้องมี unlocked_forms >= 3)"""
        try:
            self._log(f"[OP] Ultra Form Characters จำนวน {len(cat_ids)} ตัว")
            core.core_data.init_data()
            save_file = self._download_save()

            cats = self._find_owned_cats(save_file, cat_ids)
            logs = []
            not_found = [i for i in cat_ids if not any(c.id == i for c in cats)]

            # ส่งทุก cat ที่เจอเข้า fourth_form_cats() ตรงๆ เหมือน CLI (ไม่เช็ค unlocked_forms)
            if cats:
                save_file.cats.fourth_form_cats(save_file, cats)

            for cat in cats:
                logs.append(f"✔ #{cat.id} — Ultra Form applied")
                self._log(f"[CAT] ✔ #{cat.id} — Ultra Form applied")
            for i in not_found:
                logs.append(f"✘ #{i} — ไม่พบใน save")
                self._log(f"[CAT] ✘ #{i} — ไม่พบใน save")

            self._log(f"[BCSFE] Ultra Form {len(cats)}/{len(cat_ids)} cats")

            codes = self._upload_save(save_file)
            self._close_log()
            return {"success": True, "new_transfer_code": codes, "log": logs}

        except Exception as e:
            self._log(f"[BCSFE] ❌ {e}")
            self._close_log()
            return self._error_result(e)

    @staticmethod
    def _init_and_max_talents(cat, talent_data) -> int:
        """init talent objects ถ้าไม่มี แล้ว set max — return จำนวน talents ที่ max"""
        cat_skill = talent_data.get_cat_skill(cat.id)
        if cat_skill is None:
            return 0
        # init talents ถ้ายังเป็น None หรือขาด talent บางตัว
        if cat.talents is None:
            cat.talents = [BCSFETalent(s.ability_id, 0) for s in cat_skill.skills]
        else:
            existing = {t.id for t in cat.talents}
            for s in cat_skill.skills:
                if s.ability_id not in existing:
                    cat.talents.append(BCSFETalent(s.ability_id, 0))
        # max levels
        talent_count = 0
        for s in cat_skill.skills:
            talent = cat.get_talent_from_id(s.ability_id)
            if talent:
                talent.level = s.max_lv if s.max_lv > 0 else 1
                talent_count += 1
        return talent_count

    def run_talents_max_characters(self, cat_ids: list) -> dict:
        try:
            self._log(f"[OP] Max Talents Characters จำนวน {len(cat_ids)} ตัว")
            core.core_data.init_data()
            save_file = self._download_save()

            cats = self._find_owned_cats(save_file, cat_ids)

            talent_data = save_file.cats.read_talent_data(save_file)
            if talent_data is None:
                self._close_log()
                return {"success": False, "error": "ไม่สามารถโหลด talent data ได้"}

            logs = []
            not_found = [i for i in cat_ids if not any(c.id == i for c in cats)]
            count = 0
            for cat in cats:
                n = self._init_and_max_talents(cat, talent_data)
                if n > 0:
                    logs.append(f"✔ #{cat.id} — {n} talents maxed")
                    self._log(f"[CAT] ✔ #{cat.id} — {n} talents maxed")
                    count += 1
                else:
                    logs.append(f"— #{cat.id} — ไม่มี talent data")
                    self._log(f"[CAT] — #{cat.id} — ไม่มี talent data")
            for i in not_found:
                logs.append(f"✘ #{i} — ไม่พบใน save")
                self._log(f"[CAT] ✘ #{i} — ไม่พบใน save")

            self._log(f"[BCSFE] Max Talents {count}/{len(cat_ids)} cats")
            codes = self._upload_save(save_file)
            self._close_log()
            return {"success": True, "new_transfer_code": codes, "log": logs}

        except Exception as e:
            self._log(f"[BCSFE] ❌ {e}")
            self._close_log()
            return self._error_result(e)

    # ── All-cats variants (ทำกับทุกตัวใน save) ────────────────

    def run_check_id(self) -> dict:
        """Download save (ตรวจว่ารหัสใช้ได้) → re-upload โดยไม่แก้ไข → ได้ TC ใหม่"""
        try:
            self._log("[OP] Check ID — download + re-upload (no edit)")
            core.core_data.init_data()
            save_file = self._download_save(backup=False)
            inquiry = getattr(save_file, "inquiry_code", "?")
            self._log(f"[CHECK] Inquiry Code: {inquiry}")
            codes = self._upload_save(save_file, backup=False)
            self._close_log()
            return {"success": True, "new_transfer_code": codes, "inquiry_code": str(inquiry)}
        except Exception as e:
            self._log(f"[BCSFE] ❌ {e}")
            self._close_log()
            return self._error_result(e)

    def run_dupe_save(self, count: int) -> dict:
        """Download save ครั้งเดียว แล้ว dupe N ครั้งด้วย create_new_account + get_codes"""
        try:
            self._log(f"[OP] Dupe Save x{count}")
            core.core_data.init_data()
            save_file = self._download_save()

            results = []
            for i in range(count):
                self._log(f"[DUPE] ── รอบที่ {i+1}/{count} ──────────────────────────")
                inquiry_before = getattr(save_file, "inquiry_code", "?")
                self._log(f"[DUPE] Inquiry ก่อน : {inquiry_before}")
                server_handler = core.ServerHandler(save_file)
                ok = server_handler.create_new_account()
                inquiry_after = getattr(save_file, "inquiry_code", "?")
                if not ok:
                    self._log(f"[DUPE] ❌ create_new_account ล้มเหลวรอบที่ {i+1}")
                    break
                changed = "✅ เปลี่ยนแล้ว" if inquiry_before != inquiry_after else "⚠️ ไม่เปลี่ยน!"
                self._log(f"[DUPE] Inquiry หลัง: {inquiry_after}  {changed}")
                time.sleep(2)
                result = core.ServerHandler(save_file).get_codes()
                if result is None:
                    self._log(f"[DUPE] ❌ get_codes ล้มเหลวรอบที่ {i+1}")
                    break
                new_tc, new_cc = result
                self._log(f"[DUPE] ✅ TC={new_tc} | CC={new_cc}")
                results.append({"transfer": new_tc, "confirmation": new_cc, "inquiry": str(inquiry_after)})
                if i < count - 1:
                    time.sleep(3)

            # ลบ backup ทั้งหมดของ session นี้
            try:
                backup_dir = Path("saves_backup")
                deleted = 0
                if backup_dir.exists():
                    for f in backup_dir.iterdir():
                        if self.transfer[:8] in f.name or self._session_id in f.name:
                            f.unlink()
                            deleted += 1
                self._log(f"[CLEANUP] ลบ backup {deleted} ไฟล์")
            except Exception as e:
                self._log(f"[CLEANUP] ⚠ {e}")

            self._close_log()
            return {"success": True, "codes": results, "count": len(results)}

        except Exception as e:
            self._log(f"[BCSFE] ❌ {e}")
            self._close_log()
            return self._error_result(e)

    def run_unban_from_backup(self, vps_save_bytes: bytes) -> dict:
        """โหลด save จาก bytes (ดึงมาจาก VPS backup) แล้วทำ unban เหมือน dupe"""
        try:
            self._log("[OP] Unban from Backup (create_new_account + get_codes)")
            core.core_data.init_data()
            cc = self._get_cc()

            # โหลด save จาก raw bytes (ไม่ต้อง download จาก PONOS)
            save_file = core.SaveFile(core.Data(vps_save_bytes), cc=cc)
            self._log("[UNBAN] ✅ โหลด save จาก backup สำเร็จ")

            inquiry_before = getattr(save_file, "inquiry_code", "?")
            self._log(f"[UNBAN] Inquiry ก่อน : {inquiry_before}")

            # Step 1: สร้าง account ใหม่ (เหมือน dupe — unban โดยปริยาย)
            server_handler = core.ServerHandler(save_file)
            ok = server_handler.create_new_account()
            if not ok:
                raise RuntimeError("create_new_account ล้มเหลว — ไม่สามารถ unban ได้")

            inquiry_after = getattr(save_file, "inquiry_code", "?")
            changed = "✅ เปลี่ยนแล้ว" if inquiry_before != inquiry_after else "⚠️ ไม่เปลี่ยน!"
            self._log(f"[UNBAN] Inquiry หลัง: {inquiry_after}  {changed}")

            import time as _time
            _time.sleep(2)

            # Step 2: get_codes → ได้ TC ใหม่ (get_codes ตั้ง show_ban_message=False อัตโนมัติ)
            result = core.ServerHandler(save_file).get_codes()
            if result is None:
                raise RuntimeError("get_codes ล้มเหลว — ลองใหม่อีกครั้ง")

            new_tc, new_cc = result
            self._log(f"[UNBAN] ✅ TC={new_tc} | CC={new_cc}")

            self._close_log()
            return {
                "success": True,
                "new_transfer_code": new_tc,
                "new_confirmation_code": new_cc,
                "inquiry_before": str(inquiry_before),
                "inquiry_after":  str(inquiry_after),
            }

        except Exception as e:
            self._log(f"[UNBAN] ❌ {e}")
            self._close_log()
            return self._error_result(e)

    def run_remove_cheetah_and_unban(self, cat_id: int = 673) -> dict:
        """Download save fresh → ลบแมว cat_id → create_new_account (unban) → get_codes"""
        try:
            self._log(f"[OP] Remove Cat #{cat_id} + Unban")
            core.core_data.init_data()

            # 1. Download save fresh จาก TC/CC
            save_file = self._download_save(backup=True)

            # 2. ค้นหาและลบ cat
            cat = next((c for c in save_file.cats.cats if c.id == cat_id), None)
            if cat is None:
                self._log(f"[REMOVE] ⚠ ไม่พบ cat #{cat_id} ใน save (ข้าม)")
            elif cat.unlocked == 0:
                self._log(f"[REMOVE] — #{cat_id} ไม่ได้ unlock อยู่แล้ว (ข้าม)")
            else:
                cat.remove(save_file=save_file, reset=True)
                self._log(f"[REMOVE] ✅ #{cat_id} ถูกลบแล้ว (reset=True)")

            # 3. Unban: create_new_account + get_codes
            inquiry_before = getattr(save_file, "inquiry_code", "?")
            self._log(f"[UNBAN] Inquiry ก่อน : {inquiry_before}")

            server_handler = core.ServerHandler(save_file)
            ok = server_handler.create_new_account()
            if not ok:
                raise RuntimeError("create_new_account ล้มเหลว — ไม่สามารถ unban ได้")

            inquiry_after = getattr(save_file, "inquiry_code", "?")
            changed = "✅ เปลี่ยนแล้ว" if inquiry_before != inquiry_after else "⚠️ ไม่เปลี่ยน!"
            self._log(f"[UNBAN] Inquiry หลัง: {inquiry_after}  {changed}")

            import time as _time
            _time.sleep(2)

            result = core.ServerHandler(save_file).get_codes()
            if result is None:
                raise RuntimeError("get_codes ล้มเหลว — ลองใหม่อีกครั้ง")

            new_tc, new_cc = result
            self._log(f"[UNBAN] ✅ TC={new_tc} | CC={new_cc}")

            self._close_log()
            return {
                "success": True,
                "new_transfer_code": new_tc,
                "new_confirmation_code": new_cc,
                "inquiry_before": str(inquiry_before),
                "inquiry_after":  str(inquiry_after),
                "cat_removed": cat_id,
            }

        except Exception as e:
            self._log(f"[REMOVE_UNBAN] ❌ {e}")
            self._close_log()
            return self._error_result(e)

    # ── ด่านที่ได้ Talent Orb เป็น reward ปกติจากเกม ──────────────────────────
    # clear_chapter() พอ — เกมแจก orb ให้เองอัตโนมัติเมื่อโหลด save
    # ไม่ต้องทำอะไรเพิ่มใน runner
    #   394 → Valkyrie Cat's Trial  (Talent Orbs) → cat #24 Valkyrie Cat
    #   395 → Bahamut Cat's Trial   (Talent Orbs) → cat #25 Bahamut Cat
    # ────────────────────────────────────────────────────────────────────────

    # map_id → cat_id สำหรับด่านที่ให้ตัวละครเมื่อ clear ครั้งแรก (unlock)
    _STAGE_UNLOCKS_CAT = {
        # ── The Crazed Cat stages (17–25) ────────────────────────
        17: 91,   # The Crazed Cat     → Crazed Cat
        18: 92,   # The Crazed Tank    → Crazed Tank Cat
        19: 93,   # The Crazed Axe     → Crazed Axe Cat
        20: 94,   # The Crazed Gross   → Crazed Gross Cat
        21: 95,   # The Crazed Cow     → Crazed Cow Cat
        22: 96,   # The Crazed Bird    → Crazed Bird Cat
        23: 97,   # The Crazed Fish    → Crazed Fish Cat
        24: 98,   # The Crazed Lizard  → Crazed Lizard Cat
        25: 99,   # The Crazed Titan   → Crazed Titan Cat
        # Maniac stages (102–110) → True Form ของ Crazed cats (อยู่ใน _AWAKENS_STAGE_TO_CAT)
        # ── อื่นๆ ─────────────────────────────────────────────────
        161: 418, # Crazed Moneko stage → Crazed Moneko
        208: 208, # Clan of the Maniacs stage → Clan of the Maniacs
    }

    # map_id → cat_id สำหรับด่าน Awakens!/Malevolent ที่ต้อง True Form ด้วย
    _AWAKENS_STAGE_TO_CAT = {
        # ── EX Cat Awakens! (45–58) ──────────────────────────────
        45:  9,    # Actress Awakens!  → Actress Cat
        46:  10,   # Kung-Fu Awakens!  → Kung Fu Cat
        47:  11,   # Mr. Awakens!      → Mr.
        48:  12,   # Bondage Awakens!  → Bondage Cat
        49:  13,   # The Dom Awakens!  → Dom Cat
        50:  14,   # Box Cats Awaken!  → Cats in a Box
        51:  15,   # Panties Awakens!  → Panties Cat
        52:  17,   # Tricycle Awakens! → Tricycle Cat
        53:  18,   # Ninja Awakens!    → Ninja Cat
        54:  19,   # Zombie Awakens!   → Zombie Cat
        55:  20,   # Samurai Awakens!  → Samurai Cat
        56:  21,   # Sumo Awakens!     → Sumo Cat (→ Jiangshi Cat)
        57:  22,   # Boogie Awakens!   → Boogie Cat
        58:  23,   # Skirt Awakens!    → Skirt Cat
        # ── Seasonal/Event EX Awakens (83–94) ───────────────────
        83:  79,   # Adult Cat Awakes!      → Adult Cat
        84:  80,   # Evil Cat Awakes!       → Evil Cat (→ Executioner Cat)
        86:  100,  # Maiden Awakens!        → Maiden Cat
        87:  104,  # Koi Awakens!           → Koi Cat
        88:  109,  # Bride Awakens!         → Bride Cat (→ Madam Bride)
        89:  122,  # Vacation Awakens!      → Vacation Cat (→ Vacation Queen)
        90:  128,  # Vengeance Awakens!     → Vengeance Cat (→ Vengeful Cat)
        91:  132,  # Kung-Fu X Awakens!     → Kung Fu Cat X
        92:  63,   # Sports Day Awakens!    → Sports Day Cat
        93:  70,   # Salaryman Awakens!     → Salaryman Cat
        94:  74,   # Reindeer Fish Awakens! → Reindeer Fish Cat
        # ── Later EX Awakens ─────────────────────────────────────
        143: 183,  # Cat Kart Awakens!       → Cat Kart G (Cat Kart R)
        148: 127,  # Flower Cat Awakens!     → Flower Cat (→ Minigun Cat)
        153: 213,  # Catburger Awakens!      → Catburger (→ Meow-cycle)
        337: 329,  # Eggy Cat Awakens!       → Eggy Cat
        384: 303,  # Food Stall Cat Awakens! → Food Stall Cat
        # ── Li'l Cat Awakens! (130–138) ─────────────────────────
        130: 209,  # Li'l Cat Awakens!    → Li'l Cat
        131: 210,  # Li'l Tank Awakens!   → Li'l Tank Cat
        132: 211,  # Li'l Axe Awakens!    → Li'l Axe Cat
        133: 245,  # Li'l Gross Awakens!  → Li'l Gross Cat
        134: 246,  # Li'l Cow Awakens!    → Li'l Cow Cat
        135: 247,  # Li'l Bird Awakens!   → Li'l Bird Cat
        136: 311,  # Li'l Fish Awakens!   → Li'l Fish Cat
        137: 312,  # Li'l Lizard Awakens! → Li'l Lizard Cat
        138: 313,  # Li'l Titan Awakens!  → Li'l Titan Cat
        # ── Maniac stages (102–110) → True Form ของ Crazed cats ──────────────
        102: 91,  # Manic Cat stage      → Crazed Cat True Form
        103: 92,  # Manic Eraser stage   → Crazed Tank True Form
        104: 93,  # Manic Lion stage     → Crazed Axe True Form
        105: 94,  # Manic Flying stage   → Crazed Gross True Form
        106: 95,  # Manic Jamiera stage  → Crazed Cow True Form
        107: 96,  # Manic Island stage   → Crazed Bird True Form
        108: 97,  # Manic Fishing stage  → Crazed Fish True Form
        109: 98,  # Manic Dark stage     → Crazed Lizard True Form
        110: 99,  # Manic Titan stage    → Crazed Titan True Form
        # ── The Malevolent (350–358) → True Form ของ Crazed cats ─
        350: 91,   # The Malevolent Cat     → Crazed Cat
        351: 92,   # The Malevolent Tank    → Crazed Tank Cat
        352: 93,   # The Malevolent Axe     → Crazed Axe Cat
        353: 94,   # The Malevolent Gross   → Crazed Gross Cat
        354: 95,   # The Malevolent Cow     → Crazed Cow Cat
        355: 96,   # The Malevolent Bird    → Crazed Bird Cat
        356: 97,   # The Malevolent Fish    → Crazed Fish Cat
        357: 98,   # The Malevolent Lizard  → Crazed Lizard Cat
        358: 99,   # The Malevolent Titan   → Crazed Titan Cat
    }

    def run_clear_event_stages(self, map_ids: list) -> dict:
        """Clear Normal Event Stages (type=1) ตาม map_ids ที่ระบุ
        ถ้าเป็นด่าน Awakens! จะ True Form แมวที่ตรงกันด้วยอัตโนมัติ"""
        try:
            self._log(f"[OP] Clear Event Stages: {len(map_ids)} maps")
            core.core_data.init_data()
            save_file = self._download_save(backup=True)
            cleared = []
            skipped = []
            for map_id in map_ids:
                try:
                    save_file.event_stages.clear_chapter(type=1, map=map_id)
                    cleared.append(map_id)
                    self._log(f"✔ map {map_id} — cleared")
                except Exception as e:
                    skipped.append(map_id)
                    self._log(f"✘ map {map_id} — {e}")

            # True Form อัตโนมัติสำหรับด่าน Awakens!/Malevolent
            cats_to_tf = []
            for map_id in cleared:
                cat_id = self._AWAKENS_STAGE_TO_CAT.get(map_id)
                if cat_id is None:
                    continue
                try:
                    cat = next((c for c in save_file.cats.cats if c.id == cat_id), None)
                    if cat and getattr(cat, "unlocked", 0):
                        cats_to_tf.append(cat)
                        self._log(f"✔ cat #{cat_id} — queued True Form (awakening)")
                    else:
                        self._log(f"— cat #{cat_id} — ไม่ unlock / ไม่มีในเซฟ (ข้าม)")
                except Exception as e:
                    self._log(f"✘ cat #{cat_id} — True Form error: {e}")
            if cats_to_tf:
                save_file.cats.true_form_cats(save_file, cats_to_tf)
                for c in cats_to_tf:
                    self._log(f"✔ cat #{c.id} — True Form applied")

            # Unlock อัตโนมัติสำหรับด่านที่ให้ตัวละครเป็น reward (Crazed/Maniac/etc.)
            for map_id in cleared:
                cat_id = self._STAGE_UNLOCKS_CAT.get(map_id)
                if cat_id is None:
                    continue
                try:
                    cat = next((c for c in save_file.cats.cats if c.id == cat_id), None)
                    if cat is None:
                        self._log(f"— cat #{cat_id} — ไม่มีในเซฟ (ข้าม)")
                        continue
                    if getattr(cat, "unlocked", 0):
                        self._log(f"— cat #{cat_id} — unlock อยู่แล้ว (ข้าม)")
                        continue
                    cat.unlock(save_file)
                    self._log(f"✔ cat #{cat_id} — unlocked (stage reward)")
                except Exception as e:
                    self._log(f"✘ cat #{cat_id} — unlock error: {e}")

            codes = self._upload_save(save_file)
            self._log(f"[DONE] {len(cleared)} cleared, {len(skipped)} skipped → TC={codes.get('transfer')}")
            self._close_log()
            return {
                "success": True,
                "new_transfer_code": codes,
                "cleared": cleared,
                "skipped": skipped,
            }
        except Exception as e:
            self._log(f"[EVENT_STAGES] ❌ {e}")
            self._close_log()
            return self._error_result(e)

    def _reset_story_chapters_impl(self, save_file, chapter_nums: list) -> list:
        """รีเซ็ต stage clear — EoC Ch.1 (raw 0) เก็บ stage 0 ไว้ 1 ครั้งเพื่อ Transfer Code"""
        logs = []
        for num in chapter_nums:
            raw_idx = STORY_CHAPTER_MAP.get(num)
            if raw_idx is None:
                logs.append(f"✘ Chapter {num} — ไม่ถูกต้อง (ต้องเป็น 1-9)")
                continue
            chapter = save_file.story.chapters[raw_idx]
            name = STORY_CHAPTER_NAMES[num]
            if raw_idx == 0:
                # EoC Ch.1: เก็บด่านแรก (Japan stage 0) cleared=1 เพื่อให้ยังใช้ Transfer Code ได้
                chapter.progress = 1
                for i, stage in enumerate(chapter.stages):
                    stage.clear_times = 1 if i == 0 else 0
                logs.append(f"✔ {name} — reset (เก็บด่านแรก cleared=1 สำหรับ Transfer Code)")
                self._log(f"[STORY] ✔ {name} — reset minimal (stage[0]=1)")
            else:
                chapter.progress = 0
                for stage in chapter.stages:
                    stage.unclear_stage()
                logs.append(f"✔ {name} — reset แล้ว (progress=0, clear_times=0 ทุกด่าน)")
                self._log(f"[STORY] ✔ {name} — reset full")
        return logs

    def run_reset_story_chapters(self, chapter_nums: list) -> dict:
        """รีเซ็ตด่าน Main Story กลับเป็น 0 ตาม chapter ที่ระบุ"""
        try:
            self._log(f"[OP] Reset Story Chapters {chapter_nums}")
            core.core_data.init_data()
            save_file = self._download_save()
            logs = self._reset_story_chapters_impl(save_file, chapter_nums)
            codes = self._upload_save(save_file)
            self._close_log()
            return {"success": True, "new_transfer_code": codes, "log": logs}
        except Exception as e:
            self._log(f"[BCSFE] ❌ {e}")
            self._close_log()
            return self._error_result(e)

    def run_reset_story_all(self) -> dict:
        """รีเซ็ตด่าน Main Story ทั้ง 9 chapters"""
        try:
            self._log("[OP] Reset ALL Story Chapters (1-9)")
            core.core_data.init_data()
            save_file = self._download_save()
            logs = self._reset_story_chapters_impl(save_file, list(STORY_CHAPTER_MAP.keys()))
            codes = self._upload_save(save_file)
            self._close_log()
            return {"success": True, "new_transfer_code": codes, "log": logs}
        except Exception as e:
            self._log(f"[BCSFE] ❌ {e}")
            self._close_log()
            return self._error_result(e)

    def _clear_story_chapters_impl(self, save_file, chapter_nums: list, clear_amount: int) -> list:
        """เคลียร์ด่านใน story chapters ที่ระบุ — return log array"""
        logs = []
        for num in chapter_nums:
            raw_idx = STORY_CHAPTER_MAP.get(num)
            if raw_idx is None:
                logs.append(f"✘ Chapter {num} — ไม่ถูกต้อง (ต้องเป็น 1-9)")
                self._log(f"[STORY] ✘ Chapter {num} — ไม่ถูกต้อง")
                continue
            chapter = save_file.story.chapters[raw_idx]
            for stage_idx in range(STORY_STAGES_PER_CHAPTER):
                chapter.clear_stage(stage_idx, clear_amount)
            name = STORY_CHAPTER_NAMES[num]
            logs.append(f"✔ {name} — {STORY_STAGES_PER_CHAPTER} stages cleared (x{clear_amount})")
            self._log(f"[STORY] ✔ {name} — {STORY_STAGES_PER_CHAPTER} stages")
        return logs

    def run_clear_story_chapters(self, chapter_nums: list, clear_amount: int = 1) -> dict:
        """เคลียร์ด่าน Main Story ตาม chapter ที่ระบุ (1-9)"""
        try:
            self._log(f"[OP] Clear Story Chapters {chapter_nums} x{clear_amount}")
            core.core_data.init_data()
            save_file = self._download_save()
            logs = self._clear_story_chapters_impl(save_file, chapter_nums, clear_amount)
            codes = self._upload_save(save_file)
            self._close_log()
            return {"success": True, "new_transfer_code": codes, "log": logs}
        except Exception as e:
            self._log(f"[BCSFE] ❌ {e}")
            self._close_log()
            return self._error_result(e)

    def run_clear_story_all(self, clear_amount: int = 1) -> dict:
        """เคลียร์ด่าน Main Story ทั้ง 9 chapters"""
        try:
            self._log(f"[OP] Clear ALL Story Chapters (1-9) x{clear_amount}")
            core.core_data.init_data()
            save_file = self._download_save()
            logs = self._clear_story_chapters_impl(save_file, list(STORY_CHAPTER_MAP.keys()), clear_amount)
            codes = self._upload_save(save_file)
            self._close_log()
            return {"success": True, "new_transfer_code": codes, "log": logs}
        except Exception as e:
            self._log(f"[BCSFE] ❌ {e}")
            self._close_log()
            return self._error_result(e)

    # ── Treasure ──────────────────────────────────────────────────────────────

    def _set_treasure_impl(self, save_file, chapter_nums: list, treasure_value: int = 3) -> list:
        """ตั้งค่า treasure สำหรับ story chapters — return log array"""
        logs = []
        tname = {0: "None", 1: "Bronze", 2: "Silver", 3: "Gold"}.get(treasure_value, str(treasure_value))
        for num in chapter_nums:
            raw_idx = STORY_CHAPTER_MAP.get(num)
            if raw_idx is None:
                logs.append(f"✘ Chapter {num} — ไม่ถูกต้อง (ต้องเป็น 1-9)")
                continue
            chapter = save_file.story.chapters[raw_idx]
            for i in range(STORY_STAGES_PER_CHAPTER):
                chapter.stages[i].treasure = treasure_value
            name = STORY_CHAPTER_NAMES[num]
            logs.append(f"✔ {name} — {STORY_STAGES_PER_CHAPTER} stages → {tname} Treasure")
            self._log(f"[TREASURE] ✔ {name} — {STORY_STAGES_PER_CHAPTER} stages → {tname}")
        return logs

    def run_set_treasure_chapters(self, chapter_nums: list, treasure_value: int = 3) -> dict:
        """ตั้งค่า treasure สำหรับ story chapters ที่ระบุ (1-9)"""
        try:
            self._log(f"[OP] Set Treasure Chapters {chapter_nums} value={treasure_value}")
            core.core_data.init_data()
            save_file = self._download_save()
            logs = self._set_treasure_impl(save_file, chapter_nums, treasure_value)
            codes = self._upload_save(save_file)
            self._close_log()
            return {"success": True, "new_transfer_code": codes, "log": logs}
        except Exception as e:
            self._log(f"[BCSFE] ❌ {e}")
            self._close_log()
            return self._error_result(e)

    def run_set_treasure_all(self, treasure_value: int = 3) -> dict:
        """ตั้งค่า treasure สำหรับ story chapters ทั้ง 9 chapters"""
        try:
            self._log(f"[OP] Set Treasure ALL (1-9) value={treasure_value}")
            core.core_data.init_data()
            save_file = self._download_save()
            logs = self._set_treasure_impl(save_file, list(STORY_CHAPTER_MAP.keys()), treasure_value)
            codes = self._upload_save(save_file)
            self._close_log()
            return {"success": True, "new_transfer_code": codes, "log": logs}
        except Exception as e:
            self._log(f"[BCSFE] ❌ {e}")
            self._close_log()
            return self._error_result(e)

    # ── Outbreaks (Zombie Stages) ──────────────────────────────────────────────

    def _clear_outbreaks_impl(self, save_file, chapter_nums: list) -> list:
        """เคลียร์ zombie/outbreak สำหรับ chapters ที่ระบุ — return log array"""
        logs = []
        for num in chapter_nums:
            if num not in STORY_CHAPTER_MAP:
                logs.append(f"✘ Chapter {num} — ไม่ถูกต้อง (ต้องเป็น 1-9)")
                continue
            # true_id = 0-based (user 1-9 → true_id 0-8)
            true_id = num - 1
            # outbreak chapter key: skip index 3 (same pattern as story chapters)
            chapter_key = true_id if true_id < 3 else true_id + 1

            if chapter_key not in save_file.outbreaks.chapters:
                save_file.outbreaks.chapters[chapter_key] = OutbreakChapter(chapter_key, {})
            ob_chapter = save_file.outbreaks.chapters[chapter_key]

            for stage_id in range(STORY_STAGES_PER_CHAPTER):
                if stage_id not in ob_chapter.outbreaks:
                    ob_chapter.outbreaks[stage_id] = BCOutbreak(True)
                else:
                    ob_chapter.outbreaks[stage_id].cleared = True

            # Clear active outbreak markers so none are shown as "ongoing"
            if chapter_key in save_file.outbreaks.current_outbreaks:
                cur_ch = save_file.outbreaks.current_outbreaks[chapter_key]
                for stage_id in range(STORY_STAGES_PER_CHAPTER):
                    if stage_id in cur_ch.outbreaks:
                        cur_ch.outbreaks[stage_id].cleared = False

            name = STORY_CHAPTER_NAMES[num]
            logs.append(f"✔ {name} — {STORY_STAGES_PER_CHAPTER} zombie stages cleared")
            self._log(f"[OUTBREAK] ✔ {name} — {STORY_STAGES_PER_CHAPTER} stages cleared")
        return logs

    def run_clear_outbreak_chapters(self, chapter_nums: list) -> dict:
        """เคลียร์ zombie/outbreak สำหรับ story chapters ที่ระบุ (1-9)"""
        try:
            self._log(f"[OP] Clear Outbreaks Chapters {chapter_nums}")
            core.core_data.init_data()
            save_file = self._download_save()
            logs = self._clear_outbreaks_impl(save_file, chapter_nums)
            codes = self._upload_save(save_file)
            self._close_log()
            return {"success": True, "new_transfer_code": codes, "log": logs}
        except Exception as e:
            self._log(f"[BCSFE] ❌ {e}")
            self._close_log()
            return self._error_result(e)

    def run_clear_outbreak_all(self) -> dict:
        """เคลียร์ zombie/outbreak สำหรับ story chapters ทั้ง 9 chapters"""
        try:
            self._log("[OP] Clear Outbreaks ALL (1-9)")
            core.core_data.init_data()
            save_file = self._download_save()
            logs = self._clear_outbreaks_impl(save_file, list(STORY_CHAPTER_MAP.keys()))
            codes = self._upload_save(save_file)
            self._close_log()
            return {"success": True, "new_transfer_code": codes, "log": logs}
        except Exception as e:
            self._log(f"[BCSFE] ❌ {e}")
            self._close_log()
            return self._error_result(e)

    # ── Legend Stages (SoL / UL / ZL) ────────────────────────────────────────

    def _clear_legend_sol_impl(self, save_file, max_crown: int, clear_amount: int = 1) -> list:
        """เคลียร์ Stories of Legend (SoL) — save_file.event_stages type=0"""
        # SoL = EventChapters.chapters[0] (type=0, letter="N", base_index=0)
        ev = save_file.event_stages
        if not ev.chapters or not ev.chapters[0].chapters:
            return ["— Stories of Legend — ไม่มีข้อมูลใน save"]
        total_maps = len(ev.chapters[0].chapters)
        for map_id in range(total_maps):
            total_stars = ev.get_total_stars(0, map_id)
            for star in range(min(max_crown, total_stars)):
                total_stages = ev.get_total_stages(0, map_id, star)
                for stage_idx in range(total_stages):
                    ev.clear_stage(0, map_id, star, stage_idx, clear_amount)
        msg = f"✔ Stories of Legend — {total_maps} maps, crowns 1-{max_crown} cleared"
        self._log(f"[SoL] ✔ {total_maps} maps (crown 1-{max_crown})")
        return [msg]

    def _clear_legend_ul_impl(self, save_file, max_crown: int, clear_amount: int = 1) -> list:
        """เคลียร์ Uncanny Legends (UL) ทั้งหมด — return log array"""
        ul_ch = save_file.uncanny.chapters  # core.Chapters
        total_maps = len(ul_ch.chapters)
        if total_maps == 0:
            return ["— Uncanny Legends — ไม่มีข้อมูลใน save"]
        for map_id in range(total_maps):
            num_crowns = ul_ch.get_total_stars(map_id)
            for star in range(min(max_crown, num_crowns)):
                num_stages = ul_ch.get_total_stages(map_id, star)
                for stage_idx in range(num_stages):
                    ul_ch.clear_stage(map_id, star, stage_idx, clear_amount)
        msg = f"✔ Uncanny Legends — {total_maps} maps, crowns 1-{max_crown} cleared"
        self._log(f"[UL] ✔ {total_maps} maps (crown 1-{max_crown})")
        return [msg]

    def _clear_legend_zl_impl(self, save_file, max_crown: int, clear_amount: int = 1) -> list:
        """เคลียร์ Zero Legends (ZL) ทั้งหมด — return log array"""
        zl = save_file.zero_legends
        total_maps = len(zl.chapters)
        if total_maps == 0:
            return ["— Zero Legends — ไม่มีข้อมูลใน save"]
        for map_id in range(total_maps):
            chapters_stars = zl.chapters[map_id]
            num_crowns = len(chapters_stars.chapters)
            for star in range(min(max_crown, num_crowns)):
                chapter = chapters_stars.chapters[star]
                for stage_idx in range(len(chapter.stages)):
                    zl.clear_stage(map_id, star, stage_idx, clear_amount)
        msg = f"✔ Zero Legends — {total_maps} maps, crowns 1-{max_crown} cleared"
        self._log(f"[ZL] ✔ {total_maps} maps (crown 1-{max_crown})")
        return [msg]

    def run_clear_legends(self, legend_types: list, max_crown: int = 4, clear_amount: int = 1) -> dict:
        """เคลียร์ SoL/UL/ZL ตาม legend_types ที่ระบุ (sol, ul, zl)"""
        try:
            self._log(f"[OP] Clear Legends {legend_types} max_crown={max_crown} x{clear_amount}")
            core.core_data.init_data()
            save_file = self._download_save()
            logs = []
            if "sol" in legend_types:
                logs += self._clear_legend_sol_impl(save_file, max_crown, clear_amount)
            if "ul" in legend_types:
                logs += self._clear_legend_ul_impl(save_file, max_crown, clear_amount)
            if "zl" in legend_types:
                logs += self._clear_legend_zl_impl(save_file, max_crown, clear_amount)
            codes = self._upload_save(save_file)
            self._close_log()
            return {"success": True, "new_transfer_code": codes, "log": logs}
        except Exception as e:
            self._log(f"[BCSFE] ❌ {e}")
            self._close_log()
            return self._error_result(e)

    # ── Aku Realm ─────────────────────────────────────────────────────────────

    def _unlock_aku_realm_impl(self, save_file) -> list:
        """ปลดล็อค Aku Realm — clear 7 event maps ที่เกี่ยวข้อง"""
        stage_ids = [255, 256, 257, 258, 265, 266, 268]
        for sid in stage_ids:
            save_file.event_stages.clear_map(1, sid, 0, False)
        msg = f"✔ Unlock Aku Realm — {len(stage_ids)} event stages unlocked"
        self._log("[AKU] ✔ Unlock Aku Realm done")
        return [msg]

    def _clear_aku_chapters_impl(self, save_file, clear_amount: int = 1) -> list:
        """เคลียร์ Aku Realm Chapters ทั้งหมด — return log array"""
        aku = save_file.aku
        total_maps = len(aku.chapters)
        if total_maps == 0:
            return ["— Aku Realm Chapters — ไม่มีข้อมูลใน save"]
        total_stages = 0
        for map_id in range(total_maps):
            for star_chapter in aku.chapters[map_id].chapters:
                for stage in star_chapter.stages:
                    stage.clear_stage(clear_amount)
                    total_stages += 1
        msg = f"✔ Aku Realm Chapters — {total_maps} maps, {total_stages} stages cleared"
        self._log(f"[AKU] ✔ {total_maps} maps, {total_stages} stages cleared")
        return [msg]

    def run_aku(self, do_unlock: bool, do_chapters: bool, clear_amount: int = 1) -> dict:
        """ปลดล็อค Aku Realm และ/หรือ เคลียร์ Aku Chapters"""
        try:
            self._log(f"[OP] Aku unlock={do_unlock} chapters={do_chapters} x{clear_amount}")
            core.core_data.init_data()
            save_file = self._download_save()
            logs = []
            if do_unlock:
                logs += self._unlock_aku_realm_impl(save_file)
            if do_chapters:
                logs += self._clear_aku_chapters_impl(save_file, clear_amount)
            codes = self._upload_save(save_file)
            self._close_log()
            return {"success": True, "new_transfer_code": codes, "log": logs}
        except Exception as e:
            self._log(f"[BCSFE] ❌ {e}")
            self._close_log()
            return self._error_result(e)

    def run_unlock_all(self) -> dict:
        """Unlock ทุกตัวละครในเกม"""
        try:
            self._log("[OP] Unlock ALL cats in game")
            core.core_data.init_data()
            save_file = self._download_save()

            # ตัวละครที่ยกเว้นจาก unlock all (ห้ามลบ — เพิ่ม ID ได้)
            UNLOCK_ALL_EXCLUDE = {673}  # #673 Cheetah Cat (Uber Rare)

            count = 0
            logs = []
            for cat in save_file.cats.cats:
                if cat.id in UNLOCK_ALL_EXCLUDE:
                    logs.append(f"— #{cat.id} — skipped (excluded)")
                    continue
                cat.unlock(save_file)  # ใช้ BCSFE unlock() เหมือน CLI (ไม่แตะ unlocked_forms)
                logs.append(f"✔ #{cat.id} — unlocked")
                count += 1

            self._log(f"[BCSFE] Unlocked all {count} cats")
            codes = self._upload_save(save_file)
            self._close_log()
            return {"success": True, "new_transfer_code": codes, "count": count, "log": logs}

        except Exception as e:
            self._log(f"[BCSFE] ❌ {e}")
            self._close_log()
            return self._error_result(e)

    def run_true_form_all(self) -> dict:
        """True Form ทุกตัวที่ลูกค้ามีอยู่แล้ว"""
        try:
            self._log("[OP] True Form ALL unlocked cats")
            core.core_data.init_data()
            save_file = self._download_save()

            owned = save_file.cats.get_unlocked_cats()
            save_file.cats.true_form_cats(save_file, owned)
            logs = [f"✔ #{cat.id} — True Form applied" for cat in owned]
            self._log(f"[BCSFE] True Form all {len(owned)} unlocked cats")
            codes = self._upload_save(save_file)
            self._close_log()
            return {"success": True, "new_transfer_code": codes, "count": len(owned), "log": logs}

        except Exception as e:
            self._log(f"[BCSFE] ❌ {e}")
            self._close_log()
            return self._error_result(e)

    def run_ultra_form_all(self) -> dict:
        """Ultra Form ทุกตัวที่มีอยู่ — เฉพาะตัวที่มี True Form แล้ว (unlocked_forms >= 3)
        ตัวที่ยังไม่มี True Form จะถูกข้ามโดยอัตโนมัติ"""
        try:
            self._log("[OP] Ultra Form ALL unlocked cats (True Form required)")
            core.core_data.init_data()
            save_file = self._download_save()

            owned = save_file.cats.get_unlocked_cats()

            # เฉพาะตัวที่มี True Form แล้ว (unlocked_forms >= 3)
            true_formed  = [cat for cat in owned if cat.unlocked_forms >= 3]
            no_true_form = [cat for cat in owned if cat.unlocked_forms < 3]

            if true_formed:
                save_file.cats.fourth_form_cats(save_file, true_formed)

            logs  = [f"✔ #{cat.id} — Ultra Form applied" for cat in true_formed]
            logs += [f"— #{cat.id} — ข้าม (ยังไม่มี True Form)" for cat in no_true_form]

            self._log(f"[BCSFE] Ultra Form {len(true_formed)}/{len(owned)} cats"
                      f" (ข้าม {len(no_true_form)} ตัวที่ยังไม่มี True Form)")
            codes = self._upload_save(save_file)
            self._close_log()
            return {"success": True, "new_transfer_code": codes, "count": len(true_formed), "log": logs}

        except Exception as e:
            self._log(f"[BCSFE] ❌ {e}")
            self._close_log()
            return self._error_result(e)

    def run_talents_max_all(self) -> dict:
        """Max Talents ทุกตัวที่ลูกค้ามีอยู่แล้ว"""
        try:
            self._log("[OP] Max Talents ALL unlocked cats")
            core.core_data.init_data()
            save_file = self._download_save()

            talent_data = save_file.cats.read_talent_data(save_file)
            if talent_data is None:
                self._close_log()
                return {"success": False, "error": "ไม่สามารถโหลด talent data ได้"}

            owned = save_file.cats.get_unlocked_cats()
            count = 0
            logs = []
            for cat in owned:
                n = self._init_and_max_talents(cat, talent_data)
                if n > 0:
                    logs.append(f"✔ #{cat.id} — {n} talents maxed")
                    self._log(f"[CAT] ✔ #{cat.id} — {n} talents maxed")
                    count += 1

            self._log(f"[BCSFE] Max Talents all {count} cats")
            codes = self._upload_save(save_file)
            self._close_log()
            return {"success": True, "new_transfer_code": codes, "count": count, "log": logs}

        except Exception as e:
            self._log(f"[BCSFE] ❌ {e}")
            self._close_log()
            return self._error_result(e)

    def run_base_materials(self, amount: int) -> dict:
        """เพิ่ม Base Materials ทุกชนิดพร้อมกัน"""
        try:
            self._log(f"[OP] Base Materials → {amount} ทุกชนิด")
            core.core_data.init_data()
            save_file = self._download_save()

            mats = save_file.ototo.base_materials.materials
            n = len(mats)
            MATERIAL_NAMES = [
                "Bricks","Feathers","Coal","Sprockets","Gold","Meteorite","Beast Bones","Ammonite",
                "Brick Z","Feathers Z","Coal Z","Sprockets Z","Gold Z","Meteorite Z","Beast Bones Z","Ammonite Z",
            ]
            logs = []
            for i, mat in enumerate(mats):
                old = mat.amount
                mat.amount = min(old + amount, 9999)
                name = MATERIAL_NAMES[i] if i < len(MATERIAL_NAMES) else f"Mat#{i}"
                logs.append(f"✔ {name}: {old} + {amount} → {mat.amount}")
                self._log(f"[BCSFE] ✔ {name}: {old} + {amount} → {mat.amount}")
            self._log(f"[BCSFE] Base Materials {n} ชนิด เสร็จแล้ว")

            codes = self._upload_save(save_file)
            self._close_log()
            return {"success": True, "new_transfer_code": codes, "log": logs}

        except Exception as e:
            import traceback
            self._log(f"[BCSFE] ❌ {e}\n{traceback.format_exc()}")
            self._close_log()
            return self._error_result(e)
