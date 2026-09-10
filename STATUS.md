# 実装と検証状態

公開ソースのバージョンは `0.1.1` です。各環境の導入版は `aidev --version` で確認してください。ソースの取得やGitへの公開だけでは、既存インストールは更新されません。

## 検証範囲

- 既存単体テスト20件が成功。Gitは一時repoで実行し、providerのbuildとschema取得はmockを使います。
- initのdry-run/timeout、doctorのjson、installerのupgradeをCLI helpと照合しています。
- 0.1.1の実providerによる初期化・更新・接続・自然文照会の一連の受入は未実施です。
- installerの旧版からのupgrade経路は実装済みですが、実機更新の受入は未実施です。

`LOCAL_READY` はローカル設定・索引の検査結果です。現在のCodex接続、解析の意味的な網羅性、アプリのtest成功を保証しません。

## 実装済み

- 3providerのrepo設定、変更前textのbackup、索引構築と再利用。
- installed parserからの対象集合取得、内容hashによる鮮度診断。
- Serena cache検査、CRGの構造化エラー・警告の失敗判定。
- 競合・追跡済み生成物・危険なリンクの検出、timeoutと中断時のログ保存。
- 管理hashで既存ファイルを確認するrelease配置と、旧releaseを保持する更新。

## 未対応

任意のprovider選択、共通基盤の自動導入、全言語の自動設定、自動承認、rollback/uninstallコマンドはありません。詳細は利用・技術文書を参照してください。

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -W error::ResourceWarning -m unittest discover -s tests -v
```

機械固有の受入ログ、解析データ、backupは公開リポジトリに収録していません。
