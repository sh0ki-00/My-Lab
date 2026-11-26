-- 2024-06 出荷した日時を注文に持たせる（注文の画面の「出荷」ボタン用）
ALTER TABLE orders ADD COLUMN shipped_at TEXT;
