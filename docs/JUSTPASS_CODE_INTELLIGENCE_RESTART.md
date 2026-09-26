# JustPass コード調査導線の再開メモ

状態: **2026-09-26に更新停止連絡を受けて再開済み**。以下の停止時点の証拠と当初計画は履歴として残す。現在の結果は `/home/tn/projects/aidev/docs/STATUS.md` の「JustPass更新停止後の再受入」を参照する。

## 目的と停止理由

目標は、ユーザーがツール名を指定しない調査で、Codexが必要に応じてSerena・Graphify・CRG・Terrainを選び、利用可能な結果を実ソースで確認できる状態にすること。ツールを**呼んだこと**と、索引が新しく**有効な結果を返したこと**、回答まで**完了したこと**を別々に判定する。

JustPassでは別の更新が並行し、解析後にもHEADとコード入力が変わった。索引を今更新してもすぐ古くなる可能性があるため、利用者から更新停止の連絡があるまで、JustPassのinit・refresh・設定変更・Git書込みを再開しない。

## 停止時点の証拠

- aidev: `/home/tn/projects/aidev` のHEADは `4230631eb0e99159b2f748a774e43b935a8717ce`、working treeはclean。現行の操作・受入履歴は `/home/tn/projects/aidev/docs/STATUS.md`。このHEADのcommit・remote反映は別の実行で起きており、このメモの作成者はcommit/pushしていない。
- JustPass: `/home/tn/projects/JustPass` のHEADは `eb08d74d28ef71c86dd21c0c4fcc889321c2895e`。`AGENTS.md`、`.gitignore`、`.graphifyignore`、`.code-review-graphignore` に未commit変更がある。内容・所有者を再開時に再確認し、勝手にstage・破棄しない。
- 最後のread-only診断は `aidev doctor --json` が `NEEDS_INIT`、`aidev terrain doctor --json` が `TERRAIN_NEEDS_REFRESH`。どちらも並行更新後の状態。以前の `LOCAL_READY` / `TERRAIN_READY_CONTEXT_NOT_BUILT` は過去のスナップショット。
- ツール名を指定しないCodex実セッションで、Serenaの定義・参照照会は回答まで完了。GraphifyのqueryとTerrainのgrep-pack/read-pack-fileはexit 0を確認したが、回答前にセッションを中断した。CRGの `get_minimal_context_tool` は呼ばれたものの、結果は `status=not_ready` / `reason=stale_graph`。CRGの有効な影響結果は未受入。
- TerrainはCodexの `read-only` shellで一時ファイルを作れずdoctorがexit 2になった。`workspace-write` shellでソース・設定変更を禁じた依頼ではpack照会できた。この制約をすべてのCodexモードで利用可能と表現しない。

## 更新停止の連絡を受けた後の順序

1. **状態を固定して確認する。** 両RepoのGit root・HEAD・`git status --short --branch`、JustPassの更新プロセス、通常 `aidev` の導入実体を読み取る。連絡後も書込み中なら索引処理を始めない。理由: 競合と再失効を防ぎ、既存差分の所有を取り違えないため。
2. **aidevの導線の抜けを修正する。** ルートに非空の `AGENTS.override.md` があると、Codexは同じ階層の `AGENTS.md` を読まない。現行aidevは後者へだけ案内を書き、検出もしない。利用者のoverrideを保全したまま、実効instructionへの配置か明示診断を選び、fixtureで確認する。Codexのinstruction総量による切詰めも、保証できる範囲を検討する。理由: 他Repoで案内が黙って無効になることを防ぐため。
3. **JustPassの変更予定を先に確認する。** `aidev init --dry-run` と、既存Terrainも `aidev terrain init --dry-run` を順に実行する。予定差分・secret候補・既存AGENTSの保全を確認し、必要な `init` と `refresh` を実行する。Terrain contextは今回必須ではなく、`--build-context` を自動指定しない。理由: 3providerとpackを同じ安定したコード入力へ合わせるため。
4. **両doctorを再確認する。** `aidev doctor --json` の `LOCAL_READY`、Terrain doctorのpack PASS・source_fresh trueを得る。Codex MCP接続はdoctorの `UNVERIFIED` と区別する。理由: 索引の存在だけで鮮度や実接続を推定しないため。
5. **ツール名なしの実セッションで受け入れる。** 新規CodexセッションをJustPassのrootから開き、定義・参照、構造・関係、差分影響、場所不明の候補探しをそれぞれ依頼する。実ツール呼出し、エラーのない結果、実ファイル照合、回答完了を記録する。CRGは比較対象とbaseを明示し、`not_ready` / `stale_graph` を成功扱いしない。単純な文字列検索では追加能力を強制しない。理由: 自発的な選択と実用結果の両方を証明するため。
6. **結果に応じて文書とinventoryを更新する。** `/home/tn/projects/aidev/docs/STATUS.md` の過去の成功と現在の判定を区別し、CRGの失敗履歴を残す。aidevソースや受領対象が変わった場合は、必要なPython suite・`git diff --check`の後に `/home/tn/projects/aidev/tools/windows_handoff.py manifest` を更新し、内容一致を確認する。Windows実機受入はUbuntu結果から推定しない。

Terrainは現在のグローバル能力台帳には登録されていない。RepoのAGENTS案内から実使用は観測したが、共通ルーターへの登録はhost側の許可変更を伴う別判断であり、再開時に自動変更しない。新規Skill作成も前提にしない。

## 完了条件

- 安定したJustPass HEADに対し、3providerとTerrain packの鮮度診断が通る。
- CRGがreadyな影響結果を返し、4種類のツール名なし依頼で適切な能力の利用・実ソース照合・回答完了を確認する。失敗や中断はそのまま記録する。
- ルートoverrideがあるRepoで案内が黙って無効にならない。既存の利用者記述と未commit差分を保全する。
- 実施した変更、Ubuntu受入、Windows未受入、通常導入、Git commit/pushを別々に報告する。

## 再開後の判定

JustPassの現HEADでローカル鮮度と4経路の自然文調査はPASS。場所不明のシンボル調査でSerena、構造調査でGraphify、仮想変更影響でCRG、場所不明の横断調査でTerrainを使い、回答と実ソース照合まで完了した。既知hookの簡単な定義・参照では標準検索が選ばれた。Codexの能力選択は依頼内容と実セッションのツール提供に依存し、毎回の使用を保証しない。詳細な証拠と未確認項目は `/home/tn/projects/aidev/docs/STATUS.md` に記録した。
