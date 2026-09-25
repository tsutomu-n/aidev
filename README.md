# aidev — Gitリポジトリのコード解析を準備するCLI

Serena・Graphify・code-review-graph（CRG）の設定と検索用索引を、解析対象のGitリポジトリに作ります。Python・JavaScript・TypeScriptの言語設定に対応します。解析ツール自体の自動インストールは行いません。

## 使い始める

Python 3.11以降、Git、指定版の3つの解析ツールが必要です。導入とprovider登録の条件は [/home/tn/projects/aidev/docs/USER_GUIDE.md](docs/USER_GUIDE.md#install)、Windows固有の手順は [/home/tn/projects/aidev/docs/WINDOWS.md](docs/WINDOWS.md) を確認してください。

`aidev`を導入済みなら、**解析したいリポジトリのGit root**で実行します。このaidevのソースcheckoutを初期化場所として指定する必要はありません。

```sh
aidev --version
aidev init --dry-run
aidev init
aidev doctor
```

`init --dry-run`は変更予定の確認、`init`は設定・索引の作成または更新、`doctor`は書込みなしの診断です。`LOCAL_READY`はローカルの準備完了を示します。Codexとの接続と実際の照会は、新しいCodexセッションで別途確認してください。操作と結果の読み方は [/home/tn/projects/aidev/docs/USER_GUIDE.md](docs/USER_GUIDE.md#first-run) にあります。

## ソースの配置

| 場所 | 内容 |
|---|---|
| `src/` | CLI、インストーラー、provider連携、Terrain、配布用patch・qualification |
| `docs/` | 操作手順、技術仕様、検証状態と受入記録 |
| `tests/` | Python回帰テスト |
| `tools/` | Windows引き継ぎ・Terrain CI等の補助コマンド |

ソースと導入済みCLIは別です。インストーラーは必要なファイルを平坦なreleaseディレクトリへ配置します。ソースを編集しただけでは通常利用環境のCLIは更新されません。導入・更新は上記の操作手順に従ってください。

## 対応範囲と任意機能

既存3providerはTerrainなしで利用できます。TerrainはUbuntu向けの任意の探索補助で、`aidev terrain`から明示的に準備します。Agent ContextのLLM生成は`--build-context`を指定した場合だけです。契約と手順は [/home/tn/projects/aidev/docs/TERRAIN.md](docs/TERRAIN.md) を確認してください。

ソースの版は0.3.0です。Ubuntu通常環境の受入記録とWindows実機で未確認の範囲は [/home/tn/projects/aidev/docs/STATUS.md](docs/STATUS.md) に分けて記載しています。Windows引き継ぎの正本はソースcheckout直下の `WINDOWS_HANDOFF.md` で、実行用releaseには含めません。
