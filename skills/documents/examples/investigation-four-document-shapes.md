# 調査報告書: 調査報告書・ポストモーテム・要件定義書・仕様書の世界水準の形

> **3 行でわかる要約**
> 1. 4 種類の文書の雛形をどの骨格にするかを、Web の資料延べ 111 本から決めた調査報告書です。
> 2. 結論は、4 種類とも一流の実物に共通する骨格を採り、機械で確かめられる決まりに落とすことです（確信度は骨格が高、節名が中）。
> 3. 次にすることは、雛形 4 本と完成例 4 本と検査を含む 1 つの commit への、社長の承認です。

| 項目 | 内容 |
|---|---|
| 読み手と決めること | 社長が、雛形 4 本と検査の決まりを承認するかを決めるために読む |
| 調べた人 / 確かめた人 | 秘書と、種類ごとの調査役 4 人（別の文脈で動く補助の AI） / 秘書が 4 本の報告を突き合わせた |
| 期間（時間枠） | 2026-11-11 の 1 日。調査役は 1 種類ずつ、各 1 時間で打ち切った |
| 状態 | 確定（2026-11-11。読み手テスト 1 回の指摘を反映。完成例として `skills/documents/examples/` にも同じ本文を置く） |
| 様式 | My-Lab に既存の調査報告は旧い型だったので、`skills/documents/templates/investigation.md` の新しい雛形を使った |
| 版 | 1.0（2026-11-11） |

## 1. 問いと背景

問いは 1 つです。社長の指示の要旨は「4 種類の雛形も、Web で調べて世界最高峰に仕上げる」です。雛形を作る前に、一流の実物が共通して持つ骨格を知る必要がありました。手順書と運用設計書の前の調査（`tmp/flow/output-quality/research-document-shapes.md`、2026-11-11）で、骨格を実物に合わせると出力が変わることが分かっています。

| 番号 | 問い | 答えで決まること |
|---|---|---|
| 1 | 調査報告書・ポストモーテム・要件定義書・仕様書の雛形は、どの節を必須にし、何を機械で確かめるか | 雛形 4 本の節構成、完成例 4 本の形、check-doc の検査の決まり |

## 2. 範囲と前提

調べたのは、Web で読める規格の要約、一流の企業や団体の公開文書、日本の実務記事です。読めなかったのは、有料の規格本文（ISO/IEC/IEEE 29148 ほか）と書籍で、二次資料で補いました。My-Lab の外の社内文書は、社長の決まりで見ていません。

| 区分 | 内容 |
|---|---|
| 範囲 | 4 種類の文書の節構成、表の列、書き方の決まり、落とし穴、日本語の用語 |
| 範囲外 | 有料の規格本文と書籍の本文、PDF で取得できなかった資料、My-Lab の外にある文書 |
| 前提 | 読み手は写した先の AI と、その出力を読む人。採る決まりは `tools/lib/check_doc.py` で機械で確かめられるものを優先する |

### 2-1. 用語

本文で繰り返し使う規格と書き方の名前を、先にまとめます。出典の番号は 10 章の表を指します。

| 用語 | 意味 |
|---|---|
| 一次・二次 | 一次は作者が自分で観察し決めたもの（規格、公式の手引き、本人の記事）。二次はそれを解説したもの |
| 29148 | ISO/IEC/IEEE 29148。要件の書き方の国際規格で、要件文書の節構成と要件の 9 つの特性を決める（Y-6〜Y-11） |
| SRS | Software Requirements Specification。29148 が定めるソフトウェア要件仕様書（Y-7、S-6） |
| IEEE 830 | 29148 の前の、要件仕様書の規格（S-10） |
| EARS | 要件文を 5 つの型で書く書き方。Rolls-Royce で生まれた（Y-1） |
| Volere | 要件仕様の雛形。27 節と要件カード（Y-2〜Y-5） |
| ICD 203 | 米国の情報機関の分析の基準。確信度の語の出どころ（R-22） |
| IMRaD | 導入・方法・結果・考察の順に書く論文の型（R-20） |
| RFC・RFD | 設計の提案を文書で議論する形。Rust の RFC と Oxide の RFD（S-17、S-18） |
| ADR | 設計の決定を 1 枚で残す記録。Architecture Decision Record（S-19） |
| MoSCoW | 優先度を Must・Should・Could・Won't の 4 段で書く決まり（Y-23） |
| 非機能要求グレード | IPA（情報処理推進機構）が公開する非機能要件の一覧。大項目 A〜F（Y-16） |

## 3. 方法と期間

方法は、種類ごとに調査役 1 人が Web の資料を開いて読み、節構成と決まりを書き出すことです。4 本の報告を秘書が突き合わせ、共通の芯と相違を本書にまとめました。期間は 2026-11-11 の 1 日で、調査役は各 1 時間の時間枠で打ち切っています。出典は延べ 111 本で、同じページを 2 つの調査で読んだものが 3 組（R-15 と S-12、Y-6 と S-9、Y-7 と S-6）あります。

| 種類 | 読んだ出典 | 全文 | 一部 | 読めなかった主なもの |
|---|---|---|---|---|
| 調査報告書 | 31 本 | 26 | 5 | IPA の調査報告書 PDF、ICD 203 原本 PDF、MIT OCW の講義 PDF |
| ポストモーテム | 20 本 | 19 | 1（照合のみ） | Atlassian の Handbook 本文（検索抜粋と転載で照合）、SRE Workbook 付録 C 日本語版 |
| 要件定義書 | 33 本 | 30 | 3 | ISO/IEC/IEEE 29148 本文（有料）、IPA 要件定義ガイド本体 PDF、デジタル庁 DS-100 PDF |
| 仕様書 | 27 本 | 25 | 2 | 29148 と IEEE 830 と IPA の PDF、GitHub 本体（raw で代替） |

## 4. 観点と重み

雛形に載せる節と決まりは、4 つの観点で選びました。重みは観点が食い違ったときの優先の順で、点にはしていません。足切りは 1 つで、2 系統以上の出典が同じ節を求めないものは採りません。

| 観点 | 重み | 足切りか | 測り方 |
|---|---|---|---|
| 出典の一致 | 5 | はい（2 系統以上の出典が同じ節を求める） | 同じ節や列を求める出典の数 |
| 機械で確かめられるか | 4 | いいえ | 見出しの語、表の列、禁止の語で検査できるか |
| 日本の現場の語と合うか | 3 | いいえ | IPA や官公庁や国内の実務記事に同じ語があるか |
| 書く負担 | 2 | いいえ | 必須の節の数と、表の列の数 |

## 5. 候補

候補は 3 つで、A は My-Lab の今の型です。ポストモーテムは SRE の障害の記録、要件定義書は雛形が無い状態を現状としました。

| 候補 | 一言で | 現状との違い |
|---|---|---|
| A: 現状のまま | 調査報告は 5 節（問い・一次情報・比較表・結論・出典）、仕様書は 2026-11-06 の 7 節、ポストモーテムは障害の記録の 7 節、要件定義書は無し | 基準 |
| B: 一流の実物に共通する骨格 | 出典 2 系統以上が一致する節を必須にし、表の列と禁止の語を検査にする | 節が増え、表の列が決まる。検査が 17 項目増える |
| C: 規格をそのまま写す | 29148 の SRS 目次、Volere の 27 節、NASA の決定分析の 10 項目をそのまま節にする | 節が最多で、日本の現場の語と合わない節が残る |

## 6. 比較表と根拠

事実だけを書き、解釈は 7 章に分けます。根拠の列の番号は 10 章の出典を指します。R は調査報告書、P はポストモーテム、Y は要件定義書、S は仕様書の調査で読んだものです。

### 6-1. 候補の比較

4 つの観点で 3 候補を比べました。

| 観点 | A: 現状のまま | B: 一流の実物の骨格 | C: 規格をそのまま | 根拠 |
|---|---|---|---|---|
| 出典の一致 | 調査報告の 5 節は一致するが、方法・範囲・確信度の節が無い。仕様書は代替案と利用者の節が無い | 4 種類とも、2 系統以上が一致する節だけで組める | 規格 1 系統の節が多く、他の出典に無い節が残る | R-1、R-20、R-22、P-1〜P-3、Y-6〜Y-11、S-1、S-6 |
| 機械で確かめられるか | 見出しの語だけ | 見出しの語、表の列（根拠・参照日・担当・期限・優先度・状態）、禁止の語（曖昧語・反事実・注意だけの対策） | 見出しの語だけ | P-3、Y-10、Y-28、S-2 |
| 日本の現場の語と合うか | 節名が国内の実務記事の語と同じ（手順書・運用設計書・調査報告） | IPA の非機能要求グレードと、国内の実務記事の語に合わせた | 29148 や Volere の節名は、国内の実務記事に無いものが多い | R-26、Y-12〜Y-19、Y-27〜Y-30、P-14〜P-19、S-23、S-25 |
| 書く負担 | 最小 | 検査が必須にする語は種類ごとに 7〜12。雛形の必須の節は 7〜14 で、任意の節は消してよい | 27 節（Volere）、5 章と鏡写しの検証章（29148） | Y-2、Y-7、S-6 |

### 6-2. 調査報告書の骨格と根拠

出典 31 本は、分野が違っても同じ骨格を指しています。NASA の決定分析（R-1）が、最も具体的な節の一覧を持ちます。Minto（R-10〜R-12）は答えを先に置く順を、IMRaD（R-20）は結果と考察を分ける決まりを与えます。ICD 203（R-22）は、情報と判断を分け、確信度を書く決まりの出どころです。

| 節 | 要否 | 根拠（出典） |
|---|---|---|
| 問いと背景（状況・複雑化・問い） | 必須 | R-1、R-10、R-11 |
| 範囲と範囲外、前提 | 必須 | R-2、R-21 |
| 方法と期間（時間枠、環境、読んだ範囲） | 必須 | R-9、R-20、R-26 |
| 観点と重み、足切り | 比較のとき必須 | R-1、R-2、R-3、R-4 |
| 候補（現状を含む） | 比較のとき必須 | R-1、R-4、R-15 |
| 比較表（セルに事実と根拠） | 必須 | R-1、R-2、R-20、R-22 |
| 感度（上位の差が小さいとき） | 任意 | R-1、R-3 |
| 考察 | 任意 | R-20、R-26、R-27 |
| 未確認と限界 | 必須 | R-1、R-20、R-22 |
| 結論と推奨（確信度、推奨が変わる条件） | 必須 | R-1、R-2、R-22、R-23 |
| 出典（参照日） | 必須 | R-24、R-31 |
| 付録（必読にしない） | 任意 | R-14、R-27 |

機械で確かめる決まりは 4 つにしました。

| 決まり | 検査名 | 根拠 |
|---|---|---|
| 比較の表に、根拠か出典の列がある | 比較の表 | R-2、R-22 |
| 出典の表に、参照日の列がある | 出典の表 | R-24、R-31 |
| 結論の節に、確信度（高・中・低）がある | 確信度 | R-22、R-23 |
| 結論の節に、推奨が変わる条件がある | 変わる条件 | R-1、R-22 |

### 6-3. ポストモーテムの骨格と根拠

一致する節は 8 つで、要約・影響・検知・対応・タイムライン・原因・教訓・対策です。出どころは Google の SRE 本（P-1〜P-3）です。PagerDuty（P-4〜P-5）・Atlassian（P-6〜P-8）も同じ節を持ちます。incident.io（P-11〜P-13）と国内の 7 本（P-14〜P-20）も同じです。

思想が違う語もあります。Google は「根本原因と引き金」、Howie と incident.io は「寄与要因」と呼びます。根本原因の節に寄与要因を複数書く注記で、両方を満たします（P-10、P-11）。

| 節 | 要否 | 根拠（出典） |
|---|---|---|
| 文書情報（発生日、重大度、状態、著者、所有者、会議日） | 必須 | P-2、P-5、P-11 |
| 要約（2〜4 文） | 必須 | P-2、P-11、P-14 |
| 影響（数字。推定なら推定と書く） | 必須 | P-3、P-4、P-18 |
| 背景と用語 | 社外や他チームが読むなら必須 | P-3、P-10、P-18 |
| 経緯（障害の前にあったこと） | 必須 | P-4、P-7、P-15 |
| 検知（経路、検知までの時間） | 必須 | P-2、P-7、P-18 |
| 対応と復旧（復旧までの時間、確認） | 必須 | P-2、P-5、P-7 |
| タイムライン（時間帯の宣言、事実だけ、根拠） | 必須 | P-2、P-4、P-5、P-13 |
| 根本原因と引き金（寄与要因は複数） | 必須 | P-2、P-3、P-10、P-15 |
| 教訓（うまくいった・いかなかった・幸運） | 必須 | P-2、P-14、P-17 |
| 再発防止の対策（担当・期限・優先度・追跡先・状態） | 必須 | P-2、P-3、P-7、P-14 |
| やらないと決めた対策 | 任意 | P-4 |
| 外向けの文面 | 顧客に影響があれば必須 | P-4、P-17 |
| 参考資料 | 必須 | P-2、P-3 |
| レビューの記録 | 任意 | P-5 |

機械で確かめる決まりは 6 つです。

| 決まり | 検査名 | 根拠 |
|---|---|---|
| 影響の節に数字がある | 影響の数字 | P-3、P-4 |
| タイムラインは表で、時間帯（JST か UTC）を宣言する | タイムライン | P-2、P-5、P-7 |
| 対策の表に、担当・期限・優先度・状態の列がある | 対策の表 | P-2、P-3、P-7、P-14 |
| 対策の担当と期限が空でない | 担当と期限 | P-3、P-14、P-15 |
| 「注意する」「周知する」だけの対策が無い | 対策の形 | P-3、P-16、P-18 |
| 反事実（〜すべきだった、〜できたはず）が無い | 反事実 | P-9、P-10 |

### 6-4. 要件定義書の骨格と根拠

出典 33 本が一致する点は 5 つです。目的と範囲を先に置き、業務・機能・非機能の 3 分類で書き、1 要件 1 文で測れる受け入れ基準を付けます。さらに、優先度と根拠と追跡番号を列で持ち、対象外・前提・制約・未決事項を別の節に置きます。節の名前と順番は出典ごとに違いますが、芯は同じです。

文の形は EARS（Y-1）、要件の属性は 29148（Y-11）に合わせました。非機能の項目は IPA の非機能要求グレード 2018（Y-16〜Y-19）に合わせました。

| 節 | 要否 | 根拠（出典） |
|---|---|---|
| 文書情報（対象、決める人、状態、版、承認） | 必須 | Y-7、Y-27、Y-30 |
| 目的と背景 | 必須 | Y-2、Y-12、Y-28 |
| ゴールと管理指標（数値） | 必須 | Y-20、Y-30、Y-31 |
| 利害関係者と決める人 | 必須 | Y-2、Y-13、Y-30 |
| 用語定義 | 必須 | Y-7、Y-8、Y-13 |
| 範囲と対象外 | 必須 | Y-2、Y-7、Y-23、Y-27 |
| 前提と制約（由来つき） | 必須 | Y-3、Y-7、Y-15 |
| 業務要件（現行と新業務、業務量） | 必須 | Y-13、Y-27、Y-31 |
| 機能要件（ID、EARS の文、異常時、根拠、優先度、受け入れ基準、検証方法） | 必須 | Y-1、Y-3、Y-11、Y-15、Y-27、Y-28 |
| 非機能要件（非機能要求グレードの大項目、要求値、検証方法） | 必須 | Y-13、Y-16〜Y-19 |
| 移行・運用・教育・テストの要件 | 必須 | Y-13、Y-22、Y-31 |
| 受け入れ基準と検証方法（試験・実演・検査・解析） | 必須 | Y-3、Y-7、Y-11、Y-24 |
| 追跡表 | 必須 | Y-11、Y-26 |
| 未決事項（担当・期限） | 必須 | Y-3、Y-14、Y-28 |
| 保留（次の版の候補） | 任意 | Y-2、Y-30 |
| 参照文書 | 任意 | Y-7 |

機械で確かめる決まりは 5 つです。

| 決まり | 検査名 | 根拠 |
|---|---|---|
| 機能要件と非機能要件の表に、ID・優先度・受け入れ基準（か要求値）・検証方法の列がある | 要件の表 | Y-3、Y-11、Y-27、Y-28 |
| 要件 ID が空でなく、重複しない | 要件 ID | Y-11、Y-26 |
| 優先度は Must・Should・Could・Won't（必須・重要・あれば良い・今回はやらない） | 優先度 | Y-23、Y-28 |
| 要件の文に曖昧語（など、適切に、速やかに、十分な、可能な限り）が無い | 曖昧語 | Y-10、Y-27、Y-28 |
| 未決事項の表に、担当と期限の列がある | 未決の表 | Y-14、Y-28、Y-30 |

### 6-5. 仕様書の骨格と根拠

出典 27 本は 2 つの系統に分かれます。1 つは「何を・なぜ・振る舞い・受け入れ」を書く系統で、Joel と 29148 と IEEE 830 と国内の実務記事です。もう 1 つは「どう作るか」と取り捨てを記録する系統で、Google の設計文書と RFC と RFD と ADR です。雛形では 2 つの系統を 1 冊にまとめ、節で線を引きました。

2026-11-06 の仕様書の型も、新しい骨格の中にそのまま残ります。7 つの節は、完成の条件・全体像・将来の変化・実装の進め方・やらないこと・未確定・確認事項です。

| 節 | 要否 | 根拠（出典） |
|---|---|---|
| 前付け（状態、版、著者、審査者） | 必須 | S-3、S-6、S-18、S-19 |
| 要約 | 必須 | S-12、S-17 |
| 背景と範囲 | 必須 | S-1、S-6、S-25 |
| 利用者と場面 | 必須 | S-3、S-6、S-12 |
| 目標とやらないこと（やらないことは空にしない） | 必須 | S-1、S-3、S-23 |
| 全体像（文脈図と読み方） | 必須 | S-1、S-25 |
| 振る舞いの詳細（入力・処理・出力・異常時） | 必須 | S-3、S-6、S-25 |
| 外部との境目、データ、品質の数値 | 必須 | S-6、S-10、S-23、S-25 |
| 完成の条件と確かめ方（検証方法） | 必須 | S-6、S-8 |
| 設計の概要と制約 | 必須 | S-1、S-25 |
| 代替案と却下の理由 | 必須 | S-1、S-17、S-18、S-19 |
| 横断事項（安全、個人情報、観測、費用） | 必須 | S-1、S-18 |
| 実装の進め方と移行 | 既存データがあれば必須 | S-1、S-25 |
| 将来の変化（採用の理由にしない） | 任意 | S-17 |
| 未確定（担当と期限） | 必須 | S-3、S-17、S-23 |
| 用語、確認事項、改版履歴 | 必須 | S-6、S-19、S-25 |

機械で確かめる決まりは 2 つと、必須の節の特別な扱いが 1 つです。特別な扱いの根拠は出典ではなく、既存の仕様書を落とさないという 9 章の判断です。

| 決まり | 検査名 | 根拠 |
|---|---|---|
| 代替案の表に、却下の理由の列がある | 代替案の表 | S-1、S-17、S-19 |
| 未確定の表に、担当と期限の列がある | 未確定の表 | S-3、S-17、S-23 |
| 必須の節は、新しい 9 語（背景・利用者・目標・やらないこと・振る舞い・完成の条件・代替案・横断・未確定）か 2026-11-06 の 7 語のどちらかで満たせばよい | 必須の節 | 9 章の判断（既存の仕様書を落とさない） |

## 7. 考察

4 種類は 2 つの型に分かれます。調査報告書と仕様書は、判断する人が読む「資料の型」で、3 行の要約と節ごとの導入の文が効きます。要件定義書とポストモーテムは、表を芯にして現場で使う「現場の文書の型」です。文書情報の表から始まり、読み手の説明の節を置きません。この分け方は、手順書と運用設計書を現場の型にした前の調査（1 章で挙げた 2026-11-11 の調査報告）と同じ線です。

Joel の「雛形は有害」（S-5）と、規格の必須の節は矛盾しません。必須の節は出典 2 系統以上が一致する最小限にし、任意の節は消してよいと雛形に書くことで折り合います。日本語の節名は、IPA と官公庁と国内の実務記事にある語を優先しました。無い語（寄与要因、幸運だったこと）は訳を提案しています。

## 8. 未確認と限界

未確認は 5 つです。読めなかった資料 3 つは二次資料で補い、試していないこと 2 つは commit の前と最初の実地で試します。結論を変える可能性のあるものは、9 章の推奨が変わる条件に書きました。

| 未確認 | 理由 | 結論への影響 |
|---|---|---|
| ISO/IEC/IEEE 29148 の本文 | 有料で読めず、二次資料（Y-6〜Y-11）に頼った | 要件の属性の名前が本文と少し違う可能性がある。節構成への影響は小さい |
| Atlassian の Handbook 本文 | 8 回試みて案内の部分だけが返った。検索の抜粋と転載（P-7）で照合した | 項目名は 4 つの資料で一致しており、影響は小さい |
| IPA の要件定義ガイド本体と調査報告書の PDF | 10 メガバイト超か文字にならず、紹介ページと解説記事（Y-12〜Y-15、R-26）で代替した | 節構成への影響は小さい。本体の章立ては紹介ページの目次と一致する |
| 読み手テストの 2 回目 | 完成例 4 本と本書は、2026-11-11 に添削役の読み手テストを 1 回受けて指摘を反映した。直した版は 2 回目を受けていない | 節の名前の分かりやすさに影響する。次の文書の依頼のときに、見本も一緒に 2 回目を受ける |
| 写した先での実地の試し | 他のプロジェクトで雛形を使って書いた文書は、まだ無い | 相手の形に合わせる手順の過不足が分かるのは、最初の実地の後 |

## 9. 結論と推奨

問い 1 の答えは候補 B です。4 種類とも一流の実物に共通する骨格を採り、表の列と禁止の語を機械の検査に落とします。B は出典の一致と機械で確かめられるかの 2 つの観点で A と C に勝り、書く負担では A に劣ります。重みの高い観点を優先して B を採りました。確信度は、骨格については高、日本語の節名については中です。骨格は出典 2 系統以上が一致し、節名は訳語の提案を含むからです。推奨が変わる条件は 3 つです。

| 推奨が変わる条件 | 変わる内容 |
|---|---|
| 写した先に既存の同種の文書がある | 相手の節構成と文体を正本にし、雛形は欠けた節を補うだけに使う |
| 社長が節名の訳を変える | 雛形と検査の見出しの語を同時に直す |
| 29148 の本文で要件の属性の名前が違う | 要件定義書の表の列名を本文に合わせる |

次の一歩は 3 つで、最初の 1 つは社長の承認を待っています。

| 次の一歩 | 担当 | 期限 |
|---|---|---|
| 雛形 4 本、完成例 4 本、検査 17 項目を fix/output-quality の 1 つの commit に入れる | 秘書 | 社長の承認の後 |
| User Rules（Cursor の常時ルール）の本文を貼り替える | 社長 | 承認の後 |
| deploy.sh で写した先に配り、最初の実地で相手の形に合わせる手順を試す | 社長と秘書 | 写した先の最初の依頼 |

## 10. 出典

参照日はすべて 2026-11-11 です。一次は作者が自分で観察し決めたもの（規格、公式の手引き、本人の記事）、二次はそれを解説したものです。読んだ範囲の「一部」は、文字化けや会員制の壁で本文の一部しか読めなかったものです。

### 10-1. 調査報告書の調査で読んだもの（R）

一次が 19 本、二次が 12 本あります。

| 番号 | 題名 | 発行元 | URL | 一次・二次 | 読んだ範囲 | 参照日 |
|---|---|---|---|---|---|---|
| R-1 | 6.8 Decision Analysis（NASA Systems Engineering Handbook） | NASA | https://www.nasa.gov/reference/6-8-decision-analysis/ | 一次 | 全文 | 2026-11-11 |
| R-2 | Decision Management（SEBoK） | SEBoK（INCOSE ほか） | https://sebokwiki.org/wiki/Decision_Management | 一次 | 全文 | 2026-11-11 |
| R-3 | Decision-matrix method（Pugh 行列） | Wikipedia 英語版 | https://en.wikipedia.org/wiki/Decision-matrix_method | 二次 | 全文 | 2026-11-11 |
| R-4 | Pugh Matrix | iSixSigma | https://www.isixsigma.com/dictionary/pugh-matrix/ | 二次 | 全文 | 2026-11-11 |
| R-5 | Technology Radar FAQ | Thoughtworks | https://www.thoughtworks.com/radar/faq-and-more | 一次 | 全文 | 2026-11-11 |
| R-6 | Technology Radar（Vol.35、2026 年 11 月） | Thoughtworks | https://www.thoughtworks.com/radar | 一次 | 全文 | 2026-11-11 |
| R-7 | Build Your Own Radar | Thoughtworks | https://www.thoughtworks.com/radar/byor | 一次 | 全文 | 2026-11-11 |
| R-8 | Spikes | Scaled Agile（SAFe） | https://framework.scaledagile.com/spikes/ | 一次 | 一部（会員制の壁） | 2026-11-11 |
| R-9 | Agile Spikes Deliver Knowledge | Mountain Goat Software（Mike Cohn） | https://www.mountaingoatsoftware.com/blog/spikes | 一次 | 全文 | 2026-11-11 |
| R-10 | Minto Pyramid Principle（Home、Concept） | Barbara Minto 公式 | https://www.barbaraminto.com/ と /concept | 一次 | 全文（短い） | 2026-11-11 |
| R-11 | Lessons from Barbara Minto | Antoine Buteau | https://www.antoinebuteau.com/lessons-from-barbara-minto/ | 二次 | 全文 | 2026-11-11 |
| R-12 | Pyramid Principle | ThinkInsights | https://thinkinsights.net/strategy/pyramid-principle | 二次 | 全文 | 2026-11-11 |
| R-13 | The Beauty of Amazon's 6-Pager | Brad Porter（Amazon 副社長、当時） | https://www.linkedin.com/pulse/beauty-amazons-6-pager-brad-porter | 一次 | 全文 | 2026-11-11 |
| R-14 | Narratives & Decision Making | Working Backwards（Bryar と Carr のサイト） | https://workingbackwards.com/concepts/narratives-decision-making/ | 一次 | 全文 | 2026-11-11 |
| R-15 | PR/FAQ Instructions & Template | Working Backwards | https://workingbackwards.com/resources/working-backwards-pr-faq/ | 一次 | 全文 | 2026-11-11 |
| R-16 | Amazon's six-page narrative structure | Anecdote（Shawn Callahan） | https://www.anecdote.com/2018/05/amazons-six-page-narrative-structure/ | 二次 | 全文 | 2026-11-11 |
| R-17 | The Amazon Six Pager（2025-12-03） | released.so（Jens Schumacher） | https://released.so/articles/the-amazon-six-pager/ | 二次 | 全文 | 2026-11-11 |
| R-18 | Freeman の「Anatomy of an Amazon 6-pager」評 | Dennis G. Jerz | https://jerz.setonhill.edu/?p=39912 | 二次 | 全文 | 2026-11-11 |
| R-19 | Working Backwards 読書ノート | Andrew Clark | https://andrewclark.super.site/all-media/working-backwards | 二次 | 全文 | 2026-11-11 |
| R-20 | Writing an IMRaD Report | George Mason University Writing Center | https://writingcenter.gmu.edu/guides/writing-an-imrad-report | 一次 | 全文 | 2026-11-11 |
| R-21 | Organizing large documents（Technical Writing Two） | Google | https://developers.google.com/tech-writing/two/large-docs | 一次 | 全文 | 2026-11-11 |
| R-22 | Objectivity（ICD 203 の分析基準） | intelligence.gov（米 ODNI） | https://www.intelligence.gov/mission/our-values/objectivity | 一次 | 全文 | 2026-11-11 |
| R-23 | Words of estimative probability | Wikipedia 英語版 | https://en.wikipedia.org/wiki/Words_of_estimative_probability | 二次 | 全文 | 2026-11-11 |
| R-24 | MLA Works Cited: Electronic Sources | Purdue OWL | https://owl.purdue.edu/owl/research_and_citation/mla_style/mla_formatting_and_style_guide/mla_works_cited_electronic_sources.html | 一次 | 全文 | 2026-11-11 |
| R-25 | Primary Sources（図書館の手引き） | University of Illinois Library | https://www.library.illinois.edu/hpnl/tutorials/primary-sources/ | 一次 | 全文 | 2026-11-11 |
| R-26 | 調査報告書の構成と書き方 | CREX | https://crexgroup.com/ja/data/?p=3405 | 二次 | 全文 | 2026-11-11 |
| R-27 | 社会調査の講義 第 7 回「報告書」 | 田中重人（東北大学、2021 年度） | https://www.tsigeto.info/2021/intv/i211217.html | 一次 | 一部（文字化け） | 2026-11-11 |
| R-28 | 統計局の調査「調査の概要」ページ | 総務省統計局 | https://www.stat.go.jp/data/tuushin/gaiyou.html | 一次 | 一部（見出しのみ判読） | 2026-11-11 |
| R-29 | 結果報告書「契約における実質的な競争性の確保に関する調査」 | 総務省行政評価局 | https://www.soumu.go.jp/menu_news/s-news/81803.html | 一次 | 一部（章立てのみ） | 2026-11-11 |
| R-30 | IMRAD | Wikipedia 日本語版 | https://ja.wikipedia.org/wiki/IMRAD | 二次 | 一部（前半） | 2026-11-11 |
| R-31 | SIST02 スタイル（参照文献の書式の写し） | Scrapbox（pogi-log） | https://scrapbox.io/pogi-log/SIST02スタイル | 二次 | 全文 | 2026-11-11 |

読めなかった PDF は、IPA の調査報告書・田中重人の講義・MIT の講義・ICD 203 原本・北里大学図書館の手引きです。403 で開けなかったのは、IPCC の不確実性の手引き・Monash 大学の Minto 解説・Freeman の記事です。404 は Agile Alliance の用語集と Minto の Textbook ページです。SIST02 の原文は同意画面で止まりました。

### 10-2. ポストモーテムの調査で読んだもの（P）

一次が 19 本、二次が 1 本あります。

| 番号 | 題名 | 発行元 | URL | 一次・二次 | 読んだ範囲 | 参照日 |
|---|---|---|---|---|---|---|
| P-1 | SRE Book 第 15 章 Postmortem Culture: Learning from Failure | Google | https://sre.google/sre-book/postmortem-culture/ | 一次 | 全文 | 2026-11-11 |
| P-2 | SRE Book 付録 D Example Postmortem | Google | https://sre.google/sre-book/example-postmortem/ | 一次 | 全文 | 2026-11-11 |
| P-3 | SRE Workbook 第 10 章 Postmortem Culture: Learning from Failure | Google | https://sre.google/workbook/postmortem-culture/ | 一次 | 全文 | 2026-11-11 |
| P-4 | Postmortem Documentation（What Is、Step by Step、Tips、Analysis Questions、Meeting） | PagerDuty | https://postmortems.pagerduty.com/ | 一次 | 全文（雛形の PDF は読めず） | 2026-11-11 |
| P-5 | Incident Response Docs: Postmortem Template / Postmortem Process | PagerDuty | https://response.pagerduty.com/after/post_mortem_template/ と /after/post_mortem_process/ | 一次 | 全文 | 2026-11-11 |
| P-6 | Announcing postmortems for Jira Ops（2018-11-27） | Atlassian | https://www.atlassian.com/blog/company-news/announcing-postmortems-jira-ops | 一次 | 全文 | 2026-11-11 |
| P-7 | Incident postmortem / Postmortem templates / Handbook: Postmortems | Atlassian | https://www.atlassian.com/incident-management/postmortem | 一次 | 照合のみ（本文は取得できず。転載 https://slab.com/library/atlassian-postmortem-template で照合） | 2026-11-11 |
| P-8 | Opsgenie docs: Create a postmortem report | Atlassian | https://support.atlassian.com/opsgenie/docs/create-a-postmortem-report/ | 一次 | 全文 | 2026-11-11 |
| P-9 | Debriefing Facilitation Guide | Etsy | https://github.com/etsy/DebriefingFacilitationGuide | 一次 | 全文（PDF 版は読めず） | 2026-11-11 |
| P-10 | Howie: The Post-Incident Guide | Jeli（現 PagerDuty） | https://docs.pagerduty.com/ops-guides/howie-guide | 一次 | 全文（報告書の実例 PDF は未読） | 2026-11-11 |
| P-11 | Our simple-to-use incident post-mortem template | incident.io | https://incident.io/blog/incident-post-mortem-template | 一次 | 全文 | 2026-11-11 |
| P-12 | Guide: Learning from incidents — Writing a post-mortem | incident.io | https://incident.io/guide/learn-and-improve/ | 一次 | 全文 | 2026-11-11 |
| P-13 | Docs: Post-mortem templates | incident.io | https://docs.incident.io/post-incident/postmortem-templates | 一次 | 全文 | 2026-11-11 |
| P-14 | SRE チームでポストモーテムを始めてみた（2025-10-06） | GMO メディア（Zenn） | https://zenn.dev/gmomedia/articles/first-postmortem | 一次 | 全文 | 2026-11-11 |
| P-15 | ポストモーテム | kawasima（Scrapbox） | https://scrapbox.io/kawasima/ポストモーテム | 二次 | 全文 | 2026-11-11 |
| P-16 | 最強の障害報告書の書き方（2023-09-09） | みどり（Zenn） | https://zenn.dev/midori/articles/6ed7a1fca87d86 | 一次 | 全文 | 2026-11-11 |
| P-17 | 事後分析を外部と共有することの意義: CRE が現場で学んだこと（2017-12-15） | Google Cloud Japan | https://cloud.google.com/blog/ja/products/gcp/fearless-shared-postmortems-cre-life-lessons/?hl=ja | 一次 | 全文 | 2026-11-11 |
| P-18 | ミラティブサーバチームで行っている障害振り返りを紹介します（2021-04-02） | Mirrativ | https://tech.mirrativ.stream/entry/2021/04/02/130321 | 一次 | 全文 | 2026-11-11 |
| P-19 | メルカリの 3 つの Value で取り組むインシデント対応（2018-04-10） | メルカリ | https://engineering.mercari.com/blog/entry/2018-04-10-090453/ | 一次 | 全文 | 2026-11-11 |
| P-20 | データで見るサイバーエージェントグループの SRE と横断的な SRE 推進の取り組み（2023-07-12） | CyberAgent | https://developers.cyberagent.co.jp/blog/archives/42941/ | 一次 | 全文（ポストモーテムの部分） | 2026-11-11 |

読めなかったのは 2 つです。howie.jeli.io は名前が解決せず、PagerDuty への転送先（P-10）を読みました。403 だったのは、O'Reilly Japan の SRE Workbook 付録 C 日本語版です。

### 10-3. 要件定義書の調査で読んだもの（Y）

一次が 13 本、二次が 20 本あります。

| 番号 | 題名 | 発行元 | URL | 一次・二次 | 読んだ範囲 | 参照日 |
|---|---|---|---|---|---|---|
| Y-1 | EARS (Easy Approach to Requirements Syntax) | Alistair Mavin（元 Rolls-Royce） | https://alistairmavin.com/ears/ | 一次 | 全文 | 2026-11-11 |
| Y-2 | Volere Requirements Specification Template（公式紹介ページ） | Volere / Atlantic Systems Guild | https://www.volere.org/templates/volere-requirements-specification-template/ | 一次 | 全文（要件カードの欄は画像） | 2026-11-11 |
| Y-3 | Volere Requirements Specification Template Edition 13（2007） | Robertson & Robertson（silo.tips の写し） | https://silo.tips/download/volere-edition-13-august-2007 | 一次 | 一部（先頭 10 万字） | 2026-11-11 |
| Y-4 | Volere Requirements Specification Template（解説） | ReqView | https://www.reqview.com/doc/volere-template/ | 二次 | 全文 | 2026-11-11 |
| Y-5 | The Volere Snow Card | BA Coach | https://bacoach.nl/2026/03/the-volere-snow-card/ | 二次 | 全文 | 2026-11-11 |
| Y-6 | Software requirements specification | Wikipedia 英語版 | https://en.wikipedia.org/wiki/Software_requirements_specification | 二次 | 全文 | 2026-11-11 |
| Y-7 | System / Software Requirements Specification（29148 の SRS 例の目次） | Prof. Vanselow（SWEBOK 講義サイト） | https://sites.google.com/site/profvanselow/swebok/software-requirements-ch-1/5-specification/srs | 二次 | 全文 | 2026-11-11 |
| Y-8 | ISO 29148 Explained | Modern Requirements | https://www.modernrequirements.com/blogs/iso-29148-explained/ | 二次 | 全文 | 2026-11-11 |
| Y-9 | Leveraging LLMs for the Quality Assurance of Software Requirements（29148 の 9 特性の定義表） | arXiv 2408.10886 | https://arxiv.org/html/2408.10886 | 二次 | 一部（定義表） | 2026-11-11 |
| Y-10 | Rapid Quality Assurance with Requirements Smells（29148 の言語基準） | Femmer ほか、arXiv 1611.08847 | https://ar5iv.labs.arxiv.org/html/1611.08847 | 一次 | 一部（先頭 10 万字） | 2026-11-11 |
| Y-11 | ISO/IEC/IEEE 29148 Templates（要件の属性） | ReqView | https://www.reqview.com/doc/iso-iec-ieee-29148-templates/ | 二次 | 全文 | 2026-11-11 |
| Y-12 | ユーザのための要件定義ガイド 第 2 版（紹介ページ） | IPA 社会基盤センター | https://www.ipa.go.jp/archive/digital/iot-en-ci/jyouryuu/youkenteigi20190912.html | 一次 | 全文 | 2026-11-11 |
| Y-13 | 同 書籍情報ページ（目次つき） | IPA | https://www.ipa.go.jp/archive/publish/tn20191220.html | 一次 | 全文 | 2026-11-11 |
| Y-14 | IPA 要件定義ガイドの要点とは？ | 株式会社一創 | https://www.issoh.co.jp/column/details/18681/ | 二次 | 全文 | 2026-11-11 |
| Y-15 | 機能要件の合意形成ガイド（紹介ページ） | IPA | https://www.ipa.go.jp/archive/digital/iot-en-ci/jyouryuu/ent03-a.html | 一次 | 全文 | 2026-11-11 |
| Y-16 | 非機能要求グレード 2018（公式ページ） | IPA | https://www.ipa.go.jp/archive/digital/iot-en-ci/jyouryuu/hikinou/ent03-b.html | 一次 | 全文 | 2026-11-11 |
| Y-17 | 非機能要求グレードの歩き方 Index / Vol.1 | NTT DATA TECH（Zenn） | https://zenn.dev/nttdata_tech/articles/c16414c86883cb と /articles/d2cc80bf9d8ff6 | 二次 | 全文 | 2026-11-11 |
| Y-18 | IPA 非機能要求グレード 2018 とは？ | 株式会社一創 | https://www.issoh.co.jp/tech/details/8441/ | 二次 | 全文 | 2026-11-11 |
| Y-19 | 非機能要件とは？6 大項目の数値化と閾値テスト | 株式会社一創 | https://www.issoh.co.jp/tech/details/17610/ | 二次 | 全文 | 2026-11-11 |
| Y-20 | Types of Requirements as per BABOK | Techcanvass | https://techcanvass.com/blogs/types-of-requirements-as-per-babok | 二次 | 全文 | 2026-11-11 |
| Y-21 | Requirements in Business Analysis（BABOK v3） | microTOOL | https://www.microtool.de/en/knowledge-base/requirements-in-business-analysis/ | 二次 | 全文 | 2026-11-11 |
| Y-22 | Requirements Classification（CBAP 学習ガイド） | Open Exam Prep | https://open-exam-prep.com/study-guides/cbap/introduction-baccm-framework/key-concepts-requirements-classification | 二次 | 全文 | 2026-11-11 |
| Y-23 | MoSCoW Prioritisation（DSDM） | Agile Business Consortium | https://www.agilebusiness.org/?p=1907 | 一次 | 全文 | 2026-11-11 |
| Y-24 | GivenWhenThen | Martin Fowler | https://martinfowler.com/bliki/GivenWhenThen.html | 一次 | 全文 | 2026-11-11 |
| Y-25 | Gherkin Reference | Cucumber | https://cucumber.io/docs/gherkin/reference/ | 一次 | 全文 | 2026-11-11 |
| Y-26 | SWE-052 Bidirectional Traceability | NASA Software Engineering Handbook | https://swehb.nasa.gov/x/TYCZD | 一次 | 全文 | 2026-11-11 |
| Y-27 | 要件定義書の書き方: 章立てサンプル・記載項目・レビュー観点 | 株式会社一創 | https://www.issoh.co.jp/tech/details/12849/ | 二次 | 全文 | 2026-11-11 |
| Y-28 | 要件定義書の書き方と重要項目 12 選 | CREX Development | https://crexgroup.com/ja/development/project/requirements-definition-writing-guide/ | 二次 | 全文 | 2026-11-11 |
| Y-29 | 要件定義の成果物とは？ | 比較ビズまとめ | https://www.biz.ne.jp/matome/2005051/ | 二次 | 全文 | 2026-11-11 |
| Y-30 | 要件定義の進め方【発注側】5 つの手順と記入例 | AI 革命株式会社 | https://ai-revolution.co.jp/media/requirements-definition-guide/ | 二次 | 全文 | 2026-11-11 |
| Y-31 | 要件定義書サンプル（目次のみ。政府標準ガイドライン型） | 公開 Google ドキュメント（作成者不明） | https://docs.google.com/document/d/1_noLThKTpbXIQMhKmjMC3bOTFuHtb3qSqG2iopZHseg/export?format=html | 二次 | 全文（目次だけの文書） | 2026-11-11 |
| Y-32 | デジタル社会推進標準ガイドライン群（文書一覧） | デジタル庁 | https://www.digital.go.jp/resources/standard_guidelines | 一次 | 全文 | 2026-11-11 |
| Y-33 | 『デジタル・ガバメント推進標準ガイドライン』の「活用パターン」 | @IT（2020-12-14） | https://atmarkit.itmedia.co.jp/ait/articles/2012/14/news009.html | 二次 | 全文（一部文字化け） | 2026-11-11 |

ISO/IEC/IEEE 29148 の本文は有料で、特性の定義は二次資料（Y-8〜Y-10）に頼りました。10 メガバイト超で取れなかったのは、IPA の要件定義ガイド本体とデジタル庁 DS-120 の PDF です。本文が文字にならなかったのは、DS-100・Volere・INCOSE の PDF です。INCOSE の公式ページは 403 でした。

### 10-4. 仕様書の調査で読んだもの（S）

一次が 12 本、二次が 15 本あります。

| 番号 | 題名 | 発行元 | URL | 一次・二次 | 読んだ範囲 | 参照日 |
|---|---|---|---|---|---|---|
| S-1 | Design Docs at Google | Malte Ubl（industrialempathy.com） | https://www.industrialempathy.com/posts/design-docs-at-google/ | 一次 | 全文 | 2026-11-11 |
| S-2 | Painless Functional Specifications Part 1: Why Bother? | Joel Spolsky | https://www.joelonsoftware.com/2000/10/02/painless-functional-specifications-part-1-why-bother/ | 一次 | 全文 | 2026-11-11 |
| S-3 | 同 Part 2: What's a Spec? | Joel Spolsky | https://www.joelonsoftware.com/2000/10/03/painless-functional-specifications-part-2-whats-a-spec/ | 一次 | 全文 | 2026-11-11 |
| S-4 | 同 Part 3: But... How? | Joel Spolsky | https://www.joelonsoftware.com/2000/10/04/painless-functional-specifications-part-3-but-how/ | 一次 | 全文 | 2026-11-11 |
| S-5 | 同 Part 4: Tips | Joel Spolsky | https://www.joelonsoftware.com/2000/10/15/painless-functional-specifications-part-4-tips/ | 一次 | 全文 | 2026-11-11 |
| S-6 | SRS outline（ISO/IEC/IEEE 29148-2018 の節構成の要約） | Prof. Vanselow SWEBOK ノート | https://sites.google.com/site/profvanselow/swebok/software-requirements-ch-1/5-specification/srs | 二次 | 全文 | 2026-11-11 |
| S-7 | ISO/IEC/IEEE 29148 解説 | Modern Requirements | https://www.modernrequirements.com/?p=32595 | 二次 | 全文 | 2026-11-11 |
| S-8 | 29148 準拠 SRS の実例 | ReqView | https://reqview-homepage.netlify.app/doc/iso-iec-ieee-29148-srs-example | 二次 | 全文 | 2026-11-11 |
| S-9 | Software requirements specification | Wikipedia 英語版 | https://en.wikipedia.org/wiki/Software_requirements_specification | 二次 | 全文 | 2026-11-11 |
| S-10 | IEEE 830-1998 SRS 講義ページ | wildart.github.io（大学講義） | https://wildart.github.io/MISG5020/SRS.html | 二次 | 全文 | 2026-11-11 |
| S-11 | Writing Requirements | Old Dominion Univ. CS350 | https://www.cs.odu.edu/~zeil/cs350/latest/Public/reqts/index.html | 二次 | 全文 | 2026-11-11 |
| S-12 | Working Backwards PR/FAQ Instructions & Template | Colin Bryar / Bill Carr（workingbackwards.com） | https://workingbackwards.com/resources/working-backwards-pr-faq/ | 一次 | 全文 | 2026-11-11 |
| S-13 | The Amazon Working Backwards PR/FAQ Process | 同上 | https://workingbackwards.com/concepts/working-backwards-pr-faq-process/ | 一次 | 全文 | 2026-11-11 |
| S-14 | How to Write an Amazon PR/FAQ | koji.so | https://www.koji.so/docs/working-backwards-pr-faq-guide | 二次 | 全文 | 2026-11-11 |
| S-15 | The Amazon Writing Culture | Marcelo Calbucci（元 Amazon、theprfaq.com） | https://www.theprfaq.com/articles/amazon-writing-culture | 一次 | 全文 | 2026-11-11 |
| S-16 | Amazon 6-pager | Fibery blog | https://fibery.com/blog/product-management/amazon-6-pager | 二次 | 全文 | 2026-11-11 |
| S-17 | Rust RFC 0000-template.md | rust-lang/rfcs | https://raw.githubusercontent.com/rust-lang/rfcs/master/0000-template.md | 一次 | 全文 | 2026-11-11 |
| S-18 | RFD 1 Requests for Discussion | Oxide Computer | https://rfd.shared.oxide.computer/rfd/0001 | 一次 | 全文 | 2026-11-11 |
| S-19 | Documenting Architecture Decisions | Michael Nygard（Cognitect） | https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions | 一次 | 全文 | 2026-11-11 |
| S-20 | SEC BOOKS: 共通フレーム 2013（書籍紹介） | IPA | https://www.ipa.go.jp/publish/secbooks20130304.html | 一次 | 全文（HTML の部分のみ） | 2026-11-11 |
| S-21 | 共通フレーム | Wikipedia 日本語版 | https://ja.wikipedia.org/wiki/共通フレーム | 二次 | 全文 | 2026-11-11 |
| S-22 | 基本設計とは？どこまで決めるか・成果物一覧と要件定義・詳細設計との違い | 株式会社一創 | https://www.issoh.co.jp/column/details/2828/ | 二次 | 全文 | 2026-11-11 |
| S-23 | 仕様書とは？設計書・要件定義書との違いと発注者が確認すべき観点 | 株式会社一創 | https://www.issoh.co.jp/column/details/13200/ | 二次 | 全文 | 2026-11-11 |
| S-24 | システム要件定義とは？業務要件・ソフトウェア要件との違いと決める項目 | 株式会社一創 | https://www.issoh.co.jp/column/details/18676/ | 二次 | 全文 | 2026-11-11 |
| S-25 | 基本設計書の書き方とは？テンプレートでわかる作成項目とポイント | CREX Consulting | https://crexgroup.com/ja/consulting/operation/basic-design-document-template/ | 二次 | 全文 | 2026-11-11 |
| S-26 | サンプル例に見る機能仕様書の基本的な書き方＆読みやすくする 7 つのテクニック | @IT（ITmedia） | https://atmarkit.itmedia.co.jp/ait/articles/1502/06/news013.html | 二次 | 一部（1/3 ページ、文字化け） | 2026-11-11 |
| S-27 | ドキュメントは最強のコミュニケーションツールである――Joel の機能仕様書入門 | @IT（ITmedia） | https://atmarkit.itmedia.co.jp/ait/articles/1412/15/news023_2.html | 二次 | 一部 | 2026-11-11 |

GitHub 本体は 503 で、raw.githubusercontent.com で代替しました。29148 と IEEE 830 と IPA の PDF は本文を取れず、HTML の公開要約で代替しました。@IT は文字化けで、1 ページ目と一部だけを読んでいます。

## 11. 付録

付録を読まなくても、結論は 9 章までで判断できます。ここには、雛形に使った日本語の用語の対応と、主要な一次資料の節構成を置きます。

### 11-1. 用語の対応（英語と雛形の日本語）

訳は、国内の資料に同じ語があればそれを採り、無ければ提案しました。

| 英語 | 雛形の日本語 | 根拠 |
|---|---|---|
| Decision needed / Question | 問い（決めたいこと） | R-1、R-10 |
| Scope / Non-scope | 範囲と範囲外 | R-21、S-1 |
| Criteria / Weights / Mandatory criteria | 観点・重み・足切り条件 | R-1、R-2 |
| Alternatives / Baseline | 候補・現状のまま（基準案） | R-1、R-3、R-4 |
| Confidence（high / moderate / low） | 確信度（高・中・低） | R-22、R-23 |
| Accessed / Updated | 参照日・更新日 | R-24、R-31 |
| Blameless | 非難しない（人名ではなく役職で） | P-1、P-17 |
| Trigger | 引き金 | P-2、P-14 |
| Contributing factors | 寄与要因（提案） | P-6、P-11 |
| Where we got lucky | 幸運だったこと（再現性なし） | P-2、P-14 |
| Action items | 再発防止の対策 | P-2、P-14、P-19 |
| Severity | 重大度 | P-4、P-20 |
| EARS の 5 型 | 常時型・事象起点型・状態起点型・望ましくない事象型・任意機能型（提案） | Y-1 |
| Fit criterion / Acceptance criteria | 受け入れ基準 | Y-3、Y-24 |
| Verification method（Test, Demonstration, Inspection, Analysis） | 検証方法（試験・実演・検査・解析） | Y-11 |
| MoSCoW | 優先度（必須・重要・あれば良い・今回はやらない） | Y-23 |
| Open issues / Waiting room | 未決事項・保留 | Y-2、Y-3 |
| Traceability matrix | 追跡表 | Y-26 |
| Goals and non-goals | 目標とやらないこと | S-1、S-3 |
| Alternatives considered | 代替案と却下の理由 | S-1、S-17 |
| Cross-cutting concerns | 横断事項 | S-1 |
| Unresolved questions / Open issues | 未確定（未解決の問い） | S-3、S-17 |
| Status | 状態（下書き・審査中・承認・置換・放棄） | S-18、S-19 |

### 11-2. 主要な一次資料の節構成

雛形の節の順番は、次の資料の順番を参考にしました。

| 出典 | 節構成（原文の順） |
|---|---|
| R-1 NASA 決定分析の報告の 10 項目 | 任務と系統の文脈、必要な決定と意図する結果、決定基準、候補、評価の方法と道具、前提・不確実さ・感度、全候補の評価結果、推奨、最終決定と理由、学び |
| R-26 CREX の調査報告書 | 要旨、調査の目的・背景、調査の概要（期間・対象・方法・項目）、調査結果、分析・考察、まとめ・結論、提言、添付資料 |
| P-2 Google SRE 本 付録 D | Date、Authors、Status、Summary、Impact、Root Causes、Trigger、Resolution、Detection、Action Items（Type・Owner・Bug）、Lessons Learned（well・wrong・lucky）、Timeline（all times UTC）、Supporting information |
| P-5 PagerDuty の雛形 | Owner、Meeting、Overview、What Happened、Contributing Factors、Resolution、Impact、Responders、Timeline（Time (UTC)・Event・Data Link）、How'd We Do?、Action Items、Messaging |
| P-11 incident.io の 8 節 | Key information、Incident summary、Incident timeline、Contributors、Mitigators、Learnings and risks、Follow-up actions、Meeting notes |
| Y-7 29148 の SRS 例 | 1 はじめに（目的・範囲・製品の概観・定義）、2 参照文書、3 個別要件（機能・性能・使用性・インタフェース・論理データベース・設計制約・属性・補足）、4 検証（3 章と鏡写し）、5 付録 |
| Y-3 Volere の 27 節 | 駆動要因（1〜3）、制約（4〜6）、機能要件（7〜9）、非機能要件（10〜17）、プロジェクトの課題（18〜27） |
| Y-16 非機能要求グレード 2018 | 大項目 A 可用性・B 性能・拡張性・C 運用・保守性・D 移行性・E セキュリティ・F システム環境・エコロジー。中項目 35、小項目 118、メトリクス 238、レベル 0〜5 |
| S-1 Google の設計文書 | 背景と範囲、目標と非目標、設計本体（文脈図・API・データ・コード・制約の強さ）、代替案、横断事項 |
| S-3 Joel の機能仕様書 | 免責、著者、シナリオ、非目標、概要、詳細、未決事項、補足 |
| S-17 Rust RFC | 要約、動機、案内水準の説明、参照水準の説明、欠点、根拠と代替案、先行事例、未解決の問い、将来の可能性 |
| S-19 ADR | 題名、背景、決定、状態、結果 |
