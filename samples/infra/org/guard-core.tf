# 守りの口座の芯（guard core）。守りの口座へ適用する CI（orders-guard-apply）が届かない所に、その CI の役割と信頼と、
# その CI と見張りの変更を鳴らす経路を置く。守りの口座の見張りを、見張られる CI の 1 回で黙らせる道（PutMetricAlarm で宛先を空にする、
# 購読を外す、自分の信頼に別のリポジトリを足す）を、型で閉じる。
#   置き場: 守りの口座の中の物（CI の役割、出来事の転送の規則と役割、Access Analyzer、毎時の便り）は、組織の StackSet が置く。
#     StackSet を変えられるのは管理の口座の土台の CI（org-guarded）だけで、変えたら trust-root-used が鳴る（信頼の根）。
#     鳴る先は管理の口座のバスと話題で、宛先は AWS の外（メールと呼び出しの窓口）。守りの口座の誰も、宛先と経路に触れない。
#   守りの口座の上限（SCP の orders-guard-core。守りの口座に直に付ける）:
#     orders-guard-apply と orders-guard-core-* の役割の信頼・方針・境界を、守りの口座の誰にも変えさせない。StackSet の実行が SCP を受けるかは
#     未確定 20 の (3) で、どちらでも閉じる側に揃える。受けないなら StackSet は SCP の外の道なので、管理の口座の書き込みと StackSet の操作を
#     1 件ずつ鳴らす（security/watch.tf の trust-root-used と stackset-change、event-watch）。受けるなら芯の置き直しが拒まれて落ち、適用の失敗で分かる。
#     芯の規則・Access Analyzer・芯のスタックを止めも変えもさせない。記録を止める・消す操作も拒む。
#     管理の方針は ReadOnlyAccess と守りの口座の orders-guard-* の外を付けさせない（AdministratorAccess を付ける手）。
#     orders-guard-apply には、ログの中身と問い合わせ、管理の記録の履歴、記録と印の中身、秘密の値、復号を許さない。
#   外の主体: 組織の RCP（resource_perimeter）を守りの口座にも付ける。バケットと鍵の方針に外の口座を書いても、外の主体は使えない。
#     記録の行き先（組織の記録の置き場と選び方、記録のロググループの購読、口座単位の購読と配送と書き出し）は、守りの口座の誰にも変えさせない
#     （GuardFeedFixed）。変えるのは信頼の根の経路（管理の口座の土台の CI が、この SCP を一時に外して適用する。org-guard-change が鳴る）だけ。
#     役割の信頼の書き換えも同じ。出来事の宛先（PutTargets）は、watch-apply だけが置ける（TargetsOnlyByWatchApply）。
#     見張りの関数（コード、設定、呼び出しの許可）と見張りの役割も、watch-apply だけが変えられる（WatchCodeOnlyByWatchApply と
#     WatchRolesOnlyByWatchApply）。関数の URL は誰にも作らせない（NoFunctionUrls）。見張りの印は見張りの役割だけが書く。
#     watch-apply は信頼の根の経路（環境 org-guarded）だけが借り、借りた・書いた・関数を変えたを、芯が 1 件ずつ AWS の外へ鳴らす。
#     新しい役割は権限の境界 orders-guard-core-boundary を付けたときだけ作れる（RolesWithBoundary）。境界は芯の StackSet が置く許す物の一覧。
#     ログの中身、記録、秘密、復号の読み出しは、見張りの関数の役割 3 つのほかは誰にも許さない（DataReadsOnlyForWatch。適用の役割も、
#     その役割が作った役割も、人も）。調べで記録を読むときの道は未確定 31。決めた 2 つの地域の外の操作も拒む（GuardRegions）。
#   鳴らす物（出来事ごと。状態の変化を待たない）: orders-guard-apply か watch-apply を借りた、その資格で書いた（全部の書き込み）。
#     関数を変えた（watch-code。誰でも、拒まれた試みも）。記録の選び方を変えた。
#     守りの口座でログの中身を読んだ（見張りの関数の役割は除く。読むだけの出来事を受ける規則の状態は未確定 20）。Access Analyzer の所見。
#   止まったら鳴る: 守りの口座の芯が毎時の便りを送り、管理の口座で 2 時間届かなければ guard-core-silent が鳴る。
#     CloudTrail の出来事が既定のバスに届くことも、毎時の決まった書き込み 1 件（canary。SSM の値を書く）で確かめる。その出来事が
#     管理の口座に 2 時間届かなければ guard-core-trail-silent が鳴る。届かない口座では ci-writes と tamper も鳴らないので、黙らずに鳴り続ける。
#   変えられる人: 管理の口座への適用（org-guarded の環境、セキュリティの承認）だけ。

locals {
  guard_core_regions = ["us-east-1", "ap-northeast-1"]
  guard_core_bus_arn = "arn:aws:events:us-east-1:${var.management_account_id}:event-bus/orders-guard-core"
  guard_apply_arn    = "arn:aws:iam::${var.security_account_id}:role/orders-guard-apply"
  guard_core_fwd_arn = "arn:aws:iam::${var.security_account_id}:role/orders-guard-core-forward"
  guard_canary_bus   = "arn:aws:events:us-east-1:${var.management_account_id}:event-bus/orders-guard-core-canary"
  guard_boundary_arn = "arn:aws:iam::${var.security_account_id}:policy/orders-guard-core-boundary"
  # 守りの口座でデータを読める主体は、見張りの関数の役割だけ（security/github-watch.tf の watch_functions）。
  guard_watch_roles = [for f in ["github-watch", "static-watch", "event-watch"] : "arn:aws:iam::${var.security_account_id}:role/orders-guard-${f}"]
  # 見張りの関数と役割と出来事の宛先を置けるのは、この役割だけ（security/watchers/。信頼の根の経路 org-guarded の watch-apply.yml）。
  guard_watch_apply_arn = "arn:aws:iam::${var.security_account_id}:role/orders-guard-core-watch-apply"
  guard_core_patterns = {
    # 守りの口座へ適用する CI を借りた（STS は us-east-1 に届く）。
    ci-assumed = { "detail-type" = ["AWS API Call via CloudTrail"], detail = { eventName = ["AssumeRoleWithWebIdentity"], requestParameters = { roleArn = [{ suffix = ":role/orders-guard-apply" }, { suffix = ":role/orders-guard-core-watch-apply" }] } } }
    # その資格で書いた（全部の書き込み。宛先・型・購読・信頼の書き換えを 1 件ずつ外へ送る）。
    ci-writes = { "detail-type" = ["AWS API Call via CloudTrail"], detail = { userIdentity = { sessionContext = { sessionIssuer = { userName = ["orders-guard-apply", "orders-guard-core-watch-apply"] } } } } }
    # 関数の作成・コード・設定・呼び出しの許可の変更（誰でも。SCP で拒まれた試みも）。通るのは watch-apply だけなので、1 件ずつ鳴らし、
    # セキュリティが承認した計画の指紋（記録の codeSha256）と照らす。関数の URL の試みも、ここで鳴る。
    watch-code = { "detail-type" = ["AWS API Call via CloudTrail"], detail = { eventSource = ["lambda.amazonaws.com"] } }
    # 記録を止める・選び方を変える・芯を変える試み（誰でも。SCP で拒まれた試みも）。
    tamper = { "detail-type" = ["AWS API Call via CloudTrail"], detail = { eventName = ["StopLogging", "DeleteTrail", "UpdateTrail", "PutEventSelectors", "DeleteAnalyzer", "CreateArchiveRule", "DeleteStack", "UpdateStack", "UpdateAssumeRolePolicy", "AttachRolePolicy", "PutRolePolicy"] } }
    # 守りの口座でログの中身と管理の記録の履歴を読んだ（見張りの関数の役割のほか。github-watch の毎時の FilterLogEvents は鳴らさない）。
    # 読むだけの出来事なので、規則の状態を ENABLED_WITH_ALL_CLOUDTRAIL_MANAGEMENT_EVENTS にする（下の State。未確定 20）。
    reads = { "detail-type" = ["AWS API Call via CloudTrail"], detail = { eventName = ["StartQuery", "FilterLogEvents", "GetLogEvents", "GetQueryResults", "StartLiveTail", "Unmask", "LookupEvents"], "$or" = [{ userIdentity = { type = [{ "anything-but" = "AssumedRole" }] } }, { userIdentity = { sessionContext = { sessionIssuer = { userName = [{ "anything-but" = ["orders-guard-github-watch", "orders-guard-static-watch", "orders-guard-event-watch"] }] } } } }] } }
    # 外へ開いた資源（バケットと鍵の方針に外の口座を書いた）。
    analyzer = { source = ["aws.access-analyzer"], "detail-type" = ["Access Analyzer Finding"] }
  }
}

resource "aws_cloudformation_stack_set" "guard_core" {
  name             = "orders-guard-core"
  permission_model = "SERVICE_MANAGED"
  capabilities     = ["CAPABILITY_NAMED_IAM"]

  auto_deployment {
    enabled                          = true
    retain_stacks_on_account_removal = true
  }

  template_body = jsonencode({
    Conditions = { IsIamRegion = { "Fn::Equals" = [{ Ref = "AWS::Region" }, "us-east-1"] } }
    Resources = merge(
      {
        # 守りの口座へ適用する CI の役割。信頼と権限はここだけで決まり、守りの口座の誰も変えられない（SCP の GuardCoreUntouchable）。
        GuardApply = {
          Type      = "AWS::IAM::Role"
          Condition = "IsIamRegion"
          Properties = {
            RoleName           = "orders-guard-apply"
            MaxSessionDuration = 3600
            ManagedPolicyArns  = ["arn:aws:iam::aws:policy/ReadOnlyAccess"]
            AssumeRolePolicyDocument = {
              Version = "2012-10-17"
              Statement = [{
                Effect    = "Allow"
                Principal = { Federated = "arn:aws:iam::${var.security_account_id}:oidc-provider/token.actions.githubusercontent.com" }
                Action    = "sts:AssumeRoleWithWebIdentity"
                Condition = {
                  StringEquals = {
                    "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
                    "token.actions.githubusercontent.com:sub" = "repo:${var.github_repository}:environment:security-guarded:job_workflow_ref:${var.github_repository}/.github/workflows/security-apply.yml@refs/heads/main${local.gh_ids}"
                  }
                }
              }]
            }
            Policies = [{
              PolicyName = "write-guard-stack"
              PolicyDocument = {
                Version = "2012-10-17"
                Statement = [
                  {
                    Sid    = "GuardStackWrites"
                    Effect = "Allow"
                    Action = [
                      "logs:CreateLogGroup", "logs:PutRetentionPolicy", "logs:PutMetricFilter", "logs:DeleteMetricFilter", "logs:AssociateKmsKey", "logs:TagResource",
                      "cloudwatch:PutMetricAlarm", "cloudwatch:DeleteAlarms", "cloudwatch:TagResource",
                      "sns:CreateTopic", "sns:SetTopicAttributes", "sns:Subscribe", "sns:Unsubscribe", "sns:TagResource",
                      "events:PutRule", "events:CreateEventBus", "events:PutPermission",
                      "events:TagResource", "ssm:PutParameter", "ssm:AddTagsToResource", "secretsmanager:CreateSecret", "secretsmanager:PutResourcePolicy",
                      "secretsmanager:TagResource", "dynamodb:CreateTable", "dynamodb:UpdateTable", "dynamodb:UpdateContinuousBackups", "dynamodb:TagResource",
                      "s3:CreateBucket", "s3:PutBucketPolicy", "s3:PutBucketVersioning", "s3:PutEncryptionConfiguration", "s3:PutBucketPublicAccessBlock",
                      "s3:PutBucketObjectLockConfiguration", "s3:PutBucketNotification", "s3:PutBucketTagging",
                      "cloudtrail:StartLogging", "cloudtrail:AddTags",
                      "iam:CreateRole", "iam:PutRolePolicy", "iam:PutRolePermissionsBoundary", "iam:TagRole",
                    ]
                    Resource = [
                      "arn:aws:logs:*:${var.security_account_id}:log-group:*orders-guard*",
                      "arn:aws:cloudwatch:*:${var.security_account_id}:alarm:orders-guard-*",
                      "arn:aws:sns:*:${var.security_account_id}:orders-guard-*",
                      "arn:aws:events:*:${var.security_account_id}:rule/orders-guard-*",
                      "arn:aws:events:*:${var.security_account_id}:event-bus/orders-guard-*",
                      "arn:aws:ssm:*:${var.security_account_id}:parameter/orders-guard/*",
                      "arn:aws:secretsmanager:*:${var.security_account_id}:secret:orders-guard/*",
                      "arn:aws:dynamodb:*:${var.security_account_id}:table/orders-guard-*",
                      "arn:aws:s3:::orders-guard-*",
                      "arn:aws:cloudtrail:*:${var.security_account_id}:trail/orders-guard-*",
                      "arn:aws:iam::${var.security_account_id}:role/orders-guard-*",
                    ]
                  },
                  {
                    # 自分と芯の役割と見張りの役割は、上の範囲に入っても変えない（SCP でも拒む）。関数は 1 つも作れない。
                    Sid      = "NotItselfNorCoreNorWatch"
                    Effect   = "Deny"
                    Action   = ["iam:*", "lambda:*", "events:PutTargets", "events:RemoveTargets"]
                    Resource = concat([local.guard_apply_arn, "arn:aws:iam::${var.security_account_id}:role/orders-guard-core-*", "arn:aws:lambda:*:${var.security_account_id}:*", "arn:aws:events:*:${var.security_account_id}:rule/*"], local.guard_watch_roles)
                  },
                  {
                    # 鍵は 1 本（watch）。消す予約と無効化は鍵の方針が誰にも許さない。外の口座への付与は RCP が拒む。
                    Sid      = "GuardKey"
                    Effect   = "Allow"
                    Action   = ["kms:CreateKey", "kms:PutKeyPolicy", "kms:EnableKeyRotation", "kms:TagResource", "kms:CreateGrant"]
                    Resource = "arn:aws:kms:*:${var.security_account_id}:key/*"
                  },
                ]
              }
            }]
          }
        }
        # 見張りの関数と役割と出来事の宛先を置く役割（security/watchers/）。守りの口座へ適用する CI とは別の役割で、信頼の根の経路
        # （環境 org-guarded、セキュリティの承認）を通った main の watch-apply.yml だけが借りる。借りた・書いたは芯が 1 件ずつ鳴らす。
        WatchApply = {
          Type      = "AWS::IAM::Role"
          Condition = "IsIamRegion"
          Properties = {
            RoleName           = "orders-guard-core-watch-apply"
            MaxSessionDuration = 3600
            ManagedPolicyArns  = ["arn:aws:iam::aws:policy/ReadOnlyAccess"]
            AssumeRolePolicyDocument = {
              Version = "2012-10-17"
              Statement = [{
                Effect    = "Allow"
                Principal = { Federated = "arn:aws:iam::${var.security_account_id}:oidc-provider/token.actions.githubusercontent.com" }
                Action    = "sts:AssumeRoleWithWebIdentity"
                Condition = {
                  StringEquals = {
                    "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
                    "token.actions.githubusercontent.com:sub" = "repo:${var.github_repository}:environment:org-guarded:job_workflow_ref:${var.github_repository}/.github/workflows/watch-apply.yml@refs/heads/main${local.gh_ids}"
                  }
                }
              }]
            }
            Policies = [{
              PolicyName = "write-watchers"
              PolicyDocument = {
                Version = "2012-10-17"
                Statement = [
                  {
                    Sid      = "WatchFunctions"
                    Effect   = "Allow"
                    Action   = ["lambda:CreateFunction", "lambda:UpdateFunctionCode", "lambda:UpdateFunctionConfiguration", "lambda:AddPermission", "lambda:RemovePermission", "lambda:TagResource"]
                    Resource = [for f in ["github-watch", "static-watch", "event-watch"] : "arn:aws:lambda:*:${var.security_account_id}:function:orders-guard-${f}"]
                  },
                  {
                    Sid      = "WatchRoles"
                    Effect   = "Allow"
                    Action   = ["iam:CreateRole", "iam:PutRolePolicy", "iam:TagRole", "iam:PassRole"]
                    Resource = local.guard_watch_roles
                  },
                  {
                    # 宛先は許す物の一覧（見張りの関数 3 つ、守りの口座の話題、決めたロググループ）だけ。外の口座のバスや関数は置けない。
                    # events:TargetArn は複数の値を持つので、全部の宛先を縛る ForAllValues と、値が無い要求を拒む Null の組で書く（aws-facts の 41）。
                    Sid      = "TargetsOnlyToListedArns"
                    Effect   = "Allow"
                    Action   = "events:PutTargets"
                    Resource = "arn:aws:events:*:${var.security_account_id}:rule/orders-guard-*"
                    Condition = {
                      "ForAllValues:ArnLike" = {
                        "events:TargetArn" = [
                          "arn:aws:lambda:*:${var.security_account_id}:function:orders-guard-github-watch",
                          "arn:aws:lambda:*:${var.security_account_id}:function:orders-guard-static-watch",
                          "arn:aws:lambda:*:${var.security_account_id}:function:orders-guard-event-watch",
                          "arn:aws:sns:*:${var.security_account_id}:orders-guard-*",
                          "arn:aws:logs:*:${var.security_account_id}:log-group:/aws/events/orders-guard-*",
                        ]
                      }
                      Null = { "events:TargetArn" = "false" }
                    }
                  },
                  {
                    Sid      = "RemoveTargetsAndState"
                    Effect   = "Allow"
                    Action   = ["events:RemoveTargets", "ssm:PutParameter", "ssm:AddTagsToResource"]
                    Resource = ["arn:aws:events:*:${var.security_account_id}:rule/orders-guard-*", "arn:aws:ssm:*:${var.security_account_id}:parameter/orders-guard/github-watch/*"]
                  },
                  {
                    # 組織の記録のロググループの伏せ字（security/watchers/trail-masking.tf）。監査の所見の送り先を外へ向ける道を、この役割に限る。
                    Sid      = "TrailMasking"
                    Effect   = "Allow"
                    Action   = ["logs:PutDataProtectionPolicy", "logs:DeleteDataProtectionPolicy"]
                    Resource = ["arn:aws:logs:*:${var.security_account_id}:log-group:/orders-guard/org-trail", "arn:aws:logs:*:${var.security_account_id}:log-group:/orders-guard/org-trail:*"]
                  },
                  {
                    # ロググループの資源の方針（第 14 回）。守りの口座へ適用する CI の GuardStackWrites から外し、ここだけに置く。
                    # 外の口座の主体へ読み出しを開く方針を書いても、組織の RCP の logs:* が拒む（aws-facts の 1）。
                    Sid      = "WatchLogPolicies"
                    Effect   = "Allow"
                    Action   = ["logs:PutResourcePolicy", "logs:DeleteResourcePolicy", "logs:DescribeResourcePolicies"]
                    Resource = "*" # iac-scan:allow IAC-003 口座単位の資源の方針は名前で絞れない。外の口座へ開く書き方は RCP が拒む
                  },
                  {
                    Sid      = "NotCore"
                    Effect   = "Deny"
                    Action   = ["iam:*", "events:*"]
                    Resource = [local.guard_apply_arn, "arn:aws:iam::${var.security_account_id}:role/orders-guard-core-*", "arn:aws:events:*:${var.security_account_id}:rule/orders-guard-core-*"]
                  },
                ]
              }
            }]
          }
        }
        # 出来事を管理の口座のバスへ送る役割。
        Forward = {
          Type      = "AWS::IAM::Role"
          Condition = "IsIamRegion"
          Properties = {
            RoleName = "orders-guard-core-forward"
            AssumeRolePolicyDocument = {
              Version   = "2012-10-17"
              Statement = [{ Effect = "Allow", Principal = { Service = "events.amazonaws.com" }, Action = "sts:AssumeRole" }]
            }
            Policies = [{
              PolicyName     = "put-to-core-bus"
              PolicyDocument = { Version = "2012-10-17", Statement = [{ Effect = "Allow", Action = "events:PutEvents", Resource = [local.guard_core_bus_arn, local.guard_canary_bus] }] }
            }]
          }
        }
        # 守りの口座で作る役割の権限の境界（許す物の一覧）。見張りの関数と記録の配送が使う操作だけで、役割づくり・借り入れ・書き出しは入らない。
        # 境界は芯に置くので、守りの口座の誰も書き換えられない（SCP の RolesWithBoundary と GuardCoreUntouchable）。
        Boundary = {
          Type      = "AWS::IAM::ManagedPolicy"
          Condition = "IsIamRegion"
          Properties = {
            ManagedPolicyName = "orders-guard-core-boundary"
            PolicyDocument = {
              Version = "2012-10-17"
              # 資源も名指しする（Resource "*" にしない）。作った役割が見張りの印の表と前回の印を書く道と、外の口座のバケットと
              # 話題へ書く道を、資源の一覧で閉じる。印の書き込みは、さらに SCP の WatchMarksOnlyByWatch が見張りの役割だけに絞る。
              Statement = [
                # 書き込みは、名指しの役割（見張りの 3 つ、記録の配送、監査の流し出し）にだけ許す（aws:PrincipalArn）。守りの口座へ適用する CI が
                # 境界つきで作った別の名の役割は、障害の記録と組織の記録に偽の行を書けず、監査の流し出しのバケットに偽の file も置けない（第 13 回）。
                {
                  Sid       = "WatchOwnLogs"
                  Effect    = "Allow"
                  Action    = ["logs:CreateLogStream", "logs:PutLogEvents"]
                  Resource  = "arn:aws:logs:*:${var.security_account_id}:log-group:/aws/lambda/orders-guard-*:*"
                  Condition = { ArnLike = { "aws:PrincipalArn" = local.guard_watch_roles } }
                },
                {
                  Sid       = "TrailDeliveryOnly"
                  Effect    = "Allow"
                  Action    = ["logs:CreateLogStream", "logs:PutLogEvents"]
                  Resource  = "arn:aws:logs:*:${var.security_account_id}:log-group:/orders-guard/org-trail:*"
                  Condition = { ArnLike = { "aws:PrincipalArn" = "arn:aws:iam::${var.security_account_id}:role/orders-guard-org-trail-logs" } }
                },
                {
                  Sid      = "WatchLogReads"
                  Effect   = "Allow"
                  Action   = "logs:FilterLogEvents"
                  Resource = ["arn:aws:logs:*:${var.security_account_id}:log-group:/orders-guard/org-trail:*", "arn:aws:logs:*:${var.security_account_id}:log-group:/aws/events/orders-guard-incidents:*"]
                },
                {
                  Sid      = "StaticReadsAndAuditStream"
                  Effect   = "Allow"
                  Action   = ["s3:GetObject", "s3:GetObjectVersion", "s3:ListBucket", "s3:ListBucketVersions"]
                  Resource = ["arn:aws:s3:::orders-admin-*-static-*", "arn:aws:s3:::orders-admin-*-static-*/*", "arn:aws:s3:::orders-guard-github-audit-${var.security_account_id}/*"]
                },
                {
                  Sid       = "AuditStreamWrite"
                  Effect    = "Allow"
                  Action    = "s3:PutObject"
                  Resource  = "arn:aws:s3:::orders-guard-github-audit-${var.security_account_id}/*"
                  Condition = { ArnLike = { "aws:PrincipalArn" = "arn:aws:iam::${var.security_account_id}:role/orders-guard-github-audit-stream" } }
                },
                {
                  Sid       = "GuardSecretsStateMarksTopics"
                  Effect    = "Allow"
                  Action    = ["secretsmanager:GetSecretValue", "ssm:GetParameter", "ssm:PutParameter", "dynamodb:GetItem", "dynamodb:PutItem", "sns:Publish"]
                  Resource  = ["arn:aws:secretsmanager:*:${var.security_account_id}:secret:orders-guard/*", "arn:aws:ssm:*:${var.security_account_id}:parameter/orders-guard/*", "arn:aws:dynamodb:*:${var.security_account_id}:table/orders-guard-*", "arn:aws:sns:*:${var.security_account_id}:orders-guard-*"]
                  Condition = { ArnLike = { "aws:PrincipalArn" = local.guard_watch_roles } }
                },
                {
                  # DB の 2 つの像の層を読む（第 15 回。event_watch.py が押し込みのたびに層を開いて main と照らす）。読むだけで、書く操作は入らない。
                  Sid       = "DbImageReads"
                  Effect    = "Allow"
                  Action    = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
                  Resource  = ["arn:aws:ecr:*:*:repository/orders-admin-*/db-bootstrap", "arn:aws:ecr:*:*:repository/orders-admin-*/db-migrate"]
                  Condition = { ArnLike = { "aws:PrincipalArn" = "arn:aws:iam::${var.security_account_id}:role/orders-guard-event-watch" } }
                },
                {
                  # 管理の口座の IAM の数を読む役割だけを借りる（第 15 回。github_watch.py の毎時の見回り）。ほかの借り入れは境界の外。
                  Sid       = "MgmtSummaryOnly"
                  Effect    = "Allow"
                  Action    = "sts:AssumeRole"
                  Resource  = "arn:aws:iam::${var.management_account_id}:role/orders-guard-core-mgmt-summary"
                  Condition = { ArnLike = { "aws:PrincipalArn" = "arn:aws:iam::${var.security_account_id}:role/orders-guard-github-watch" } }
                },
                {
                  # 復号は鍵の方針と ViaService で絞る（作業の口座の画面の鍵と守りの口座の watch の鍵）。外へ書く操作は入らない。
                  Sid      = "Decrypt"
                  Effect   = "Allow"
                  Action   = ["kms:Decrypt", "kms:GenerateDataKey"]
                  Resource = "arn:aws:kms:*:*:key/*"
                },
              ]
            }
          }
        }
        # CloudTrail の出来事が既定のバスに届くことの確かめ（canary）。毎時、決まった SSM の値を 1 件書く。その管理の出来事を下の
        # RuleCanary が管理の口座の canary のバスへ送り、2 時間届かなければ guard-core-trail-silent が鳴る。
        CanaryRole = {
          Type      = "AWS::IAM::Role"
          Condition = "IsIamRegion"
          Properties = {
            RoleName = "orders-guard-core-canary"
            AssumeRolePolicyDocument = {
              Version = "2012-10-17"
              Statement = [{
                Effect    = "Allow"
                Principal = { Service = "scheduler.amazonaws.com" }
                Action    = "sts:AssumeRole"
                Condition = { StringEquals = { "aws:SourceAccount" = var.security_account_id } }
              }]
            }
            Policies = [{
              PolicyName     = "write-canary"
              PolicyDocument = { Version = "2012-10-17", Statement = [{ Effect = "Allow", Action = "ssm:PutParameter", Resource = "arn:aws:ssm:*:${var.security_account_id}:parameter/orders-guard-core/canary-*" }] }
            }]
          }
        }
        CanarySchedule = {
          Type = "AWS::Scheduler::Schedule"
          Properties = {
            Name               = "orders-guard-core-canary"
            ScheduleExpression = "rate(1 hour)"
            FlexibleTimeWindow = { Mode = "OFF" }
            Target = {
              Arn     = "arn:aws:scheduler:::aws-sdk:ssm:putParameter"
              RoleArn = "arn:aws:iam::${var.security_account_id}:role/orders-guard-core-canary"
              Input   = { "Fn::Sub" = "{\"Name\":\"/orders-guard-core/canary-$${AWS::Region}\",\"Value\":\"tick\",\"Type\":\"String\",\"Overwrite\":true}" }
            }
          }
        }
        RuleCanary = {
          Type = "AWS::Events::Rule"
          Properties = {
            Name         = "orders-guard-core-canary"
            EventPattern = { "detail-type" = ["AWS API Call via CloudTrail"], detail = { eventSource = ["ssm.amazonaws.com"], eventName = ["PutParameter"], requestParameters = { name = [{ prefix = "/orders-guard-core/canary-" }] } } }
            Targets      = [{ Id = "canary-bus", Arn = local.guard_canary_bus, RoleArn = local.guard_core_fwd_arn }]
          }
        }
        # 外の口座へ開いた資源の所見。所見は下の analyzer の規則が外へ送る。
        Analyzer = {
          Type       = "AWS::AccessAnalyzer::Analyzer"
          Properties = { AnalyzerName = { "Fn::Sub" = "orders-guard-core-$${AWS::Region}" }, Type = "ACCOUNT" }
        }
        # 毎時の便り。管理の口座で 2 時間届かなければ guard-core-silent が鳴る（芯を止めた、規則を外した）。
        Heartbeat = {
          Type = "AWS::Events::Rule"
          Properties = {
            Name               = "orders-guard-core-heartbeat"
            ScheduleExpression = "rate(1 hour)"
            Targets            = [{ Id = "core-bus", Arn = local.guard_core_bus_arn, RoleArn = local.guard_core_fwd_arn }]
          }
        }
      },
      { for k, p in local.guard_core_patterns : "Rule${replace(title(replace(k, "-", " ")), " ", "")}" => {
        Type = "AWS::Events::Rule"
        Properties = {
          Name         = "orders-guard-core-${k}"
          EventPattern = p
          State        = k == "reads" ? "ENABLED_WITH_ALL_CLOUDTRAIL_MANAGEMENT_EVENTS" : "ENABLED"
          Targets      = [{ Id = "core-bus", Arn = local.guard_core_bus_arn, RoleArn = local.guard_core_fwd_arn }]
        }
      } },
    )
  })
}

resource "aws_cloudformation_stack_set_instance" "guard_core" {
  for_each                  = toset(local.guard_core_regions)
  stack_set_name            = aws_cloudformation_stack_set.guard_core.name
  stack_set_instance_region = each.value

  deployment_targets {
    organizational_unit_ids = [var.security_ou_id]
    accounts                = [var.security_account_id]
    account_filter_type     = "INTERSECTION"
  }
}

# ---- 守りの口座の上限（守りの口座に直に付ける）

resource "aws_organizations_policy" "guard_core" {
  name        = "orders-guard-core"
  description = "The guard apply CI cannot change itself, the core forwarding, the analyzer or the trail, and cannot read data"
  type        = "SERVICE_CONTROL_POLICY"
  content = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "GuardCoreUntouchable"
        Effect   = "Deny"
        Action   = ["iam:UpdateAssumeRolePolicy", "iam:PutRolePolicy", "iam:DeleteRolePolicy", "iam:AttachRolePolicy", "iam:DetachRolePolicy", "iam:PutRolePermissionsBoundary", "iam:DeleteRolePermissionsBoundary", "iam:UpdateRole", "iam:DeleteRole", "iam:TagRole", "iam:UntagRole"]
        Resource = [local.guard_apply_arn, "arn:aws:iam::${var.security_account_id}:role/orders-guard-core-*"]
      },
      {
        Sid      = "GuardCoreRulesAndTrail"
        Effect   = "Deny"
        Action   = ["events:PutRule", "events:DeleteRule", "events:DisableRule", "events:PutTargets", "events:RemoveTargets", "access-analyzer:DeleteAnalyzer", "access-analyzer:CreateArchiveRule", "access-analyzer:UpdateArchiveRule", "access-analyzer:ApplyArchiveRule", "cloudformation:DeleteStack", "cloudformation:UpdateStack", "cloudtrail:StopLogging", "cloudtrail:DeleteTrail"]
        Resource = ["arn:aws:events:*:${var.security_account_id}:rule/orders-guard-core-*", "arn:aws:access-analyzer:*:${var.security_account_id}:analyzer/orders-guard-core-*", "arn:aws:cloudformation:*:${var.security_account_id}:stack/StackSet-orders-guard-core-*", "arn:aws:cloudtrail:*:${var.security_account_id}:trail/*"]
      },
      {
        # 記録の行き先と役割の信頼は、守りの口座の誰にも変えさせない（信頼の根の経路だけ）。外の口座のバケット、論理的な送り先、配送、書き出し、
        # 2 本目の組織の記録で、組織の記録を流し続ける道を閉じる。芯の canary の予定も止めさせない（止めれば trail-silent が鳴る）。
        Sid      = "GuardFeedFixed"
        Effect   = "Deny"
        Action   = ["cloudtrail:CreateTrail", "cloudtrail:UpdateTrail", "cloudtrail:PutEventSelectors", "cloudtrail:PutInsightSelectors", "cloudtrail:CreateEventDataStore", "cloudtrail:UpdateEventDataStore", "logs:PutSubscriptionFilter", "logs:DeleteSubscriptionFilter", "logs:PutDestination", "logs:PutDestinationPolicy", "logs:PutAccountPolicy", "logs:PutDeliverySource", "logs:PutDeliveryDestination", "logs:PutDeliveryDestinationPolicy", "logs:CreateDelivery", "logs:CreateExportTask", "logs:PutIntegration", "iam:UpdateAssumeRolePolicy", "scheduler:UpdateSchedule", "scheduler:DeleteSchedule"]
        Resource = "*"
      },
      {
        # 役割は権限の境界（芯の許す物の一覧）を付けたときだけ作れる。境界を外す・替えることも拒む。
        Sid       = "RolesWithBoundary"
        Effect    = "Deny"
        Action    = ["iam:CreateRole", "iam:PutRolePermissionsBoundary"]
        Resource  = "*"
        Condition = { StringNotEquals = { "iam:PermissionsBoundary" = local.guard_boundary_arn } }
      },
      {
        Sid      = "BoundaryFixed"
        Effect   = "Deny"
        Action   = ["iam:DeleteRolePermissionsBoundary", "iam:CreatePolicyVersion", "iam:DeletePolicy", "iam:DeletePolicyVersion", "iam:SetDefaultPolicyVersion"]
        Resource = ["arn:aws:iam::${var.security_account_id}:role/*", "arn:aws:iam::${var.security_account_id}:policy/orders-guard-core-*"]
      },
      {
        # 決めた 2 つの地域の外では、全部の地域にまたがる仕組みのほかを拒む（地域の窓口で芯の規則の外を通る道）。
        Sid       = "GuardRegions"
        Effect    = "Deny"
        NotAction = ["iam:*", "organizations:*", "support:*", "account:*", "health:*"]
        Resource  = "*"
        Condition = { StringNotEquals = { "aws:RequestedRegion" = local.guard_core_regions } }
      },
      {
        Sid       = "NoAdminManagedPolicies"
        Effect    = "Deny"
        Action    = ["iam:AttachRolePolicy", "iam:AttachUserPolicy", "iam:AttachGroupPolicy"]
        Resource  = "*"
        Condition = { ArnNotLike = { "iam:PolicyARN" = ["arn:aws:iam::aws:policy/ReadOnlyAccess", "arn:aws:iam::${var.security_account_id}:policy/orders-guard-*"] } }
      },
      {
        # データの読み出しは、見張りの関数の役割 3 つのほかは誰にも許さない（適用の役割も、それが作った役割も、人も）。
        # メトリクスの一覧と値も入れる。メトリクスフィルタの次元に記録の欄を名指しすると、欄の値が次元の値として ListMetrics に出る（第 13 回）。
        Sid       = "DataReadsOnlyForWatch"
        Effect    = "Deny"
        Action    = ["logs:GetLogEvents", "logs:FilterLogEvents", "logs:StartQuery", "logs:GetQueryResults", "logs:StartLiveTail", "logs:GetLogRecord", "logs:Unmask", "logs:DescribeQueries", "cloudtrail:LookupEvents", "cloudtrail:StartQuery", "s3:GetObject", "s3:GetObjectVersion", "dynamodb:GetItem", "dynamodb:Query", "dynamodb:Scan", "dynamodb:BatchGetItem", "secretsmanager:GetSecretValue", "kms:Decrypt", "cloudwatch:ListMetrics", "cloudwatch:GetMetricData", "cloudwatch:GetMetricStatistics"]
        Resource  = "*"
        Condition = { ArnNotLike = { "aws:PrincipalArn" = local.guard_watch_roles } }
      },
    ]
  })
}

resource "aws_organizations_policy_attachment" "guard_core" {
  policy_id = aws_organizations_policy.guard_core.id
  target_id = var.security_account_id
}

# 守りの口座の上限の 2 枚目（見張りの関数と宛先と印）。1 枚の SCP は 5,120 字までなので分ける。守りの口座に直に付ける。
resource "aws_organizations_policy" "guard_core_watch" {
  name        = "orders-guard-core-watch"
  description = "Only the watch apply role changes the watch functions, roles and event targets; only the watchers write their marks"
  type        = "SERVICE_CONTROL_POLICY"
  content = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # 出来事の宛先は、watch-apply（信頼の根の経路）だけが置ける。外の口座のバスへ全部の出来事を送る道を、条件キー（events:TargetArn）に
        # 頼らず、操作そのものを 1 つの役割に限って閉じる。芯の宛先は StackSet が置く（SCP を受けるかは未確定 20 の (3)。受けるなら置き直しが落ちて分かる）。
        Sid       = "TargetsOnlyByWatchApply"
        Effect    = "Deny"
        Action    = ["events:PutTargets", "events:RemoveTargets"]
        Resource  = "*"
        Condition = { ArnNotLike = { "aws:PrincipalArn" = local.guard_watch_apply_arn } }
      },
      {
        # 関数（作成、コード、設定、呼び出しの許可、版と別名、層）は、watch-apply だけが変えられる。守りの口座へ適用する CI が、
        # 見張りの役割で動く自前のコードを置き、DataReadsOnlyForWatch の例外で読む道と、呼び出しの許可を外の口座へ開く道を閉じる。
        Sid       = "WatchCodeOnlyByWatchApply"
        Effect    = "Deny"
        NotAction = ["lambda:Get*", "lambda:List*", "lambda:InvokeFunction"]
        Resource  = ["arn:aws:lambda:*:${var.security_account_id}:function:*", "arn:aws:lambda:*:${var.security_account_id}:layer:*", "arn:aws:lambda:*:${var.security_account_id}:event-source-mapping:*"]
        Condition = { ArnNotLike = { "aws:PrincipalArn" = local.guard_watch_apply_arn } }
      },
      {
        # データ保護の方針（伏せ字と監査の所見の送り先）は、watch-apply だけが置ける。守りの口座へ適用する CI の 1 回で、
        # 組織の記録の所見の送り先を外の口座へ向けて、記録の一部を流し続ける道を閉じる（所見に値が入るかは確かめないで閉じる）。
        Sid       = "MaskingOnlyByWatchApply"
        Effect    = "Deny"
        Action    = ["logs:PutDataProtectionPolicy", "logs:DeleteDataProtectionPolicy"]
        Resource  = "*"
        Condition = { ArnNotLike = { "aws:PrincipalArn" = local.guard_watch_apply_arn } }
      },
      {
        # 関数の URL（認証なしの入口を作れる）は誰にも作らせない。見張りは URL を使わない。
        Sid      = "NoFunctionUrls"
        Effect   = "Deny"
        Action   = ["lambda:CreateFunctionUrlConfig", "lambda:UpdateFunctionUrlConfig"]
        Resource = "*"
      },
      {
        # 見張りの役割の受け渡しと書き換えは、watch-apply だけ。
        Sid       = "WatchRolesOnlyByWatchApply"
        Effect    = "Deny"
        Action    = ["iam:PassRole", "iam:CreateRole", "iam:UpdateAssumeRolePolicy", "iam:PutRolePolicy", "iam:DeleteRolePolicy", "iam:AttachRolePolicy", "iam:DetachRolePolicy", "iam:PutRolePermissionsBoundary", "iam:DeleteRolePermissionsBoundary", "iam:UpdateRole", "iam:DeleteRole", "iam:TagRole", "iam:UntagRole"]
        Resource  = local.guard_watch_roles
        Condition = { ArnNotLike = { "aws:PrincipalArn" = local.guard_watch_apply_arn } }
      },
      {
        # 照らした版の印は static-watch の役割だけ、前回の main の印は github-watch の役割（と最初に置く watch-apply）だけが書く。
        # 境界つきの役割で先に印を入れて照らしを飛ばす道を閉じる。
        Sid       = "StaticMarksOnlyByStaticWatch"
        Effect    = "Deny"
        Action    = ["dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem", "dynamodb:BatchWriteItem", "dynamodb:PartiQLInsert", "dynamodb:PartiQLUpdate", "dynamodb:PartiQLDelete"]
        Resource  = "arn:aws:dynamodb:*:${var.security_account_id}:table/orders-guard-static-checked"
        Condition = { ArnNotLike = { "aws:PrincipalArn" = "arn:aws:iam::${var.security_account_id}:role/orders-guard-static-watch" } }
      },
      {
        Sid       = "GitHubStateOnlyByGitHubWatch"
        Effect    = "Deny"
        Action    = ["ssm:PutParameter", "ssm:DeleteParameter", "ssm:DeleteParameters", "ssm:LabelParameterVersion"]
        Resource  = "arn:aws:ssm:*:${var.security_account_id}:parameter/orders-guard/github-watch/*"
        Condition = { ArnNotLike = { "aws:PrincipalArn" = ["arn:aws:iam::${var.security_account_id}:role/orders-guard-github-watch", local.guard_watch_apply_arn] } }
      }
    ]
  })
}

resource "aws_organizations_policy_attachment" "guard_core_watch" {
  policy_id = aws_organizations_policy.guard_core_watch.id
  target_id = var.security_account_id
}

# 守りの口座の上限の 3 枚目（主体の許す一覧。第 16 回）。守りの口座で操作できる主体を、名指しの役割だけに限る。
#   前の作りは、守りの口座の主体の一覧を持たず、管理の口座から借りる OrganizationAccountAccessRole、新しい許可セットの割り当て、
#   AssumeRoot で入った root が、数秒で話題とアラームとメトリクスフィルタを消せた（出来事が組織の記録に届く前に、鳴る先が無くなる）。
#   通すのは、守りの適用（orders-guard-apply）、見張りの適用（watch-apply）、芯の転送と canary、見張りの関数 3 つ、記録の配送
#   （org-trail-logs）、監査の流し出し（github-audit-stream）と、StackSet の実行の役割だけ。人の許可セット、root、
#   OrganizationAccountAccessRole は何もできない。調べで人が入る道は未確定 31（この SCP を外すのは信頼の根の経路だけで、外せば
#   org-guard-change と 15 分ごとの便りの途絶が AWS の外で鳴る）。
#   2 つ目の文は、鳴る経路（話題、購読、アラーム、メトリクスフィルタ、記録の購読、ロググループ）の削除と書き換えを、
#   watch-apply と守りの適用（と芯を置く StackSet）のほかに拒む。守りの適用の書き込みは、芯（ci-writes）が 1 件ずつ管理の口座の外へ送る。
locals {
  guard_principals = concat([local.guard_apply_arn, local.guard_watch_apply_arn, local.guard_core_fwd_arn,
    "arn:aws:iam::${var.security_account_id}:role/orders-guard-core-canary",
    "arn:aws:iam::${var.security_account_id}:role/orders-guard-org-trail-logs",
    "arn:aws:iam::${var.security_account_id}:role/orders-guard-github-audit-stream",
  "arn:aws:iam::${var.security_account_id}:role/stacksets-exec-*"], local.guard_watch_roles)
}

resource "aws_organizations_policy" "guard_core_principals" {
  name        = "orders-guard-core-principals"
  description = "Only the named roles act in the guard account; only the two apply roles change the alert path"
  type        = "SERVICE_CONTROL_POLICY"
  content = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "GuardPrincipalsAllowList"
        Effect    = "Deny"
        Action    = "*"
        Resource  = "*"
        Condition = { ArnNotLike = { "aws:PrincipalArn" = local.guard_principals } }
      },
      {
        Sid    = "AlertPathOnlyByApply"
        Effect = "Deny"
        Action = ["sns:DeleteTopic", "sns:SetTopicAttributes", "sns:Unsubscribe", "sns:SetSubscriptionAttributes", "sns:AddPermission", "sns:RemovePermission", "sns:PutDataProtectionPolicy",
          "cloudwatch:DeleteAlarms", "cloudwatch:PutMetricAlarm", "cloudwatch:PutCompositeAlarm", "cloudwatch:DisableAlarmActions", "cloudwatch:SetAlarmState",
        "logs:DeleteMetricFilter", "logs:PutMetricFilter", "logs:DeleteSubscriptionFilter", "logs:DeleteLogGroup", "logs:PutRetentionPolicy", "events:DeleteRule", "events:DisableRule", "events:PutRule"]
        Resource  = "*"
        Condition = { ArnNotLike = { "aws:PrincipalArn" = [local.guard_apply_arn, local.guard_watch_apply_arn, "arn:aws:iam::${var.security_account_id}:role/stacksets-exec-*"] } }
      },
    ]
  })
}

resource "aws_organizations_policy_attachment" "guard_core_principals" {
  policy_id = aws_organizations_policy.guard_core_principals.id
  target_id = var.security_account_id
}

# 外の主体を拒む組織の RCP を、守りの口座にも付ける（組織の記録のバケットと見張りの鍵を、外の口座に開かせない）。
resource "aws_organizations_policy_attachment" "resource_perimeter_guard" {
  policy_id = aws_organizations_policy.resource_perimeter.id
  target_id = var.security_account_id
}

# ---- 管理の口座の受け口（バス、宛先、便りの途絶）

resource "aws_cloudwatch_event_bus" "guard_core" {
  name = "orders-guard-core"
}

resource "aws_cloudwatch_event_bus_policy" "guard_core" {
  event_bus_name = aws_cloudwatch_event_bus.guard_core.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "GuardCoreForwardOnly"
      Effect    = "Allow"
      Principal = { AWS = local.guard_core_fwd_arn }
      Action    = "events:PutEvents"
      Resource  = aws_cloudwatch_event_bus.guard_core.arn
    }]
  })
}

# 宛先の鍵。AWS の管理の鍵（alias/aws/sns）には CloudWatch のアラームと EventBridge が送れないので、この口座の鍵で暗号化する。
# 鍵の方針の Resource "*" は「この鍵そのもの」を指す（鍵の方針の決まり）。鍵が止まると宛先が黙るので、消す予約と無効化は誰にも許さない。
# 鍵を使える送り手は、この file でこの話題へ送る 2 つのサービスだけ（EventBridge の guard_core_alert と、CloudWatch の guard_core_silent と guard_canary_silent）。
# 送り手の口座の条件は付けない。確かめていない条件キーで宛先が黙るのを避け、送り手の口座は話題の方針（RulesAndAlarmsInThisAccount）で絞る。
resource "aws_kms_key" "guard_core" {
  description             = "Guard core alert topic in the management account"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AccountAdmin"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${var.management_account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        Sid       = "DenyKeyDestruction"
        Effect    = "Deny"
        Principal = { AWS = "*" }
        Action    = ["kms:ScheduleKeyDeletion", "kms:DisableKey", "kms:DeleteImportedKeyMaterial"]
        Resource  = "*"
      },
      {
        Sid       = "RulesAndAlarmsPublish"
        Effect    = "Allow"
        Principal = { Service = ["events.amazonaws.com", "cloudwatch.amazonaws.com"] }
        Action    = ["kms:GenerateDataKey*", "kms:Decrypt"]
        Resource  = "*"
      },
    ]
  })
}

resource "aws_sns_topic" "guard_core" {
  name              = "orders-guard-core"
  kms_master_key_id = aws_kms_key.guard_core.arn
}

resource "aws_sns_topic_policy" "guard_core" {
  arn = aws_sns_topic.guard_core.arn
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "RulesAndAlarmsInThisAccount"
      Effect    = "Allow"
      Principal = { Service = ["events.amazonaws.com", "cloudwatch.amazonaws.com"] }
      Action    = "sns:Publish"
      Resource  = aws_sns_topic.guard_core.arn
      Condition = { StringEquals = { "aws:SourceAccount" = var.management_account_id } }
    }]
  })
}

# 宛先は AWS の外（セキュリティのメールと呼び出しの窓口）。解除には持ち主の署名が要る形で確認する（未確定 24）。
resource "aws_sns_topic_subscription" "guard_core" {
  for_each  = { email = var.guard_core_email, pager = var.guard_core_pager_url }
  topic_arn = aws_sns_topic.guard_core.arn
  protocol  = each.key == "email" ? "email" : "https"
  endpoint  = each.value
}

# 便りのほかの出来事は全部、1 件ずつ宛先へ送る。
resource "aws_cloudwatch_event_rule" "guard_core_alert" {
  name           = "orders-guard-core-alert"
  event_bus_name = aws_cloudwatch_event_bus.guard_core.name
  event_pattern  = jsonencode({ account = [var.security_account_id], "detail-type" = [{ "anything-but" = "Scheduled Event" }] })
}

resource "aws_cloudwatch_event_target" "guard_core_alert" {
  rule           = aws_cloudwatch_event_rule.guard_core_alert.name
  event_bus_name = aws_cloudwatch_event_bus.guard_core.name
  arn            = aws_sns_topic.guard_core.arn
}

resource "aws_cloudwatch_log_group" "guard_core_heartbeat" {
  name              = "/aws/events/orders-guard-core-heartbeat"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_resource_policy" "guard_core_heartbeat" {
  policy_name = "orders-guard-core-heartbeat"
  policy_document = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = ["events.amazonaws.com", "delivery.logs.amazonaws.com"] }
      Action    = ["logs:CreateLogStream", "logs:PutLogEvents"]
      Resource  = "${aws_cloudwatch_log_group.guard_core_heartbeat.arn}:*"
    }]
  })
}

resource "aws_cloudwatch_event_rule" "guard_core_heartbeat" {
  name           = "orders-guard-core-heartbeat"
  event_bus_name = aws_cloudwatch_event_bus.guard_core.name
  event_pattern  = jsonencode({ account = [var.security_account_id], "detail-type" = ["Scheduled Event"] })
}

resource "aws_cloudwatch_event_target" "guard_core_heartbeat" {
  rule           = aws_cloudwatch_event_rule.guard_core_heartbeat.name
  event_bus_name = aws_cloudwatch_event_bus.guard_core.name
  arn            = aws_cloudwatch_log_group.guard_core_heartbeat.arn
}

resource "aws_cloudwatch_log_metric_filter" "guard_core_heartbeat" {
  name           = "orders-guard-core-heartbeat"
  log_group_name = aws_cloudwatch_log_group.guard_core_heartbeat.name
  pattern        = ""

  metric_transformation {
    name      = "guard-core-heartbeat"
    namespace = "orders-guard-core"
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "guard_core_silent" {
  alarm_name          = "orders-guard-core-silent"
  alarm_description   = "The guard account core did not send its hourly heartbeat for 2 hours"
  namespace           = "orders-guard-core"
  metric_name         = "guard-core-heartbeat"
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 2
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = [aws_sns_topic.guard_core.arn]

  depends_on = [aws_cloudwatch_log_metric_filter.guard_core_heartbeat]
}

# ---- 管理の口座の canary の受け口（CloudTrail の出来事が守りの口座の既定のバスに届くことの確かめ）

resource "aws_cloudwatch_event_bus" "guard_canary" {
  name = "orders-guard-core-canary"
}

resource "aws_cloudwatch_event_bus_policy" "guard_canary" {
  event_bus_name = aws_cloudwatch_event_bus.guard_canary.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "GuardCoreForwardOnly"
      Effect    = "Allow"
      Principal = { AWS = local.guard_core_fwd_arn }
      Action    = "events:PutEvents"
      Resource  = aws_cloudwatch_event_bus.guard_canary.arn
    }]
  })
}

resource "aws_cloudwatch_log_group" "guard_canary" {
  name              = "/aws/events/orders-guard-core-canary"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_resource_policy" "guard_canary" {
  policy_name = "orders-guard-core-canary"
  policy_document = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = ["events.amazonaws.com", "delivery.logs.amazonaws.com"] }
      Action    = ["logs:CreateLogStream", "logs:PutLogEvents"]
      Resource  = "${aws_cloudwatch_log_group.guard_canary.arn}:*"
    }]
  })
}

resource "aws_cloudwatch_event_rule" "guard_canary" {
  name           = "orders-guard-core-canary"
  event_bus_name = aws_cloudwatch_event_bus.guard_canary.name
  event_pattern  = jsonencode({ account = [var.security_account_id], "detail-type" = ["AWS API Call via CloudTrail"] })
}

resource "aws_cloudwatch_event_target" "guard_canary" {
  rule           = aws_cloudwatch_event_rule.guard_canary.name
  event_bus_name = aws_cloudwatch_event_bus.guard_canary.name
  arn            = aws_cloudwatch_log_group.guard_canary.arn
}

resource "aws_cloudwatch_log_metric_filter" "guard_canary" {
  name           = "orders-guard-core-canary"
  log_group_name = aws_cloudwatch_log_group.guard_canary.name
  pattern        = ""

  metric_transformation {
    name      = "guard-core-canary"
    namespace = "orders-guard-core"
    value     = "1"
  }
}

# 2 時間、canary の出来事が届かなければ鳴る。守りの口座の既定のバスに CloudTrail の出来事が届かない（組織の記録だけの口座で届かない、
# 芯の規則を外した、予定を止めた）なら、ci-writes・ci-assumed・tamper・reads も鳴らないので、ここが鳴り続ける。
resource "aws_cloudwatch_metric_alarm" "guard_canary_silent" {
  alarm_name          = "orders-guard-core-trail-silent"
  alarm_description   = "CloudTrail events from the guard account did not reach the core for 2 hours; the core rules cannot see the guard apply"
  namespace           = "orders-guard-core"
  metric_name         = "guard-core-canary"
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 2
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = [aws_sns_topic.guard_core.arn]

  depends_on = [aws_cloudwatch_log_metric_filter.guard_canary]
}

# 管理の口座の IAM の数を読む役割（第 15 回。信頼の根の「長く使える鍵を持たない」をコードにする）。
#   守りの口座の github-watch が毎時借り、GetAccountSummary の Users と AccountAccessKeysPresent が 0、AccountMFAEnabled が 1 かを確かめる。
#   1 つでも外れるか、借りられなければ ng（github_watch.py の check_mgmt_summary）。読めるのは数だけで、利用者の名前と鍵の中身は返らない。
#   変えられるのは管理の口座（信頼の根）だけで、変えたら trust-root-used と event-watch が 1 件ずつ鳴る。消されたら次の回が借りられずに ng になる。
resource "aws_iam_role" "mgmt_summary" {
  name                 = "orders-guard-core-mgmt-summary"
  max_session_duration = 3600
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { AWS = "arn:aws:iam::${var.security_account_id}:role/orders-guard-github-watch" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "mgmt_summary" {
  name = "account-summary-only"
  role = aws_iam_role.mgmt_summary.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "CountsOnly"
      Effect   = "Allow"
      Action   = "iam:GetAccountSummary"
      Resource = "*" # iac-scan:allow IAC-003 iam:GetAccountSummary は対象を絞れない（AWS の仕様）。返るのは数だけ
    }]
  })
}
