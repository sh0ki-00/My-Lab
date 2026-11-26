"""会員。"""
import db

MAIL_OK = 1  # お知らせのメールを受け取る


def register(form):
    """会員登録の画面から。"""
    mail_ok = MAIL_OK if form.get("mail_ok") else 0
    return db.exe(
        "INSERT INTO customers (name, email, pref, mail_ok, created_at) VALUES (?, ?, ?, ?, ?)",
        (form["name"], form["email"], form.get("pref"), mail_ok, db.jst_now()),
    )


def set_mail(customer_id, ok):
    """マイページのお知らせのメールの設定。"""
    db.exe("UPDATE customers SET mail_ok = ? WHERE id = ?", (MAIL_OK if ok else 0, customer_id))


def find_by_email(email):
    return db.q1("SELECT * FROM customers WHERE email = ?", (email,))


def count_members():
    """会員の数。"""
    return db.q1("SELECT COUNT(*) FROM customers")[0]
