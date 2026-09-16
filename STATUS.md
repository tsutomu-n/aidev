# 実装と検証状態

入口：[/home/tn/projects/aidev/README.md](README.md) ／ 操作手順：[/home/tn/projects/aidev/USER_GUIDE.md](USER_GUIDE.md)

作業ソースのバージョンは `0.2.0` です。現在のコード判定は **CODE_READY_CI_PENDING** です。remote CIのUbuntu/Windows × Python 3.11/3.13が未実行のため、**READY_FOR_MAIN** ではありません。既存環境への導入とWindows実機受入は行っていません。各環境の導入版は `aidev --version` で確認してください。ソースの取得やGitへの公開だけでは、既存インストールは更新されません。

## source修正済み・引き継ぎ

Windows側の作業要求と手順は、ソースに含む [/home/tn/projects/aidev/WINDOWS_HANDOFF.md](WINDOWS_HANDOFF.md) を正本とします。W-01〜W-03のsource修正とnative Windows用W-01回帰testを含むコードは **CODE_READY_CI_PENDING** です。remote CI成功前に通常利用やWindows完全受入とは扱いません。

- W-01：launcherは裸の `py -3` を廃止し、導入時に検証したPython絶対パス・version・形式をrelease manifestへ記録する。native Windows testは空白・日本語・`&`・括弧・`!`を含む一時Python環境からinstallerを実行し、生成された`.cmd`の起動、子プロセスのPython実体とmatrix指定版、引数・終了コードを照合する。cwdの偽`py`とPATH上の偽`python`が名前探索で実行される対照試験も含む。native evidenceはこのtestがWindows上でPASSした時点で成立する（現在PENDING CI）。
- W-02：所有判定をロック取得後へ移し、release準備後・公開直前のentry再照合と、上書き禁止の公開へ変更した。一時fixtureで管理外commandの保全を確認した。Windows API実機試験は未実施。
- W-03：installer所有の進行記録を残し、source失敗・コピー/公開失敗後に完成releaseを照合して通常installで再開する。所有記録のない旧partialは保全して停止する。一時fixtureで確認し、Windows実機試験は未実施。

W-02/W-03の再現はUbuntu上でWindowsのファイル処理分岐を用いたもので、Windows APIの実機試験ではありません。source修正後のfixture回帰と再現ツールはPASSですが、Windows 11受入完了を意味しません。

## 引き継ぎの補助

- sourceに [/home/tn/projects/aidev/AGENTS.md](AGENTS.md) を配置し、Windows側Codexの開始時に引き継ぎ資料を読む導線を追加。
- [/home/tn/projects/aidev/tools/windows_handoff.py](tools/windows_handoff.py) は、受領内容照合と一時fixtureでの既知不具合再現を担当。通常利用環境への導入・provider実行はしない。
- [/home/tn/projects/aidev/WINDOWS_HANDOFF_MANIFEST.json](WINDOWS_HANDOFF_MANIFEST.json) はUTF-8/LF正規化したsource inventory。期待commitとcleanなGit状態も照合して受領を確認する。署名や実機受入の代替ではない。

引き継ぎ補助のUbuntu検証では、cleanな一時Git repoの受領成功、異なるHEADの拒否、CRLFの許容、内容変更の拒否、不正inventoryの拒否を確認しました。PowerShell例13ブロックは構文検査済みで、Windows上での実行結果ではありません。source修正後の再現ツールはW-01をUNVERIFIED、W-02・W-03-source・W-03-publishをPASSとして返します。これらはunit testsとは別の確認です。

## 検証範囲

- Ubuntu / Python 3.13.7で42件中40件成功、Windows専用junctionとW-01 native cmd testの2件はskip。Gitは一時repoで実行し、providerのbuildとschema取得はmockを使います。
- initのdry-run/timeout、doctorのjson、setupの明示登録、installerのupgradeを実装・CLI helpと照合しています。
- 0.2.0のWindows実機、実providerによる初期化・更新・接続・自然文照会の一連の受入は未実施です。
- installerの一時環境での導入・同版再実行・更新、旧4ファイル形式からの移行、利用者変更保全は成功。WindowsレイアウトはUbuntu上でもfixture検査済みですが、cmd実行・Job Object・Windows排他ロックはWindows実機での確認が必要です。
- Ubuntu/Windows × Python 3.11/3.13のGitHub Actionsを追加しました。remoteでの実行結果はまだありません。

ローカルにPython 3.11がないことは失敗条件にしません。Ubuntu Python 3.11とWindows Python 3.11/3.13はPENDING CIです。必要な4構成のCI成功後にREADY_FOR_MAINを判定します。Windows実providerとCodex MCPはmain merge gateに含めず、Windows 0.2.0完全受入の別項目としてUNVERIFIEDを維持します。

`LOCAL_READY` はローカル設定・索引の検査結果です。現在のCodex接続、解析の意味的な網羅性、アプリのtest成功を保証しません。

## 実装済み

- 3providerのrepo設定、変更前textのbackup、索引構築と再利用。
- installed parserからの対象集合取得、内容hashによる鮮度診断。
- Serena cache検査、CRGの構造化エラー・警告の失敗判定。
- 競合・追跡済み生成物・危険なリンクの検出、timeoutと中断時のログ保存。
- 管理hashで既存ファイルを確認するrelease配置と、旧releaseを保持する更新。
- Windows向けのシンボリックリンク不要のcmd配置、semaphoreロック、Job Objectによる子孫終了、junction/reparse point拒否、UTF-8入出力。
- 専用venvのPythonとCLIを指定・検査して明示承認する `setup`。Ubuntu台帳のないWindowsでも登録を利用できます。

## 未対応

任意のprovider選択、共通基盤の自動導入、全言語の自動設定、自動承認、rollback/uninstallコマンドはありません。詳細は利用・技術文書を参照してください。

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -W error::ResourceWarning -m unittest discover -s tests -v
```

機械固有の受入ログ、解析データ、backupは公開リポジトリに収録していません。
