# aidev — リポジトリのコード調査環境を準備するCLI

Serena・Graphify・code-review-graph（CRG）の設定と索引を、対象のGitリポジトリへ用意します。初期化は `aidev init`、設定・索引・鮮度の確認は `aidev doctor` です。Terrainの知識・探索機能は独立した `aidev terrain` から利用します。

## 導入済み環境での基本操作

解析したいリポジトリのルートで実行します。aidev本体のソースcheckoutで実行するという意味ではありません。

```sh
aidev --version
aidev init --dry-run
aidev init
aidev doctor --json
```

`--dry-run` は変更予定だけを表示します。`init` は設定と索引を作成・更新し、変更前の設定テキストをバックアップします。`doctor` は対象リポジトリを書き換えずに診断します。`LOCAL_READY` は、CodexからのMCP接続や解析の網羅性まで保証する判定ではありません。

新規Codexセッションで、実際の定義・参照・構造・変更影響の照会を確認してください。単純な検索や既知ファイルの小修正まで、すべての解析ツールを経由する必要はありません。

## 手順書

| 目的 | 資料 |
|---|---|
| 初回導入・更新・日常操作・トラブル対応 | [利用ガイド](docs/USER_GUIDE.md) |
| 変更する設定・保存先・安全性の契約 | [技術仕様](docs/TECHNICAL.md) |
| Terrainの準備・更新・検索 | [Terrainガイド](docs/TERRAIN.md) |
| Windowsでの導入 | [Windowsガイド](docs/WINDOWS.md) |
| 検証済み範囲と未検証事項 | [実装・検証状態](docs/STATUS.md) |

Python 3.11以降とGit、所定の版の解析ツールが必要です。既存3providerを自動インストールする機能ではありません。Terrainには別途runtimeの準備が必要で、WindowsでのTerrain操作は未サポートです。OS・版ごとの受入範囲は上記資料で確認してください。

## Terrainと既存3providerの境界

現在の `aidev init` は既存3provider用です。Terrainは `aidev terrain init` で対象リポジトリへ導入します。Agent ContextのLLM生成は、`init` または `refresh` に明示的に `--build-context` を付けた場合だけです。runtimeの準備・外部送信の条件はTerrainガイドに従ってください。

Terrainは探索用の案内・索引です。重要な判断や編集の前には、現在のコード・テスト・設定・schemaを確認します。圧縮packだけで実装の正しさを判断しません。

## 保全と撤去について

設定の変更予定は、計画を作るために最初に読んだ内容と、適用直前の内容を照合します。計画中の並行編集や実効指示ファイルの切替を検出した場合は、その変更を上書きせず停止します。全プロセスによる書込みを一括で排他する保証ではありません。

構築記録がない旧版の状態と、新しい構築記録の欠落・不正を区別します。不正な状態ファイルを正常扱いしたり、自動で削除したりしません。既存3providerの設定バックアップにある `changes.json` は変更前の `before_sha256` と予定する変更後の `after_sha256` を記録します。この記録だけで、導入前から存在した設定やディレクトリ全体の所有を証明したことにはなりません。

自動撤去・全体ロールバックのコマンドはまだありません。`.codex/`、`.serena/`、`.terrain/`、`.aidev/` を一括削除しないでください。既存設定、利用者の文書・作業記録、バックアップが混在し得ます。`backup:` は変更前の設定テキストの保存先であり、ソース全体・索引・会話履歴のバックアップではありません。
