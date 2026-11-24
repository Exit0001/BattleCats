"""
ถอด QR code ของสลิป -> บอก transRef + ธนาคาร

วิธีใช้:
  1. สแกน QR บนสลิปด้วยแอปอะไรก็ได้ (กล้องมือถือ / Google Lens / เว็บ QR scanner)
  2. ก๊อปสตริงที่ได้มาวางในคำสั่งนี้

  .venv/Scripts/python.exe -X utf8 decode_qr.py "0046000600000101030250225APF..."
"""
import sys

BANKS = {
    "002": "กรุงเทพ", "004": "กสิกรไทย", "006": "กรุงไทย", "011": "ทหารไทยธนชาต",
    "014": "ไทยพาณิชย์", "017": "ซิตี้แบงก์", "020": "สแตนดาร์ดชาร์เตอร์ด",
    "022": " CIMB", "024": "UOB", "025": "กรุงศรีอยุธยา", "030": "ออมสิน",
    "033": "อาคารสงเคราะห์", "034": "ธ.ก.ส.", "066": "อิสลาม", "067": "ทิสโก้",
    "069": "เกียรตินาคินภัทร", "070": "ไอซีบีซี", "071": "ไทยเครดิต",
    "073": "แลนด์ แอนด์ เฮ้าส์", "000": "TrueMoney / e-wallet",
}

def tlv(s):
    """แยก TLV: tag(2) + length(2) + value"""
    out, i = [], 0
    while i + 4 <= len(s):
        tag, ln = s[i:i+2], s[i+2:i+4]
        if not ln.isdigit():
            break
        n = int(ln)
        out.append((tag, s[i+4:i+4+n]))
        i += 4 + n
    return out

if len(sys.argv) < 2:
    print(__doc__)
    raise SystemExit(1)

raw = sys.argv[1].strip()
print(f"QR: {raw}")
print()

top = tlv(raw)
payload = next((v for t, v in top if t == "00"), None)
country = next((v for t, v in top if t == "51"), "-")

if not payload:
    print("อ่านไม่ออก — ไม่ใช่ QR สลิปมาตรฐาน")
    raise SystemExit(1)

inner = tlv(payload)
bank = next((v for t, v in inner if t == "01"), "-")
tx   = next((v for t, v in inner if t == "02"), "-")

print("=" * 66)
print(f"  transRef  : {tx}          <-- ID ที่ระบบเราใช้")
print(f"  ธนาคาร     : {bank}  ({BANKS.get(bank, 'ไม่รู้จัก')})")
print(f"  ประเทศ     : {country}")
print("=" * 66)
