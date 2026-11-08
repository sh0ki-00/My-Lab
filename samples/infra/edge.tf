# 公開の層。画面のファイルは非公開のバケットに置き、CloudFront だけが読む。
# 画面のバケットに書けるのは配る役割だけ。書くたびに、守りの口座の画面の照らし（security/static-watch.tf）が、書かれた版を
# 作りの来歴の署名と照らす。照らしは CI の外にあり、版の履歴も見る。読むための許しだけを、ここで守りの口座の役割に渡す。
# 控えの長さ: assets/ の下（名前に指紋を入れた html と script）は長く、入口（index.html ほか assets/ の外）は 60 秒まで。
# 利用者の端末に向けた Cache-Control も応答の見出しの方針で上書きするので、書き込みに長い max-age を付けても効かない。
# API は CloudFront の VPC オリジンから内部のロードバランサーへ渡す。WAF は事務所のアドレスだけを通す。
# 事務所のアドレスは入口の札の 1 枚にすぎない（来客の網や乗っ取られた社内の端末も、同じアドレスから来る）。
# 利用者の鍵ごとに量を絞り、利用者の認証（未確定 1）が決まるまで本番には適用しない（下の precondition）。
# 応答には見出しの方針を付け、画面のブラウザが送れる先を CSP で同じ源（と認証の発行元）に絞る。
# 配信と WAF とその伏せ字の設定を作る・変える操作は、守りの適用の役割（承認 2 人）にしか許していない（org/scp.tf）。WAF の無い 2 本目の配信は作れず、
# 作られたら毎日の棚卸しが知らせる（functions/copy_inventory.py）。

resource "aws_s3_bucket" "static" {
  bucket = "${local.name}-static-${local.account_id}"
}

resource "aws_s3_bucket_public_access_block" "static" {
  bucket                  = aws_s3_bucket.static.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "static" {
  bucket = aws_s3_bucket.static.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_versioning" "static" {
  bucket = aws_s3_bucket.static.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "static" {
  bucket = aws_s3_bucket.static.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.static.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_policy" "static" {
  bucket = aws_s3_bucket.static.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "CloudFrontRead"
        Effect    = "Allow"
        Principal = { Service = "cloudfront.amazonaws.com" }
        Action    = "s3:GetObject"
        Resource  = "${aws_s3_bucket.static.arn}/*"
        Condition = {
          StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.admin.arn }
        }
      },
      {
        # 画面の file を書く・消すのは、配る役割だけ。
        Sid       = "StaticWritesOnlyFromDeployRole"
        Effect    = "Deny"
        Principal = "*"
        Action    = ["s3:PutObject", "s3:DeleteObject", "s3:DeleteObjectVersion", "s3:PutObjectAcl", "s3:PutObjectVersionAcl"]
        Resource  = "${aws_s3_bucket.static.arn}/*"
        Condition = { ArnNotEquals = { "aws:PrincipalArn" = aws_iam_role.ci_push_static.arn } }
      },
      {
        # 守りの口座の画面の照らしが、書かれた版と版の履歴を読む。画面の file は公開の中身で、データではない。
        Sid       = "GuardStaticWatchReads"
        Effect    = "Allow"
        Principal = { AWS = var.guard_static_watch_role_arn }
        Action    = ["s3:GetObject", "s3:GetObjectVersion", "s3:ListBucket", "s3:ListBucketVersions"]
        Resource  = [aws_s3_bucket.static.arn, "${aws_s3_bucket.static.arn}/*"]
      },
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource  = [aws_s3_bucket.static.arn, "${aws_s3_bucket.static.arn}/*"]
        Condition = {
          Bool = { "aws:SecureTransport" = "false" }
        }
      },
    ]
  })
}

resource "aws_cloudfront_origin_access_control" "static" {
  name                              = "${local.name}-static"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_vpc_origin" "api" {
  vpc_origin_endpoint_config {
    name                   = "${local.name}-api"
    arn                    = aws_lb.api.arn
    http_port              = 80
    https_port             = 443
    origin_protocol_policy = "https-only"

    origin_ssl_protocols {
      items    = ["TLSv1.2"]
      quantity = 1
    }
  }
}

data "aws_cloudfront_cache_policy" "disabled" {
  name = "Managed-CachingDisabled"
}

# 控えの長さは 2 つだけ。名前に指紋を入れた script と style（assets/*.js、assets/*.css）は 1 年、それ以外（入口と html を含む）は 60 秒まで
# （元の Cache-Control が長くても、上限で切る）。html を長く控えると、外した部品の古い html を後で案内されたとき、配信の端と端末の控えから
# 古い script ごと読み込まれる。html を短くすれば、古い script は名前を知っていても、それを読み込む同じ源の頁が無い。
resource "aws_cloudfront_cache_policy" "static" {
  for_each    = { entry = 60, assets = 31536000 }
  name        = "${local.name}-static-${each.key}"
  min_ttl     = 0
  default_ttl = each.value
  max_ttl     = each.value

  parameters_in_cache_key_and_forwarded_to_origin {
    enable_accept_encoding_brotli = true
    enable_accept_encoding_gzip   = true

    cookies_config {
      cookie_behavior = "none"
    }
    headers_config {
      header_behavior = "none"
    }
    query_strings_config {
      query_string_behavior = "none"
    }
  }
}

data "aws_cloudfront_origin_request_policy" "all_viewer" {
  name = "Managed-AllViewerExceptHostHeader"
}

# 画面の部品（npm）に悪い版が混ざっても、鍵と注文を外の宛先へ送らせない。fetch・画像・フォームの送り先を同じ源に絞る。
# 認証の発行元（未確定 1）は、決まったら connect-src と form-action に足す。画面の側の条件（同じ源の外へ通信しない、
# inline の script と style を使わない、Service Worker と Web Worker を使わない）はフロントエンドへ渡す（横断事項）。
# worker-src 'none' で、Service Worker の登録そのものを止める（無いと script-src 'self' に落ち、束の中の /sw.js を登録できる）。
# 登録が残ると、部品を外した後も端末の中で入口の応答を作り、CSP の無い応答で inline の script を動かせるからである。
locals {
  auth_origin = var.user_auth_issuer_url == "" ? "" : " ${regex("^https://[^/]+", var.user_auth_issuer_url)}"
  csp = join("; ", [
    "default-src 'none'", "script-src 'self'", "style-src 'self'", "img-src 'self'", "font-src 'self'", "manifest-src 'self'",
    "connect-src 'self'${local.auth_origin}", "form-action 'self'${local.auth_origin}", "frame-ancestors 'none'", "base-uri 'none'",
    "object-src 'none'", "worker-src 'none'", "upgrade-insecure-requests",
  ])
}

# 利用者の端末の控えも、ここで決める。入口と html は毎回確かめ、名前に指紋を入れた script と style は 1 年、API の応答（注文の中身）は
# 端末に残さない。書き込みの側で付けた Cache-Control は、override で上書きする。
# 部品を外した版を出すときは、clear_site_cache を真にして入口の応答に Clear-Site-Data: "cache", "storage" を付ける。
# "cache" は HTTP の控えだけを消し、Service Worker の登録は消さない。"storage" が登録と端末の保存を消す（入り直しになるのは受け入れる）。
# 入口の応答まで残った Service Worker が横取りする端末には届かないので、外した版では /sw.js に登録を外すだけの作りを置く（設計書の手順）。
# （外した file の配信の端の無効化は未確定 32）。
resource "aws_cloudfront_response_headers_policy" "admin" {
  for_each = {
    entry  = "no-cache"
    assets = "public, max-age=31536000, immutable"
    api    = "no-store"
  }
  name = "${local.name}-security-headers-${each.key}"

  custom_headers_config {
    items {
      header   = "Cache-Control"
      value    = each.value
      override = true
    }
    dynamic "items" {
      for_each = each.key == "entry" && var.clear_site_cache ? ["\"cache\", \"storage\""] : []
      content {
        header   = "Clear-Site-Data"
        value    = items.value
        override = true
      }
    }
  }

  security_headers_config {
    content_security_policy {
      content_security_policy = local.csp
      override                = true
    }
    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = true
      override                   = true
    }
    content_type_options {
      override = true
    }
    frame_options {
      frame_option = "DENY"
      override     = true
    }
    referrer_policy {
      referrer_policy = "no-referrer"
      override        = true
    }
  }
}

resource "aws_cloudfront_distribution" "admin" {
  enabled             = true
  comment             = "${local.name} admin screen"
  aliases             = [var.admin_domain]
  default_root_object = "index.html"
  http_version        = "http2and3"
  price_class         = "PriceClass_200"
  web_acl_id          = aws_wafv2_web_acl.admin.arn

  origin {
    origin_id                = "static"
    domain_name              = aws_s3_bucket.static.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.static.id
  }

  origin {
    origin_id   = "api"
    domain_name = aws_lb.api.dns_name
    vpc_origin_config {
      vpc_origin_id = aws_cloudfront_vpc_origin.api.id
    }
  }

  default_cache_behavior {
    target_origin_id           = "static"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    cache_policy_id            = aws_cloudfront_cache_policy.static["entry"].id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.admin["entry"].id
    compress                   = true
  }

  # 長く控えるのは、名前に指紋を入れた script と style だけ。assets/ の下の html と他の file は、既定（入口と同じ短い控え）に落ちる。
  dynamic "ordered_cache_behavior" {
    for_each = ["/assets/*.js", "/assets/*.css"]
    content {
      path_pattern               = ordered_cache_behavior.value
      target_origin_id           = "static"
      viewer_protocol_policy     = "redirect-to-https"
      allowed_methods            = ["GET", "HEAD"]
      cached_methods             = ["GET", "HEAD"]
      cache_policy_id            = aws_cloudfront_cache_policy.static["assets"].id
      response_headers_policy_id = aws_cloudfront_response_headers_policy.admin["assets"].id
      compress                   = true
    }
  }

  ordered_cache_behavior {
    path_pattern               = "/api/*"
    target_origin_id           = "api"
    viewer_protocol_policy     = "https-only"
    allowed_methods            = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods             = ["GET", "HEAD"]
    cache_policy_id            = data.aws_cloudfront_cache_policy.disabled.id
    origin_request_policy_id   = data.aws_cloudfront_origin_request_policy.all_viewer.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.admin["api"].id
    compress                   = true
  }

  restrictions {
    geo_restriction {
      restriction_type = "whitelist"
      locations        = ["JP"]
    }
  }

  viewer_certificate {
    acm_certificate_arn      = var.edge_certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }

  lifecycle {
    precondition {
      condition     = var.env != "prod" || var.user_auth_issuer_url != ""
      error_message = "利用者の認証（未確定 1）が決まるまで、本番には適用しない。user_auth_issuer_url を決めてから計画を出す。"
    }
  }
}

# ---- WAF（us-east-1）。悪い要求の型を止め、同じアドレスからの量を絞り、事務所のアドレスだけを通す。

resource "aws_wafv2_ip_set" "office" {
  provider           = aws.us_east_1
  name               = "${local.name}-office"
  scope              = "CLOUDFRONT"
  ip_address_version = "IPV4"
  addresses          = var.office_cidrs
}

# 見本の要求（sampled requests）は、どの規則でも取らない。見本には Authorization や問い合わせの文字列がそのまま入り、
# ログの伏せ字（redacted_fields）は見本に掛からない。止めた数と理由は、指標と伏せ字つきのログで見る。
resource "aws_wafv2_web_acl" "admin" {
  provider = aws.us_east_1
  name     = "${local.name}-admin"
  scope    = "CLOUDFRONT"

  default_action {
    block {}
  }

  rule {
    name     = "aws-common"
    priority = 0
    override_action {
      none {}
    }
    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesCommonRuleSet"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "aws-common"
      sampled_requests_enabled   = false
    }
  }

  # 同じアドレスからの量（鍵の無い要求の洪水を止める）。事務所の 5 人は 1 つのアドレスを共有するので、1 人は絞れない。
  rule {
    name     = "rate-per-ip"
    priority = 1
    action {
      block {}
    }
    statement {
      rate_based_statement {
        limit              = 2000
        aggregate_key_type = "IP"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "rate-per-ip"
      sampled_requests_enabled   = false
    }
  }

  # /api/ への要求の形。次のどちらかなら止める（1 本の規則にまとめる）。
  #   Authorization が「Bearer 1 つの空白 札」の形でない。大文字と小文字や空白の数を変えて、量を数える鍵を別にする手を止める。
  #   パスが正規の形でない。二重の斜線、./ と ../、逆斜線、符号（% の付いた文字。英字も斜線も点も）の全部を止める。
  #   API のパスは英数と斜線と記号の - _ だけなので、符号を許す理由が無い（許す文字の一覧）。配信の振る舞いの合わせ方が符号を解くかに頼らない。
  # バックエンドも同じ形の Authorization だけを受ける（横断事項）。量を数える鍵とパスも、下で正規化してから見る。
  rule {
    name     = "api-request-shape"
    priority = 2
    action {
      block {}
    }
    statement {
      and_statement {
        statement {
          # /api/ かどうかは、量を数える規則と同じく、符号を解いて正規化したパスで決める（/%61pi/ で形の検査を外す手）。
          byte_match_statement {
            search_string         = "/api/"
            positional_constraint = "STARTS_WITH"
            field_to_match {
              uri_path {}
            }
            text_transformation {
              priority = 0
              type     = "URL_DECODE"
            }
            text_transformation {
              priority = 1
              type     = "NORMALIZE_PATH"
            }
            text_transformation {
              priority = 2
              type     = "LOWERCASE"
            }
          }
        }
        statement {
          or_statement {
            statement {
              not_statement {
                statement {
                  regex_match_statement {
                    regex_string = "^Bearer [A-Za-z0-9._~+/=-]+$"
                    field_to_match {
                      single_header {
                        name = "authorization"
                      }
                    }
                    text_transformation {
                      priority = 0
                      type     = "NONE"
                    }
                  }
                }
              }
            }
            # Authorization が 2 つ以上ある要求。量の上限（rate-per-key）が 1 つ目の値で数え、API が後の値で認可すると、
            # 毎回違う作り物の鍵を前に置いて上限を外せる。見出しの並び（header_order）で 2 つ目を見つけて止める。
            # 値に「,」が入る形（重なりをまとめた形）は、上の形の検査（Bearer と札だけ）が止める。API も 2 つ以上を 400 にする（横断事項）。
            statement {
              regex_match_statement {
                regex_string = "(^|:)authorization:(.*:)?authorization(:|$)"
                field_to_match {
                  header_order {
                    oversize_handling = "MATCH"
                  }
                }
                text_transformation {
                  priority = 0
                  type     = "LOWERCASE"
                }
              }
            }
            statement {
              regex_match_statement {
                regex_string = "(//|/\\.\\.?(/|$)|%|\\\\)"
                field_to_match {
                  uri_path {}
                }
                text_transformation {
                  priority = 0
                  type     = "NONE"
                }
              }
            }
          }
        }
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "api-request-shape"
      sampled_requests_enabled   = false
    }
  }

  # 利用者の鍵（Authorization の見出し）ごとの量。盗んだ鍵 1 本で抜ける速さを、5 分あたりで 3 段に絞る。
  #   API 全体は var.api_rate_per_key 回、注文の詳細と書き込みは var.api_detail_rate_per_key 回、
  #   注文の一覧（1 回で最大 100 件の氏名を返す）は var.api_list_rate_per_key 回。どれも止めたら知らせる（guardrails.tf）。
  # 鍵は空白を詰めて小文字にしてから数え、パスは符号を解いて正規化し、小文字にしてから見る。
  dynamic "rule" {
    for_each = {
      "rate-per-key"        = { priority = 3, limit = var.api_rate_per_key, path = "^/api/" }
      "rate-per-key-detail" = { priority = 4, limit = var.api_detail_rate_per_key, path = "^/api/v1/orders/[^/]+" }
      "rate-per-key-list"   = { priority = 5, limit = var.api_list_rate_per_key, path = "^/api/v1/orders/?$" }
    }
    content {
      name     = rule.key
      priority = rule.value.priority
      action {
        block {}
      }
      statement {
        rate_based_statement {
          limit                 = rule.value.limit
          evaluation_window_sec = 300
          aggregate_key_type    = "CUSTOM_KEYS"
          custom_key {
            header {
              name = "authorization"
              text_transformation {
                priority = 0
                type     = "COMPRESS_WHITE_SPACE"
              }
              text_transformation {
                priority = 1
                type     = "LOWERCASE"
              }
            }
          }
          scope_down_statement {
            regex_match_statement {
              regex_string = rule.value.path
              field_to_match {
                uri_path {}
              }
              text_transformation {
                priority = 0
                type     = "URL_DECODE"
              }
              text_transformation {
                priority = 1
                type     = "NORMALIZE_PATH"
              }
              text_transformation {
                priority = 2
                type     = "LOWERCASE"
              }
            }
          }
        }
      }
      visibility_config {
        cloudwatch_metrics_enabled = true
        metric_name                = rule.key
        sampled_requests_enabled   = false
      }
    }
  }

  # 一覧と詳細の 1 日の総量を数える（止めない）。guardrails.tf の waf-list-daily-total と waf-detail-daily-total が、目安を超えた日に知らせる。
  #   詳細は 5 分の上限の下で 1 日続ける手（5 分 99 回を 12 時間）があるので、一覧と同じ形で数える。
  dynamic "rule" {
    for_each = {
      "list-volume"   = { priority = 6, path = "^/api/v1/orders/?$" }
      "detail-volume" = { priority = 7, path = "^/api/v1/orders/[^/]+" }
    }
    content {
      name     = rule.key
      priority = rule.value.priority
      action {
        count {}
      }
      statement {
        regex_match_statement {
          regex_string = rule.value.path
          field_to_match {
            uri_path {}
          }
          text_transformation {
            priority = 0
            type     = "URL_DECODE"
          }
          text_transformation {
            priority = 1
            type     = "NORMALIZE_PATH"
          }
          text_transformation {
            priority = 2
            type     = "LOWERCASE"
          }
        }
      }
      visibility_config {
        cloudwatch_metrics_enabled = true
        metric_name                = rule.key
        sampled_requests_enabled   = false
      }
    }
  }

  rule {
    name     = "office-only"
    priority = 8
    action {
      allow {}
    }
    statement {
      ip_set_reference_statement {
        arn = aws_wafv2_ip_set.office.arn
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "office-only"
      sampled_requests_enabled   = false
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "${local.name}-admin"
    sampled_requests_enabled   = false
  }
}

resource "aws_cloudwatch_log_group" "waf" {
  provider          = aws.us_east_1
  name              = "aws-waf-logs-${local.name}"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.logs_use1.arn
}

resource "aws_wafv2_web_acl_logging_configuration" "admin" {
  provider                = aws.us_east_1
  resource_arn            = aws_wafv2_web_acl.admin.arn
  log_destination_configs = [aws_cloudwatch_log_group.waf.arn]

  redacted_fields {
    single_header {
      name = "authorization"
    }
  }

  redacted_fields {
    single_header {
      name = "cookie"
    }
  }

  # 問い合わせの文字列（q は氏名の部分一致）を伏せる。パスは残す。API の契約で、パスには注文の id だけが入り、氏名は入らない。
  redacted_fields {
    query_string {}
  }
}
