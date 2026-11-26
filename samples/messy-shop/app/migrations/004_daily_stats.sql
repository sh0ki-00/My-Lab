-- 2025-04 トップの画面が遅いので、日ごとの数を先にまとめておく
CREATE TABLE daily_stats (
  day TEXT PRIMARY KEY,
  orders INTEGER,
  sales INTEGER,
  updated_at TEXT
);

CREATE INDEX idx_orders_created ON orders (created_at);
