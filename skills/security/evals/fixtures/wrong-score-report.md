# 侵入テストの報告: 点数の負例（試験用）

> **3 行でわかる要約**
> 1. cvss4 の --report の負例です。
> 2. F-1 は点数を盛り、F-2 は重さを軽く書いています。
> 3. 計算との食い違いを名指しで落とすことを確かめます。

## 発見

発見は 2 件です。

### F-1: 点数を盛った

採点は `CVSS:4.0/AV:N/AC:L/AT:N/PR:L/UI:N/VC:H/VI:N/VA:N/SC:N/SI:N/SA:N` で、点数: 9.1、重さ: Critical です。

### F-2: 重さを軽く書いた

採点は `CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:N/SC:N/SI:N/SA:N` で、点数: 9.3、重さ: High です。
