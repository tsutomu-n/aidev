# aidev — コード解析の準備をまとめるCLI

Windows 11 / UbuntuのGitリポジトリに、Serena・Graphify・code-review-graph（CRG）の設定と検索用索引を作ります。自動言語設定はPython・JavaScript・TypeScriptに対応します。

**Windowsで仕上げる方は、先に次の「Windows側で実装を引き継ぐ」へ進んでください。** Python 3.11以降・Gitと指定版の解析ツールが必要です。Windowsでは専用のprovider登録、Ubuntuでは既存共通基盤または専用登録を使います。providerの自動導入は行いません。

## Windows側で実装を引き継ぐ

**W-01〜W-03のsource修正は未commit差分で完了し、Windows 11実機受入は未完了です。** Windows側のCodexには、ソースに含む [/home/tn/projects/aidev/WINDOWS_HANDOFF.md](WINDOWS_HANDOFF.md) を渡してください。検証済みPythonへの固定、競合時の停止、所有記録を使う再試行、隔離条件と受入証拠をまとめています。通常利用環境への導入は別途指示が必要です。

## マニュアルへ進む

| やりたいこと | ジャンプ先 |
|---|---|
| Windows 11で導入する | [/home/tn/projects/aidev/WINDOWS.md](WINDOWS.md) |
| 導入・初回操作・日常操作を学ぶ | [/home/tn/projects/aidev/USER_GUIDE.md](USER_GUIDE.md) |
| エラーから復旧する | [/home/tn/projects/aidev/USER_GUIDE.md — トラブル対応](USER_GUIDE.md#troubleshooting) |
| 実装や設定の契約を調べる | [/home/tn/projects/aidev/TECHNICAL.md](TECHNICAL.md) |
| 対応範囲・未検証事項を確認する | [/home/tn/projects/aidev/STATUS.md](STATUS.md) |

リンクはclone内とGitHubで移動できる相対リンクです。表示パスはこの作業環境の配置先です。インストーラーは実行用Python 4ファイルと5件の利用・技術文書を同じreleaseに配置します。インストール先からも文書リンクを開けます。

## 導入済みの方の操作

**解析したいGitリポジトリのルート**へ移動し、1行ずつ結果を確認します。

```sh
aidev --version
aidev init --dry-run
aidev init
aidev doctor
```

`--dry-run` は変更予定だけを表示します。`init` は設定と索引を作成・更新し、`doctor` は書き換えずに診断します。`LOCAL_READY` が出たら、新規Codexセッションで接続と実際のコード照会を確認します。`codex_mcp: UNVERIFIED` は接続未検査の意味です。

初回導入・更新の手順は [/home/tn/projects/aidev/USER_GUIDE.md](USER_GUIDE.md#install) にあります。文書の対象はソース **0.2.0**。Windows実機・実providerでの一連の受入は未実施です。詳細は [/home/tn/projects/aidev/STATUS.md](STATUS.md) を参照してください。
