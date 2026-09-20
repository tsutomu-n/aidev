# 実装と検証状態

入口：[/home/tn/projects/aidev/README.md](README.md) ／ 操作手順：[/home/tn/projects/aidev/USER_GUIDE.md](USER_GUIDE.md)

## 0.3.0 Ubuntu scopeの現在状態

判定は **実装CI成功・実LLM受入未完了** です。検証した実装HEADは `e0272b53cf70ce6a0d12510eb7ca6895e50696f1`、branchは `feat/terrain-integration`。この文書と受領inventoryの更新は、その実装に対する文書変更です。

| 項目 | 確認結果と境界 |
|---|---|
| 正式Terrain runtime scope | Ubuntu 24.04 x86_64。Python回帰は3.11・3.13、runtime専用CIは3.13 |
| Python CI | 同一実装HEADのUbuntu 24.04 / Windows × 3.11 / 3.13、全4job成功。[実行結果](https://github.com/tsutomu-n/aidev/actions/runs/35447587893) |
| Ubuntu runtime CI | 同一実装HEADでexact upstream・正式patch・baseline比較・focused tests・release build・behavior/worktree smoke成功。[実行結果](https://github.com/tsutomu-n/aidev/actions/runs/35447587861) |
| 内容ベースのキー | 内容不変のstage/commit・生成物commit後の再利用、入力変更・旧キー移行を回帰で確認 |
| ACP経路 | engine・CODEX_HOME・JS版Nodeを登録し、認証検査とACP起動先を一致させる。実ACP childの観測は未受入 |
| 失敗保全 | force削除後にpair不在なら正常pairを復元し再試行。未知の部分出力・並行変更は保全して手動復旧を案内 |
| local Python | Ubuntu 25.10 x86_64、Python 3.11.14 / 3.13.7で各76 tests、74成功・Windows専用2skip。24.04の証拠とは別 |
| Windows Terrain | 未サポート。通常操作を副作用前に拒否。helpと内部Python fixture、既存3providerは維持 |
| 配布・live | 今回の最終配布物を使う実context生成・再利用・更新・検索・意味確認は未完了。UBUNTU_ACCEPTEDではない |
| 公開・導入 | 上記実装HEADはremote featureと一致。mainへの統合・release・通常利用環境への導入は、この検証の成功から推定しない |

非liveのコード・CI・文書・配布物検査を揃えた判定を `READY_FOR_MAIN_UBUNTU`、実context受入まで揃えた判定を `UBUNTU_ACCEPTED` と区別します。Windows Terrain成功は今回のgateではありません。以前のWindows失敗は下記に履歴として保持します。commit・push・merge・導入の許可は、それぞれ現在の利用者依頼に従います。

local詳細証拠は [/home/tn/projects/aidev/verification/ubuntu-finish](/home/tn/projects/aidev/verification/ubuntu-finish) と [/home/tn/projects/aidev/verification/terrain-ci](/home/tn/projects/aidev/verification/terrain-ci) に保存されています。公開・配布には含めません。以下のtests・installer・引き継ぎ・inventoryはGitHubのfeature sourceへの参照です。導入版と参照先commitの一致は別途確認してください。

## 0.3.0 初回統合の検証履歴（旧scope）

当時のsource判定は **0.3.0 / NOT_READY**。base mainは `b1bbe5194977ad2296c133656f0978a0812e1c60`、作業branchは `feat/terrain-integration` です。実装commit `356143979fc9c2c4105db4637294f15f2e1a2ec6` をpushし、Python 4-matrixは成功しました。Terrain Windows CIはclean upstreamのtest harnessコンパイル失敗で停止しました。PR・merge・release・通常利用環境への反映は行っていません。

| 受入項目 | 結果と範囲 |
|---|---|
| 既存42 tests | UbuntuのPython 3.11.14 / 3.13.7で各40成功・Windows専用2skip |
| Terrain追加26 tests | 両Pythonで26成功。dry-run/doctor書込みなし、gating、実Git worktree、source競合、backup、manual AGENTS、秘密ファイル候補、runtime hash/approval、別process groupの子孫終了を含む |
| 合計 | 両Pythonで68件中66成功・2skip |
| Ubuntu 3.11 / 3.13 CI | Python 3.11.16 / 3.13.15で各68件中66成功・Windows専用2skip |
| Windows 3.11 / 3.13 CI | Python 3.11.9 / 3.13.15で各68件中66成功・Unix専用2skip。既存42件は41成功・1skip、Terrain26件は25成功・1skip |
| Terrain upstream | clean 0.9.5、SHA `8d888ae13a6b1253406cac379c8eb30037c96862` を確認 |
| patch適用 | 別clean cloneへ `git apply --check` 成功。対象は下記3ファイルだけ |
| Rust focused tests | context recovery 3、OpenAPI ignore 5、ACP mode/JSON stdio 2の計10成功 |
| cargo check / Linux release build | 成功。rustc 1.98.1 / cargo 1.98.1 |
| runtime install/setup | 隔離data homeでclean local sourceからbuild・content-addressed配置・承認登録まで成功。既存binary setupもbehavior smoke後に登録成功 |
| runtime behavior | version、register隔離、scan/pack、ignored OpenAPI排除、正規OpenAPI保存、repair-contextのpath/H2/Unicode、read tools成功 |
| repo workflow | 実runtimeのinit再利用、dirty入力後のrefresh、doctor、同名slugの2 worktreeでread-context/grep-pack/read-pack-fileの分離成功 |
| Ubuntu Terrain CI | exact SHA・patch適用・3ファイル検査・focused tests 10件・release build・全behavior smoke・worktree隔離PASS。baselineと同名同内容の既知3failureのみ |
| Windows Terrain build/behavior | CI FAIL。patch前のclean upstream test harnessがコンパイル不能。focused tests・release build・behavior smokeには未到達 |
| live Codex ACP | **UNVERIFIED**。外部LLM呼出し・認証変更は行っていない |

CI証拠: [Python 4-matrix](https://github.com/tsutomu-n/aidev/actions/runs/35213235246)、[Terrain runtime](https://github.com/tsutomu-n/aidev/actions/runs/35213235406)。いずれも上記実装commitに対する結果です。

Windows失敗の分類は **Terrain upstream test harness / OS差**。Rust 1.98.1、Python 3.13.15の `runtime (windows-latest)` で、test実行前に次の2件が発生しました。

- `crates/terrain-core/src/model_text.rs:416`: `env!("HOME")` のcompile-time環境変数が未定義。
- `crates/terrain-core/src/shell_path.rs:439`: Unix限定の `std::os::unix::fs::PermissionsExt` を無条件importし、E0433。

clean upstream SHAのコンパイルで発生しており、aidev 0.2.0回帰でも3ファイルpatchによる新規failureでもありません。ただしWindows focused testsは同じtest harnessをcompileするため、baselineだけを省略しても受入を満たしません。Linuxでは再現せず、Windows CIで再現済みです。後者の修正には今回固定した3ファイル外のtestコード変更が必要です。正式patchの範囲・SHAは維持し、失敗のskipや別patchの暗黙適用はしていません。

patch SHA256（LF正規化）: `893efe60ec622ef6741e20d8a81c840124de60b823e842854c789ee9681f40c1`。

patchのsource識別子は `crates/terrain-core/src/assets/agent_context.rs`、`crates/terrain-core/src/ingest/openapi.rs`、`crates/terrain-agent/src/acp.rs`。MarketLens正式patchを使用し、ACP mode伝播と空白を含むbinaryのavailability判定・回帰testを追加しました。MarketLensと既存のdirty Terrain sourceは変更していません。

ローカルUbuntuではruntimeのcore/agent/CLI full testsをclean upstreamと比較し、新規failureなしを確認しました。両者の失敗は次のtest名と内容で一致します。件数だけの許容ではありません。

- `assets::env::status::plan::tests::bundled_tool_reinstall_produces_plan_steps`: bundled CodeGraph/RTK unavailableでreinstall plan stepsが空。
- `freshness::drift_factors::tests::context_baseline_behind_is_explained_when_pack_is_current`: baseline説明文のassertion不一致。
- `freshness::drift_factors::tests::different_context_baseline_without_source_drift_is_not_blamed`: source driftなしの説明文のassertion不一致。

coreの修正版は128成功・3失敗、integration testsは7成功。agentは14成功・認証依存のsmoke 1ignored、CLIは0 tests。desktop GUIを含むworkspace全体のfull suiteは実行していません。upstream全体へのformat変更も行っていません。

生成gateはfixtureで確認済みで、live LLM生成は別受入です。context本文の事実性・網羅性は機械validationの保証外です。legacy migrationでdirty入力のlineageを証明できない場合やAGENTSを新たに変更する場合はpackを更新し、contextをstaleとして保持します。migrationだけではLLMを呼びません。submodule、symlink/reparse/hardlink入力、unignoredの代表的秘密ファイル名は初版では停止します。任意の秘密文字列のredactionは保証しません。

当時は4-matrix CIとUbuntu/Windows Terrain runtime CIをREADY_FOR_MAINの条件とし、live ACPを別受入としていました。この旧gateは今回のUbuntu scopeへ置き換えられています。通常利用環境への導入は別の明示操作です。操作・契約は [/home/tn/projects/aidev/TERRAIN.md](TERRAIN.md) を参照してください。

## 0.2.0 Windows回帰の履歴

以下は0.2.0の過去検証です。当時のコード判定はREADY_FOR_MAINで、W-01〜W-03の修正とfixture正規化が全4構成のCIで成功しました。Windows 11実機・実provider・通常利用環境への導入は未確認です。各環境の導入版は `aidev --version` で確認してください。

CIの証拠はcommit `b91bf2c00fb0fd7e6b031b5dbede4fffd02ed991` の [PR検証](https://github.com/tsutomu-n/aidev/actions/runs/35207281491) です。[修正前のCI](https://github.com/tsutomu-n/aidev/actions/runs/35083256979) ではWindows 2構成がfixtureのパス不整合で失敗しました。[/home/tn/projects/aidev/tests/test_aidev.py](https://github.com/tsutomu-n/aidev/blob/feat/terrain-integration/tests/test_aidev.py) の `InitTests` と [/home/tn/projects/aidev/tests/test_portability.py](https://github.com/tsutomu-n/aidev/blob/feat/terrain-integration/tests/test_portability.py) の `FoundationTests` で、一時ルートを `Path(self.tmp.name).resolve()` に統一しました。安全性assertion・Windows専用テスト・公開API・CLI・設定形式は維持しています。

| CI環境 | Python実測版 | 結果 |
|---|---|---|
| Ubuntu 24.04 | 3.11.16 | 42件中40件成功、Windows専用2件skip |
| Ubuntu 24.04 | 3.13.15 | 42件中40件成功、Windows専用2件skip |
| Windows Server 2025 | 3.11.9 | 42件中41件成功、Unix専用の旧4ファイル形式からの移行1件skip |
| Windows Server 2025 | 3.13.15 | 42件中41件成功、Unix専用の旧4ファイル形式からの移行1件skip |

WindowsのOS実測はServer 2025 Datacenter build `10.0.26100`、runner imageは `windows-2025-vs2026`、image versionは `20260907.229.1` です。Windows 11端末の受入結果とは区別します。

## source修正済み・引き継ぎ

Windows側の作業要求と手順は、ソースに含む [/home/tn/projects/aidev/WINDOWS_HANDOFF.md](https://github.com/tsutomu-n/aidev/blob/feat/terrain-integration/WINDOWS_HANDOFF.md) を正本とします。W-01〜W-03のsource修正とnative Windows用W-01回帰testを含むコードは上記CIで成功しました。通常利用やWindows完全受入は別の判定です。

- W-01：launcherは裸の `py -3` を廃止し、導入時に検証したPython絶対パス・version・形式をrelease manifestへ記録する。native Windows testは空白・日本語・`&`・括弧・`!`を含む一時Python環境からinstallerを実行し、生成された`.cmd`の起動、子プロセスのPython実体とmatrix指定版、引数・終了コードを照合する。cwdの偽`py`とPATH上の偽`python`が名前探索で実行される対照試験も含む。このtestはWindows CIの両Python構成でPASSし、起動Python固定のnative evidenceが成立した。
- W-02：所有判定をロック取得後へ移し、release準備後・公開直前のentry再照合と、上書き禁止の公開へ変更した。管理外commandを保全する回帰テストはUbuntu/Windows CIで成功した。
- W-03：installer所有の進行記録を残し、source失敗・コピー/公開失敗後に完成releaseを照合して通常installで再開する。所有記録のない旧partialは保全して停止する。初回失敗からの復旧・管理外partial保全・更新時の旧release保持の回帰テストはUbuntu/Windows CIで成功した。

W-02/W-03の再現ツールの記録はUbuntu上でWindowsのファイル処理分岐を用いたものです。今回のWindows CIでは実OS上のfixture回帰も成功しましたが、Windows 11受入完了を意味しません。

Windowsの導入・更新テストでは、成功時にも既存の `Parameter format not correct - code` が出力されています。[/home/tn/projects/aidev/install.py](https://github.com/tsutomu-n/aidev/blob/feat/terrain-integration/install.py) の `windows_launcher()` にある `chcp` 出力の分割と復元処理に由来すると考えられ、元のcode pageの復元成功は未確認です。今回のfixture修正ではlauncherを変更しておらず、起動Python固定の成功とこの残課題を区別します。

## 引き継ぎの補助

- sourceに [/home/tn/projects/aidev/AGENTS.md](https://github.com/tsutomu-n/aidev/blob/feat/terrain-integration/AGENTS.md) を配置し、Windows側Codexの開始時に引き継ぎ資料を読む導線を追加。
- [/home/tn/projects/aidev/tools/windows_handoff.py](https://github.com/tsutomu-n/aidev/blob/feat/terrain-integration/tools/windows_handoff.py) は、受領内容照合と一時fixtureでの既知不具合再現を担当。通常利用環境への導入・provider実行はしない。
- [/home/tn/projects/aidev/WINDOWS_HANDOFF_MANIFEST.json](https://github.com/tsutomu-n/aidev/blob/feat/terrain-integration/WINDOWS_HANDOFF_MANIFEST.json) はUTF-8/LF正規化したsource inventory。期待commitとcleanなGit状態も照合して受領を確認する。署名や実機受入の代替ではない。

引き継ぎ補助のUbuntu検証では、cleanな一時Git repoの受領成功、異なるHEADの拒否、CRLFの許容、内容変更の拒否、不正inventoryの拒否を確認しました。PowerShell例13ブロックは構文検査済みで、Windows上での実行結果ではありません。source修正後の再現ツールはW-01をUNVERIFIED、W-02・W-03-source・W-03-publishをPASSとして返します。これらはunit testsとは別の確認です。

## 検証範囲

- Ubuntu / Python 3.13.7で42件中40件成功、Windows専用junctionとW-01 native cmd testの2件はskip。Gitは一時repoで実行し、providerのbuildとschema取得はmockを使います。
- initのdry-run/timeout、doctorのjson、setupの明示登録、installerのupgradeを実装・CLI helpと照合しています。
- 0.2.0のWindows実機、実providerによる初期化・更新・接続・自然文照会の一連の受入は未実施です。
- installerの一時環境での導入・同版再実行・更新、利用者変更保全はUbuntu/Windows CIで成功。旧4ファイル形式からの移行はUbuntuで成功し、WindowsではUnix専用としてskipしています。
- Windows CIで実cmd起動、junction/symlink拒否、別プロセスの排他と解放、Job Object経由のtimeout時の子孫終了、repo内provider拒否、設定・管理外entryの保全を確認しました。Windows 11実機での受入は未実施です。
- Ubuntu/Windows × Python 3.11/3.13のGitHub Actions全4構成が成功しました。ActionsのNode.js 20非推奨・Node.js 24実行への移行通知は残っており、workflowの版更新は今回の変更に含めていません。

ローカルにないPython構成は上記CIで確認しました。Windows実providerとCodex MCPはmain merge gateに含めず、Windows 0.2.0完全受入の別項目としてUNVERIFIEDを維持します。

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
