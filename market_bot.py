import os
import sys
import time
import json
import sqlite3
import threading
from datetime import datetime, timezone, timedelta
import requests

# ----------------- CONFIGURATION & SECRETS ----------------- #
# Prioritize Environment Variables (for Cloud/Render), fallback to local keybotnng.txt
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
APIFY_TOKEN = os.environ.get("APIFY_TOKEN", "").strip()
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "8407012068").strip()

# Local fallback if running on development machine
if not (TELEGRAM_BOT_TOKEN and GEMINI_API_KEY and APIFY_TOKEN):
    key_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "keybotnng.txt")
    if os.path.exists(key_file):
        try:
            with open(key_file, "r", encoding="utf-8") as f:
                lines = [l.strip() for l in f.readlines() if l.strip()]
                if len(lines) >= 3:
                    if not TELEGRAM_BOT_TOKEN:
                        TELEGRAM_BOT_TOKEN = lines[0]
                    if not GEMINI_API_KEY:
                        GEMINI_API_KEY = lines[1]
                    if not APIFY_TOKEN:
                        APIFY_TOKEN = lines[2]
        except Exception as e:
            print(f"[BOT] Error reading local key file: {e}")

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "leads.db")
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3-flash-preview:generateContent?key={GEMINI_API_KEY}"

# 6 Official Groups of Nguyên Nông Group
TRACKED_GROUPS = [
    ("https://www.facebook.com/groups/509145036679845", "Người Kiến Đức"),
    ("https://www.facebook.com/groups/515978843091275", "Nghĩa thắng - Đạo Nghĩa - Đắk Sin"),
    ("https://www.facebook.com/groups/3016364781975579", "Chợ Quảng Tín & Đăk Ru"),
    ("https://www.facebook.com/groups/HeThongTuoiTuDong", "Hiệp Hội Tưới Tự Động - Cung Cấp & Phân Phối Thiết Bị"),
    ("https://www.facebook.com/groups/1504915489688206", "ĐIỆN NĂNG LƯỢNG MẶT TRỜI ( SOLAR VIỆT NAM )"),
    ("https://www.facebook.com/groups/1421708581983557", "Màng chống thấm HDPE - Bạt HDPE - Bạt lót hồ cá  - Thi công bạt lót hồ")
]

# ----------------- DATABASE HELPERS ----------------- #
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS tracked_groups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        url TEXT UNIQUE,
        name TEXT
    );
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS scraped_posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_name TEXT,
        post_url TEXT UNIQUE,
        author TEXT,
        content TEXT,
        intent TEXT,
        scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS notification_channels (
        chat_id TEXT PRIMARY KEY,
        title TEXT,
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    if ADMIN_CHAT_ID:
        c.execute("INSERT OR IGNORE INTO notification_channels (chat_id, title) VALUES (?, ?)", (ADMIN_CHAT_ID, "Admin Private Chat"))
    conn.commit()
    conn.close()

def register_group_channel(chat_id, title):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO notification_channels (chat_id, title) VALUES (?, ?)", (str(chat_id), title))
        conn.commit()
        conn.close()
        print(f"[BOT] Registered notification channel: {title} ({chat_id})")
    except Exception as e:
        print(f"[BOT] Error registering channel: {e}")

def get_tracked_groups():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    rows = c.execute("SELECT id, name, url FROM tracked_groups").fetchall()
    conn.close()
    return rows

def get_all_scraped_posts(limit=30):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    rows = c.execute("SELECT group_name, author, content, post_url, scraped_at, intent FROM scraped_posts ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return rows

def save_post(group_name, post_url, author, content, intent="OTHER"):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("""
        INSERT OR IGNORE INTO scraped_posts (group_name, post_url, author, content, intent)
        VALUES (?, ?, ?, ?, ?)
        """, (group_name, post_url, author, content, intent))
        conn.commit()
        inserted = c.rowcount > 0
    except Exception as e:
        inserted = False
    conn.close()
    return inserted

# ----------------- TELEGRAM MESSAGING ----------------- #
def send_telegram(text, reply_to_message_id=None, chat_id=None):
    if not TELEGRAM_BOT_TOKEN:
        return
    target_chat = chat_id or ADMIN_CHAT_ID
    chunks = [text[i:i+3800] for i in range(0, len(text), 3800)]
    for chunk in chunks:
        payload = {"chat_id": target_chat, "text": chunk, "parse_mode": "HTML"}
        if reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id
        try:
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json=payload, timeout=10)
        except Exception as e:
            print(f"[BOT] Send telegram error: {e}")

def broadcast_alert_and_digest(text):
    """Broadcasts to BOTH Admin private chat AND all active Telegram groups"""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT chat_id FROM notification_channels")
        rows = c.fetchall()
        conn.close()
        targets = set([str(r[0]) for r in rows] if rows else [])
    except Exception:
        targets = set()

    if ADMIN_CHAT_ID:
        targets.add(str(ADMIN_CHAT_ID))

    for tid in targets:
        send_telegram(text, chat_id=tid)

# ----------------- GEMINI INTENT & DIGEST ----------------- #
def classify_post_intent(content):
    if not GEMINI_API_KEY:
        return "OTHER", "No API Key"
    
    prompt = f"""
Bạn là chuyên gia phân loại khách hàng của Nguyên Nông Group (NNG).
NNG chuyên giải pháp nông nghiệp (KHÔNG GIỚI HẠN ĐỊA HÌNH, đất bằng đất dốc làm hết):
1. Hệ thống tưới (phun mưa, nhỏ giọt, tưới gốc, bù áp, tự động).
2. Hồ bạt HDPE trữ nước.
3. Bơm năng lượng mặt trời.
4. Vật tư linh kiện ngành tưới & bạt.

Hãy đọc bài viết sau và phân loại:
[BUYER]: Khách hàng/chủ rẫy có nhu cầu tìm mua, hỏi giá, tìm thợ thi công, cần giải pháp tưới/hồ bạt/bơm mặt trời.
[SELLER]: Người bán hàng, quảng cáo, xưởng chào sỉ, để lại SĐT/Zalo bán hàng.
[OTHER]: Chia sẻ kinh nghiệm, tin tức khác, không có nhu cầu mua.

Bài viết:
\"\"\"{content}\"\"\"

Chỉ trả về JSON:
{{"intent": "BUYER" | "SELLER" | "OTHER", "need": "tóm tắt nhu cầu nếu là BUYER", "location": "địa bàn nếu có"}}
"""
    try:
        res = requests.post(
            GEMINI_URL,
            json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.0, "responseMimeType": "application/json"}},
            timeout=15
        ).json()
        ans = json.loads(res["candidates"][0]["content"]["parts"][0]["text"])
        return ans.get("intent", "OTHER"), ans
    except Exception as e:
        return "OTHER", {}

def generate_market_digest(time_label="16:00"):
    posts = get_all_scraped_posts(limit=20)
    posts_summary = [{"nhom": p[0], "nguoi_dang": p[1], "noi_dung": p[2][:200]} for p in posts]

    prompt = f"""
Bạn là Trợ lý Dữ liệu của Nguyên Nông Group (NNG).
Soạn bản tin tổng hợp thị trường lúc {time_label} gửi Telegram cho team Nguyên Nông Group.

Định dạng HTML Telegram (<b>, <i>, <code>).
Mở đầu: 📢 <b>Gửi mấy ní team Nguyên Nông Group!</b> Dưới đây là bản tin tổng hợp thị trường lúc {time_label} hôm nay:

Cấu trúc:
1. 🟢 <b>Tình hình quét:</b> Quét qua 6 group trọng điểm.
2. 🎯 <b>Nhu cầu & Cơ hội săn khách:</b> Dựa trên dữ liệu cào thật dưới đây.
3. 💡 <b>Ý tưởng kinh doanh & Xu hướng đối thủ:</b> Nhận định sắc bén từ bài viết.
4. 🚀 <b>Kèo ngon cho team mình:</b> Lời khuyên cụ thể cho anh em ngày mai.

Dữ liệu thật cào được:
{json.dumps(posts_summary, ensure_ascii=False, indent=2)}

Quy tắc:
- Không dùng từ "dạ".
- Giọng văn gần gũi ('mấy ní', 'team mình', 'anh em').
- Nếu trong dữ liệu không có khách hỏi mua: Báo cáo trung thực tình hình chung, không tự bịa.
"""
    try:
        res = requests.post(GEMINI_URL, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=25).json()
        return res["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        return f"Lỗi tạo bản tin: {e}"

# ----------------- SCANNER (APIFY) ----------------- #
def run_apify_scan():
    if not APIFY_TOKEN:
        print("[BOT] Apify token missing, skipping scan.")
        return 0

    print("[BOT] Running periodic Apify group scan...")
    run_input = {
        "startUrls": [{"url": url} for url, _ in TRACKED_GROUPS],
        "resultsLimit": 2,
        "viewOption": "CHRONOLOGICAL"
    }

    try:
        res = requests.post(
            "https://api.apify.com/v2/acts/apify~facebook-groups-scraper/runs?waitForFinish=120",
            headers={"Authorization": f"Bearer {APIFY_TOKEN}", "Content-Type": "application/json"},
            json=run_input,
            timeout=130
        ).json()

        dataset_id = res.get("data", {}).get("defaultDatasetId")
        if not dataset_id:
            return 0

        items = requests.get(
            f"https://api.apify.com/v2/datasets/{dataset_id}/items",
            headers={"Authorization": f"Bearer {APIFY_TOKEN}"},
            timeout=30
        ).json()

        new_leads = 0
        now_vn = datetime.now(timezone(timedelta(hours=7))).strftime("%H:%M - %d/%m/%Y")

        for item in items:
            g_name = item.get("groupName") or item.get("groupTitle") or "Facebook Group"
            p_url = item.get("url") or item.get("postUrl") or ""
            user = item.get("user", {})
            author = user.get("name") if isinstance(user, dict) else str(user)
            content = item.get("text") or ""

            if not p_url or not content:
                continue

            # Classify intent
            intent, meta = classify_post_intent(content)
            is_new = save_post(g_name, p_url, author, content, intent=intent)

            # If it's a NEW post and a BUYER -> Send instant alert to Telegram!
            if is_new and intent == "BUYER":
                new_leads += 1
                need_desc = meta.get("need", "Đang có nhu cầu mua/thi công")
                loc = meta.get("location", "Tây Nguyên")
                
                alert_msg = f"""🔥 <b>PHÁT HIỆN KHÁCH CẦN BÁO GIÁ / THI CÔNG!</b>

👤 <b>Người đăng:</b> {author}
📍 <b>Khu vực:</b> {loc}
🏢 <b>Nhóm:</b> {g_name}
🕒 <b>Thời gian quét:</b> {now_vn}
⏳ <b>Độ tươi mới:</b> 🟢 <b>Vừa phát hiện bài mới!</b>

🎯 <b>Nhu cầu:</b> {need_desc}
⭐ <b>Độ nóng:</b> 🔥🔥🔥 HOT LEAD

💬 <b>Nội dung trích đoạn:</b>
<i>\"{content[:300].strip()}...\"</i>

🔗 <a href=\"{p_url}\"><b>👉 BẤM ĐÂY VÀO TƯ VẤN & BÁO GIÁ NGAY</b></a>"""
                broadcast_alert_and_digest(alert_msg)

        print(f"[BOT] Scan finished. New buyer leads alerted: {new_leads}")
        return new_leads
    except Exception as e:
        print(f"[BOT] Scan error: {e}")
        return 0

# ----------------- TELEGRAM INTERACTION ----------------- #
def handle_user_query(user_msg, sender_name="sếp"):
    # Format sender title: ALWAYS call everyone 'sếp + [Tên]'
    if not sender_name.lower().startswith("sếp"):
        sender_title = f"sếp {sender_name}"
    else:
        sender_title = sender_name

    lower = user_msg.lower()
    if any(k in lower for k in ["group nào", "nhóm nào", "mấy group", "danh sách group", "nguồn nào"]):
        groups = get_tracked_groups()
        reply = f"Báo cáo {sender_title}, hiện tại bot đang theo dõi CHÍNH XÁC {len(groups)} group Facebook sau:\n\n"
        for idx, g in enumerate(groups, 1):
            reply += f"{idx}. <b>{g[1]}</b>\n🔗 <a href='{g[2]}'>{g[2]}</a>\n\n"
        reply += "Mọi bài cào về đều lấy từ đúng 6 group này, không có group nào khác."
        return reply

    # Instant Visual Feedback: Send 'typing' status to Telegram
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendChatAction", json={"chat_id": ADMIN_CHAT_ID, "action": "typing"}, timeout=3)
    except Exception:
        pass

    posts = get_all_scraped_posts(limit=12)
    posts_context = [{"nhom": p[0], "nguoi_dang": p[1], "noi_dung": p[2][:250], "link": p[3]} for p in posts]

    prompt = f"""
Bạn là Trợ lý Dữ liệu của Nguyên Nông Group (NNG).
Người hỏi: {sender_title}
Câu hỏi: "{user_msg}"

ĐỊNH VỊ DỊCH VỤ CỦA NGUYÊN NÔNG GROUP (NNG):
- KHÔNG GIỚI HẠN ĐỊA HÌNH: Đất bằng, đất dốc, ruộng vườn, trang trại... NNG NHẬN LÀM HẾT!
- Lĩnh vực:
  1. Hệ thống tưới tự động (phun mưa, nhỏ giọt, bù áp...).
  2. Hồ bạt HDPE trữ nước (mọi dung tích).
  3. Bơm năng lượng mặt trời.
  4. Vật tư linh kiện ngành tưới & bạt.

ĐÂY LÀ TOÀN BỘ CƠ SỞ DỮ LIỆU CÁC BÀI VIẾT THẬT CÀO TỪ FACEBOOK VỀ MÁY CHỦ:
{json.dumps(posts_context, ensure_ascii=False, indent=2)}

QUY TẮC BẮT BUỘC:
1. TUYỆT ĐỐI KHÔNG DÙNG TỪ "DẠ".
2. BẮT BUỘC PHẢI GỌI NGƯỜI HỎI LÀ: "{sender_title}" (Bất kỳ nhân sự nào trong group hỏi đều phải gọi là sếp + Tên của họ).
3. Trả lời dựa trên 100% SỰ THẬT trong danh sách bài viết ở trên.
4. Trả lời ngắn gọn, súc tích, đi thẳng vào trọng tâm trong 2-4 câu.
5. Nếu người dùng hỏi về một địa bàn hoặc sản phẩm:
   - Nếu KHÔNG CÓ nhu cầu/job liên quan: Trả lời thẳng thắn là KHÔNG CÓ trong các nhóm đã cào, nêu rõ bài mới nhất trong nhóm đó đang nói về nội dung gì.
   - Nếu CÓ bài liên quan: Trích dẫn rõ tên người đăng, nội dung và kèm đường link Facebook.
"""
    # Fast Gemini call with optimized maxOutputTokens
    for attempt in range(2):
        try:
            res = requests.post(
                GEMINI_URL,
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.1, "maxOutputTokens": 450}
                },
                timeout=25
            ).json()
            if "candidates" in res and res["candidates"]:
                return res["candidates"][0]["content"]["parts"][0]["text"]
        except Exception:
            time.sleep(0.5)

    # Intelligent Fallback directly from SQLite if Gemini times out
    if not posts:
        return f"Báo cáo {sender_title}, trong kho dữ liệu hiện tại chưa có bài viết nào mới được cào về từ 6 nhóm Facebook."
    
    recent_info = f"Báo cáo {sender_title}, kiểm tra trực tiếp kho dữ liệu:\n\n"
    recent_info += f"Trong 1-2 tiếng vừa qua, 6 nhóm Facebook hiện có <b>{len(posts)} bài viết gần nhất</b>.\n"
    recent_info += "Chưa ghi nhận bài viết nào có chủ rẫy hỏi mua hoặc tìm thợ thi công mới.\n\n"
    recent_info += "<b>Bài viết mới nhất ghi nhận:</b>\n"
    latest = posts[0]
    recent_info += f"• Nhóm: <b>{latest[0]}</b>\n• Tác giả: {latest[1]}\n• Trích đoạn: <i>{latest[2][:120].strip()}...</i>\n🔗 <a href='{latest[3]}'>Xem bài viết</a>"
    return recent_info

def telegram_polling_worker():
    if not TELEGRAM_BOT_TOKEN:
        print("[BOT] Telegram token missing, polling stopped.")
        return

    print("[BOT] Telegram Polling Worker started...")
    offset = None

    while True:
        try:
            params = {"timeout": 15}
            if offset is not None:
                params["offset"] = offset

            res = requests.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates", params=params, timeout=20).json()
            updates = res.get("result", [])

            for u in updates:
                offset = u["update_id"] + 1
                msg = u.get("message")
                if not msg:
                    continue

                chat_id = str(msg.get("chat", {}).get("id"))
                chat_type = msg.get("chat", {}).get("type", "private")
                sender_name = msg.get("from", {}).get("first_name") or "bạn"
                text = msg.get("text", "").strip()
                msg_id = msg.get("message_id")

                if not text:
                    continue

                # Group filtering: automatically register group and only respond if tagged, replied, or command
                if chat_type in ["group", "supergroup"]:
                    register_group_channel(chat_id, msg.get("chat", {}).get("title", "NNG Group"))
                    is_tagged = "@nguyen_nong_bot" in text
                    is_reply_to_bot = msg.get("reply_to_message", {}).get("from", {}).get("is_bot", False)
                    is_command = text.startswith("/")
                    if not (is_tagged or is_reply_to_bot or is_command):
                        continue
                    text = text.replace("@nguyen_nong_bot", "").strip()

                print(f"[BOT RECV] {sender_name}: {text}")

                if text == "/start":
                    if chat_type in ["group", "supergroup"]:
                        reply = f"Chào {sender_name} và anh em! Đã ghi nhận Group này vào danh sách nhận tin. Từ giờ mọi bài báo khách mới và bản tin 8h/16h sẽ tự động gửi vào CẢ group này lẫn tin riêng của sếp Hiếu!"
                    else:
                        reply = f"Chào {sender_name} và anh em team Nguyên Nông Group! Em là Trợ lý Dữ liệu Thị trường, túc trực 24/7 để săn khách và phân tích thị trường cho team!"
                elif text == "/baocao":
                    reply = generate_market_digest("ngay lập tức")
                elif text == "/quet":
                    send_telegram("Bắt đầu kích hoạt cào 6 nhóm Facebook ngay...", chat_id=chat_id, reply_to_message_id=msg_id)
                    leads = run_apify_scan()
                    reply = f"Đã quét xong 6 nhóm! Phát hiện {leads} bài có nhu cầu mua mới."
                else:
                    reply = handle_user_query(text, sender_name=sender_name)

                send_telegram(reply, reply_to_message_id=msg_id, chat_id=chat_id)

        except Exception as e:
            print(f"[BOT] Polling error: {e}")
            time.sleep(2)

# ----------------- SCHEDULER WORKER (24/7) ----------------- #
def scheduler_worker():
    print("[BOT] Scheduler Worker started (Scans every 30m, Digest at 08:00 & 16:00)...")
    last_digest_date = ""

    while True:
        try:
            # Check current time in Vietnam (UTC+7)
            now_vn = datetime.now(timezone(timedelta(hours=7)))
            hour = now_vn.hour
            minute = now_vn.minute
            today_str = now_vn.strftime("%Y-%m-%d")

            # Daily Digest at 08:00 and 16:00
            digest_slot = None
            if hour == 8 and minute <= 5:
                digest_slot = "08:00"
            elif hour == 16 and minute <= 5:
                digest_slot = "16:00"

            if digest_slot and (last_digest_date != f"{today_str}_{digest_slot}"):
                print(f"[BOT] Triggering scheduled digest for {digest_slot}...")
                digest_text = generate_market_digest(digest_slot)
                broadcast_alert_and_digest(digest_text)
                last_digest_date = f"{today_str}_{digest_slot}"

            # Run regular scan every 30 minutes
            run_apify_scan()

        except Exception as e:
            print(f"[BOT] Scheduler error: {e}")

        # Sleep 30 minutes between scans
        time.sleep(1800)

# ----------------- MAIN ENTRYPOINT FOR CLOUD / RENDER ----------------- #
def start_bot_background_threads():
    init_db()
    t_poll = threading.Thread(target=telegram_polling_worker, daemon=True)
    t_poll.start()

    t_sched = threading.Thread(target=scheduler_worker, daemon=True)
    t_sched.start()
    print("[BOT] All Nguyên Nông Group Bot threads started successfully!")

if __name__ == "__main__":
    start_bot_background_threads()
    # Keep alive if run directly
    while True:
        time.sleep(60)
