# アプリの層。内部のロードバランサーと注文 API（ECS Fargate）。公開のアドレスを持たない。

resource "aws_lb" "api" {
  name                       = "${local.name}-api"
  internal                   = true
  load_balancer_type         = "application"
  subnets                    = aws_subnet.app[*].id
  security_groups            = [aws_security_group.alb.id]
  drop_invalid_header_fields = true
  enable_deletion_protection = true
}

resource "aws_lb_target_group" "api" {
  name        = "${local.name}-api"
  port        = 8080
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id

  health_check {
    path    = "/healthz"
    matcher = "200"
  }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.api.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.api_certificate_arn

  # 決めたパスの外は 404 で返す。CloudFront は /api/* をそのまま渡すので、API が受けるパスは /api/v1/ で始まる。
  # WAF の量の上限（/api/v1/orders）は、API が受けるパスと同じ文字列を見る。
  default_action {
    type = "fixed-response"
    fixed_response {
      content_type = "application/json"
      status_code  = "404"
      message_body = "{\"error\":\"not_found\"}"
    }
  }
}

resource "aws_lb_listener_rule" "api_v1" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 10

  condition {
    path_pattern {
      values = ["/api/v1/*"]
    }
  }

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

resource "aws_ecr_repository" "api" {
  name                 = "${local.name}/orders-api"
  image_tag_mutability = "IMMUTABLE"

  # 押し込みのときの検査。配備した後に見つかった穴は、下の継続の検査（Amazon Inspector）が拾う。
  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.data.arn
  }
}

# 利用者づくり専用のイメージ。中身は PostgreSQL の利用者の道具と db/roles.sql だけで、API の部品は入れない。
# 管理者の合言葉を受け取るのはこのイメージだけなので、API の部品が乗っ取られても合言葉には届かない。
resource "aws_ecr_repository" "db_bootstrap" {
  name                 = "${local.name}/db-bootstrap"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.data.arn
  }
}

# 移行専用のイメージ。中身は PostgreSQL の道具と、バックエンドの移行の SQL と、決まった流し方だけで、API の部品（npm）は入れない。
# 移行は表の持ち主（orders_migrate、RLS を受けない）として動くので、API の部品が乗っ取られても、ここへは届かない。
# 押し込めるのは db-image-push.yml（守りの環境、承認 2 人）の役割だけで、API のビルドの役割は押し込めない（iam.tf）。
resource "aws_ecr_repository" "db_migrate" {
  name                 = "${local.name}/db-migrate"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.data.arn
  }
}

# DB の 2 つの像は、守りの口座の出来事ごとの見張り（event_watch.py）が、押し込みのたびに層を自分で開いて main と照らす（第 15 回）。
# 許すのは、その 1 つの役割の読み出しだけ。作業の口座の役割は借りないので、名指しの主体の一覧（SCP）は変えない。
# 方針を変えられるのは守りの適用だけ（SCP の ecr:SetRepositoryPolicy）。外の主体は RCP が拒む。
resource "aws_ecr_repository_policy" "db_images_guard_read" {
  for_each   = { db_bootstrap = aws_ecr_repository.db_bootstrap.name, db_migrate = aws_ecr_repository.db_migrate.name }
  repository = each.value
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "GuardEventWatchReadsLayers"
      Effect    = "Allow"
      Principal = { AWS = var.guard_event_watch_role_arn }
      Action    = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
    }]
  })
}

# 古いイメージを残さない。札の無いイメージは 7 日で消し、札つきは新しい 10 個だけ残す（古い版を選んで動かす道を細くする）。
# 動いている作業の定義が指すダイジェストは、配備のたびに新しい物へ替わる。規則を変えられるのは守りの適用だけ（SCP）。
resource "aws_ecr_lifecycle_policy" "keep_recent" {
  for_each = {
    api          = aws_ecr_repository.api.name
    db_bootstrap = aws_ecr_repository.db_bootstrap.name
    db_migrate   = aws_ecr_repository.db_migrate.name
  }
  repository = each.value
  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged images after 7 days"
        selection    = { tagStatus = "untagged", countType = "sinceImagePushed", countUnit = "days", countNumber = 7 }
        action       = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Keep the 10 most recent images"
        selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 10 }
        action       = { type = "expire" }
      },
    ]
  })
}

# 継続の検査。新しい穴の情報が出るたびに、配備中のイメージを検査し直す。HIGH 以上は guardrails.tf が通知する。
resource "aws_ecr_registry_scanning_configuration" "main" {
  scan_type = "ENHANCED"

  rule {
    scan_frequency = "CONTINUOUS_SCAN"
    repository_filter {
      filter      = "${local.name}/*"
      filter_type = "WILDCARD"
    }
  }
}

resource "aws_ecs_cluster" "main" {
  name = local.name

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/${local.name}/orders-api"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.logs.arn
}

# 配送会社の API の鍵は置かない。この構成には外の宛先へ出る道が無く、API は外を呼ばない（バックエンドの計画）。
# 呼ぶと決めたら、宛先を固定した出口を別の設計で足す（NAT とインターネットゲートウェイは SCP が拒む）。

resource "aws_secretsmanager_secret" "session_signing_key" {
  name                    = "${local.name}/session-signing-key"
  description             = "管理画面のセッションの署名の鍵。値は回転の仕組みが入れる"
  kms_key_id              = aws_kms_key.data.arn
  recovery_window_in_days = 30
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${local.name}-orders-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.api_execution.arn
  task_role_arn            = aws_iam_role.api_task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

  container_definitions = jsonencode([
    {
      name                   = "orders-api"
      image                  = "${aws_ecr_repository.api.repository_url}@${var.api_image_digest}"
      essential              = true
      user                   = "10001"
      readonlyRootFilesystem = true
      portMappings           = [{ containerPort = 8080, protocol = "tcp" }]
      environment = [
        { name = "DB_HOST", value = aws_db_instance.orders.address },
        { name = "DB_NAME", value = "orders" },
        { name = "DB_USER", value = "orders_api" },
        { name = "DB_IAM_AUTH", value = "true" },
        { name = "API_TIMEOUT_SECONDS", value = "8" },
        { name = "AUTH_ISSUER_URL", value = var.user_auth_issuer_url },
      ]
      secrets = [
        { name = "SESSION_SIGNING_KEY", valueFrom = aws_secretsmanager_secret.session_signing_key.arn },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.api.name
          awslogs-region        = var.region
          awslogs-stream-prefix = "api"
        }
      }
    },
  ])
}

resource "aws_ecs_service" "api" {
  name            = "orders-api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.api_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.app[*].id
    security_groups  = [aws_security_group.api.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "orders-api"
    container_port   = 8080
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
}

resource "aws_appautoscaling_target" "api" {
  service_namespace  = "ecs"
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.api.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  min_capacity       = var.api_desired_count
  max_capacity       = var.api_max_count
}

resource "aws_appautoscaling_policy" "api_cpu" {
  name               = "${local.name}-api-cpu"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = aws_appautoscaling_target.api.service_namespace
  resource_id        = aws_appautoscaling_target.api.resource_id
  scalable_dimension = aws_appautoscaling_target.api.scalable_dimension

  target_tracking_scaling_policy_configuration {
    target_value = 60
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}

# ---- データベースの中の利用者づくり（最初の 1 回）と、移行（スキーマを変えるリリースごと）。どちらも ECS の 1 回だけの作業。
# どちらも守りの適用の役割（承認 2 人）だけが起動する（SCP が作業の起動と、移行と利用者づくりの役割の受け渡しを、ほかに拒む）。
# 利用者づくりは専用のイメージで db/roles.sql を流し、最後に権限の一覧を確かめる。終わったら管理者の合言葉を 1 回回す。
# 移行は専用のイメージ（API の部品なし）で動く。起動する版は CI が状態から読んだ 1 つで、命令や環境変数の上書きは使わない。
# ログは作業ごとに別のロググループに置く。読めるのは当番だけ（SCP）。

resource "aws_cloudwatch_log_group" "db_bootstrap" {
  name              = "/${local.name}/db-jobs/bootstrap"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.logs.arn
}

resource "aws_cloudwatch_log_group" "db_migrate" {
  name              = "/${local.name}/db-jobs/migrate"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.logs.arn
}

resource "aws_ecs_task_definition" "db_bootstrap" {
  family                   = "${local.name}-db-bootstrap"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = local.bootstrap_role

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

  container_definitions = jsonencode([
    {
      name                   = "db-bootstrap"
      image                  = "${aws_ecr_repository.db_bootstrap.repository_url}@${var.db_bootstrap_image_digest}"
      essential              = true
      user                   = "10001"
      readonlyRootFilesystem = true
      environment = [
        { name = "DB_HOST", value = aws_db_instance.orders.address },
        { name = "DB_NAME", value = "orders" },
        { name = "DB_ADMIN_USER", value = "orders_admin" },
      ]
      secrets = [
        { name = "DB_ADMIN_CREDENTIAL", valueFrom = "${aws_db_instance.orders.master_user_secret[0].secret_arn}:password::" },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.db_bootstrap.name
          awslogs-region        = var.region
          awslogs-stream-prefix = "bootstrap"
        }
      }
    },
  ])
}

resource "aws_ecs_task_definition" "db_migrate" {
  family                   = "${local.name}-db-migrate"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.db_migrate_execution.arn
  task_role_arn            = aws_iam_role.db_migrate.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

  container_definitions = jsonencode([
    {
      name                   = "db-migrate"
      image                  = "${aws_ecr_repository.db_migrate.repository_url}@${var.db_migrate_image_digest}"
      essential              = true
      user                   = "10001"
      readonlyRootFilesystem = true
      environment = [
        { name = "DB_HOST", value = aws_db_instance.orders.address },
        { name = "DB_NAME", value = "orders" },
        { name = "DB_USER", value = "orders_migrate" },
        { name = "DB_IAM_AUTH", value = "true" },
        # 移行の SQL を流す役割（正本の owner。db/migrate-run.sh が SET ROLE する）。最後に突き合わせ（guard.check_all）を回す。
        { name = "DB_TABLE_OWNER", value = var.db_table_owner },
        { name = "AWS_REGION", value = var.region },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.db_migrate.name
          awslogs-region        = var.region
          awslogs-stream-prefix = "migrate"
        }
      }
    },
  ])
}
