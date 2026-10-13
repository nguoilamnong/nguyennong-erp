# -*- coding: utf-8 -*-
"""
Database initialization and helpers for Nguyên Nông Group (NNG) Management System
"""
import sqlite3
import hashlib
import json
import os
from datetime import datetime

DB_FILE = os.path.join(os.path.dirname(__file__), "nng_system.db")

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def hash_pw(password: str) -> str:
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

def init_db():
    conn = get_db()
    c = conn.cursor()

    # Users table
    c.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        full_name TEXT NOT NULL,
        role TEXT NOT NULL, -- admin, tech, sales
        email TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # Categories
    c.execute('''
    CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        description TEXT
    )
    ''')

    # Materials / Products table
    c.execute('''
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        category TEXT NOT NULL, -- He thong tuoi, Bat ho, Nang luong mat troi, Khac
        unit TEXT NOT NULL, -- Cai, Met, Cuon, Tam, Bo, etc.
        cost_price REAL NOT NULL, -- Gia nhap
        retail_markup_pct REAL DEFAULT 30.0, -- % Loi nhuan ban le (default 30%)
        project_markup_pct REAL DEFAULT 20.0, -- % Loi nhuan du an (default 20%)
        stock_qty REAL DEFAULT 0, -- Ton kho hien tai
        min_alert_qty REAL DEFAULT 5, -- Muc ton toi thieu de canh bao
        supplier TEXT, -- Nha cung cap
        notes TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # Customers table
    c.execute('''
    CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        phone TEXT,
        address TEXT,
        email TEXT,
        customer_type TEXT DEFAULT 'retail', -- retail (ca nhan), project (chu dau tu/nha thau)
        notes TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # Quotes / Invoices table
    c.execute('''
    CREATE TABLE IF NOT EXISTS quotes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        quote_code TEXT UNIQUE NOT NULL, -- BG-20261013-001
        quote_type TEXT NOT NULL, -- 'retail' or 'project'
        customer_id INTEGER,
        customer_name TEXT,
        customer_phone TEXT,
        customer_address TEXT,
        created_by_user_id INTEGER,
        created_by_name TEXT,
        status TEXT DEFAULT 'draft', -- draft (Ban nhap), sent (Da gui khach), approved_invoiced (Da chot/Xuat hoa don - da tru kho), cancelled
        discount_amount REAL DEFAULT 0,
        tax_pct REAL DEFAULT 0,
        labor_cost REAL DEFAULT 0, -- Tien cong tho (cho du an)
        transport_cost REAL DEFAULT 0, -- Van chuyen
        other_cost REAL DEFAULT 0, -- Chi phi khac
        other_cost_note TEXT,
        subtotal REAL DEFAULT 0,
        total_amount REAL DEFAULT 0,
        is_deducted INTEGER DEFAULT 0, -- 1 neu da tru kho
        notes TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        invoiced_at TEXT,
        FOREIGN KEY (customer_id) REFERENCES customers(id)
    )
    ''')

    # Quote Items table
    c.execute('''
    CREATE TABLE IF NOT EXISTS quote_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        quote_id INTEGER NOT NULL,
        product_id INTEGER,
        item_code TEXT,
        item_name TEXT NOT NULL,
        category TEXT,
        unit TEXT,
        quantity REAL NOT NULL,
        cost_price REAL DEFAULT 0,
        unit_price REAL NOT NULL,
        markup_pct REAL DEFAULT 0,
        total_price REAL NOT NULL,
        notes TEXT,
        FOREIGN KEY (quote_id) REFERENCES quotes(id) ON DELETE CASCADE
    )
    ''')

    # Stock History / Log
    c.execute('''
    CREATE TABLE IF NOT EXISTS stock_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL,
        change_qty REAL NOT NULL, -- duong la nhap, am la xuat
        new_balance REAL NOT NULL,
        reason TEXT NOT NULL, -- 'import', 'sale_invoice', 'adjustment'
        reference_id TEXT, -- quote_code or import note
        user_name TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # System Settings
    c.execute('''
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    ''')

    conn.commit()

    # Seed default users if empty (4 team members)
    c.execute('SELECT COUNT(*) FROM users')
    if c.fetchone()[0] == 0:
        default_users = [
            ('admin', hash_pw('nng123'), 'Quản Trị Viên (CEO)', 'admin', 'admin@nguyennong.vn'),
            ('hieu', hash_pw('nng123'), 'Minh Hiếu (Sáng Lập)', 'admin', 'hieu@nguyennong.vn'),
            ('kythuat', hash_pw('nng123'), 'Kỹ Thuật Dự Án', 'tech', 'kythuat@nguyennong.vn'),
            ('kinhdoanh', hash_pw('nng123'), 'Kinh Doanh & Bán Lẻ', 'sales', 'sales@nguyennong.vn')
        ]
        c.executemany('INSERT INTO users (username, password_hash, full_name, role, email) VALUES (?, ?, ?, ?, ?)', default_users)
        conn.commit()

    # Seed default settings
    c.execute('SELECT COUNT(*) FROM settings')
    if c.fetchone()[0] == 0:
        default_settings = [
            ('company_name', 'CÔNG TY TNHH NGUYÊN NÔNG GROUP'),
            ('slogan', 'Giải Pháp Nông Nghiệp Bền Vững - Hệ Thống Tưới • Bạt Hồ • Điện Mặt Trời'),
            ('hotline', '0988 123 456 - 0912 345 678'),
            ('email', 'contact@nguyennong.vn'),
            ('address', 'Khu Nông Nghiệp Công Nghệ Cao, Việt Nam'),
            ('bank_info', 'STK: 190368888888 - Techcombank - NGUYEN NONG GROUP'),
            ('default_retail_markup', '30'),
            ('default_project_markup', '20'),
            ('alert_email_receiver', 'admin@nguyennong.vn, hieu@nguyennong.vn'),
            ('alert_threshold_default', '5')
        ]
        c.executemany('INSERT INTO settings (key, value) VALUES (?, ?)', default_settings)
        conn.commit()

    # Seed initial products from real data if empty
    c.execute('SELECT COUNT(*) FROM products')
    if c.fetchone()[0] == 0:
        default_products = [
            # Hệ thống tưới
            ('TUOI-001', 'Đầu béc tưới nhỏ giọt bù áp Rivulis 4L/h', 'Hệ thống tưới', 'Cái', 45000, 30.0, 20.0, 15, 5, 'Nhà Bè Agri', 'Hàng Israel cao cấp'),
            ('TUOI-002', 'Đầu béc phun sương 4 hướng chống nhỏ giọt', 'Hệ thống tưới', 'Cái', 22000, 35.0, 25.0, 8, 5, 'Việt An Nông', 'Dùng làm mát lan, nhà kính'),
            ('TUOI-003', 'Ống tưới LDPE phi 16mm dày 1.2mm', 'Hệ thống tưới', 'Cuộn (100m)', 480000, 25.0, 18.0, 6, 3, 'Việt An Nông', 'Chống tia UV'),
            ('TUOI-004', 'Bộ lọc đĩa chữ T phi 60mm lưu lượng 25m3/h', 'Hệ thống tưới', 'Bộ', 1250000, 25.0, 15.0, 4, 2, 'Nhà Bè Agri', 'Bảo hành 24 tháng'),
            ('TUOI-005', 'Van điện từ phi 34mm DC 24V tự động hóa', 'Hệ thống tưới', 'Cái', 380000, 30.0, 20.0, 3, 5, 'HACHI', 'Cảnh báo sắp hết'),
            
            # Bạt hồ
            ('BAT-001', 'Bạt HDPE lót hồ chứa nước 0.5mm', 'Bạt hồ', 'm²', 26000, 30.0, 18.0, 450, 100, 'Lê Hà Group', 'Nguyên sinh chuẩn quốc tế'),
            ('BAT-002', 'Bạt HDPE chống thấm hồ tôm/cá 0.75mm', 'Bạt hồ', 'm²', 38000, 28.0, 18.0, 200, 100, 'Hòa Phát Đạt', 'Solmax Canada'),
            ('BAT-003', 'Bạt HDPE 0.3mm kinh tế tưới tiêu', 'Bạt hồ', 'm²', 16000, 35.0, 20.0, 600, 150, 'Hoàng Dũng Green', 'Sản xuất trong nước'),
            ('BAT-004', 'Keo dán chuyên dụng / Mối hàn nhiệt HDPE', 'Bạt hồ', 'Cuộn/Thùng', 320000, 30.0, 20.0, 4, 5, 'Bạt Nguyễn Lê Phát', 'Cảnh báo sắp hết'),

            # Năng lượng mặt trời
            ('SOLAR-001', 'Tấm pin Mono-PERC 550W N-Type TOPCon', 'Năng lượng mặt trời', 'Tấm', 2650000, 20.0, 15.0, 12, 5, 'DAT Solar', 'LONGi / Jinko'),
            ('SOLAR-002', 'Biến tần bơm năng lượng mặt trời 3 pha 5.5kW', 'Năng lượng mặt trời', 'Bộ', 8900000, 22.0, 15.0, 2, 3, 'Vũ Phong Energy', 'Chuyên dụng bơm tưới'),
            ('SOLAR-003', 'Khung giá đỡ tấm pin nhôm định hình chuyên dụng', 'Năng lượng mặt trời', 'Bộ', 450000, 25.0, 18.0, 10, 4, 'Tech South', 'Chống oxy hóa muối biển'),
            ('SOLAR-004', 'Dây cáp chuyên dụng DC Solar 4.0mm2', 'Năng lượng mặt trời', 'Cuộn (100m)', 1400000, 25.0, 18.0, 5, 2, 'DAT Solar', 'Chống cháy ngoài trời')
        ]
        for p in default_products:
            c.execute('''
            INSERT INTO products (code, name, category, unit, cost_price, retail_markup_pct, project_markup_pct, stock_qty, min_alert_qty, supplier, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', p)
        conn.commit()

    conn.close()

if __name__ == "__main__":
    init_db()
    print("Database nng_system.db initialized successfully!")
