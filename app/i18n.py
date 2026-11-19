# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Obsidian Stream Hub
"""Menu language: Thai / English (added in the Obsidian Mirror fork).

Source strings in the code are English. `T(text)` returns the Thai version when the
language is Thai, otherwise the text itself. A missing Thai entry falls back to English,
and `test_i18n.py` checks that every `T("...")` in the app has a Thai entry.
"""
from __future__ import annotations

LANGUAGES = ("auto", "th", "en")
_lang = "en"


def resolve(language: str) -> str:
    """auto → Thai when Windows is set to Thai, otherwise English."""
    if language in ("th", "en"):
        return language
    try:
        from PySide6.QtCore import QLocale
        return "th" if QLocale.system().language() == QLocale.Thai else "en"
    except Exception:  # noqa: BLE001 - no Qt during some tests
        return "en"


def set_language(language: str) -> str:
    global _lang
    _lang = resolve(language)
    return _lang


def current() -> str:
    return _lang


def T(text: str) -> str:  # noqa: N802 - short name on purpose, used everywhere
    if _lang == "th":
        return TH.get(text, text)
    return text


MONTHS = {
    "en": ("January", "February", "March", "April", "May", "June", "July", "August",
           "September", "October", "November", "December"),
    "th": ("มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน", "กรกฎาคม",
           "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"),
}
WEEKDAYS = {
    "en": ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"),
    "th": ("วันจันทร์", "วันอังคาร", "วันพุธ", "วันพฤหัสบดี", "วันศุกร์", "วันเสาร์", "วันอาทิตย์"),
}


def date_line(weekday: int, day: int, month: int) -> str:
    if _lang == "th":
        return f"{WEEKDAYS['th'][weekday]}ที่ {day} {MONTHS['th'][month - 1]}"
    return f"{WEEKDAYS['en'][weekday]}, {day} {MONTHS['en'][month - 1]}"


TH: dict[str, str] = {
    # --- waiting screen (dark, with steps) --------------------------------------------
    "Waiting for the iPhone": "รอเชื่อมต่อ iPhone",
    "Mirroring ✓": "กำลังสะท้อนจอ ✓",
    "The receiver stopped": "ตัวรับภาพหยุดทำงาน",
    "UxPlay is not installed": "ยังไม่ได้ติดตั้ง UxPlay",
    "Connected by cable ✓": "ต่อสายแล้ว ✓",
    "Through the iPhone hotspot ✓": "ต่อผ่านฮอตสปอตของ iPhone ✓",
    "Picture hidden to save the PC.\nThe OBS link keeps working.": "ซ่อนภาพไว้ให้เครื่องเบา\nลิงก์ OBS ยังทำงานตามปกติ",
    "Right-click → “Restart receiver”": "คลิกขวา → “เริ่มตัวรับภาพใหม่”",
    "Run setup\\install.ps1": "รัน setup\\install.ps1",
    "Open Control Center on the iPhone\n(swipe down from the top-right corner)":
        "เปิดศูนย์ควบคุมบน iPhone\n(ปัดลงจากมุมขวาบนของจอ)",
    "Tap “Screen Mirroring”": "แตะ “การสะท้อนหน้าจอ”",
    "Choose “{name}”": "เลือก “{name}”",
    "Right-click for settings": "คลิกขวาเพื่อตั้งค่า",
    # --- Android (USB, scrcpy) ---------------------------------------------------------
    "Phone: {name}": "โทรศัพท์: {name}",
    # Android = beta: not tried on a real phone yet (owner 2026-11-20: ship it, wait for feedback)
    "Using an Android phone?\nRight-click → Phone → Android (USB cable or Wi‑Fi) · beta":
        "ใช้มือถือ Android?\nคลิกขวา → โทรศัพท์ → Android (สาย USB หรือ Wi‑Fi) · เบต้า",
    "No cable? (Android 11+)\nRight-click → Phone → Connect Android over Wi‑Fi (QR code)":
        "ไม่มีสาย? (Android 11 ขึ้นไป)\nคลิกขวา → โทรศัพท์ → เชื่อมต่อ Android ผ่าน Wi‑Fi (QR Code)",
    "Android (USB cable or Wi‑Fi) · beta": "Android (สาย USB หรือ Wi‑Fi) · เบต้า",
    "Connect Android over Wi‑Fi (QR code)…": "เชื่อมต่อ Android ผ่าน Wi‑Fi (QR Code)…",
    "Connect Android over Wi‑Fi": "เชื่อมต่อ Android ผ่าน Wi‑Fi",
    "Scan with the Android phone": "สแกนด้วยมือถือ Android",
    "1. Connect the phone to the same Wi‑Fi as this PC\n"
    "2. Settings → Developer options → Wireless debugging → On\n"
    "3. Tap “Pair device with QR code” and scan this code":
        "1. ต่อมือถือกับ Wi‑Fi เดียวกับคอมเครื่องนี้\n"
        "2. การตั้งค่า → ตัวเลือกสำหรับนักพัฒนา → การแก้ไขข้อบกพร่องผ่าน Wi‑Fi → เปิด\n"
        "3. แตะ “จับคู่อุปกรณ์ด้วยคิวอาร์โค้ด” แล้วสแกนโค้ดนี้",
    "Starting…": "กำลังเริ่ม…",
    "Waiting for the phone to scan…": "รอมือถือสแกน…",
    "Pairing…": "กำลังจับคู่…",
    "Paired ✓ Connecting…": "จับคู่แล้ว ✓ กำลังเชื่อมต่อ…",
    "Connected ✓ From now on it connects by itself when Wireless debugging is on.":
        "เชื่อมต่อแล้ว ✓ ครั้งต่อไปจะต่อเองเมื่อเปิด “การแก้ไขข้อบกพร่องผ่าน Wi‑Fi”",
    "This PC cannot search the network for phones (adb mDNS is off).":
        "คอมเครื่องนี้ค้นหามือถือในเครือข่ายไม่ได้ (adb mDNS ปิดอยู่)",
    "No phone scanned the code in 3 minutes. Close and try again.":
        "ไม่มีมือถือสแกนภายใน 3 นาที ปิดหน้าต่างแล้วลองใหม่",
    "Pairing failed: {err}": "จับคู่ไม่สำเร็จ: {err}",
    "Android 11 or newer. Older phones: use the USB cable.": "ใช้ได้กับ Android 11 ขึ้นไป รุ่นเก่ากว่านั้นใช้สาย USB",
    "Android phone over Wi‑Fi: {addr}": "มือถือ Android ผ่าน Wi‑Fi: {addr}",
    "iPhone (AirPlay, Wi‑Fi or cable)": "iPhone (AirPlay, Wi‑Fi หรือสาย)",
    "Android (USB cable)": "Android (สาย USB)",
    "Waiting for the Android phone (beta)": "รอเชื่อมต่อมือถือ Android (เบต้า)",
    "Allow USB debugging on the phone": "กดอนุญาต USB debugging บนมือถือ",
    "adb is missing": "ไม่พบ adb",
    "Tap “Allow” on the phone screen\n(tick “Always allow from this computer”)":
        "แตะ “อนุญาต” บนหน้าจอมือถือ\n(ติ๊ก “อนุญาตจากคอมพิวเตอร์นี้เสมอ”)",
    "Run setup\\get_scrcpy.ps1": "รัน setup\\get_scrcpy.ps1",
    "Turn on Developer options\n(Settings → About phone → tap Build number 7 times)":
        "เปิดตัวเลือกสำหรับนักพัฒนา\n(การตั้งค่า → เกี่ยวกับโทรศัพท์ → แตะหมายเลขบิลด์ 7 ครั้ง)",
    "Turn on USB debugging\n(Settings → System → Developer options)":
        "เปิด “การแก้ไขข้อบกพร่อง USB”\n(การตั้งค่า → ระบบ → ตัวเลือกสำหรับนักพัฒนา)",
    "Connect the USB cable and tap “Allow” on the phone": "เสียบสาย USB แล้วแตะ “อนุญาต” บนมือถือ",
    "adb not found. Run setup\\get_scrcpy.ps1": "ไม่พบ adb ให้รัน setup\\get_scrcpy.ps1",
    "Android connection failed: {err}": "ต่อ Android ไม่สำเร็จ: {err}",
    "Android phone found: {serial}": "พบมือถือ Android: {serial}",
    "the phone did not start sending video": "มือถือไม่ส่งภาพมา",
    "Android phone disconnected": "มือถือ Android หลุดการเชื่อมต่อ",
    # --- lock screen / placeholder (old texts) -------------------------------------
    "Open Control Center →\nScreen Mirroring → “{name}”": "เปิดศูนย์ควบคุม →\nการสะท้อนหน้าจอ → “{name}”",
    "UxPlay is not installed.\nRun setup\\install.ps1": "ยังไม่ได้ติดตั้ง UxPlay\nรัน setup\\install.ps1",
    "The receiver stopped.\nRight-click → “Restart receiver”": "ตัวรับภาพหยุดทำงาน\nคลิกขวา → “เริ่มตัวรับภาพใหม่”",
    "Receiver is off": "ตัวรับภาพปิดอยู่",
    "Connecting…": "กำลังเชื่อมต่อ…",
    "Connected by cable ✓\nScreen Mirroring → “{name}”": "ต่อสายแล้ว ✓\nการสะท้อนหน้าจอ → “{name}”",
    "Through the iPhone hotspot ✓\nScreen Mirroring → “{name}”": "ผ่านฮอตสปอตของ iPhone ✓\nการสะท้อนหน้าจอ → “{name}”",
    "Mirroring ✓ · picture hidden to save the PC\nThe OBS link keeps working":
        "สะท้อนจออยู่ ✓ · ซ่อนภาพไว้ให้เครื่องเบา\nลิงก์ OBS ยังทำงานตามปกติ",
    # --- common menu ---------------------------------------------------------------
    "Window view": "รูปแบบหน้าต่าง",
    "View: phone frame": "แบบกรอบโทรศัพท์",
    "View: plain window": "แบบหน้าต่างธรรมดา",
    "Screenshot  (Ctrl+S)": "แคปหน้าจอ  (Ctrl+S)",
    "Open screenshots folder": "เปิดโฟลเดอร์ภาพแคป",
    "Sound on PC": "เล่นเสียงบน PC",
    "Receiver name…": "ชื่อตัวรับภาพ…",
    "Cable connection (USB)…": "ต่อด้วยสาย (USB)…",
    "Restart receiver": "เริ่มตัวรับภาพใหม่",
    "UxPlay log": "บันทึกของ UxPlay",
    "About…": "เกี่ยวกับโปรแกรม…",
    # --- feedback (app/feedback.py → dashboard "แจ้งปัญหา") --------------------------------
    "💬 Send feedback / report a problem…": "💬 ส่งฟีดแบ็ก / แจ้งปัญหา…",
    # sign-in (app/account.py · app/login_dialog.py)
    "Account: @{name}": "บัญชี: @{name}",
    "Sign out…": "ออกจากระบบ…",
    "Sign out": "ออกจากระบบ",
    "Sign out of @{name}? Obsidian Mirror closes and asks to sign in next time.":
        "ออกจากระบบ @{name} ใช่ไหม? โปรแกรมจะปิด และเปิดครั้งหน้าต้องเข้าสู่ระบบใหม่",
    "Sign in to Obsidian Mirror": "เข้าสู่ระบบ Obsidian Mirror",
    "Use your Obsidian Hub account (free on every plan). The browser opens for the sign-in; Google accounts work too.":
        "ใช้บัญชี Obsidian Hub ของคุณ (ใช้ฟรีทุกแพ็กเกจ) · ระบบจะเปิดเบราว์เซอร์ให้เข้าสู่ระบบ ใช้บัญชี Google ได้",
    "Sign in with the browser": "เข้าสู่ระบบผ่านเบราว์เซอร์",
    "Open the browser again": "เปิดเบราว์เซอร์อีกครั้ง",
    "Quit": "ปิดโปรแกรม",
    "Checking your account…": "กำลังตรวจสอบบัญชี…",
    "Finish signing in in the browser, then come back here.": "เข้าสู่ระบบและกด \"อนุญาต\" ในเบราว์เซอร์ให้เสร็จ แล้วกลับมาที่นี่",
    "Sign-in took too long. Please try again.": "รอนานเกินไป กรุณาลองเข้าสู่ระบบอีกครั้ง",
    "Sign-in did not finish. Please try again.": "เข้าสู่ระบบไม่สำเร็จ กรุณาลองอีกครั้ง",
    "Could not reach Obsidian Hub. Check the internet and try again.": "เชื่อมต่อ Obsidian Hub ไม่ได้ ตรวจอินเทอร์เน็ตแล้วลองอีกครั้ง",
    "Could not reach Obsidian Hub for a while. Connect to the internet, then sign in.":
        "เชื่อมต่อ Obsidian Hub ไม่ได้มาหลายวันแล้ว ต่ออินเทอร์เน็ตแล้วเข้าสู่ระบบอีกครั้ง",
    "Phone Cast is switched off for this account.": "Phone Cast ถูกปิดใช้งานสำหรับบัญชีนี้",
    "Phone Cast is switched off for this account. Contact us through \"Report a problem\" in the dashboard.":
        "Phone Cast ถูกปิดใช้งานสำหรับบัญชีนี้ ติดต่อเราได้ที่เมนู \"แจ้งปัญหา\" ใน dashboard",
    "Signed in. You can close this tab and go back to Obsidian Mirror.": "เข้าสู่ระบบแล้ว ปิดแท็บนี้แล้วกลับไปที่ Obsidian Mirror ได้เลย",
    "This sign-in link is not valid. Press \"Sign in\" in Obsidian Mirror again.":
        "ลิงก์เข้าสู่ระบบนี้ใช้ไม่ได้ กด \"เข้าสู่ระบบ\" ในโปรแกรม Obsidian Mirror อีกครั้ง",
    "Send feedback": "ส่งฟีดแบ็ก",
    "The dashboard opens at “แจ้งปัญหา” (log in if asked). Type what happened and press send — "
    "the team answers you in that chat.\n\nThese details are attached so we can fix it faster "
    "(no passwords, no addresses):":
        "จะเปิด dashboard ที่เมนู “แจ้งปัญหา” (ถ้าขึ้นหน้า login ให้ login ก่อน) พิมพ์ว่าเกิดอะไรขึ้นแล้วกดส่ง — "
        "ทีมพัฒนาจะตอบกลับในแชทนั้น\n\nแนบข้อมูลเหล่านี้ไปด้วยเพื่อให้แก้ได้เร็วขึ้น "
        "(ไม่มีรหัสผ่าน ไม่มีที่อยู่ IP):",
    "Open the dashboard": "เปิด dashboard",
    "Cancel": "ยกเลิก",
    "Quit  (Ctrl+Q)": "ออก  (Ctrl+Q)",
    "Language / ภาษา": "ภาษา / Language",
    "Automatic (Windows)": "อัตโนมัติ (ตาม Windows)",
    "Receiver name": "ชื่อตัวรับภาพ",
    "Name of this PC in Screen Mirroring:": "ชื่อของ PC นี้ในเมนูการสะท้อนหน้าจอ:",
    "Screenshot": "แคปหน้าจอ",
    "Screenshots": "ภาพแคป",
    "No active mirroring.": "ยังไม่มีภาพจาก iPhone",
    "Could not create the folder: {err}": "สร้างโฟลเดอร์ไม่ได้: {err}",
    "Saved:\n{path}": "บันทึกแล้ว:\n{path}",
    "Could not save the file.": "บันทึกไฟล์ไม่ได้",
    "Could not open the folder: {err}": "เปิดโฟลเดอร์ไม่ได้: {err}",
    "Cable connection": "ต่อด้วยสาย",
    "Now: no direct connection to the iPhone.": "ตอนนี้: ยังไม่ได้ต่อตรงกับ iPhone",
    "by cable": "ด้วยสาย",
    "through the iPhone hotspot": "ผ่านฮอตสปอตของ iPhone",
    "Now: the iPhone is connected {how} ({iface}, PC IP {ip}).": "ตอนนี้: iPhone ต่ออยู่{how} ({iface}, IP ของ PC {ip})",
    "USB_HELP": (
        "สะท้อนจอผ่านสาย — ไม่ต้องใช้ Wi‑Fi หรือเราเตอร์:\n\n"
        "1. บน iPhone: การตั้งค่า → ฮอตสปอตส่วนบุคคล → “อนุญาตให้ผู้อื่นเข้าร่วม” — เปิด\n"
        "2. เสียบสาย iPhone เข้ากับ PC แล้วกด “เชื่อถือ” บน iPhone\n"
        "3. รอสักครู่ หน้าต่างจะขึ้นป้าย “USB” สีเขียว\n"
        "4. ศูนย์ควบคุม → การสะท้อนหน้าจอ → “{name}”\n\n"
        "ต้องมีไดรเวอร์ของ Apple (แอป Apple Devices จาก Microsoft Store หรือ iTunes)\n"
        "ภาพวิ่งผ่านสายโดยตรง ไม่เปลืองเน็ตมือถือ ถ้า Windows เริ่มใช้เน็ตจาก iPhone "
        "ให้ปิดข้อมูลมือถือบน iPhone\n\n"
        "{state}"
    ),
    "UxPlay log title": "บันทึกของ UxPlay",
    # --- OBS / preview ---------------------------------------------------------------
    "OBS Browser Source": "OBS Browser Source",
    "Copy OBS link": "คัดลอกลิงก์ OBS",
    "Open the link in a browser": "เปิดลิงก์ในเบราว์เซอร์",
    "Link copied: {url}\nIn OBS: Sources → + → Browser → paste it as URL, width 1080, height 1920.":
        "คัดลอกลิงก์แล้ว: {url}\nใน OBS: Sources → + → Browser → วางเป็น URL, กว้าง 1080 สูง 1920",
    "OBS link is off (port {port} is busy).": "ลิงก์ OBS ใช้ไม่ได้ (พอร์ต {port} ถูกใช้อยู่)",
    "Preview: show 1 minute after connecting, then hide (lightest)":
        "ภาพตัวอย่าง: โชว์ 1 นาทีหลังต่อ แล้วซ่อน (เบาสุด)",
    "Preview: always show": "ภาพตัวอย่าง: แสดงตลอด",
    "Preview: never show": "ภาพตัวอย่าง: ไม่แสดง",
    "Show preview for 1 minute": "แสดงภาพตัวอย่าง 1 นาที",
    "Decoder: {name}": "ตัวถอดภาพ: {name}",
    "graphics card": "การ์ดจอ",
    "processor (CPU)": "หน่วยประมวลผล (CPU)",
    "Use the graphics card (needs restart of mirroring)": "ใช้การ์ดจอถอดภาพ (มีผลเมื่อต่อใหม่)",
    "Frame rate": "อัตราเฟรม",
    "Frame rate: {fps} fps": "อัตราเฟรม: {fps} fps",
    "30 fps — light (recommended)": "30 fps — เบาเครื่อง (แนะนำ)",
    "60 fps — smoothest, for a strong PC": "60 fps — ลื่นที่สุด สำหรับคอมแรง",
    "Frame rate set to {fps} fps.\nStart Screen Mirroring on the iPhone again to apply it.":
        "ตั้งอัตราเฟรมเป็น {fps} fps แล้ว\nเปิดการสะท้อนหน้าจอบน iPhone ใหม่อีกครั้งเพื่อให้มีผล",
    "Late OBS viewer: re-encoding with {name}": "มีหน้า OBS เปิดทีหลัง: เข้ารหัสภาพใหม่ด้วย {name}",
    # --- phone window --------------------------------------------------------------
    "Natural titanium": "ไทเทเนียมธรรมชาติ",
    "Black titanium": "ไทเทเนียมดำ",
    "White titanium": "ไทเทเนียมขาว",
    "Blue titanium": "ไทเทเนียมน้ำเงิน",
    "Always on top": "อยู่บนสุดเสมอ",
    "Size: {pct}%": "ขนาด: {pct}%",
    "Fit screen height": "พอดีความสูงจอ",
    "Larger  (Ctrl +)": "ใหญ่ขึ้น  (Ctrl +)",
    "Smaller  (Ctrl −)": "เล็กลง  (Ctrl −)",
    "Default  (Ctrl 0)": "ค่าเริ่มต้น  (Ctrl 0)",
    "Drag an edge of the phone or Ctrl + wheel": "ลากขอบโทรศัพท์ หรือ Ctrl + ลูกกลิ้งเมาส์",
    "Frame color": "สีกรอบ",
    "Minimize  (double-click)": "ย่อหน้าต่าง  (ดับเบิลคลิก)",
    # --- plain window --------------------------------------------------------------
    "Fit (keep proportions)": "พอดีกรอบ (คงสัดส่วน)",
    "Stretch to the whole window": "ยืดเต็มหน้าต่าง",
    "Fill (crop the edges)": "เต็มกรอบ (ตัดขอบ)",
    "Mirror  (Ctrl+M)": "กลับด้านซ้ายขวา  (Ctrl+M)",
    "Picture mode": "โหมดภาพ",
    "Full screen  (F11, double-click)": "เต็มจอ  (F11, ดับเบิลคลิก)",
    "Rotate left  (Ctrl+Shift+R)": "หมุนซ้าย  (Ctrl+Shift+R)",
    "Rotate right  (Ctrl+R)": "หมุนขวา  (Ctrl+R)",
    "Fit window to picture": "ปรับหน้าต่างให้พอดีภาพ",
    "Screenshots folder": "โฟลเดอร์ภาพแคป",
    "Phone frame view": "มุมมองกรอบโทรศัพท์",
    "More": "เพิ่มเติม",
    "Full screen  (F11)": "เต็มจอ  (F11)",
    "Picture": "ภาพ",
    "Reset rotation and mirror": "รีเซ็ตการหมุนและกลับด้าน",
    "Rotation {deg}°": "หมุน {deg}°",
    "Full screen — Esc or double-click to leave": "เต็มจอ — กด Esc หรือดับเบิลคลิกเพื่อออก",
    # --- about -----------------------------------------------------------------------
    "About": "เกี่ยวกับโปรแกรม",
    "Close": "ปิด",
    "iPhone screen and sound on Windows — over Wi‑Fi or cable, with an OBS Browser Source link.":
        "ภาพและเสียงจาก iPhone บน Windows — ผ่าน Wi‑Fi หรือสาย พร้อมลิงก์ Browser Source สำหรับ OBS",
    "Based on": "พัฒนาต่อจาก",
    "Changes in this version": "สิ่งที่แก้ในเวอร์ชันนี้",
    "Thai/English menus, graphics-card decoding, OBS Browser Source.":
        "เมนูไทย/อังกฤษ ถอดภาพด้วยการ์ดจอ และลิงก์ Browser Source สำหรับ OBS",
    "License GPL-3.0-or-later. Uses UxPlay, GStreamer, FFmpeg, Qt.<br>AirPlay and iPhone are trademarks of Apple Inc. Not affiliated with Apple.":
        "สัญญาอนุญาต GPL-3.0-or-later ใช้ UxPlay, GStreamer, FFmpeg, Qt<br>AirPlay และ iPhone เป็นเครื่องหมายการค้าของ Apple Inc. โปรแกรมนี้ไม่เกี่ยวข้องกับ Apple",
    # --- receiver log ------------------------------------------------------------------
    "UxPlay not found. Run setup\\install.ps1 (see README).": "ไม่พบ UxPlay ให้รัน setup\\install.ps1 (ดู README)",
    "Network announcement: {how}": "ประกาศตัวในเครือข่าย: {how}",
    "UxPlay exited (code {code}).": "UxPlay ปิดตัว (รหัส {code})",
    "UxPlay process error: {err}": "UxPlay มีข้อผิดพลาด: {err}",
    "Bonjour (all network interfaces)": "Bonjour (ทุกการ์ดเครือข่าย)",
    "built-in mDNS (Bonjour variant not found)": "mDNS ในตัว (ไม่พบตัวที่ใช้ Bonjour)",
    "built-in mDNS": "mDNS ในตัว",
    "Direct connection to the iPhone: {link}": "ต่อตรงกับ iPhone: {link}",
    "Direct connection to the iPhone: none": "ต่อตรงกับ iPhone: ไม่มี",
    "Port {port} is busy or unavailable: {err}": "พอร์ต {port} ถูกใช้อยู่หรือใช้ไม่ได้: {err}",
    "Socket error: {err}": "ข้อผิดพลาดของ socket: {err}",
    "Video stream error: {err}": "ภาพจาก iPhone มีปัญหา: {err}",
    "OBS link: {url}": "ลิงก์ OBS: {url}",
    # --- updates -----------------------------------------------------------------------
    "Updates": "อัปเดตโปรแกรม",
    "Check for updates now": "ตรวจหาอัปเดตตอนนี้",
    "Check automatically": "ตรวจอัตโนมัติ (ตอนเปิดและทุก 6 ชั่วโมง)",
    "⬆ Update to version {version}…": "⬆ อัปเดตเป็นเวอร์ชัน {version}…",
    "Update Obsidian Mirror": "อัปเดต Obsidian Mirror",
    "A new version is ready: {new}": "มีเวอร์ชันใหม่: {new}",
    "You have {old} · download {mb} MB": "เวอร์ชันที่ใช้อยู่ {old} · ดาวน์โหลด {mb} MB",
    "This update is required: the old version no longer works properly.":
        "จำเป็นต้องอัปเดต: เวอร์ชันเดิมใช้งานได้ไม่ถูกต้องแล้ว",
    "Your settings are kept. The program closes, installs and opens again by itself (Windows may ask for permission).":
        "การตั้งค่าเดิมอยู่ครบ โปรแกรมจะปิด ติดตั้ง แล้วเปิดใหม่เอง (Windows อาจถามสิทธิ์ ให้กด “ใช่”) ไม่ต้องถอนการติดตั้ง",
    "Skip this version": "ข้ามเวอร์ชันนี้",
    "Later": "ไว้ทีหลัง",
    "Update now": "อัปเดตเลย",
    "Try again": "ลองอีกครั้ง",
    "Running from source code: update with git pull, or install the new installer.":
        "กำลังรันจากซอร์สโค้ด: อัปเดตด้วย git pull หรือลงตัวติดตั้งใหม่",
    "A phone is mirroring now. Updating stops the picture in OBS for about a minute. Update anyway?":
        "มือถือกำลังส่งภาพอยู่ ถ้าอัปเดตตอนนี้ภาพใน OBS จะหายราว 1 นาที อัปเดตเลยไหม?",
    "Downloading…": "กำลังดาวน์โหลด…",
    "Downloading… {done} / {total} MB": "กำลังดาวน์โหลด… {done} / {total} MB",
    "Checked ✓ Installing — the program will close and open again.":
        "ตรวจไฟล์ผ่าน ✓ กำลังติดตั้ง — โปรแกรมจะปิดแล้วเปิดใหม่เอง",
    "You have the latest version ({version}).": "ใช้เวอร์ชันล่าสุดอยู่แล้ว ({version})",
    "Could not check for updates: {error}": "ตรวจหาอัปเดตไม่ได้: {error}",
    "The update note is damaged.": "ข้อมูลอัปเดตเสียหาย",
    "The update note is not signed by Obsidian Stream Hub.":
        "ข้อมูลอัปเดตไม่มีลายเซ็นของ Obsidian Stream Hub (ไม่ติดตั้ง เพื่อความปลอดภัย)",
    "Could not reach the update server.": "ติดต่อเซิร์ฟเวอร์อัปเดตไม่ได้",
    "The update address must use https.": "ที่อยู่อัปเดตต้องเป็น https",
    "The download stopped. Check the internet and try again.": "ดาวน์โหลดหยุดกลางทาง ตรวจอินเทอร์เน็ตแล้วลองอีกครั้ง",
    "The download does not match the update note.": "ไฟล์ที่ดาวน์โหลดไม่ตรงกับข้อมูลอัปเดต (ลบทิ้งแล้ว ไม่ติดตั้ง)",
    "Windows did not start the installer (permission refused?).": "Windows ไม่เปิดตัวติดตั้ง (ไม่ได้กดอนุญาตหรือเปล่า?)",
    "Updates install only on Windows.": "อัปเดตได้เฉพาะบน Windows",
    "Cancelled.": "ยกเลิกแล้ว",
    # --- virtual camera ---------------------------------------------------------------
    "Virtual camera: {state}": "กล้องเสมือน: {state}",
    "Virtual camera": "กล้องเสมือน",
    "Off": "ปิด",
    "1280×720 landscape (most apps)": "1280×720 แนวนอน (แอปส่วนใหญ่)",
    "1920×1080 landscape": "1920×1080 แนวนอน",
    "1080×1920 portrait (TikTok LIVE Studio)": "1080×1920 แนวตั้ง (TikTok LIVE Studio)",
    "How to use the camera…": "วิธีใช้กล้องเสมือน…",
    "The camera is not installed (run native\\register_camera.ps1).":
        "ยังไม่ได้ติดตั้งกล้อง (รัน native\\register_camera.ps1)",
    "The phone picture becomes a webcam called “Obsidian Mirror Camera”.\n\n"
    "TikTok LIVE Studio: Add source → Camera → Obsidian Mirror Camera (pick 1080×1920 portrait here).\n"
    "Discord / Zoom / Meet: choose it as the camera in video settings.\n\n"
    "Picture only — the sound does not go through the camera.\n"
    "Using OBS? The OBS link is lighter and sharper than the camera.":
        "ภาพจากมือถือจะกลายเป็นกล้องเว็บแคมชื่อ “Obsidian Mirror Camera”\n\n"
        "TikTok LIVE Studio: เพิ่มแหล่งที่มา → กล้อง → Obsidian Mirror Camera (ที่นี่เลือก 1080×1920 แนวตั้ง)\n"
        "Discord / Zoom / Meet: เลือกเป็นกล้องในการตั้งค่าวิดีโอ\n\n"
        "ส่งได้แต่ภาพ — เสียงไม่ผ่านกล้อง\n"
        "ใช้ OBS อยู่? ลิงก์ OBS เบากว่าและคมกว่ากล้อง",
    "Waiting for the phone…": "รอภาพจากมือถือ…",
    "Virtual camera could not start: {err}": "เปิดกล้องเสมือนไม่ได้: {err}",
    "Virtual camera on: {w}×{h}, {fps} fps": "เปิดกล้องเสมือนแล้ว: {w}×{h}, {fps} fps",
    "the camera is in use by another program": "มีโปรแกรมอื่นใช้กล้องนี้อยู่ (เปิด Obsidian Mirror ซ้อนกันอยู่หรือเปล่า?)",
    # --- phone camera (clean picture) ---------------------------------------------------
    "Picture: the mirrored phone screen": "ภาพจาก: หน้าจอมือถือที่สะท้อนมา",
    "Picture: phone camera only, no buttons (scan a QR)": "ภาพจาก: กล้องมือถือล้วน ไม่มีปุ่ม (สแกน QR)",
    "Show the QR for the phone…": "แสดง QR ให้มือถือสแกน…",
    "Phone camera (clean picture)": "กล้องมือถือ (ภาพล้วน)",
    "Scan with the phone": "สแกนด้วยมือถือ",
    "1. Connect the phone to the same Wi‑Fi as this PC\n"
    "2. Scan this code with the phone camera and open the page\n"
    "3. Tap “▶ Start camera” and allow the camera\n"
    "Keep the page open and the screen on while you are live.":
        "1. ต่อมือถือเข้า Wi‑Fi เดียวกับคอมเครื่องนี้\n"
        "2. ใช้กล้องมือถือสแกนโค้ดนี้แล้วเปิดหน้าเว็บ\n"
        "3. แตะ “▶ เปิดกล้อง” แล้วกดอนุญาตให้ใช้กล้อง\n"
        "ระหว่างไลฟ์ให้เปิดหน้านั้นค้างไว้และอย่าล็อกจอ",
    "Connecting to the server…": "กำลังต่อ server…",
    "Cannot reach the server. Check the internet on this PC.": "ต่อ server ไม่ได้ ตรวจอินเทอร์เน็ตของคอมเครื่องนี้",
    "Phone camera connected ✓": "ต่อกล้องมือถือแล้ว ✓",
    "The phone camera is off.": "ปิดกล้องมือถืออยู่",
    "Phone camera: waiting for the phone…": "กล้องมือถือ: รอมือถือ…",
    "Only the camera picture is sent — no buttons, no status bar. iPhone and Android.":
        "ส่งมาแค่ภาพจากกล้อง ไม่มีปุ่ม ไม่มีแถบสถานะ ใช้ได้ทั้ง iPhone และ Android",
    "Copy link": "คัดลอกลิงก์",
    "Link copied.": "คัดลอกลิงก์แล้ว",
}
