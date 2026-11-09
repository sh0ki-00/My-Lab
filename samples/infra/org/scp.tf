# 口座の上限（SCP）と、資源の上限（RCP）。どれも検証環境と本番の口座の OU に付ける。1 枚の上限は 5,120 字。
# SCP は 6 枚（AWS の FullAWSAccess と合わせて 7 枚。OU に直接付けられる上限は 10 枚）。字数は skills/infra の作業で数えて、どれも 5,120 字の内側。
# 守りは「許す物の一覧」で書く（6 枚目の allow_list）。名指しで拒む一覧を伸ばすと、並べ忘れた型が毎回残るからである。
#   使うサービスの一覧: 一覧の外のサービス（App Runner、CloudShell など）は、名指ししなくても全部拒む（NotAction）。
#   主体の一覧: 名指しの役割と、2 つの許可セット（当番と緊急の管理）のほかの主体は、何もできない（root、管理の口座から借りる役割を含む）。
#   データへの入口の一覧: DB への IAM の接続、秘密の読み出し、データの鍵の直の復号は、それを使う役割だけ。
# 例外にする主体は、環境ごとの役割の名前で 1 つずつ名指しする（名前の型「*-apply」では名指ししない）。
#   適用の役割（承認 1 人）: 作業の定義の登録、サービスの更新だけ（plan-gate の一覧と同じ範囲）。データベースの変更は持たない。
#   守りの適用の役割（承認 2 人）と土台: 権限、方針、配信、WAF、監査と検出、作業の起動、移行と利用者づくりの役割の受け渡し、
#     データベースの作成と変更（大きさを含む）とパラメータグループ、秘密と鍵の別名、リポジトリの寿命、守りの関数（Lambda）、
#     VPC に入口を置く操作を変えられる。
#   土台（platform-foundation）だけ: 例外の名を持つ役割と、権限の境界と、口座の公開のブロックを変えられる。
# 例外の名を持つ役割は foundation/ が作り、SCP がそれ以外の主体に作らせない・変えさせない。同じ名の役割を作って例外に入る道は無い。
# この file を変えられるのは、組織の管理の口座だけ（信頼の根）。付け外しと書き換えは、守りの口座の org-guard-change が鳴らす。

locals {
  role      = "arn:aws:iam::*:role"
  envs      = var.workload_envs
  per_env   = { for s in ["plan", "apply", "apply-guarded", "restore", "backup", "db-bootstrap-execution"] : s => [for e in local.envs : "${local.role}/orders-admin-${e}-${s}"] }
  root_role = ["${local.role}/platform-foundation"]

  guard_roles     = concat(local.per_env["apply-guarded"], local.root_role)
  apply_roles     = concat(local.per_env["apply"], local.guard_roles)
  backup_roles    = local.per_env["backup"]
  restore_roles   = concat(local.per_env["restore"], local.per_env["backup"])
  protected_roles = flatten(values(local.per_env))
  boundaries      = [for e in local.envs : "arn:aws:iam::*:policy/orders-admin-${e}-boundary"]
  # 人の役割の型。path の段の数に頼らない（置き場の地域によって、sso.amazonaws.com の後に地域の段が入るときと入らないときがある）。
  # 許可セットの名前は完全一致で名指しする。役割の名前は AWSReservedSSO_<許可セットの名前>_<16 字の印> なので、名前の後ろを「_」と
  # 16 個の「?」で閉じる。orders-oncall- で始まる 3 つ目の許可セットは型に合わない。印の字数が違えば、当番と緊急の管理は
  # OnlyTwoHumanSets と OnlyNamedPrincipals で何もできなくなる（閉じる側に倒れる。未確定 20 で確かめる）。
  sso_base        = "${local.role}/aws-reserved/sso.amazonaws.com"
  sso_roles       = ["${local.sso_base}/*"]
  sso_suffix      = "_????????????????"
  oncall_roles    = flatten([for e in local.envs : ["${local.sso_base}/AWSReservedSSO_orders-oncall-${e}${local.sso_suffix}", "${local.sso_base}/*/AWSReservedSSO_orders-oncall-${e}${local.sso_suffix}"]])
  breakglass_role = flatten([for e in local.envs : ["${local.sso_base}/AWSReservedSSO_orders-breakglass-${e}${local.sso_suffix}", "${local.sso_base}/*/AWSReservedSSO_orders-breakglass-${e}${local.sso_suffix}"]])
  # 緊急の管理の、復旧に要る操作の一覧（設定を読む、データベースの再起動、作業の停止）。許可セットの方針（org/sso.tf）も同じ一覧だけを許す。
  # データの中身を読む操作（ログの中身、問い合わせの結果、Performance Insights、DB のログのファイル、管理の記録の履歴）は入れない。
  breakglass_actions = [
    "ec2:Describe*", "ecs:Describe*", "ecs:List*", "rds:Describe*", "rds:ListTagsForResource", "elasticloadbalancing:Describe*",
    "cloudwatch:Describe*", "cloudwatch:GetMetricData", "cloudwatch:GetMetricStatistics", "cloudwatch:ListMetrics",
    "logs:DescribeLogGroups", "logs:DescribeLogStreams", "logs:DescribeMetricFilters", "cloudtrail:DescribeTrails", "cloudtrail:GetTrailStatus", "iam:Get*", "iam:List*", "kms:DescribeKey", "kms:ListAliases",
    "backup:Describe*", "backup:List*", "lambda:GetFunctionConfiguration", "lambda:ListFunctions", "events:DescribeRule",
    "events:ListRules", "sns:ListSubscriptionsByTopic", "sns:GetSubscriptionAttributes", "sns:GetTopicAttributes",
    "wafv2:GetWebACL", "wafv2:ListWebACLs", "cloudfront:GetDistribution", "cloudfront:ListDistributions",
    "access-analyzer:ListFindings", "ecr:DescribeRepositories", "ecr:DescribeImages", "ecr:DescribeImageScanFindings",
    "inspector2:ListFindings", "secretsmanager:DescribeSecret", "secretsmanager:ListSecrets", "health:Describe*", "support:Describe*",
    "sts:GetCallerIdentity", "tag:GetResources", "ce:GetCostAndUsage", "rds:RebootDBInstance", "ecs:StopTask",
  ]
  # 承認 1 人の適用がサービスに付けてよい作業の定義は、API の family の版だけ（plan-gate の APPLY_VALUES と同じ）。
  api_task_defs = [for e in local.envs : "arn:aws:ecs:*:*:task-definition/orders-admin-${e}-orders-api:*"]
  # 移行と利用者づくりの役割（表の持ち主と、管理者の合言葉を読む役割）。渡せるのは守りの適用だけ。
  db_job_roles = flatten([for e in local.envs : [for s in ["db-migrate", "db-migrate-execution", "db-bootstrap-execution"] : "${local.role}/orders-admin-${e}-${s}"]])

  # ---- 許す物の一覧（6 枚目の allow_list）
  # 作業の口座で使うサービス。構成コード（samples/infra と foundation/）の資源と、動いている役割と人が呼ぶ操作の全部。
  # ここに無いサービスは、どの主体も使えない（App Runner、CloudShell、SSM、Kinesis、DynamoDB など）。足すときは守りの経路で足す。
  # Performance Insights（pi）も入れない。性能の記録には SQL の本文と、旧い書き手が文に埋めた値が入る（aws-facts の 31）。
  # 当番を含めて誰も読まない（第 13 回）。DB の負荷は CloudWatch の数の指標で見る。
  used_services = [
    "ec2:*", "ecs:*", "ecr:*", "rds:*", "rds-db:*", "logs:*", "cloudwatch:*", "events:*", "sns:*", "s3:*", "kms:*",
    "secretsmanager:*", "iam:*", "sts:*", "lambda:*", "backup:*", "backup-storage:*", "cloudtrail:*", "cloudfront:*", "wafv2:*",
    "elasticloadbalancing:*", "application-autoscaling:*", "route53resolver:*", "access-analyzer:*", "inspector2:*", "xray:*",
    "acm:*", "tag:*", "health:*", "support:*", "ce:*", "organizations:Describe*", "organizations:List*",
  ]
  # 作業の口座の役割（iam.tf と foundation/iam.tf）。役割を足したら、ここにも足す。足し忘れた役割は何もできない（閉じる側）。
  workload_roles = [
    "api-execution", "api-task", "flow-logs", "cloudtrail", "ci-push-api", "ci-push-db-jobs", "ci-push-static",
    "db-migrate-execution", "db-migrate", "copy-inventory", "plan", "apply", "apply-guarded", "restore", "backup", "db-bootstrap-execution",
    "alarm-forward",
  ]
  named_principals = concat(
    flatten([for e in local.envs : [for s in local.workload_roles : "${local.role}/orders-admin-${e}-${s}"]]),
    local.root_role, local.oncall_roles, local.breakglass_role,
  )
  # データへの入口を使う役割。DB への IAM の接続は API と移行の実行中の役割、秘密の読み出しは API と利用者づくりの起動の役割だけ。
  db_connect_roles  = flatten([for e in local.envs : [for s in ["api-task", "db-migrate"] : "${local.role}/orders-admin-${e}-${s}"]])
  secret_read_roles = flatten([for e in local.envs : [for s in ["api-execution", "db-bootstrap-execution"] : "${local.role}/orders-admin-${e}-${s}"]])
}

resource "aws_organizations_policy" "data_guard" {
  name        = "orders-admin-data-guard"
  description = "No sharing, export or replication out, no manual snapshots, restore only by the restore role, no network openings, log reads for oncall"
  type        = "SERVICE_CONTROL_POLICY"
  content = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # 複製の共有と写しに加えて、S3 への書き出し、別の地域への自動の複製、バケットの複製、ログの書き出しと転送、
        # 関数の公開の URL、作業の中への入り込みを、誰にも許さない。ログの転送は 3 つの型をまとめて拒む:
        # ロググループごとの購読、口座単位の方針（購読・変換・索引の型を含む PutAccountPolicy）、配送（Delivery の 4 操作）。
        Sid    = "NoSharingNoCopyOut"
        Effect = "Deny"
        Action = [
          "rds:ModifyDBSnapshotAttribute", "rds:ModifyDBClusterSnapshotAttribute", "rds:CopyDBSnapshot", "rds:CopyDBClusterSnapshot",
          "rds:StartExportTask", "rds:StartDBInstanceAutomatedBackupsReplication", "ec2:ModifySnapshotAttribute", "ec2:ModifyImageAttribute",
          "backup:StartCopyJob", "ram:CreateResourceShare", "s3:PutBucketReplication", "logs:CreateExportTask", "logs:PutSubscriptionFilter",
          "logs:PutDestination", "logs:PutDestinationPolicy", "lambda:CreateFunctionUrlConfig", "ecs:ExecuteCommand", "ssm:StartSession",
          "logs:PutAccountPolicy", "logs:DeleteAccountPolicy", "logs:PutDeliverySource", "logs:PutDeliveryDestination",
          "logs:PutDeliveryDestinationPolicy", "logs:CreateDelivery", "logs:UpdateDeliveryConfiguration",
        ]
        Resource = "*"
      },
      {
        # Lambda を呼べる相手は EventBridge だけ。外の口座に関数を呼ばせて、結果を受け取らせない。
        Sid       = "LambdaInvokedByEventsOnly"
        Effect    = "Deny"
        Action    = "lambda:AddPermission"
        Resource  = "*"
        Condition = { StringNotEquals = { "lambda:Principal" = "events.amazonaws.com" } }
      },
      {
        # データの境界。この口座の主体は、組織の外の資源へ書けない（外のバケット、通知、列、関数、イベントの宛先）。
        Sid    = "WritesStayInOrg"
        Effect = "Deny"
        Action = [
          "s3:PutObject", "sns:Publish", "sqs:SendMessage", "lambda:InvokeFunction", "events:PutEvents", "kinesis:PutRecord",
          "kinesis:PutRecords", "firehose:PutRecord", "firehose:PutRecordBatch",
        ]
        Resource  = "*"
        Condition = { StringNotEqualsIfExists = { "aws:ResourceOrgID" = var.org_id } }
      },
      {
        Sid       = "SnapshotsOnlyByBackup"
        Effect    = "Deny"
        Action    = ["rds:CreateDBSnapshot", "rds:CreateDBClusterSnapshot", "backup:StartBackupJob"]
        Resource  = "*"
        Condition = { ArnNotLike = { "aws:PrincipalArn" = local.backup_roles } }
      },
      {
        Sid    = "RestoreOnlyByRestoreRole"
        Effect = "Deny"
        Action = [
          "rds:RestoreDBInstanceFromDBSnapshot", "rds:RestoreDBInstanceToPointInTime", "rds:RestoreDBInstanceFromS3",
          "rds:RestoreDBClusterFromSnapshot", "rds:RestoreDBClusterToPointInTime", "backup:StartRestoreJob",
        ]
        Resource  = "*"
        Condition = { ArnNotLike = { "aws:PrincipalArn" = local.restore_roles } }
      },
      {
        Sid    = "NoNetworkOpenings"
        Effect = "Deny"
        Action = [
          "ec2:CreateInternetGateway", "ec2:AttachInternetGateway", "ec2:CreateEgressOnlyInternetGateway", "ec2:CreateNatGateway",
          "ec2:CreateVpcPeeringConnection", "ec2:AcceptVpcPeeringConnection", "ec2:CreateDefaultVpc", "ec2:CreateDefaultSubnet",
          "ec2:RunInstances", "ec2:CreateClientVpnEndpoint", "ec2:CreateVpnConnection", "ec2:AttachVpnGateway",
        ]
        Resource = "*"
      },
      {
        # データの中身を読む操作は、当番だけ。型でまとめて拒む: ログの中身（読み出し、問い合わせとその結果、実況、伏せ字の解除、
        # 異常の検知の見本の行）、WAF の見本の要求、データベースのログのファイル。Performance Insights は使うサービスの一覧の外で、
        # 管理の記録の履歴（LookupEvents）と問い合わせの一覧（DescribeQueries）は下の NoQueryHistory が当番にも拒む。
        # 計画と適用の役割は、自分の方針でも読めない（foundation/iam.tf）。緊急の管理も読めない。
        Sid    = "LogReadsOnlyForOncall"
        Effect = "Deny"
        Action = [
          "logs:GetLogEvents", "logs:FilterLogEvents", "logs:StartQuery", "logs:StartLiveTail", "logs:GetLogRecord",
          "logs:GetQueryResults", "logs:GetLogObject", "logs:CreateLogAnomalyDetector", "logs:ListAnomalies",
          "logs:GetLogAnomalyDetector", "wafv2:GetSampledRequests", "rds:DownloadDBLogFilePortion", "rds:DownloadCompleteDBLogFile",
          "cloudtrail:StartQuery", "cloudtrail:GetQueryResults",
        ]
        Resource  = "*"
        Condition = { ArnNotLike = { "aws:PrincipalArn" = local.oncall_roles } }
      },
      {
        # 伏せ字を外す操作は、当番も含めて誰にも許さない。外す必要が出たら、守りの経路で別に決める（未確定 28）。
        Sid      = "NoUnmask"
        Effect   = "Deny"
        Action   = "logs:Unmask"
        Resource = "*"
      },
      {
        # 当番も含めて誰にも許さない、数えない読み方（第 13 回）。DescribeQueries は同僚の問い合わせの文と queryId を返し、
        # GetQueryResults は queryId だけで結果を返す（aws-facts の 23 と 24）。LookupEvents は StartQuery の記録から queryId と文を返す。
        # 当番が読めるのは、自分で始めた問い合わせの結果だけになる（queryId は推せない）。数えるのは StartQuery の回数（oncall-queries-hourly）。
        Sid      = "NoQueryHistory"
        Effect   = "Deny"
        Action   = ["logs:DescribeQueries", "cloudtrail:LookupEvents"]
        Resource = "*"
      },
      {
        # 作業の口座の管理の記録（/<名前>/cloudtrail）と DNS の問い合わせの記録は、当番も含めて誰にも中身を読ませない（第 14 回）。
        # 管理の記録には同僚の StartQuery の queryId と文が残り、読めば GetQueryResults で同僚の結果を読み直せる。
        # 組織の記録は守りの口座にあり、そこで読むのは見張りの関数だけ（org/guard-core.tf の reads）。
        Sid    = "NoTrailAndDnsLogReads"
        Effect = "Deny"
        Action = [
          "logs:GetLogEvents", "logs:FilterLogEvents", "logs:StartQuery", "logs:StartLiveTail", "logs:GetLogRecord",
          "logs:GetLogObject", "logs:CreateExportTask", "logs:PutSubscriptionFilter",
        ]
        Resource  = ["arn:aws:logs:*:*:log-group:/orders-admin-*/cloudtrail*", "arn:aws:logs:*:*:log-group:/orders-admin-*/dns-queries*"]
        Condition = { ArnNotLike = { "aws:PrincipalArn" = local.guard_roles } }
      },
    ]
  })
}

resource "aws_organizations_policy" "control_guard" {
  name        = "orders-admin-control-guard"
  description = "Regions, key destruction, audit, policy, edge and guard tampering, long-lived keys"
  type        = "SERVICE_CONTROL_POLICY"
  content = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "OnlyAllowedRegions"
        Effect = "Deny"
        NotAction = [
          "iam:*", "sts:*", "organizations:*", "cloudfront:*", "route53:*", "support:*", "budgets:*", "ce:*",
          "health:*", "sso:*", "account:*",
        ]
        Resource  = "*"
        Condition = { StringNotEquals = { "aws:RequestedRegion" = var.allowed_regions } }
      },
      {
        Sid      = "NoKeyDestruction"
        Effect   = "Deny"
        Action   = ["kms:ScheduleKeyDeletion", "kms:DisableKey", "kms:DeleteImportedKeyMaterial"]
        Resource = "*"
      },
      {
        # 監査と検出を止める・書き換える操作（アラームの条件、記録の型、データベースのログの設定、ログの伏せ字と WAF の伏せ字を含む）と、
        # 資源の方針（鍵・秘密・バケット・保管庫・関数）を変える操作。配信と WAF を作る・変える操作。通知の宛先を外す操作。
        # 通知の経路（購読の絞り込み、話題の方針、ロググループの変換と鍵、アラームの状態）も同じ型で、ここに並べる。
        # どれも守りの適用の役割（承認 2 人）と土台のほかは拒む。WAF を付けない 2 本目の配信も、ここで作れない。
        Sid    = "GuardsOnlyFromGuardedApply"
        Effect = "Deny"
        Action = [
          "cloudtrail:StopLogging", "cloudtrail:DeleteTrail", "cloudtrail:UpdateTrail", "cloudtrail:PutEventSelectors",
          "kms:PutKeyPolicy", "kms:CreateKey", "secretsmanager:PutResourcePolicy", "secretsmanager:DeleteResourcePolicy",
          "s3:PutBucketPolicy", "s3:DeleteBucketPolicy", "s3:PutBucketPublicAccessBlock", "s3:PutBucketAcl", "s3:PutObjectAcl",
          "backup:PutBackupVaultAccessPolicy", "backup:DeleteBackupVaultAccessPolicy", "lambda:AddPermission",
          "logs:DeleteLogGroup", "logs:DeleteMetricFilter", "logs:PutMetricFilter", "cloudwatch:PutMetricAlarm", "events:PutRule",
          "events:PutTargets", "events:DisableRule", "events:DeleteRule", "events:RemoveTargets", "logs:DeleteDataProtectionPolicy", "logs:PutRetentionPolicy",
          "logs:DeleteRetentionPolicy", "cloudwatch:DeleteAlarms", "cloudwatch:DisableAlarmActions", "sns:DeleteTopic", "sns:Subscribe",
          "sns:SetTopicAttributes", "access-analyzer:DeleteAnalyzer", "route53resolver:DisassociateFirewallRuleGroup",
          "route53resolver:UpdateFirewallConfig", "route53resolver:DisassociateResolverQueryLogConfig",
          "cloudfront:CreateDistribution", "cloudfront:CreateDistributionWithTags", "cloudfront:CopyDistribution",
          "cloudfront:UpdateDistribution", "cloudfront:CreateVpcOrigin", "cloudfront:UpdateVpcOrigin",
          "cloudfront:UpdateResponseHeadersPolicy", "wafv2:UpdateWebACL", "wafv2:DeleteWebACL", "wafv2:UpdateIPSet",
          "wafv2:AssociateWebACL", "wafv2:DisassociateWebACL", "wafv2:DeleteLoggingConfiguration", "wafv2:PutLoggingConfiguration",
          "logs:PutDataProtectionPolicy", "logs:PutResourcePolicy", "sns:Unsubscribe", "sns:SetSubscriptionAttributes",
          "sns:PutDataProtectionPolicy", "sns:AddPermission", "sns:RemovePermission", "logs:PutTransformer", "logs:DeleteTransformer",
          "logs:AssociateKmsKey", "logs:DisassociateKmsKey", "cloudwatch:PutCompositeAlarm", "cloudwatch:SetAlarmState",
        ]
        Resource  = "*"
        Condition = { ArnNotLike = { "aws:PrincipalArn" = local.guard_roles } }
      },
      {
        Sid      = "NoLongLivedKeys"
        Effect   = "Deny"
        Action   = ["iam:CreateUser", "iam:CreateAccessKey", "iam:CreateLoginProfile", "organizations:LeaveOrganization"]
        Resource = "*"
      },
    ]
  })
}

# データへ届く操作は、名指しの役割のほかに拒む（4 枚目）。plan-gate の「承認 1 人の一覧」と同じ範囲だけを適用の役割に残す。
#   適用の役割（承認 1 人）: 作業の定義の登録、サービスの作成と更新、役割の受け渡し（API の役割だけ）。
#   守りの適用の役割（承認 2 人）: データベースの作成と変更（rds:ModifyDBInstance。大きさの変更も。IAM の条件キーで大きさだけに絞れない）、
#     作業の起動、移行と利用者づくりの役割の受け渡し、パラメータグループ、秘密と鍵の別名、
#     リポジトリの寿命と削除、守りの関数（棚卸しの Lambda）。リポジトリを外へ開く方針と複製は、土台のほかに誰にも許さない。
resource "aws_organizations_policy" "path_guard" {
  name        = "orders-admin-path-guard"
  description = "Data paths only from named roles: tasks, services, pass role, database settings, secrets, repositories, guard functions"
  type        = "SERVICE_CONTROL_POLICY"
  content = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "TasksAndServicesOnlyFromApply"
        Effect = "Deny"
        Action = [
          "ecs:RegisterTaskDefinition", "ecs:DeregisterTaskDefinition", "ecs:CreateService", "ecs:UpdateService", "ecs:DeleteService",
          "ecs:CreateTaskSet", "ecs:UpdateTaskSet", "ecs:UpdateServicePrimaryTaskSet",
        ]
        Resource  = "*"
        Condition = { ArnNotLike = { "aws:PrincipalArn" = local.apply_roles } }
      },
      {
        # サービスに付けてよい作業の定義は、承認 1 人の適用でも API の family の版だけ。移行と利用者づくりの版をサービスで動かす道を拒む。
        # 条件キー ecs:task-definition が要求に無いときも、否定の条件は真になり拒否になる（安全側。未確定 9 で確かめる）。
        Sid       = "ServicesRunApiFamilyOnly"
        Effect    = "Deny"
        Action    = ["ecs:CreateService", "ecs:UpdateService", "ecs:CreateTaskSet"]
        Resource  = "*"
        Condition = { StringNotLike = { "ecs:task-definition" = local.api_task_defs }, ArnNotLike = { "aws:PrincipalArn" = local.guard_roles } }
      },
      {
        Sid       = "PassRoleOnlyFromApply"
        Effect    = "Deny"
        Action    = "iam:PassRole"
        Resource  = "*"
        Condition = { ArnNotLike = { "aws:PrincipalArn" = concat(local.apply_roles, local.restore_roles) } }
      },
      {
        # 移行（表の持ち主）と利用者づくり（管理者の合言葉）の役割を渡す操作と、作業の起動は、守りの適用だけ。
        Sid       = "DbJobRolesOnlyFromGuarded"
        Effect    = "Deny"
        Action    = "iam:PassRole"
        Resource  = local.db_job_roles
        Condition = { ArnNotLike = { "aws:PrincipalArn" = local.guard_roles } }
      },
      {
        # データベースを作る・変える（rds:ModifyDBInstance は大きさのつもりの 1 回で合言葉・公開・網・削除の保護・保持の日数まで変わり、
        # IAM の条件キーで大きさだけに絞れない。aws-facts の 47〜52）、パラメータグループを作る・変える・付け替える（ログの設定を既定に戻す道）、
        # 秘密の値と鍵の別名、リポジトリの寿命と削除、守りの関数、作業の起動、DB に役割を付ける操作（aws_s3 と aws_lambda の拡張から
        # 外へ出す道。第 15 回）。どれも守りの適用の役割だけ。
        Sid    = "GuardedDataSettings"
        Effect = "Deny"
        Action = [
          "ecs:RunTask", "ecs:StartTask", "rds:CreateDBInstance", "rds:ModifyDBInstance", "rds:CreateDBCluster", "rds:ModifyDBCluster",
          "rds:CreateDBInstanceReadReplica", "rds:CreateDBParameterGroup", "rds:ModifyDBParameterGroup", "rds:ResetDBParameterGroup",
          "secretsmanager:CreateSecret", "secretsmanager:PutSecretValue", "secretsmanager:UpdateSecret", "secretsmanager:RotateSecret",
          "secretsmanager:CancelRotateSecret", "secretsmanager:DeleteSecret", "secretsmanager:UpdateSecretVersionStage",
          "kms:CreateAlias", "kms:UpdateAlias", "kms:DeleteAlias", "ecr:PutLifecyclePolicy", "ecr:DeleteLifecyclePolicy",
          "ecr:PutImageTagMutability", "ecr:DeleteRepository", "ecr:BatchDeleteImage", "ecr:PutRegistryScanningConfiguration",
          "lambda:CreateFunction", "lambda:UpdateFunctionCode", "lambda:UpdateFunctionConfiguration", "lambda:DeleteFunction",
          "lambda:PutFunctionConcurrency", "lambda:DeleteFunctionConcurrency", "lambda:PutFunctionEventInvokeConfig",
          "rds:AddRoleToDBInstance", "rds:AddRoleToDBCluster",
        ]
        Resource  = "*"
        Condition = { ArnNotLike = { "aws:PrincipalArn" = local.guard_roles } }
      },
      {
        # パラメータグループの名指し（付け替え）は守りの適用だけ。データベースの変更そのものも上で守りの適用だけにしたので、2 重の錠。
        Sid       = "DbParameterGroupOnlyFromGuarded"
        Effect    = "Deny"
        Action    = ["rds:ModifyDBInstance", "rds:CreateDBInstance"]
        Resource  = "arn:aws:rds:*:*:pg:*"
        Condition = { ArnNotLike = { "aws:PrincipalArn" = local.guard_roles } }
      },
      {
        # 合言葉を RDS の管理から外す変更（外せば、既知の値で上書きできる）は、どの役割にも許さない。
        Sid       = "KeepManagedMasterPassword"
        Effect    = "Deny"
        Action    = ["rds:ModifyDBInstance", "rds:CreateDBInstance"]
        Resource  = "*"
        Condition = { Bool = { "rds:ManageMasterUserPassword" = "false" } }
      },
      {
        # イメージのリポジトリを外へ開く方針、複製、外のイメージの取り込みは、土台のほかに誰にも許さない（RCP の外の型）。
        Sid       = "NoImageSharing"
        Effect    = "Deny"
        Action    = ["ecr:SetRepositoryPolicy", "ecr:PutRegistryPolicy", "ecr:PutReplicationConfiguration", "ecr:CreatePullThroughCacheRule"]
        Resource  = "*"
        Condition = { ArnNotLike = { "aws:PrincipalArn" = local.root_role } }
      },
    ]
  })
}

# 入口と緊急の管理の上限（5 枚目）。起点ごとに型で答える。
#   緊急の管理: 復旧に要る操作の一覧（設定を読む、データベースの再起動、作業の停止）の外を、すべて拒む（NotAction）。
#     役割の ARN の型は path の段の数に頼らない（sso.amazonaws.com/*AWSReservedSSO_...）。地域の段が無くても縛りが外れない。
#     人の許可セットは 2 つだけで、ほかの許可セットの役割は何もできない（OnlyTwoHumanSets）。
#     データの中身を読む操作は、一覧に入れても 1 枚目の LogReadsOnlyForOncall が先に拒む（明示の拒否が勝つ）。
#     使った瞬間に、守りの口座が組織の CloudTrail から拾って鳴らす（security/ の breakglass-used）。作業の口座からは止められない。
#   入口: 受ける通信の規則、窓口、ロードバランサーの受け口、API Gateway、経路、ネットワークのインターフェース、
#     Verified Access の端点、VPC のコネクタは、守りの適用の役割と土台のほかに拒む（VPC に入口を置く操作の一覧）。
#     ECS と RDS とロードバランサーが置くインターフェースは、サービスにリンクされた役割が作るので、SCP は掛からない。
#   データを消す操作: データベースとクラスタと保管庫を消す操作は、訓練の写し（名前が -restore-）のほかは誰にも許さない。
resource "aws_organizations_policy" "entry_guard" {
  name        = "orders-admin-entry-guard"
  description = "Break-glass is limited to recovery actions; network entrances only from the guarded apply; no data deletion"
  type        = "SERVICE_CONTROL_POLICY"
  content = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "BreakglassRecoveryOnly"
        Effect    = "Deny"
        NotAction = local.breakglass_actions
        Resource  = "*"
        Condition = { ArnLike = { "aws:PrincipalArn" = local.breakglass_role } }
      },
      {
        # 人の入口は、当番と緊急の管理の 2 つの許可セットだけ。ほかの許可セットを足されても、その役割は何もできない。
        Sid       = "OnlyTwoHumanSets"
        Effect    = "Deny"
        Action    = "*"
        Resource  = "*"
        Condition = { ArnLike = { "aws:PrincipalArn" = local.sso_roles }, ArnNotLike = { "aws:PrincipalArn" = concat(local.oncall_roles, local.breakglass_role) } }
      },
      {
        Sid    = "NetworkEntrancesOnlyFromGuarded"
        Effect = "Deny"
        Action = [
          "ec2:AuthorizeSecurityGroupIngress", "ec2:AuthorizeSecurityGroupEgress", "ec2:ModifySecurityGroupRules",
          "ec2:CreateVpcEndpoint", "ec2:ModifyVpcEndpoint", "ec2:CreateVpcEndpointServiceConfiguration",
          "ec2:ModifyVpcEndpointServicePermissions", "ec2:CreateRoute", "ec2:ReplaceRoute", "ec2:AssociateRouteTable",
          "ec2:CreateTransitGatewayVpcAttachment", "ec2:ModifyNetworkInterfaceAttribute", "elasticloadbalancing:CreateLoadBalancer",
          "elasticloadbalancing:CreateListener", "elasticloadbalancing:ModifyListener", "elasticloadbalancing:CreateRule",
          "elasticloadbalancing:ModifyRule", "elasticloadbalancing:SetSecurityGroups", "elasticloadbalancing:SetSubnets",
          "apigateway:POST", "apigateway:PUT", "apigateway:PATCH", "vpc-lattice:*", "globalaccelerator:*",
          "ec2:CreateNetworkInterface", "ec2:CreateNetworkInterfacePermission", "ec2:AttachNetworkInterface",
          "ec2:CreateVerifiedAccess*", "ec2:ModifyVerifiedAccess*", "ec2:AttachVerifiedAccessTrustProvider",
          "apprunner:CreateVpcConnector", "apprunner:CreateVpcIngressConnection",
        ]
        Resource  = "*"
        Condition = { ArnNotLike = { "aws:PrincipalArn" = local.guard_roles } }
      },
      {
        Sid    = "NoDataDeletion"
        Effect = "Deny"
        Action = [
          "rds:DeleteDBInstance", "rds:DeleteDBCluster", "rds:DeleteDBInstanceAutomatedBackup", "backup:DeleteRecoveryPoint",
          "backup:DeleteBackupVault", "backup:DeleteBackupVaultLockConfiguration",
        ]
        NotResource = [for e in local.envs : "arn:aws:rds:*:*:db:orders-admin-${e}-restore-*"]
      },
    ]
  })
}

resource "aws_organizations_policy" "identity_guard" {
  name        = "orders-admin-identity-guard"
  description = "Roles only from the guarded apply, always with the boundary; exempt roles, boundary and account settings only from the foundation"
  type        = "SERVICE_CONTROL_POLICY"
  content = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "IamOnlyFromGuardedApply"
        Effect = "Deny"
        Action = [
          "iam:CreateRole", "iam:DeleteRole", "iam:UpdateAssumeRolePolicy", "iam:PutRolePolicy", "iam:DeleteRolePolicy",
          "iam:AttachRolePolicy", "iam:DetachRolePolicy", "iam:PutRolePermissionsBoundary", "iam:DeleteRolePermissionsBoundary",
          "iam:CreatePolicy", "iam:CreatePolicyVersion", "iam:SetDefaultPolicyVersion", "iam:TagRole", "iam:UntagRole",
          "iam:CreateOpenIDConnectProvider", "iam:UpdateOpenIDConnectProviderThumbprint", "iam:AddClientIDToOpenIDConnectProvider",
        ]
        Resource  = "*"
        Condition = { ArnNotLike = { "aws:PrincipalArn" = local.guard_roles } }
      },
      {
        # 作る役割と書き換える役割には、権限の境界が付いていること。境界の無い役割は、土台のほかに誰も作れない。
        Sid    = "RolesNeedBoundary"
        Effect = "Deny"
        Action = [
          "iam:CreateRole", "iam:PutRolePolicy", "iam:DeleteRolePolicy", "iam:AttachRolePolicy", "iam:DetachRolePolicy",
          "iam:PutRolePermissionsBoundary",
        ]
        Resource = "*"
        Condition = {
          StringNotLike = { "iam:PermissionsBoundary" = local.boundaries }
          ArnNotLike    = { "aws:PrincipalArn" = local.root_role }
        }
      },
      {
        # 例外の名を持つ役割（計画・適用・守りの適用・復元・バックアップ・利用者づくり）と境界は、土台だけが変えられる。
        Sid    = "ExemptRolesOnlyFromFoundation"
        Effect = "Deny"
        Action = [
          "iam:CreateRole", "iam:DeleteRole", "iam:UpdateAssumeRolePolicy", "iam:PutRolePolicy", "iam:DeleteRolePolicy",
          "iam:AttachRolePolicy", "iam:DetachRolePolicy", "iam:PutRolePermissionsBoundary", "iam:DeleteRolePermissionsBoundary",
          "iam:TagRole", "iam:UntagRole", "iam:CreatePolicyVersion", "iam:SetDefaultPolicyVersion", "iam:DeletePolicy",
          "iam:DeletePolicyVersion",
        ]
        Resource  = concat(local.protected_roles, local.boundaries)
        Condition = { ArnNotLike = { "aws:PrincipalArn" = local.root_role } }
      },
      {
        Sid       = "AccountPublicBlockOnlyFromFoundation"
        Effect    = "Deny"
        Action    = ["s3:PutAccountPublicAccessBlock"]
        Resource  = "*"
        Condition = { ArnNotLike = { "aws:PrincipalArn" = local.root_role } }
      },
    ]
  })
}

# 許す物の一覧（6 枚目）。起点を 1 つずつ拒まず、許す物を並べて、ほかを全部拒む。
#   OnlyUsedServices: 使うサービスの一覧の外を、どの主体にも許さない。CloudShell と App Runner と、まだ見ていないサービスも止まる。
#   OnlyNamedPrincipals: 名指しの役割と 2 つの許可セットのほかの主体（root、管理の口座から借りる役割、ほかの許可セット）は何もできない。
#     サービスにリンクされた役割には SCP が掛からない（AWS の決まり）。そのため ECS と RDS の動きは止まらない。
#     root の利用と、一覧の外の役割を借りたことは、守りの口座が組織の記録から鳴らす（security/watch.tf の breakglass-used と outside-principal）。
#   DataEntrancesOnlyForUsers: DB への IAM の接続と秘密の読み出しは、使う役割だけ。データの鍵は、RDS・秘密・イメージ・バックアップの
#     サービスを通すときだけ復号できる。直の復号は誰にも許さない（中身を手で解く道を閉じる）。
resource "aws_organizations_policy" "allow_list" {
  name        = "orders-admin-allow-list"
  description = "Only used services, only named principals, data entrances only for the roles that use them"
  type        = "SERVICE_CONTROL_POLICY"
  content = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "OnlyUsedServices"
        Effect    = "Deny"
        NotAction = local.used_services
        Resource  = "*"
      },
      {
        Sid       = "OnlyNamedPrincipals"
        Effect    = "Deny"
        Action    = "*"
        Resource  = "*"
        Condition = { ArnNotLike = { "aws:PrincipalArn" = local.named_principals } }
      },
      {
        Sid       = "DbConnectOnlyForApiAndMigrate"
        Effect    = "Deny"
        Action    = "rds-db:connect"
        Resource  = "*"
        Condition = { ArnNotLike = { "aws:PrincipalArn" = local.db_connect_roles } }
      },
      {
        Sid       = "SecretReadsOnlyForUsers"
        Effect    = "Deny"
        Action    = ["secretsmanager:GetSecretValue", "secretsmanager:BatchGetSecretValue"]
        Resource  = "*"
        Condition = { ArnNotLike = { "aws:PrincipalArn" = local.secret_read_roles } }
      },
      {
        Sid      = "DataKeyOnlyThroughServices"
        Effect   = "Deny"
        Action   = ["kms:Decrypt", "kms:ReEncryptFrom"]
        Resource = "*"
        Condition = {
          "ForAnyValue:StringLike" = { "kms:ResourceAliases" = [for e in local.envs : "alias/orders-admin-${e}-data"] }
          StringNotLikeIfExists    = { "kms:ViaService" = ["rds.*.amazonaws.com", "secretsmanager.*.amazonaws.com", "ecr.*.amazonaws.com", "backup.*.amazonaws.com"] }
        }
      },
    ]
  })
}

# 資源の上限（RCP）。バケット・鍵・秘密・列と、役割の借り受けを、組織の外の主体に使わせない。
# 移行と利用者づくりの役割は、組織の中の主体にも借りさせない（ECS の作業だけ）。
# バケットの方針や鍵の方針に外の口座を書いても、外の口座からは読めない。AWS のサービス（CloudTrail、CloudFront など）は外す。
resource "aws_organizations_policy" "resource_perimeter" {
  name        = "orders-admin-resource-perimeter"
  description = "Only principals of this organization may use buckets, keys, secrets, queues and role assumption"
  type        = "RESOURCE_CONTROL_POLICY"
  content = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "OrgPrincipalsOnly"
        Effect    = "Deny"
        Principal = "*"
        # logs:* も入れる（第 14 回）。ロググループの資源の方針で外の口座の主体に読み出し（GetLogEvents、FilterLogEvents、StartQuery）を
        # 許しても、外の主体は使えない。RCP は CloudWatch Logs に効く（aws-facts の 1）。守りの口座にも付ける（guard-core.tf）。
        Action   = ["s3:*", "kms:*", "secretsmanager:*", "sqs:*", "logs:*", "sts:AssumeRole"]
        Resource = "*"
        Condition = {
          StringNotEqualsIfExists = { "aws:PrincipalOrgID" = var.org_id }
          BoolIfExists            = { "aws:PrincipalIsAWSService" = "false" }
        }
      },
      {
        # 表の持ち主（orders_migrate）と管理者の合言葉を使う役割は、ECS の作業のほかは借りられない。組織の中の主体
        # （管理の口座から来る主体を含む）でも借りられない。信頼の方針を書き換えても、この上限は外れない。
        Sid       = "DbJobRolesOnlyForEcsTasks"
        Effect    = "Deny"
        Principal = "*"
        Action    = ["sts:AssumeRole", "sts:AssumeRoleWithWebIdentity", "sts:AssumeRoleWithSAML"]
        Resource  = local.db_job_roles
        Condition = { BoolIfExists = { "aws:PrincipalIsAWSService" = "false" } }
      },
    ]
  })
}

resource "aws_organizations_policy_attachment" "data_guard" {
  policy_id = aws_organizations_policy.data_guard.id
  target_id = var.workload_ou_id
}

resource "aws_organizations_policy_attachment" "control_guard" {
  policy_id = aws_organizations_policy.control_guard.id
  target_id = var.workload_ou_id
}

resource "aws_organizations_policy_attachment" "path_guard" {
  policy_id = aws_organizations_policy.path_guard.id
  target_id = var.workload_ou_id
}

resource "aws_organizations_policy_attachment" "entry_guard" {
  policy_id = aws_organizations_policy.entry_guard.id
  target_id = var.workload_ou_id
}

resource "aws_organizations_policy_attachment" "identity_guard" {
  policy_id = aws_organizations_policy.identity_guard.id
  target_id = var.workload_ou_id
}

resource "aws_organizations_policy_attachment" "allow_list" {
  policy_id = aws_organizations_policy.allow_list.id
  target_id = var.workload_ou_id
}

resource "aws_organizations_policy_attachment" "resource_perimeter" {
  policy_id = aws_organizations_policy.resource_perimeter.id
  target_id = var.workload_ou_id
}

# 組織の CloudTrail を、守りの口座に任せる（委任された管理者）。組織の記録は作業の口座の管理者には止められない。
# 記録と通知の本体は security/（守りの口座）にある。
resource "aws_organizations_delegated_administrator" "cloudtrail" {
  account_id        = var.security_account_id
  service_principal = "cloudtrail.amazonaws.com"
}
