# 実装と検証状態

入口：[/home/tn/projects/aidev/README.md](../README.md) ／ 操作手順：[/home/tn/projects/aidev/docs/USER_GUIDE.md](USER_GUIDE.md)

## 2026-09-26 Terrain CLIヘルプの案内修正

`aidev --help`、`aidev terrain --help`、`aidev terrain init --help` に、runtime登録とRepoごとの初期化、dry-run→init→doctor、秘密ファイル候補・例外・既存assets衝突時の停止、LLM処理は `--build-context` 指定時のみという境界を表示します。Ubuntu / Python 3.13.7の全96 testsは94成功・Windows専用2件skip。修正したhelpの表示と文言をCLI testで確認しました。Windows実機と別Repoのinit成功はこの結果から推定しません。

## 2026-09-26 JustPass Terrainローカル導入

Git管理中の設定例 `/home/tn/projects/JustPass/.env.example` と、認証情報を扱うPythonソース `secrets.py`・`credentials.py` が名前ベースの秘密ファイル判定で止まったため、これらの正確な名前だけを許容しました。実際の `.env`、`.env.production`、`secrets.json` 等は拒否し続けます。例外は内容の安全性を保証せず、JustPassの対象3ファイルは実物を確認しました。

Ubuntu / Python 3.13.7で96件中94件成功、Windows専用2件skip。通常コマンドを更新し、JustPassで `terrain init --dry-run` 成功後、`terrain init` によるローカルscan/packを実行しました。最終doctorは `TERRAIN_READY_CONTEXT_NOT_BUILT`、runtime・packはPASS、入力鮮度trueです。packは約76 MB・metadata上2481ファイルで、`grep-pack` と `credentials.py` の `read-pack-file` を実測しました。一方、`secrets.py` はpackに見つからず個別読取りに失敗しました。packの網羅性を保証せず、live source照合が必要です。context生成、外部LLM、Codexからの実接続、Windows実機受入は行っていません。

## 2026-09-26 Serenaログリンクの互換修正

既存の `/home/tn/projects/JustPass/.serena/runtime/logs` が `/home/tn/.serena/logs` を指すため、従来の `init` と `doctor` は解析状態のリンク検査で停止しました。Ubuntuでは、この既存ログリンクだけを許容するようsourceを修正しました。リンク先を走査・変更せず、その他の外部リンクや設定・出力先のリンク拒否は維持します。

Ubuntu / Python 3.13.7で95件中93件成功、Windows専用2件skip。リンクを保全したfixtureで `init` と `doctor` が `LOCAL_READY`、別の外部ログリンクは拒否することを確認しました。修正版を通常コマンドに導入後、実JustPassで `aidev init --dry-run` が成功し、変更予定4ファイル・対象コード3323ファイル・書込みなしでした。`aidev doctor --json` はリンクエラーを越え、未初期化を `NEEDS_INIT` と診断しました。実providerによる同repoの索引構築とCodex接続は未確認です。過去の通常環境受入やWindows実機受入へこの結果を合算しません。

## Ubuntu通常環境への導入・受入

今回の通常環境は **UBUNTU_NORMAL_ACCEPTED**。旧0.1.0の3ファイル配置から0.3.0へ更新し、通常launcher `/home/tn/.local/bin/aidev` と通常認証 `/home/tn/.codex` で受入を実施しました。過去の隔離候補の成功とは別の結果です。

| 項目 | 今回の結果 |
|---|---|
| 実測環境 | Ubuntu 25.10 x86_64 / Python 3.14.3 / Codex 0.155.1 / Node 24.20.0 / Terrain 0.9.5 |
| 通常導入 | 既知hashの旧3ファイルをreleaseと元ファイルbackupへ保存して管理リンクへ移行。利用者変更・競合拒否・中断再開・復元fixture成功 |
| 依存 | `/home/tn/.local/share/aidev/dependencies` の内容hash別配置へ既存Terrain・ACP・MCPをコピー。移設前後hash一致、package取得・更新なし |
| qualification | 移設後protocol・実Codex権限・OS拒否・MCP起動・中断復旧がPASS。SHA256 `d2fc0a6d669f1183da3dd408ae6431e1e70c12f040784abad38293e16b427a8a` |
| Python全suite | 92件中90成功、Windows専用2件skip。依存欠落・改変時の拒否も含む |
| 実LLM | `gpt-6-astra / medium` で初回と機能変更後の更新を各1回。通常launcherから実行しsessionのmodel・effort・read-only/neverを照合 |
| 再利用・鮮度 | 同一入力と生成物のみcommit後はreused、文書・生成log不変、ACP/app-server再起動なし。source変更後stale検出 |
| 内容・保全 | 検索・読取り・主要記述とsource/tests/schemaの照合成功。生成前後source不変、通常設定・hooks・依存保全、観測した所有process残存0 |
| 最終doctor | 受入fixtureで `TERRAIN_READY`。既存利用者repoへのinitは行っていない |
| 同期 | 既存pluginの通常同期とcatalog cache更新を記録。plugin cache内容不変、新規plugin・依存package取得は観測なし |

実LLM確認時のreleaseは `ceaf905fc016a8fdca25`、runtime identityは `eed5176dea5da0b99fd40199b97476bde5bd6baf2ba885923438a6e191de1fca`。その後の配布文書更新でrelease identityは変わります。最終receipt [/home/tn/projects/aidev/verification/normal-install-20260922T114000Z/final-install.json](/home/tn/projects/aidev/verification/normal-install-20260922T114000Z/final-install.json) で実行Python・patch・qualification・依存が受入対象と同一であることを照合します。詳細受入結果は [/home/tn/projects/aidev/verification/normal-install-20260922T114000Z/RESULT.md](/home/tn/projects/aidev/verification/normal-install-20260922T114000Z/RESULT.md)。これらはローカル検証証拠で配布対象外です。

復旧基準は [/home/tn/projects/aidev/verification/normal-install-20260922T114000Z/deployment-before](/home/tn/projects/aidev/verification/normal-install-20260922T114000Z/deployment-before)、旧3ファイルreleaseは `/home/tn/.local/share/aidev/releases/2b0de1a5672a1f8b98cc`。今回の入口・管理リンク・Terrain登録だけを、切替後記録と一致する場合に復元します。並行変更は上書きしません。通常repoのcommit・push・PR・release・公開は行っていません。

Windows実機・今回のCIは未実施。shell sandboxはMCP・hooks全体の作用を封じず、HTTPS内容・観測前に離脱した短命processの完全捕捉は保証しません。生成文書は圧縮packが省いた実装本体・test coverageを未確認として扱います。

## 0.3.0 context修正候補の実LLM受入（導入前の履歴）

隔離候補の判定は **UBUNTU_ACCEPTED**。受入済みのruntime/provider修正、固定ACP差分、検証記録、Linux監督helperをこのsourceへ統合しました。通常環境への導入・launcher切替・package releaseは行っていません。Windows Terrainは未サポートのままです。

| 項目 | 確認結果と境界 |
|---|---|
| 対象候補 | release `8b3caf8c3a89f24281cb`、runtime identity `d18e90cdbc5042980ba82c0a401e56d16e9229ee701ee734d67553d4c5583008` |
| 実測環境 | Ubuntu 25.10 x86_64 / Python 3.14.3 / Codex 0.155.1 / Node 24.20.0 / Terrain 0.9.5。Ubuntu 24.04 CIや別環境の実LLM受入とは区別 |
| 実モデル | 初回・更新とも `gpt-6-astra`、effort `medium`。保存済みsessionのturn_contextで確認。backend内部routingは未確認 |
| 通常設定とoverlay | 通常 `/home/tn/.codex` を使用。context専用read-only/never、turnのnetworkAccess=false、検証済みNode・既存chrome-devtools MCPの直接起動overlayあり。通常設定と完全同一ではない |
| 初回・更新生成 | installed候補CLIから計2回とも成功。生成前後のsource集合・内容を照合 |
| 再利用2種 | 同一入力、および生成物のみfixture内commit後に `reused`。文書hash・生成log不変とACP/app-server再起動なしを照合 |
| 意図した機能変更 | 梱包料を指定可能なkeyword-only引数へ変更、既定値3。testは初期2件・変更後5件成功。stale検出後の更新文書にも変更を反映 |
| 検索・意味確認 | 初回・更新ともread-context、grep-pack、read-pack-file成功。主要記述をlive source/tests/schemaと照合。最終doctorは `TERRAIN_READY` |
| 承認済み同期 | ars-codex `main` の照会とremote catalog cache更新を観測。既存remote plugin 10件のID・有効状態・release・内容は不変。新規plugin・依存package取得は観測なし |
| 保全・終了 | 通常config・AGENTS・hooks、通常repo、通常aidev/Terrain/launcher、候補・依存・過去結果の禁止対象差分0。所有照合対象827 processの残存0 |

受入runは `run-20260922T105500Z`。詳細原本は [/home/tn/handoffs/aidev-context-fix-isolated-20260921/evidence/run-20260922T105500Z/RESULT.md](/home/tn/handoffs/aidev-context-fix-isolated-20260921/evidence/run-20260922T105500Z/RESULT.md) と [/home/tn/handoffs/aidev-context-fix-isolated-20260921/evidence/run-20260922T105500Z/result.json](/home/tn/handoffs/aidev-context-fix-isolated-20260921/evidence/run-20260922T105500Z/result.json) に保持し、ログ・認証情報・個別plugin IDは公開sourceへ含めません。元の実LLM `FAIL`、非LLM `PASS WITH ISSUES`、直前runの `BLOCKED_UNAPPROVED_FETCH` は履歴のままです。

HTTPS全通信・観測前に離脱した子processの完全捕捉は保証しません。共有CODEX_HOMEのcache差分は他セッションに由来する場合もあり、全更新の排他的帰属は未確認です。圧縮packが省略した実装本体・例外・test coverageは生成文書でも未確認です。shell sandboxはMCP・hooks・plugin起動時の作用全体を遮断するものではありません。

検証記録はその候補の実体hashと絶対パスに固定されています。別環境で起動できる一般的なqualificationではなく、記録・依存不一致は起動前に停止します。記録を手編集してこの検査を通してはいけません。今回のsource統合では文書・配布対象・回帰testも更新するため、将来installするreleaseのidentityは受入候補と別になります。新配布物の導入・実LLM再受入を実行したとは扱いません。

source統合時のlocal検証はUbuntu 25.10 / Python 3.13.7で88 tests中86成功・Windows専用2skip。修正済み監督helperがwrapperと実receiverを区別し、PID/start ticksで所有確認したreceiverへSIGINTを送り正常終了する回帰を含みます。ACP差分は既存原本の隔離コピーへ適用し、受入済みbundleと同じSHA256になること、Node構文、qualificationと実依存の一致を確認しました。今回のcommitに対するGitHub CI・Windows実行結果は、このlocal検証から推定しません。

## 0.3.0 Ubuntu scopeの実装CI履歴（context修正前）

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

当時は4-matrix CIとUbuntu/Windows Terrain runtime CIをREADY_FOR_MAINの条件とし、live ACPを別受入としていました。この旧gateは今回のUbuntu scopeへ置き換えられています。通常利用環境への導入は別の明示操作です。操作・契約は [/home/tn/projects/aidev/docs/TERRAIN.md](TERRAIN.md) を参照してください。

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

Windows側の作業要求と手順は、ソースに含む [/home/tn/projects/aidev/docs/WINDOWS_HANDOFF.md](https://github.com/tsutomu-n/aidev/blob/main/docs/WINDOWS_HANDOFF.md) を正本とします。W-01〜W-03のsource修正とnative Windows用W-01回帰testを含むコードは上記CIで成功しました。通常利用やWindows完全受入は別の判定です。

- W-01：launcherは裸の `py -3` を廃止し、導入時に検証したPython絶対パス・version・形式をrelease manifestへ記録する。native Windows testは空白・日本語・`&`・括弧・`!`を含む一時Python環境からinstallerを実行し、生成された`.cmd`の起動、子プロセスのPython実体とmatrix指定版、引数・終了コードを照合する。cwdの偽`py`とPATH上の偽`python`が名前探索で実行される対照試験も含む。このtestはWindows CIの両Python構成でPASSし、起動Python固定のnative evidenceが成立した。
- W-02：所有判定をロック取得後へ移し、release準備後・公開直前のentry再照合と、上書き禁止の公開へ変更した。管理外commandを保全する回帰テストはUbuntu/Windows CIで成功した。
- W-03：installer所有の進行記録を残し、source失敗・コピー/公開失敗後に完成releaseを照合して通常installで再開する。所有記録のない旧partialは保全して停止する。初回失敗からの復旧・管理外partial保全・更新時の旧release保持の回帰テストはUbuntu/Windows CIで成功した。

W-02/W-03の再現ツールの記録はUbuntu上でWindowsのファイル処理分岐を用いたものです。今回のWindows CIでは実OS上のfixture回帰も成功しましたが、Windows 11受入完了を意味しません。

Windowsの導入・更新テストでは、成功時にも既存の `Parameter format not correct - code` が出力されています。[/home/tn/projects/aidev/src/install.py](https://github.com/tsutomu-n/aidev/blob/feat/terrain-integration/install.py) の `windows_launcher()` にある `chcp` 出力の分割と復元処理に由来すると考えられ、元のcode pageの復元成功は未確認です。今回のfixture修正ではlauncherを変更しておらず、起動Python固定の成功とこの残課題を区別します。

## 引き継ぎの補助

- sourceに [/home/tn/projects/aidev/AGENTS.md](https://github.com/tsutomu-n/aidev/blob/feat/terrain-integration/AGENTS.md) を配置し、Windows側Codexの開始時に引き継ぎ資料を読む導線を追加。
- [/home/tn/projects/aidev/tools/windows_handoff.py](https://github.com/tsutomu-n/aidev/blob/feat/terrain-integration/tools/windows_handoff.py) は、受領内容照合と一時fixtureでの既知不具合再現を担当。通常利用環境への導入・provider実行はしない。
- [/home/tn/projects/aidev/docs/WINDOWS_HANDOFF_MANIFEST.json](https://github.com/tsutomu-n/aidev/blob/main/docs/WINDOWS_HANDOFF_MANIFEST.json) はUTF-8/LF正規化したsource inventory。期待commitとcleanなGit状態も照合して受領を確認する。署名や実機受入の代替ではない。

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
