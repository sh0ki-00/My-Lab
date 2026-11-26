"""注文などの決まった値。"""

STATUS_PENDING = "pending"
STATUS_PAID = "paid"
STATUS_SHIPPED = "shipped"
STATUS_DELIVERED = "delivered"
STATUS_CANCELED = "canceled"

# 注文の状態は 5 つ
ORDER_STATUSES = [
    STATUS_PENDING,
    STATUS_PAID,
    STATUS_SHIPPED,
    STATUS_DELIVERED,
    STATUS_CANCELED,
]

STATUS_LABELS = {
    STATUS_PENDING: "入金待ち",
    STATUS_PAID: "入金済み",
    STATUS_SHIPPED: "発送済み",
    STATUS_DELIVERED: "配達済み",
    STATUS_CANCELED: "キャンセル",
}

# 売上に入れる状態
SALES_STATUSES = [STATUS_PAID, STATUS_SHIPPED, STATUS_DELIVERED]

# お客様が選ぶ払い方
PAY_METHODS = ["card", "konbini", "bank"]
# ギフト券は払い方と一緒に使う（payments に 1 行足す）
GIFT_METHOD = "giftcard"

CARRIERS = ["yamato", "sagawa", "japanpost"]

# orders の列のメモ
#   total         合計（税込み）
#   tax           消費税
#   shipping_fee  送料。total には入れない
#   is_deleted    削除の印（古い）。いまは deleted_at を見る
#   created_at    注文日時（日本時間）
#   shipped_at    出荷した日時
