# orders-admin 注文 API 再起動 手順書

| 項目 | 内容 |
|---|---|
| 作業名 | 注文 API の再起動 |
| 対象システム | orders-admin（検証 stg） |
| 作業者 / 確認者 | SRE 役 / インフラ役 |
| 承認 | 不要（検証環境） |
| 版 | 1.0（2026-11-11） |

## 1. 目的

検証環境の注文 API を再起動し、起動後に正常に応答することを確かめる。

## 2. 前提条件

- 検証環境を操作できる権限がある。

## 3. 事前確認

| # | 確認項目 | 確認方法 | 期待結果 |
|---|---|---|---|
| 1 | サービスの状態 | `aws ecs describe-services --cluster orders-admin-stg --services orders-api` | `runningCount` が 1 以上 |

## 4. 作業手順

1. サービスを強制的に再配置する。
   ```sh
   aws ecs update-service --cluster orders-admin-stg --service orders-api --force-new-deployment
   ```
2. 安定するまで待つ。
   ```sh
   aws ecs wait services-stable --cluster orders-admin-stg --services orders-api
   ```
   - 期待結果: 命令が終了コード 0 で終わる。

## 5. 切り戻し

1. 前の版のタスク定義に戻す。
   - 期待結果: `runningCount` が 1 以上に戻る。

## 6. 作業記録

```text
- 実施日時:
```
