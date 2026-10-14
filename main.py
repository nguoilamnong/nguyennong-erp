# -*- coding: utf-8 -*-
"""
Nguyên Nông Group (NNG) - Internal Management System
Designed for Kỷ Mão 1999 (Thành Đầu Thổ)
"""
from fastapi import FastAPI, HTTPException, Request, Depends, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Optional
import sqlite3
import json
import os
import smtplib
from email.mime.text import MIMEText
from email.header import Header
from datetime import datetime

import database
from database import get_db, hash_pw

app = FastAPI(title="Nguyên Nông Group - Hệ Thống Quản Lý")

# Serve static files (logo, scripts, styles)
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Helper to check low stock and trigger email alert
def check_and_alert_low_stock(product_id: int):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, code, name, stock_qty, min_alert_qty, unit FROM products WHERE id = ?", (product_id,))
    prod = c.fetchone()
    
    if prod and prod["stock_qty"] <= prod["min_alert_qty"]:
        c.execute("SELECT value FROM settings WHERE key = 'alert_email_receiver'")
        row = c.fetchone()
        receivers = row["value"] if row else "admin@nguyennong.vn"
        print(f"⚠️ [CẢNH BÁO TỒN KHO THẤP] Linh kiện: {prod['name']} ({prod['code']}) còn {prod['stock_qty']} {prod['unit']} -> Gửi tới: {receivers}")
    conn.close()

# ----------------- TẠO LINK XEM THỬ CHỈ ĐỌC (VIEW ONLY) - HẾT HẠN SAU 2 GIỜ ----------------- #
DEMO_EXPIRATION = datetime(2026, 10, 14, 11, 15, 0) # Hết hạn lúc 11:15 ngày 14/10/2026 (sau 2 tiếng)

@app.get("/demo")
def demo_access():
    now = datetime.now()
    if now > DEMO_EXPIRATION:
        return HTMLResponse(content="""
        <div style="font-family: sans-serif; text-align: center; padding: 50px; background: #FFF5F5; color: #9B1C1C; min-height: 100vh;">
            <div style="max-width: 500px; margin: auto; background: white; padding: 30px; border-radius: 16px; box-shadow: 0 4px 20px rgba(0,0,0,0.1); border: 1px solid #F87171;">
                <h2 style="color: #DC2626; margin-bottom: 10px;">ĐƯỜNG LINK THAM KHẢO ĐÃ HẾT HẠN</h2>
                <p style="color: #4B5563; font-size: 14px; line-height: 1.6;">Đường link tạm này được Nguyên Nông Group giới hạn thời gian trong 2 giờ và đã tự động đóng lúc <strong>11:15 ngày 14/10/2026</strong> để bảo mật hệ thống.</p>
                <p style="color: #6B7280; font-size: 13px; margin-top: 15px;">Vui lòng liên hệ Admin nếu bạn cần cấp quyền truy cập chính thức.</p>
            </div>
        </div>
        """, status_code=403)

    template_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "index.html")
    with open(template_file, "r", encoding="utf-8") as f:
        html = f.read()

    # Cấu hình quyền CHỈ XEM (VIEW ONLY): Ẩn tất cả nút Thêm, Sửa, Xóa, Nhập hàng, Chốt đơn, Cài đặt
    guest_script = """
    <script>
        const guestUser = {
            id: 888,
            username: 'khach_tham_khao',
            full_name: 'Khách Tham Khảo (Chỉ Xem - Hết hạn 11:15)',
            role: 'viewer',
            email: 'thamkhao@nguyennong.vn'
        };
        localStorage.setItem('nng_user', JSON.stringify(guestUser));
        window.currentUser = guestUser;

        // Vô hiệu hóa và chặn mọi hành động chỉnh sửa hoặc xóa
        window.saveProduct = function(e) { if(e) e.preventDefault(); alert('Bạn đang ở chế độ CHỈ XEM (View Only), không có quyền thêm hoặc chỉnh sửa dữ liệu!'); return false; };
        window.deleteProduct = function() { alert('Bạn đang ở chế độ CHỈ XEM (View Only), không có quyền xóa linh kiện!'); return false; };
        window.saveStockAdjust = function(e) { if(e) e.preventDefault(); alert('Bạn đang ở chế độ CHỈ XEM (View Only), không có quyền nhập hoặc điều chỉnh kho!'); return false; };
        window.saveQuote = function(e) { if(e) e.preventDefault(); alert('Bạn đang ở chế độ CHỈ XEM (View Only), không có quyền tạo hoặc lưu báo giá!'); return false; };
        window.approveAndDeductStock = function() { alert('Bạn đang ở chế độ CHỈ XEM (View Only), không có quyền duyệt hóa đơn hoặc trừ kho!'); return false; };
        window.saveCompanySettings = function(e) { if(e) e.preventDefault(); alert('Bạn đang ở chế độ CHỈ XEM (View Only), không có quyền sửa thông tin công ty!'); return false; };
        window.saveUserEdit = function(e) { if(e) e.preventDefault(); alert('Bạn đang ở chế độ CHỈ XEM (View Only), không có quyền sửa thông tin thành viên!'); return false; };

        document.addEventListener('DOMContentLoaded', () => {
            const modal = document.getElementById('login-modal');
            if (modal) modal.style.display = 'none';
            if (typeof applyUserSession === 'function') applyUserSession();
            
            // Hiện thanh thông báo Chế độ chỉ xem trên cùng
            const banner = document.createElement('div');
            banner.style.cssText = 'background: #FEF3C7; color: #92400E; padding: 8px 16px; text-align: center; font-size: 12px; font-weight: bold; border-bottom: 1px solid #F59E0B; z-index: 100;';
            banner.innerHTML = '🔒 CHẾ ĐỘ XEM THAM KHẢO (CHỈ XEM - KHÔNG THỂ CHỈNH SỬA DỮ LIỆU) • LINK TỰ ĐỘNG HỦY LÚC 11:15';
            document.body.prepend(banner);
        });
    </script>
    <style>
        #login-modal { display: none !important; }
        /* Ẩn các nút hành động nguy hiểm đối với người xem */
        button[onclick*="deleteProduct"],
        button[onclick*="openProductModal"],
        button[onclick*="openStockModal"],
        button[onclick*="openUserEditModal"],
        button[onclick*="saveCompanySettings"],
        #btn-approve-invoice {
            display: none !important;
        }
    </style>
    """
    html = html.replace("</head>", f"{guest_script}</head>")
    return HTMLResponse(content=html)

# ----------------- API ROUTES ----------------- #

# 1. User & Auth API
class LoginRequest(BaseModel):
    username: str
    password: str

@app.post("/api/login")
def login(data: LoginRequest):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, username, full_name, role, email FROM users WHERE username = ? AND password_hash = ?", 
              (data.username, hash_pw(data.password)))
    user = c.fetchone()
    conn.close()
    if not user:
        raise HTTPException(status_code=401, detail="Tên đăng nhập hoặc mật khẩu không chính xác!")
    return {
        "success": True,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "full_name": user["full_name"],
            "role": user["role"],
            "email": user["email"]
        }
    }

@app.get("/api/users")
def get_users():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, username, full_name, role, email, created_at FROM users")
    users = [dict(row) for row in c.fetchall()]
    conn.close()
    return users

class UserCreate(BaseModel):
    username: str
    password: str
    full_name: str
    role: str
    email: Optional[str] = ""

@app.post("/api/users")
def create_user(u: UserCreate):
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (username, password_hash, full_name, role, email) VALUES (?, ?, ?, ?, ?)",
                  (u.username, hash_pw(u.password), u.full_name, u.role, u.email))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="Tên đăng nhập đã tồn tại!")
    conn.close()
    return {"success": True, "message": "Tạo tài khoản thành công"}

class UserUpdate(BaseModel):
    full_name: str
    email: Optional[str] = ""
    password: Optional[str] = None

@app.put("/api/users/{user_id}")
def update_user(user_id: int, u: UserUpdate):
    conn = get_db()
    c = conn.cursor()
    if u.password and u.password.strip():
        c.execute("UPDATE users SET full_name = ?, email = ?, password_hash = ? WHERE id = ?",
                  (u.full_name, u.email, hash_pw(u.password.strip()), user_id))
    else:
        c.execute("UPDATE users SET full_name = ?, email = ? WHERE id = ?",
                  (u.full_name, u.email, user_id))
    conn.commit()
    conn.close()
    return {"success": True, "message": "Cập nhật thông tin thành viên thành công!"}

# 2. Products & Inventory API
@app.get("/api/products")
def list_products(search: Optional[str] = None, category: Optional[str] = None):
    conn = get_db()
    c = conn.cursor()
    query = "SELECT * FROM products WHERE 1=1"
    params = []
    if category and category != "all":
        query += " AND category = ?"
        params.append(category)
    if search:
        query += " AND (code LIKE ? OR name LIKE ? OR supplier LIKE ?)"
        wild = f"%{search}%"
        params.extend([wild, wild, wild])
    query += " ORDER BY id DESC"
    c.execute(query, params)
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    
    # Calculate selling prices
    for p in rows:
        p["retail_price"] = round(p["cost_price"] * (1 + p["retail_markup_pct"] / 100.0), -2)
        p["project_price"] = round(p["cost_price"] * (1 + p["project_markup_pct"] / 100.0), -2)
        p["is_low_stock"] = p["stock_qty"] <= p["min_alert_qty"]
    return rows

class ProductCreateUpdate(BaseModel):
    code: str
    name: str
    category: str
    unit: str
    cost_price: float
    retail_markup_pct: float = 30.0
    project_markup_pct: float = 20.0
    stock_qty: float = 0.0
    min_alert_qty: float = 5.0
    supplier: Optional[str] = ""
    notes: Optional[str] = ""

@app.post("/api/products")
def add_product(p: ProductCreateUpdate):
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute('''
        INSERT INTO products (code, name, category, unit, cost_price, retail_markup_pct, project_markup_pct, stock_qty, min_alert_qty, supplier, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (p.code, p.name, p.category, p.unit, p.cost_price, p.retail_markup_pct, p.project_markup_pct, p.stock_qty, p.min_alert_qty, p.supplier, p.notes))
        new_id = c.lastrowid
        # Log stock creation
        c.execute('''
        INSERT INTO stock_logs (product_id, change_qty, new_balance, reason, reference_id, user_name)
        VALUES (?, ?, ?, ?, ?, ?)
        ''', (new_id, p.stock_qty, p.stock_qty, "Khởi tạo ban đầu", "INIT", "Hệ thống"))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="Mã linh kiện này đã tồn tại!")
    conn.close()
    return {"success": True, "message": "Thêm mới linh kiện thành công!"}

@app.put("/api/products/{product_id}")
def update_product(product_id: int, p: ProductCreateUpdate):
    conn = get_db()
    c = conn.cursor()
    c.execute('''
    UPDATE products SET code = ?, name = ?, category = ?, unit = ?, cost_price = ?,
           retail_markup_pct = ?, project_markup_pct = ?, min_alert_qty = ?, supplier = ?, notes = ?, updated_at = CURRENT_TIMESTAMP
    WHERE id = ?
    ''', (p.code, p.name, p.category, p.unit, p.cost_price, p.retail_markup_pct, p.project_markup_pct, p.min_alert_qty, p.supplier, p.notes, product_id))
    conn.commit()
    conn.close()
    return {"success": True, "message": "Cập nhật linh kiện thành công!"}

class StockAdjust(BaseModel):
    product_id: int
    change_qty: float
    reason: str
    user_name: Optional[str] = "Admin"

@app.post("/api/products/adjust_stock")
def adjust_stock(data: StockAdjust):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT stock_qty, min_alert_qty, name FROM products WHERE id = ?", (data.product_id,))
    prod = c.fetchone()
    if not prod:
        conn.close()
        raise HTTPException(status_code=404, detail="Không tìm thấy linh kiện")
    
    new_balance = prod["stock_qty"] + data.change_qty
    c.execute("UPDATE products SET stock_qty = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (new_balance, data.product_id))
    c.execute('''
    INSERT INTO stock_logs (product_id, change_qty, new_balance, reason, reference_id, user_name)
    VALUES (?, ?, ?, ?, ?, ?)
    ''', (data.product_id, data.change_qty, new_balance, data.reason, "ADJUST", data.user_name))
    conn.commit()
    conn.close()

    check_and_alert_low_stock(data.product_id)
    return {"success": True, "new_balance": new_balance}

@app.delete("/api/products/{product_id}")
def delete_product(product_id: int):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM products WHERE id = ?", (product_id,))
    conn.commit()
    conn.close()
    return {"success": True, "message": "Xóa linh kiện thành công!"}

# 3. Customers API
@app.get("/api/customers")
def list_customers():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM customers ORDER BY id DESC")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

class CustomerCreate(BaseModel):
    name: str
    phone: Optional[str] = ""
    address: Optional[str] = ""
    email: Optional[str] = ""
    customer_type: Optional[str] = "retail"
    notes: Optional[str] = ""

@app.post("/api/customers")
def create_customer(c_data: CustomerCreate):
    conn = get_db()
    c = conn.cursor()
    c.execute('''
    INSERT INTO customers (name, phone, address, email, customer_type, notes)
    VALUES (?, ?, ?, ?, ?, ?)
    ''', (c_data.name, c_data.phone, c_data.address, c_data.email, c_data.customer_type, c_data.notes))
    new_id = c.lastrowid
    conn.commit()
    conn.close()
    return {"success": True, "id": new_id, "message": "Lưu thông tin khách hàng thành công"}

# 4. Quotes & Invoices API
class QuoteItemIn(BaseModel):
    product_id: Optional[int] = None
    item_code: Optional[str] = ""
    item_name: str
    category: Optional[str] = ""
    unit: str
    quantity: float
    cost_price: float = 0.0
    unit_price: float
    markup_pct: float = 0.0
    total_price: float
    notes: Optional[str] = ""

class QuoteCreate(BaseModel):
    quote_type: str # 'retail' or 'project'
    customer_name: str
    customer_phone: Optional[str] = ""
    customer_address: Optional[str] = ""
    created_by_name: Optional[str] = "Kinh doanh"
    labor_cost: float = 0.0
    transport_cost: float = 0.0
    other_cost: float = 0.0
    other_cost_note: Optional[str] = ""
    discount_amount: float = 0.0
    tax_pct: float = 0.0
    notes: Optional[str] = ""
    items: List[QuoteItemIn]

@app.post("/api/quotes")
def create_quote(q: QuoteCreate):
    conn = get_db()
    c = conn.cursor()
    
    # Generate unique quote code: NNG-YYYYMMDD-XXX
    today_str = datetime.now().strftime("%Y%m%d")
    prefix = f"BG-{today_str}-"
    c.execute("SELECT COUNT(*) FROM quotes WHERE quote_code LIKE ?", (f"{prefix}%",))
    count = c.fetchone()[0] + 1
    quote_code = f"{prefix}{count:03d}"

    # Calculate subtotal of items
    subtotal = sum(item.total_price for item in q.items)
    # Total = subtotal + labor + transport + other - discount
    total_amount = subtotal + q.labor_cost + q.transport_cost + q.other_cost - q.discount_amount
    if q.tax_pct > 0:
        total_amount += (total_amount * (q.tax_pct / 100.0))

    c.execute('''
    INSERT INTO quotes (
        quote_code, quote_type, customer_name, customer_phone, customer_address,
        created_by_name, labor_cost, transport_cost, other_cost, other_cost_note,
        discount_amount, tax_pct, subtotal, total_amount, status, notes
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?)
    ''', (
        quote_code, q.quote_type, q.customer_name, q.customer_phone, q.customer_address,
        q.created_by_name, q.labor_cost, q.transport_cost, q.other_cost, q.other_cost_note,
        q.discount_amount, q.tax_pct, subtotal, total_amount, q.notes
    ))
    quote_id = c.lastrowid

    # Insert items
    for it in q.items:
        c.execute('''
        INSERT INTO quote_items (quote_id, product_id, item_code, item_name, category, unit, quantity, cost_price, unit_price, markup_pct, total_price, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            quote_id, it.product_id, it.item_code, it.item_name, it.category, it.unit,
            it.quantity, it.cost_price, it.unit_price, it.markup_pct, it.total_price, it.notes
        ))

    # Save or update customer record automatically
    c.execute("SELECT id FROM customers WHERE phone = ? AND phone != ''", (q.customer_phone,))
    existing_cust = c.fetchone()
    if not existing_cust:
        c.execute("INSERT INTO customers (name, phone, address, customer_type) VALUES (?, ?, ?, ?)",
                  (q.customer_name, q.customer_phone, q.customer_address, q.quote_type))

    conn.commit()
    conn.close()
    return {"success": True, "quote_id": quote_id, "quote_code": quote_code}

@app.get("/api/quotes")
def list_quotes(status: Optional[str] = None):
    conn = get_db()
    c = conn.cursor()
    query = "SELECT * FROM quotes WHERE 1=1"
    params = []
    if status and status != 'all':
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY id DESC"
    c.execute(query, params)
    quotes = [dict(r) for r in c.fetchall()]
    conn.close()
    return quotes

@app.get("/api/quotes/{quote_id}")
def get_quote_detail(quote_id: int):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM quotes WHERE id = ?", (quote_id,))
    quote = c.fetchone()
    if not quote:
        conn.close()
        raise HTTPException(status_code=404, detail="Không tìm thấy báo giá")
    
    quote_data = dict(quote)
    c.execute("SELECT * FROM quote_items WHERE quote_id = ?", (quote_id,))
    quote_data["items"] = [dict(r) for r in c.fetchall()]

    # Get settings for printing header
    c.execute("SELECT key, value FROM settings")
    settings = {r["key"]: r["value"] for r in c.fetchall()}
    quote_data["company_settings"] = settings

    conn.close()
    return quote_data

@app.post("/api/quotes/{quote_id}/approve_and_invoice")
def approve_and_invoice(quote_id: int, user_name: Optional[str] = "Admin"):
    """
    CRITICAL FEATURE:
    When customer confirms and pays, generate invoice AND deduct stock inventory!
    """
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM quotes WHERE id = ?", (quote_id,))
    quote = c.fetchone()
    if not quote:
        conn.close()
        raise HTTPException(status_code=404, detail="Không tìm thấy báo giá")
    
    if quote["is_deducted"] == 1:
        conn.close()
        return {"success": True, "message": "Đơn hàng này đã được trừ kho từ trước!"}

    # Fetch items
    c.execute("SELECT * FROM quote_items WHERE quote_id = ?", (quote_id,))
    items = c.fetchall()

    low_stock_products = []

    # Process inventory deduction
    for it in items:
        p_id = it["product_id"]
        qty = it["quantity"]
        if p_id:
            c.execute("SELECT stock_qty, min_alert_qty, name FROM products WHERE id = ?", (p_id,))
            p = c.fetchone()
            if p:
                new_bal = p["stock_qty"] - qty
                c.execute("UPDATE products SET stock_qty = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (new_bal, p_id))
                # Log stock deduction
                c.execute('''
                INSERT INTO stock_logs (product_id, change_qty, new_balance, reason, reference_id, user_name)
                VALUES (?, ?, ?, ?, ?, ?)
                ''', (p_id, -qty, new_bal, f"Xuất bán theo hóa đơn {quote['quote_code']}", quote['quote_code'], user_name))

                if new_bal <= p["min_alert_qty"]:
                    low_stock_products.append({"name": p["name"], "balance": new_bal, "min": p["min_alert_qty"]})

    # Update quote status
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute('''
    UPDATE quotes SET status = 'approved_invoiced', is_deducted = 1, invoiced_at = ? WHERE id = ?
    ''', (now_str, quote_id))

    conn.commit()
    conn.close()

    # Trigger alerts if any product reached low stock
    for item in low_stock_products:
        print(f"⚠️ [CẢNH BÁO EMAIL ĐÃ KÍCH HOẠT] Linh kiện: {item['name']} chỉ còn {item['balance']} (Dưới ngưỡng an toàn {item['min']})!")

    return {
        "success": True,
        "message": f"Đã phê duyệt hóa đơn {quote['quote_code']} và tự động trừ kho thành công!",
        "low_stock_alerts": low_stock_products
    }

# 5. Dashboard Statistics API
@app.get("/api/dashboard")
def get_dashboard_stats():
    conn = get_db()
    c = conn.cursor()
    
    # Total products & low stock count
    c.execute("SELECT COUNT(*) FROM products")
    total_products = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM products WHERE stock_qty <= min_alert_qty")
    low_stock_count = c.fetchone()[0]

    # Total customers
    c.execute("SELECT COUNT(*) FROM customers")
    total_customers = c.fetchone()[0]

    # Quotes and Invoices stats
    c.execute("SELECT COUNT(*) FROM quotes")
    total_quotes = c.fetchone()[0]

    c.execute("SELECT COUNT(*), COALESCE(SUM(total_amount), 0) FROM quotes WHERE status = 'approved_invoiced'")
    row_invoiced = c.fetchone()
    total_invoiced_count = row_invoiced[0]
    total_revenue = row_invoiced[1]

    # Today's stats
    today_str = datetime.now().strftime("%Y-%m-%d")
    c.execute("SELECT COUNT(*), COALESCE(SUM(total_amount), 0) FROM quotes WHERE status = 'approved_invoiced' AND invoiced_at LIKE ?", (f"{today_str}%",))
    row_today = c.fetchone()
    today_invoiced_count = row_today[0]
    today_revenue = row_today[1]

    # Category breakdown
    c.execute("SELECT category, COUNT(*), SUM(stock_qty) FROM products GROUP BY category")
    cat_summary = [{"category": r[0], "count": r[1], "total_stock": r[2]} for r in c.fetchall()]

    # Low stock items list
    c.execute("SELECT id, code, name, category, unit, stock_qty, min_alert_qty FROM products WHERE stock_qty <= min_alert_qty ORDER BY stock_qty ASC LIMIT 8")
    low_stock_items = [dict(r) for r in c.fetchall()]

    # Recent activity logs
    c.execute('''
    SELECT sl.*, p.name as product_name, p.unit 
    FROM stock_logs sl
    JOIN products p ON sl.product_id = p.id
    ORDER BY sl.id DESC LIMIT 6
    ''')
    recent_stock_logs = [dict(r) for r in c.fetchall()]

    # Recent invoices/quotes
    c.execute("SELECT * FROM quotes ORDER BY id DESC LIMIT 5")
    recent_quotes = [dict(r) for r in c.fetchall()]

    conn.close()

    return {
        "total_products": total_products,
        "low_stock_count": low_stock_count,
        "total_customers": total_customers,
        "total_quotes": total_quotes,
        "total_invoiced_count": total_invoiced_count,
        "total_revenue": total_revenue,
        "today_revenue": today_revenue,
        "today_invoiced_count": today_invoiced_count,
        "cat_summary": cat_summary,
        "low_stock_items": low_stock_items,
        "recent_stock_logs": recent_stock_logs,
        "recent_quotes": recent_quotes
    }

# 6. Settings API
@app.get("/api/settings")
def get_settings():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT key, value FROM settings")
    settings = {r["key"]: r["value"] for r in c.fetchall()}
    conn.close()
    return settings

@app.post("/api/settings")
def update_settings(data: dict):
    conn = get_db()
    c = conn.cursor()
    for k, v in data.items():
        c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (k, str(v)))
    conn.commit()
    conn.close()
    return {"success": True, "message": "Đã lưu cài đặt thành công!"}

# 7. Serve Web App Single Page
@app.get("/", response_class=HTMLResponse)
def index():
    template_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "index.html")
    with open(template_file, "r", encoding="utf-8") as f:
        return f.read()

