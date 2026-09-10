# aidev — repoの解析準備をまとめるCLI

既存のUbuntu共通基盤を使い、Serena・Graphify・code-review-graph（CRG）のrepo設定とローカル索引を作ります。対応する自動言語設定はPython・JavaScript・TypeScriptです。

## 最短の使い方

対象のGit repoルートで実行します。新規フォルダーは先に利用者がGit repoとして用意してください。

```sh
aidev --version
aidev init --dry-run
aidev init
aidev doctor
```

- `init --dry-run`：設定の変更予定をJSON表示。解析・索引構築は実行しません。
- `init`：設定、backup、初期解析を実行。鮮度が一致する既存索引は再利用します。
- `doctor`：書き換えずに設定・索引・コードの鮮度を診断します。
- `doctor --json`：診断結果を機械処理できます。
- `init --timeout 1800`：各providerの処理上限を1800秒に変更します。既定は600秒です。

`LOCAL_READY` の後も、そのrepoから新規Codexセッションを開き、MCP接続と定義・参照・影響の実照会を確認します。CLIの `codex_mcp: UNVERIFIED` は接続を診断していないという意味です。

## 導入と更新

このCLIは承認台帳とprovider導入を済ませた環境向けです。このリポジトリ単体で共通基盤を構築する機能はありません。前提となる台帳のentrypointは設定値 `$HOME/.local/share/dev-capabilities/core/catalog.py` です。未導入環境では初期化を停止します。

以下はaidevをcloneしたdirectoryで実行します。最初に取得してください。

```sh
git clone https://github.com/tsutomu-n/aidev.git
cd aidev
```

前提はPython 3.11以降、Git、承認済み共通基盤、PATHで使えるSerena 1.7.0・Graphify 0.9.55・CRG 2.3.8、および各providerの既存uv tool環境です。aidevはこれらを自動インストールしません。

初回導入:

```sh
python3 install.py
```

既存のaidevを更新する場合:

```sh
python3 install.py --upgrade
"$HOME/.local/bin/aidev" --version
```

`--upgrade` は現在の `0.1.1` ソースの機能です。管理対象の旧版だけを更新し、旧releaseを保持します。既存ファイルの利用者変更や管理外コマンドを検出すると停止します。更新経路の実機検証状況はSTATUSを参照してください。

入口は `$HOME/.local/bin/aidev`、管理先は `$HOME/.local/share/aidev` です。インストーラーは実行用Python3ファイルとこのREADMEだけを配置します。詳細文書は下記のGitHubリンクで参照します。

## できることと制限

初期化では3能力をまとめて設定します。個別providerだけを選ぶoptionはありません。既存の無効化や異なる同名MCP設定は上書きせず、衝突として停止します。既存の手動導入設定へそのまま再適用できる保証はありません。

コード・設定変更後は同じ `init` で再確認できます。設定ファイルは変更前backupを保存し、失敗後も再実行できます。ただし複数ファイルを一括で戻すtransactionや自動rollbackではありません。

外部LLM抽出・embedding、watcher、Git hook、自動commit/push、共通基盤の承認変更は行いません。初回のSerena解析では必要な言語サーバーを取得する場合があるため、完全オフライン動作の保証ではありません。

## 詳しい文書

- 利用手順・復旧: [https://github.com/tsutomu-n/aidev/blob/main/USER_GUIDE.md](https://github.com/tsutomu-n/aidev/blob/main/USER_GUIDE.md)
- 実装契約・保守: [https://github.com/tsutomu-n/aidev/blob/main/TECHNICAL.md](https://github.com/tsutomu-n/aidev/blob/main/TECHNICAL.md)
- 版と検証の現状: [https://github.com/tsutomu-n/aidev/blob/main/STATUS.md](https://github.com/tsutomu-n/aidev/blob/main/STATUS.md)

文書はソース `0.1.1` を基準にしています。インストール版は `aidev --version` で確認してください。
