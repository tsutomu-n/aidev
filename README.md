# aidev — コード解析の準備をまとめるCLI

Windows 11 / UbuntuのGitリポジトリに、Serena・Graphify・code-review-graph（CRG）の設定と検索用索引を作ります。自動言語設定はPython・JavaScript・TypeScriptに対応します。

**Windowsで仕上げる方は、先に次の「Windows側で実装を引き継ぐ」へ進んでください。** Python 3.11以降・Gitと指定版の解析ツールが必要です。Windowsでは専用のprovider登録、Ubuntuでは既存共通基盤または専用登録を使います。既存3providerの自動導入は行いません。

## Windows側で実装を引き継ぐ

**W-01〜W-03のsource修正とfixtureのパス正規化は、Ubuntu/Windows × Python 3.11/3.13のCI全4構成で成功しました。Windows 11実機受入は未完了です。** 検証したcommit・CIの証拠と残る警告は [/home/tn/projects/aidev/STATUS.md](STATUS.md) を参照してください。Windows側のCodexには、ソースに含む [/home/tn/projects/aidev/WINDOWS_HANDOFF.md](WINDOWS_HANDOFF.md) を渡してください。通常利用環境への導入は別途指示が必要です。

## マニュアルへ進む

| やりたいこと | ジャンプ先 |
|---|---|
| Windows 11で導入する | [/home/tn/projects/aidev/WINDOWS.md](WINDOWS.md) |
| 導入・初回操作・日常操作を学ぶ | [/home/tn/projects/aidev/USER_GUIDE.md](USER_GUIDE.md) |
| エラーから復旧する | [/home/tn/projects/aidev/USER_GUIDE.md — トラブル対応](USER_GUIDE.md#troubleshooting) |
| 実装や設定の契約を調べる | [/home/tn/projects/aidev/TECHNICAL.md](TECHNICAL.md) |
| 対応範囲・未検証事項を確認する | [/home/tn/projects/aidev/STATUS.md](STATUS.md) |

リンクはclone内とGitHubで移動できる相対リンクです。表示パスはこの作業環境の配置先です。インストーラーはTerrain modules・patch・操作文書を含む13ファイルを同じreleaseに配置します。同梱文書間のリンクはインストール先でも開けます。開発引き継ぎ・tests・installer・inventoryへのリンクはsource checkout専用です。

## 導入済みの方の操作

**解析したいGitリポジトリのルート**へ移動し、1行ずつ結果を確認します。

```sh
aidev --version
aidev init --dry-run
aidev init
aidev doctor
```

`--dry-run` は変更予定だけを表示します。`init` は設定と索引を作成・更新し、`doctor` は書き換えずに診断します。`LOCAL_READY` が出たら、新規Codexセッションで接続と実際のコード照会を確認します。`codex_mcp: UNVERIFIED` は接続未検査の意味です。

初回導入・更新の手順は [/home/tn/projects/aidev/USER_GUIDE.md](USER_GUIDE.md#install) にあります。文書の対象はソース **0.3.0**。Windows実機・実providerでの一連の受入は未実施です。詳細は [/home/tn/projects/aidev/STATUS.md](STATUS.md) を参照してください。

## 任意のTerrain knowledge layer

Terrain runtimeの正式検証対象はUbuntu 24.04 x86_64です。WindowsではTerrain操作は未サポートですが、既存3providerは継続利用できます。0.3.0では `aidev terrain install --allow-download` または `aidev terrain setup` でruntimeを準備し、対象repoで `aidev terrain init` → `aidev terrain doctor` を使えます。Agent ContextのLLM生成は明示的な `--build-context` 時だけです。既存の `aidev init` にTerrainは自動追加しません。

CLI、安全性、migration、検証の境界は [/home/tn/projects/aidev/TERRAIN.md](TERRAIN.md) にあります。Terrainは探索補助であり、編集前にlive source/testsへ戻って確認します。
