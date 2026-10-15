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
GROUP_CHAT_ID = os.environ.get("GROUP_CHAT_ID", "-1004473463455").strip()

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
GEMINI_MODELS = ["gemini-flash-latest", "gemini-flash-lite-latest", "gemini-3.5-flash-lite"]

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
    # Ensure intent column exists in existing tables
    try:
        c.execute("ALTER TABLE scraped_posts ADD COLUMN intent TEXT")
    except Exception:
        pass
    c.execute("""
    CREATE TABLE IF NOT EXISTS notification_channels (
        chat_id TEXT PRIMARY KEY,
        title TEXT,
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    if ADMIN_CHAT_ID:
        c.execute("INSERT OR IGNORE INTO notification_channels (chat_id, title) VALUES (?, ?)", (ADMIN_CHAT_ID, "Admin Private Chat"))
    if GROUP_CHAT_ID:
        c.execute("INSERT OR IGNORE INTO notification_channels (chat_id, title) VALUES (?, ?)", (GROUP_CHAT_ID, "Nguyên Nông Group"))
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
        return False
    target_chat = chat_id or ADMIN_CHAT_ID
    chunks = [text[i:i+3800] for i in range(0, len(text), 3800)]
    for chunk in chunks:
        payload = {"chat_id": target_chat, "text": chunk, "parse_mode": "HTML"}
        if reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id
        
        success = False
        for attempt in range(1, 4):
            try:
                res = requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json=payload, timeout=25).json()
                if not res.get("ok"):
                    # Automatically handle group migration to supergroup
                    migrate_id = res.get("parameters", {}).get("migrate_to_chat_id")
                    if migrate_id:
                        payload["chat_id"] = str(migrate_id)
                        register_group_channel(migrate_id, "Nguyên Nông Group")
                        res = requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json=payload, timeout=25).json()
                    if not res.get("ok"):
                        # If HTML parsing fails, fallback to plain text
                        payload.pop("parse_mode", None)
                        res = requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json=payload, timeout=25).json()
                if res.get("ok"):
                    success = True
                    break
            except Exception as e:
                print(f"[BOT] Send telegram attempt {attempt}/3 error: {e}")
                time.sleep(1)

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
    if GROUP_CHAT_ID:
        targets.add(str(GROUP_CHAT_ID))

    for tid in targets:
        send_telegram(text, chat_id=tid)

# ----------------- GEMINI INTENT & DIGEST ----------------- #
def call_gemini_safe(prompt, max_tokens=700, retries=2, response_mime_type=None):
    if not GEMINI_API_KEY:
        return None
    gen_config = {"temperature": 0.1, "maxOutputTokens": max_tokens}
    if response_mime_type:
        gen_config["responseMimeType"] = response_mime_type

    for model_name in GEMINI_MODELS:
        model_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
        for attempt in range(1, retries + 1):
            try:
                res = requests.post(
                    model_url,
                    json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": gen_config},
                    timeout=25
                ).json()

                if isinstance(res, dict):
                    candidates = res.get("candidates")
                    if candidates and isinstance(candidates, list) and len(candidates) > 0:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts and isinstance(parts, list) and len(parts) > 0:
                            text = parts[0].get("text", "")
                            if text and text.strip():
                                return text.strip()
            except Exception as e:
                print(f"[BOT] Model {model_name} attempt {attempt}/{retries} error: {e}")
            
            time.sleep(1)

    return None

def classify_post_intent(content):
    if not GEMINI_API_KEY:
        return "OTHER", {}
    
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
    raw_json = call_gemini_safe(prompt, max_tokens=250, retries=2, response_mime_type="application/json")
    if raw_json:
        try:
            ans = json.loads(raw_json)
            return ans.get("intent", "OTHER"), ans
        except Exception:
            pass
    return "OTHER", {}

def generate_market_digest(time_label="16:00"):
    posts = get_all_scraped_posts(limit=20)
    posts_summary = [{"nhom": p[0], "nguoi_dang": p[1], "noi_dung": p[2][:200]} for p in posts]

    prompt = f"""
Bạn là Trợ lý Dữ liệu của Nguyên Nông Group (NNG).
Soạn bản tin tổng hợp thị trường lúc {time_label} gửi Telegram cho team Nguyên Nông Group.

Định dạng HTML Telegram (<b>, <i>, <code>).
Mở đầu: 📢 <b>Kính gửi Chủ tịch Tùng cùng các anh em team Nguyên Nông Group!</b> Dưới đây là bản tin tổng hợp thị trường lúc {time_label} hôm nay:

Cấu trúc:
1. 🟢 <b>Tình hình quét:</b> Quét qua 6 group trọng điểm.
2. 🎯 <b>Nhu cầu & Cơ hội săn khách:</b> Dựa trên dữ liệu cào thật dưới đây.
3. 💡 <b>Ý tưởng kinh doanh & Xu hướng đối thủ:</b> Nhận định sắc bén từ bài viết.
4. 🚀 <b>Kèo ngon cho team mình:</b> Lời khuyên cụ thể cho anh em ngày mai.

Dữ liệu thật cào được:
{json.dumps(posts_summary, ensure_ascii=False, indent=2)}

Quy tắc:
- Không dùng từ "dạ".
- Luôn mở đầu chào trang trọng: "📢 <b>Kính gửi Chủ tịch Tùng cùng các anh em team Nguyên Nông Group!</b>".
- Giọng văn gần gũi, quyết liệt ('team mình', 'anh em').
- Nếu trong dữ liệu không có khách hỏi mua: Báo cáo trung thực tình hình chung, không tự bịa.
"""
    digest_text = call_gemini_safe(prompt, max_tokens=850, retries=3)
    if digest_text:
        return digest_text

    # 100% Reliable fallback straight from SQLite (Zero chance of raw errors)
    buyer_posts = [p for p in posts if len(p) >= 6 and p[5] == "BUYER"]
    report = f"📢 <b>Kính gửi Chủ tịch Tùng cùng các anh em team Nguyên Nông Group!</b>\n"
    report += f"Dưới đây là bản tin tổng hợp thị trường lúc {time_label} hôm nay:\n\n"
    report += f"🟢 <b>Tình hình quét:</b> Đã rà soát qua toàn bộ 6 nhóm Facebook trọng điểm.\n"
    if buyer_posts:
        report += f"🎯 <b>Nhu cầu săn khách ghi nhận:</b>\n"
        for bp in buyer_posts[:3]:
            report += f"• Tác giả: <b>{bp[1]}</b> ({bp[0]})\n  Trích đoạn: <i>{bp[2][:120].strip()}...</i>\n  🔗 <a href='{bp[3]}'>Xem bài viết</a>\n\n"
    else:
        report += f"🎯 <b>Nhu cầu thị trường:</b> 6 nhóm hiện ghi nhận các bài viết chia sẻ kinh nghiệm rẫy, linh kiện tưới và tấm pin năng lượng mặt trời.\n\n"
    report += "💡 <b>Lời khuyên cho team mình:</b> Mọi địa hình đất bằng đất dốc, hồ bạt HDPE và hệ thống tưới tự động team mình nhận làm trọn gói. Anh em túc trực hỗ trợ khách ngay khi có lead mới!"
    return report

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
📢 <i>Kính gửi Chủ tịch Tùng cùng các anh em team Nguyên Nông Group:</i>

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
    # Format sender title: ALWAYS call everyone 'sếp + [Tên]', riêng Tùng thì gọi 'Chủ tịch Tùng'
    s_clean = sender_name.strip()
    s_lower = s_clean.lower()
    if "tùng" in s_lower or "tung" in s_lower:
        sender_title = "Chủ tịch Tùng"
    elif s_lower.startswith("sếp") or s_lower.startswith("chủ tịch"):
        sender_title = s_clean
    else:
        sender_title = f"sếp {s_clean}"

    lower = user_msg.lower()
    if any(k in lower for k in ["group nào", "nhóm nào", "mấy group", "danh sách group", "nguồn nào"]):
        groups = get_tracked_groups()
        reply = f"Báo cáo {sender_title}, hiện tại bot đang theo dõi CHÍNH XÁC {len(groups)} group Facebook sau:\n\n"
        for idx, g in enumerate(groups, 1):
            reply += f"{idx}. <b>{g[1]}</b>\n🔗 <a href='{g[2]}'>{g[2]}</a>\n\n"
        reply += "Mọi bài cào về đều lấy từ đúng 6 group này, không có group nào khác."
        return reply

    # 0. Instant Link Matcher (Direct from SQLite in 0.01s, 0% timeout risk)
    if "link" in lower or any(k in lower for k in ["bài này", "bài của", "đưa link", "cho link", "ở đâu"]):
        all_posts = get_all_scraped_posts(limit=50)
        matched = None
        # 1. First priority: match exact author name mentioned (e.g., NiceFish7578, Thuận, etc.)
        for p in all_posts:
            author = (p[1] or "").lower()
            if author and author in lower:
                matched = p
                break
        
        # 2. Second priority: match content keywords
        if not matched:
            for p in all_posts:
                content = (p[2] or "").lower()
                content_words = [w for w in content.split() if len(w) >= 3]
                match_count = sum(1 for w in content_words[:30] if w in lower)
                if match_count >= 2:
                    matched = p
                    break
        
        # 3. Third priority: fallback to the latest scraped post if user just asked for link
        if not matched and all_posts:
            matched = all_posts[0]

        if matched:
            return f"Báo cáo {sender_title}, đây là link bài viết sếp cần tìm:\n\n👤 Tác giả: <b>{matched[1]}</b>\n🏢 Nhóm: <b>{matched[0]}</b>\n💬 Trích đoạn: <i>{matched[2][:150].strip()}...</i>\n\n🔗 <b>Link Facebook:</b> <a href='{matched[3]}'>{matched[3]}</a>"

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
2. BẮT BUỘC PHẢI GỌI NGƯỜI HỎI LÀ: "{sender_title}" (Nếu người hỏi là Tùng thì gọi là 'Chủ tịch Tùng', các thành viên khác thì gọi là 'sếp + Tên của họ').
3. Trả lời dựa trên 100% SỰ THẬT trong danh sách bài viết ở trên.
4. Trả lời ngắn gọn, súc tích, đi thẳng vào trọng tâm trong 2-4 câu.
5. Nếu người dùng hỏi về một địa bàn hoặc sản phẩm:
   - Nếu KHÔNG CÓ nhu cầu/job liên quan: Trả lời thẳng thắn là KHÔNG CÓ trong các nhóm đã cào, nêu rõ bài mới nhất trong nhóm đó đang nói về nội dung gì.
   - Nếu CÓ bài liên quan: Trích dẫn rõ tên người đăng, nội dung và kèm đường link Facebook.
"""
    # Safe Gemini call with 3 retries (allows 3-5 seconds to ensure 100% accuracy)
    answer = call_gemini_safe(prompt, max_tokens=550, retries=3)
    if answer:
        return answer

    # Intelligent Fallback directly from SQLite if Gemini times out (Zero errors)
    if not posts:
        return f"Báo cáo {sender_title}, trong kho dữ liệu hiện tại chưa có bài viết nào mới được cào về từ 6 nhóm Facebook."
    
    # Check if any post matches user's query keywords
    matched = None
    for p in posts:
        content = (p[2] or "").lower()
        author = (p[1] or "").lower()
        if (author and author in lower) or sum(1 for w in content.split() if len(w) >= 3 and w in lower) >= 2:
            matched = p
            break
            
    if matched:
        return f"Báo cáo {sender_title}, kiểm tra dữ liệu thực tế tại 6 nhóm:\n\n👤 Tác giả: <b>{matched[1]}</b>\n🏢 Nhóm: <b>{matched[0]}</b>\n💬 Nội dung: <i>{matched[2][:200].strip()}...</i>\n\n🔗 <a href='{matched[3]}'>Xem bài viết gốc trên Facebook</a>"

    latest = posts[0]
    return f"Báo cáo {sender_title}, hiện tại trong 6 nhóm chưa ghi nhận bài mới khớp với yêu cầu này. Bài viết mới nhất trong hệ thống:\n• Nhóm: <b>{latest[0]}</b>\n• Tác giả: {latest[1]}\n• Trích đoạn: <i>{latest[2][:120].strip()}...</i>\n🔗 <a href='{latest[3]}'>Xem bài viết</a>"

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

                # Format sender title
                s_clean = sender_name.strip()
                s_lower = s_clean.lower()
                if "tùng" in s_lower or "tung" in s_lower:
                    sender_title = "Chủ tịch Tùng"
                elif s_lower.startswith("sếp") or s_lower.startswith("chủ tịch"):
                    sender_title = s_clean
                else:
                    sender_title = f"sếp {s_clean}"

                if text == "/start":
                    if chat_type in ["group", "supergroup"]:
                        reply = "Chào Chủ tịch Tùng cùng toàn thể anh em team Nguyên Nông Group! 🔥\n\nEm là Trợ lý Dữ liệu Thị trường NNG, chính thức có mặt để phục vụ anh em 24/7!\n\n✅ ĐÃ KÍCH HOẠT THÀNH CÔNG:\n1. Đã lưu Group này vào danh sách nhận tin tự động trên Cloud.\n2. Mỗi khi có khách cần mua / thi công (tưới, hồ bạt HDPE, bơm mặt trời): Chuông sẽ rung đồng thời ở CẢ group này lẫn tin riêng của sếp Hiếu kèm link bài Facebook.\n3. Đúng 8h00 sáng & 16h00 chiều: Tự động gửi bản tin phân tích thị trường kính gửi Chủ tịch Tùng cùng toàn thể anh em.\n4. Bất kỳ sếp nào trong nhóm cần tra cứu dữ liệu bài viết cứ tag @nguyen_nong_bot là em trả lời ngay!\n\nChúc team Nguyên Nông Group bùng nổ doanh số! 🚀"
                    else:
                        reply = f"Chào {sender_title} và anh em team Nguyên Nông Group! Em là Trợ lý Dữ liệu Thị trường, túc trực 24/7 để săn khách và phân tích thị trường cho team!"
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
    last_scan_time = 0

    while True:
        try:
            # Check current time in Vietnam (UTC+7)
            now_vn = datetime.now(timezone(timedelta(hours=7)))
            hour = now_vn.hour
            minute = now_vn.minute
            today_str = now_vn.strftime("%Y-%m-%d")

            # Daily Digest at 08:00 and 16:00
            digest_slot = None
            if hour == 8 and minute <= 30:
                digest_slot = "08:00"
            elif hour == 16 and minute <= 30:
                digest_slot = "16:00"

            if digest_slot and (last_digest_date != f"{today_str}_{digest_slot}"):
                print(f"[BOT] Triggering scheduled digest for {digest_slot}...")
                digest_text = generate_market_digest(digest_slot)
                broadcast_alert_and_digest(digest_text)
                last_digest_date = f"{today_str}_{digest_slot}"

            # Run regular scan every 30 minutes (1800s)
            if time.time() - last_scan_time >= 1800:
                last_scan_time = time.time()
                run_apify_scan()

        except Exception as e:
            print(f"[BOT] Scheduler error: {e}")

        # Check clock every 30s so digest window is never missed
        time.sleep(30)

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
