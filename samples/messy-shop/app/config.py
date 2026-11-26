"""設定。本番はサーバーの環境変数で上書きする。"""
import os

DB_PATH = os.environ.get("SHOP_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "shop.db"))

SHOP_NAME = "こもの屋"

TAX_RATE = 0.1
SHIPPING_FEE = 600
FREE_SHIPPING_OVER = 5000  # 税込みでこれ以上なら送料無料

# 運送会社から毎晩届く CSV の置き場
CARRIER_CSV_DIR = os.environ.get("CARRIER_CSV_DIR", "/var/shop/carrier")

PAGE_SIZE = 50
