# 信頼の根の CI（組織の管理の口座）。org/ と foundation/ を適用する土台の CI の資格と、その信頼を、ここでコードにする。
#   管理の口座の役割 orders-org-apply: 借りられるのは、セキュリティだけが承認する環境 org-guarded を通った main の org-apply.yml だけ。
#     sub は org/github.tf で repo・context・job_workflow_ref の形。環境と workflow の file が合わない job（作る job、PR）は借りられない。
#   作業の口座の役割 platform-foundation: 管理の口座の orders-org-apply だけが借りられる。役割そのものは、組織の StackSet が
#     作業の口座の OU に置く（作業の口座の中の主体は作れない。StackSet の変更は管理の口座の操作なので、trust-root-used が鳴る）。
#   使ったら鳴る: 管理の口座で役割を借りた瞬間（人でも CI でも）に、守りの口座の trust-root-used が鳴る。作業の口座で platform-foundation を
#     借りた瞬間に guarded-apply-used が鳴る。組織の形を変える操作（口座の移動と外し、委任、SCP の付け外し）は org-guard-change が鳴る。
#   この file を変えられるのは、管理の口座への適用だけ（org-guarded の承認と、上の 3 つの見張り）。最初の 1 回は人が管理の口座で適用し、
#   その入りも trust-root-used が鳴る。

data "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
}

resource "aws_iam_role" "org_apply" {
  name                 = "orders-org-apply"
  max_session_duration = 3600
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = data.aws_iam_openid_connect_provider.github.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          "token.actions.githubusercontent.com:sub" = "repo:${var.github_repository}:environment:org-guarded:job_workflow_ref:${var.github_repository}/.github/workflows/org-apply.yml@refs/heads/main${local.gh_ids}"
        }
      }
    }]
  })
}

# 組織の上限と人の許可セットと、土台の役割を置く StackSet を変える操作。どれも組織の操作で、対象を ARN で名指しできない物が多い。
resource "aws_iam_role_policy" "org_apply" {
  name = "apply-org-and-foundation"
  role = aws_iam_role.org_apply.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "OrgPoliciesSsoTrailStackSets"
        Effect = "Allow"
        Action = [
          "organizations:DescribeOrganization", "organizations:DescribeOrganizationalUnit", "organizations:DescribePolicy",
          "organizations:DescribeAccount", "organizations:ListRoots", "organizations:ListPolicies", "organizations:ListTargetsForPolicy",
          "organizations:ListPoliciesForTarget", "organizations:ListTagsForResource", "organizations:ListDelegatedAdministrators",
          "organizations:ListAccountsForParent", "organizations:CreatePolicy", "organizations:UpdatePolicy", "organizations:AttachPolicy",
          "organizations:DetachPolicy", "organizations:EnablePolicyType", "organizations:TagResource", "organizations:RegisterDelegatedAdministrator",
          "sso:ListInstances", "sso:DescribePermissionSet", "sso:CreatePermissionSet", "sso:UpdatePermissionSet", "sso:ListTagsForResource",
          "sso:GetInlinePolicyForPermissionSet", "sso:PutInlinePolicyToPermissionSet", "sso:ListManagedPoliciesInPermissionSet",
          "sso:AttachManagedPolicyToPermissionSet", "sso:ProvisionPermissionSet", "sso:DescribePermissionSetProvisioningStatus",
          "sso:CreateAccountAssignment", "sso:ListAccountAssignments", "sso:DescribeAccountAssignmentCreationStatus",
          "identitystore:DescribeGroup", "cloudformation:CreateStackSet", "cloudformation:UpdateStackSet", "cloudformation:DescribeStackSet",
          "cloudformation:DescribeStackSetOperation", "cloudformation:CreateStackInstances", "cloudformation:DescribeStackInstance",
          "cloudformation:ListStackInstances", "iam:GetRole", "iam:GetRolePolicy", "iam:ListRolePolicies", "iam:ListAttachedRolePolicies",
          "iam:GetOpenIDConnectProvider",
        ]
        Resource = "*" # iac-scan:allow IAC-003 組織・許可セット・StackSet の操作は対象を ARN で名指しできない物が多い。管理の口座の役割で、使えば trust-root-used が鳴る
      },
      {
        Sid      = "AssumeFoundationOnly"
        Effect   = "Allow"
        Action   = "sts:AssumeRole"
        Resource = [for a in values(var.workload_accounts) : "arn:aws:iam::${a}:role/platform-foundation"]
      },
      {
        # 組織の形を変えて SCP を外す操作は、この役割にも許さない。口座の移動と外し、組織の解体、SCP の型を止める、委任の解除。
        Sid      = "NoOrgShapeChange"
        Effect   = "Deny"
        Action   = ["organizations:MoveAccount", "organizations:RemoveAccountFromOrganization", "organizations:DeleteOrganization", "organizations:DisablePolicyType", "organizations:DeregisterDelegatedAdministrator", "organizations:DeleteOrganizationalUnit"]
        Resource = "*"
      },
    ]
  })
}

# 作業の口座の platform-foundation。foundation/ の適用に要る操作だけを名指しする（役割と方針と OIDC の窓口、口座の公開のブロック、状態のバケット）。
# 作業の口座の SCP（allow_list）の内側で動き、借りた瞬間に守りの口座の guarded-apply-used が鳴る。
resource "aws_cloudformation_stack_set" "platform_foundation" {
  name             = "orders-platform-foundation"
  permission_model = "SERVICE_MANAGED"
  capabilities     = ["CAPABILITY_NAMED_IAM"]

  auto_deployment {
    enabled                          = true
    retain_stacks_on_account_removal = false
  }

  template_body = jsonencode({
    Resources = {
      Role = {
        Type = "AWS::IAM::Role"
        Properties = {
          RoleName           = "platform-foundation"
          MaxSessionDuration = 3600
          AssumeRolePolicyDocument = {
            Version = "2012-10-17"
            Statement = [{
              Effect    = "Allow"
              Principal = { AWS = aws_iam_role.org_apply.arn }
              Action    = "sts:AssumeRole"
            }]
          }
          Policies = [{
            PolicyName = "apply-foundation"
            PolicyDocument = {
              Version = "2012-10-17"
              Statement = [
                {
                  Effect = "Allow"
                  Action = [
                    "iam:CreateRole", "iam:UpdateRole", "iam:DeleteRole", "iam:GetRole", "iam:TagRole", "iam:UntagRole",
                    "iam:PutRolePolicy", "iam:DeleteRolePolicy", "iam:GetRolePolicy", "iam:ListRolePolicies",
                    "iam:AttachRolePolicy", "iam:DetachRolePolicy", "iam:ListAttachedRolePolicies", "iam:PutRolePermissionsBoundary",
                    "iam:UpdateAssumeRolePolicy", "iam:ListInstanceProfilesForRole", "iam:CreatePolicy", "iam:CreatePolicyVersion",
                    "iam:DeletePolicyVersion", "iam:GetPolicy", "iam:GetPolicyVersion", "iam:ListPolicyVersions", "iam:DeletePolicy",
                    "iam:CreateOpenIDConnectProvider", "iam:GetOpenIDConnectProvider", "iam:AddClientIDToOpenIDConnectProvider",
                  ]
                  Resource = ["arn:aws:iam::*:role/orders-admin-*", "arn:aws:iam::*:policy/orders-admin-*", "arn:aws:iam::*:oidc-provider/token.actions.githubusercontent.com"]
                },
                {
                  Effect   = "Allow"
                  Action   = ["s3:ListBucket", "s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:GetLifecycleConfiguration", "s3:PutLifecycleConfiguration"]
                  Resource = ["arn:aws:s3:::orders-admin-*-tfstate-*", "arn:aws:s3:::orders-admin-*-tfstate-*/*"]
                },
                {
                  Effect   = "Allow"
                  Action   = ["s3:GetAccountPublicAccessBlock", "s3:PutAccountPublicAccessBlock"]
                  Resource = "*" # iac-scan:allow IAC-003 口座の公開のブロックは口座の単位の操作で、対象を名指しできない
                },
              ]
            }
          }]
        }
      }
    }
  })
}

resource "aws_cloudformation_stack_set_instance" "platform_foundation" {
  stack_set_name            = aws_cloudformation_stack_set.platform_foundation.name
  stack_set_instance_region = "us-east-1"

  deployment_targets {
    organizational_unit_ids = [var.workload_ou_id]
  }
}

# org-guarded の環境と、守りの口座へ適用する security-guarded の環境（security/ci.tf の orders-guard-apply が信頼する）。
# 承認するのはセキュリティのチームの 1 人で、自分の変更は承認できない。管理者も承認を越えられない。配備できるのは main だけ。
resource "github_repository_environment" "org_guarded" {
  for_each            = toset(["org-guarded", "security-guarded"])
  repository          = local.repo_name
  environment         = each.value
  prevent_self_review = true
  can_admins_bypass   = false

  reviewers {
    teams = [var.security_reviewer_team_id]
  }

  deployment_branch_policy {
    protected_branches     = false
    custom_branch_policies = true
  }
}

resource "github_repository_environment_deployment_policy" "org_guarded" {
  for_each       = github_repository_environment.org_guarded
  repository     = local.repo_name
  environment    = each.value.environment
  branch_pattern = "main"
}

# 環境を 2 つにしたときの置き場の移し。計画に置き換えと削除を出さない。
moved {
  from = github_repository_environment.org_guarded
  to   = github_repository_environment.org_guarded["org-guarded"]
}

moved {
  from = github_repository_environment_deployment_policy.org_guarded
  to   = github_repository_environment_deployment_policy.org_guarded["org-guarded"]
}
