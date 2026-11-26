-- 2024-04 注文の削除を日時で持つ
ALTER TABLE orders ADD COLUMN deleted_at TEXT;
