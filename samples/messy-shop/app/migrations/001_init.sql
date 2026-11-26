-- 2023-01 開店のときの表

CREATE TABLE customers (
  id INTEGER PRIMARY KEY,
  name TEXT,
  email TEXT,
  pref TEXT,
  mail_ok,              -- お知らせのメール
  created_at TEXT
);

CREATE TABLE products (
  id INTEGER PRIMARY KEY,
  sku TEXT,
  name TEXT,
  price INTEGER,        -- 税抜き
  stock INTEGER,
  is_active INTEGER DEFAULT 1,
  created_at TEXT
);

CREATE TABLE orders (
  id INTEGER PRIMARY KEY,
  customer_id INTEGER,
  status TEXT,
  total INTEGER,        -- 合計
  tax INTEGER,
  shipping_fee INTEGER,
  pay_method TEXT,
  is_deleted INTEGER DEFAULT 0,
  created_at TEXT,
  updated_at TEXT
);

CREATE TABLE order_items (
  id INTEGER PRIMARY KEY,
  order_id INTEGER,
  product_id INTEGER,
  qty INTEGER,
  unit_price INTEGER
);

CREATE TABLE payments (
  id INTEGER PRIMARY KEY,
  order_id INTEGER,
  method TEXT,
  amount INTEGER,
  paid_at TEXT          -- 決済会社の時刻
);

CREATE TABLE shipments (
  id INTEGER PRIMARY KEY,
  order_id INTEGER,
  carrier TEXT,
  tracking_no TEXT,
  shipped_on TEXT,
  delivered_on TEXT
);
