-- 評価用のサンプルの DB（sqlite）。値はすべて架空。evals/run.sh が一時のディレクトリに作り、道具は読み取りだけで開く。
-- 仕込んだ罠: status に cancel と canceled が混ざる、deleted_at は書かれない、顧客の無い注文が 1 行、
--             orders_old は今は書かれない、order_events はトリガーが書く、合計 0 円の注文が 1 行。
CREATE TABLE customers (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  email TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE orders (
  id INTEGER PRIMARY KEY,
  customer_id INTEGER NOT NULL REFERENCES customers(id),
  status TEXT NOT NULL,
  total INTEGER NOT NULL,
  deleted_at TEXT,
  is_deleted INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE INDEX orders_status_created ON orders (status, created_at);
CREATE TABLE order_events (
  id INTEGER PRIMARY KEY,
  order_id INTEGER NOT NULL,
  kind TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE orders_old (
  id INTEGER PRIMARY KEY,
  status TEXT,
  total INTEGER,
  created_at TEXT
);
CREATE TRIGGER orders_status_event AFTER UPDATE OF status ON orders
BEGIN
  INSERT INTO order_events (order_id, kind, created_at) VALUES (NEW.id, NEW.status, NEW.created_at);
END;

INSERT INTO customers (id, name, email, created_at) VALUES
  (1, 'Customer A', 'a@example.invalid', '2026-01-10 09:00:00'),
  (2, 'Customer B', 'b@example.invalid', '2026-03-02 12:30:00'),
  (3, 'Customer C', NULL, '2026-05-21 18:45:00'),
  (4, 'Customer D', 'd@example.invalid', '2026-08-30 08:15:00');

INSERT INTO orders (id, customer_id, status, total, deleted_at, is_deleted, created_at) VALUES
  (1, 1, 'paid', 4200, NULL, 0, '2026-09-03 10:00:00'),
  (2, 2, 'paid', 1800, NULL, 0, '2026-09-08 11:20:00'),
  (3, 3, 'shipped', 5600, NULL, 0, '2026-09-12 14:05:00'),
  (4, 1, 'canceled', 2300, NULL, 0, '2026-09-19 16:40:00'),
  (5, 4, 'paid', 3100, NULL, 0, '2026-09-25 09:10:00'),
  (6, 2, 'paid', 900, NULL, 1, '2026-09-30 22:55:00'),
  (7, 3, 'paid', 4700, NULL, 0, '2026-10-01 08:00:00'),
  (8, 1, 'shipped', 2600, NULL, 0, '2026-10-03 13:30:00'),
  (9, 4, 'canceled', 1500, NULL, 0, '2026-10-05 19:00:00'),
  (10, 2, 'paid', 0, NULL, 0, '2026-10-08 10:45:00'),
  (11, 99, 'paid', 3900, NULL, 0, '2026-10-11 15:15:00'),
  (12, 3, 'cancel', 2200, NULL, 0, '2026-10-14 09:30:00'),
  (13, 1, 'shipped', 6100, NULL, 0, '2026-10-17 17:20:00'),
  (14, 4, 'canceled', 1200, NULL, 0, '2026-10-20 11:00:00'),
  (15, 2, 'paid', 3300, NULL, 1, '2026-10-23 20:10:00'),
  (16, 3, 'shipped', 2800, NULL, 0, '2026-10-26 07:50:00'),
  (17, 1, 'canceled', 4400, NULL, 0, '2026-10-29 12:00:00'),
  (18, 4, 'paid', 1700, NULL, 0, '2026-10-31 23:30:00'),
  (19, 2, 'paid', 5200, NULL, 0, '2026-11-02 10:10:00'),
  (20, 3, 'paid', 2500, NULL, 0, '2026-11-05 14:40:00'),
  (21, 1, 'shipped', 3600, NULL, 0, '2026-11-09 09:00:00'),
  (22, 4, 'canceled', 1900, NULL, 0, '2026-11-13 16:30:00'),
  (23, 2, 'paid', 4100, NULL, 0, '2026-11-18 11:45:00'),
  (24, 3, 'paid', 2900, NULL, 0, '2026-11-22 18:05:00');

INSERT INTO order_events (id, order_id, kind, created_at) VALUES
  (1, 4, 'canceled', '2026-09-19 16:40:00'),
  (2, 9, 'canceled', '2026-10-05 19:00:00'),
  (3, 12, 'cancel', '2026-10-14 09:30:00'),
  (4, 14, 'canceled', '2026-10-20 11:00:00'),
  (5, 17, 'canceled', '2026-10-29 12:00:00'),
  (6, 22, 'canceled', '2026-11-13 16:30:00');

INSERT INTO orders_old (id, status, total, created_at) VALUES
  (1, 'paid', 3000, '2023-11-02 10:00:00'),
  (2, 'cancel', 1500, '2023-12-05 15:30:00'),
  (3, 'paid', 2700, '2023-12-28 09:20:00');
