"""前の管理画面の処理。2024-02 に作り直したので、いまはどこからも呼ばない。消すのがこわいので残している。"""
import db


def cancel_v1(order_id):
    db.exe("UPDATE orders SET status = 'cancel', updated_at = ? WHERE id = ?", (db.jst_now(), order_id))


def delete_v1(order_id):
    db.exe("UPDATE orders SET is_deleted = 1, updated_at = ? WHERE id = ?", (db.jst_now(), order_id))


def sales_v1(ym):
    return db.q1("SELECT SUM(total) FROM orders WHERE created_at LIKE ? AND status != 'cancel'", (ym + "%",))[0]
