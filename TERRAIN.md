# Terrain Knowledge Layer（aidev 0.3.0）

Terrainは任意導入のderived navigation/index layerです。Code、tests、schemas、config、lockfiles、CI、CLI helpを正本とします。

## 目的と使い分け

既存の `aidev init` / `doctor` / `setup` は従来の3provider用です。Terrain未導入でも動作します。Terrainは `aidev terrain` namespaceから明示導入します。`--with-terrain` / `--allow-llm` はありません。

known-fileの小修正ではlive sourceを直接読みます。architecture・multi-module・場所不明の調査では、doctor → read-context → grep-pack/read-pack-fileの順に絞り、重要な主張と編集対象をlive source/tests/schemasで確かめます。pack全文をLLM contextへ読み込みません。

## マシンで一度だけ準備

```sh
aidev terrain install --allow-download
# cleanなexact upstream sourceを使い、network cloneを避ける場合:
aidev terrain install --source /absolute/path/to/clean-terrain --allow-download --timeout 3600

# 既存binaryを採用（承認なしは実行・書込みのないPLAN）:
aidev terrain setup --terrain-binary /absolute/path/to/terrain
# 検証し、この利用者のaidevで利用することを承認:
aidev terrain setup --terrain-binary /absolute/path/to/terrain --approve
# ACPを明示登録する場合:
aidev terrain setup --terrain-binary /absolute/path/to/terrain --codex-acp /absolute/path/to/codex-acp --approve --replace
```

例中の絶対パスは未作成の説明用です。実在する通常ファイルを指定してください。symlink、reparse point、hardlink、対象repo内の実行ファイルは拒否します。Windowsでは `.cmd` / npm shimではなくnative `.exe` を指定します。npm global installやnpxによる自動取得は行いません。

`install`にはGit、cargo、rustc >= 1.94が必要です。Rust自体は導入しません。`--allow-download`なしはPLANのみ。指定sourceはclean・exact upstream SHAを確認して別cloneへ複製し、元sourceを変更しません。cargoの依存取得は `--source` 指定時にもあり得るためdownload許可が必要です。focused Rust tests、release build、behavior smokeの成功後だけ登録します。

保存先はUnixのdata home設定値 `$HOME/.local/share/aidev/terrain`、Windowsの `%LOCALAPPDATA%\aidev\terrain`。binary・patch・upstream identityごとの `releases/<sha256>`、build manifest、`foundation.json` を保持します。PATH・既存Terrain binary・既存global registryを上書きせず、旧releaseや失敗buildのログは削除しません。再buildによって既存登録が変わる場合は、作成済みbinaryを `setup --approve --replace` で選択します。

setupはversionだけで採用しません。一時Git repoでregister/scan/pack、ignored OpenAPI排除、正規OpenAPI保存、context repair、absolute path正規化、H2数・Unicode文字数、read toolsとregistry隔離を検査します。version・binary hash・upstream/patch identity・behavior結果を保存し、利用前にhashを再照合します。既存binaryのbuild provenanceを証明する署名ではありません。採用するbinaryの入手元は利用者が確認してください。

## repo導入と更新

対象Git rootで実行します。

```sh
aidev terrain init --dry-run
aidev terrain init
aidev terrain init --slug example-project
aidev terrain doctor --json
aidev terrain refresh
```

slugは初回の明示指定、origin名、root名の順に選び、repo-shared configへ保存します。以降は保存値を優先し、異なるslug指定は拒否します。同名repo・worktreeでもregistryはcheckoutごとに独立します。

dry-runはruntimeの保存hash、paths、既存assets等を検査し、repo・machine登録・registryへ書き込みません。refreshはinit済みrepo専用です。変更がなければscan/packを再実行しません。HEAD、indexのblob ID、Gitが認識するnonignored入力の実内容、runtime identity、生成policyをfingerprintへ含めます。dirty、staged、untrackedの内容変更を検出し、ignored directoryを全走査しません。実行中sourceが変わればstateを最新として確定せず、再実行を求めます。sourceは巻き戻しません。

Terrainのscanはpackも作ります。aidevは古いpack metadataを退避してHEADだけによる誤再利用を防ぎ、scan後にpackがreadyでない場合だけpack-agentへfallbackします。

## 必要な場合だけAgent Contextを生成

```sh
aidev terrain init --build-context
aidev terrain refresh --build-context
```

このflagはCodex ACPによるLLM処理・外部送信を許可する操作です。同じ入力・runtime・policy・出力hashなら再生成しません。flagなしはローカルscan/packのみで、既存contextを削除せずstaleと記録します。

初期サポートは `@agentclientprotocol/codex-acp 1.11.0`。事前に登録hash・版・実行pathを確認し、Codex CLIの `login status` で認証状態を確認します。不足時は停止し、利用者によるloginを案内します。browser・loginは自動起動しません。ACP binaryと空argsを分離し、JSON stdio設定と `INITIAL_AGENT_MODE=read-only` を使います。native LLM設定は追加しません。permissionの自動承認は無効です。

Terrainの起動自体にHOME側asset展開があるため、wrapperは一時HOMEと設定を用意します。`.env` の自動読込みを避けるためTerrain launcherのcwdはその一時HOME、対象repoは絶対 `--repo-path`・registry・環境で指定します。ACPのworking directoryは対象repoです。認証をコピーせず既存の `CODEX_HOME` を引き継ぎます。keyring等の認証方式は実環境で別途受入が必要です。

Git ignoreを尊重し、nonignoredの `.env`、credentials、key等の代表的ファイル名は処理前に拒否します。これは任意の秘密文字列の自動redactionではありません。送信前にrepoのignoreと内容を確認してください。

## 書込みなし診断

```sh
aidev terrain doctor
aidev terrain doctor --json
```

doctorはPythonとread-only Git plumbingだけを使用し、Terrain/ACPを起動しません。登録・scan・pack・context build・settings write・lock作成をしません。runtime hash/identity、slug/registry/checkout、Git境界、pack、context構造とmetadata、OpenAPI provenance、fingerprintと出力hashを検査します。

| status | 意味 |
|---|---|
| TERRAIN_READY | pack/contextと記録入力が一致 |
| TERRAIN_READY_CONTEXT_NOT_BUILT | packは利用可能、context未生成 |
| TERRAIN_NEEDS_REFRESH | source/runtimeまたはpackが記録と相違 |
| TERRAIN_NEEDS_CONTEXT_REFRESH | contextの入力・出力が古い |
| TERRAIN_RUNTIME_MISSING | 承認runtimeなし・hash/identity不正 |
| TERRAIN_INVALID | config、registry、Git境界、context等が不正 |

ready/PLANはexit 0、doctorの更新必要・不正はexit 1、実行エラーはexit 2。JSONのruntime/pack/context/source_fresh/writesを分離します。Terrain freshnessを正確率とはみなしません。

contextは4個以上のH2・500文字以上というupstream最小構造、実H2数とsection_count、Unicode文字数とchar_count、repo-relative metadataとabsolute checkout pathの不在を確認します。7節固定による判定ではありません。自然言語の事実性や網羅性を保証しません。

## 探索入口

```sh
aidev terrain tools read-context
aidev terrain tools read-context --section Architecture
aidev terrain tools grep-pack --pattern Strategy --context 2 --limit 20
aidev terrain tools read-pack-file --file src/example.py --start-line 1 --end-line 120
```

wrapperは承認runtime・local registry・保存slugを設定します。stale/不正packは先にrefreshを要求します。contextだけがstaleならgrep-pack/read-pack-fileは使えますが、read-contextは明示更新を要求します。Terrainが返す `matched_path` を確認し、編集前にlive sourceへ戻ってください。Terrain read toolの起動に伴う一時HOME内の副作用はありますが、doctorはその起動もしません。timeout・中断は既存のprocess group/Windows Job Objectで子孫を終了します。

## 共有とローカルの境界

以下は対象repo内の相対識別子です。aidevはGit add/commitしません。

```text
共有候補（存在するものだけ）:
.terrain/.gitignore
.terrain/.gitattributes
.terrain/aidev.json
.terrain/index.md
.terrain/agent/context.md
.terrain/agent/context-meta.json
.terrain/modules/*
.terrain/interfaces/*
.terrain/routes/*
.terrain/events/*

Git管理外:
.terrain/agent/repomix.md
.terrain/agent/meta.json
.terrain/agent/meta-inputs*
.terrain/.meta/*
.aidev/terrain/state.json
.aidev/terrain/registry.json
.aidev/terrain/logs/*
.aidev/terrain/backups/*
```

正規OpenAPI由来のinterfaces/routesは保持します。各docのsourceがnonignoredのrepo入力であることが条件で、件数0を一般条件にしません。

## migrationと失敗復旧

既存assetsは先に監査します。legacy metadataのHEADとcleanな入力が一致し、AGENTSの入力変更も不要ならpack/contextを再利用し、local registry・config・stateだけを整備します。dirty/untracked入力のlineageを証明できない場合はpackを再構築し、contextをstaleとして保持します。migrationだけでは `--build-context` があってもLLMを呼びません。必要なら次のrefreshで明示更新してください。

AGENTSの既存本文を保全し、aidev管理marker内だけを更新します。markerなしの既存 `## Terrain Knowledge Layer` はmanualとして保全し、重複追加しません。

変更前のAGENTS/configと共有Terrain assetsはrun別backupへ保存します。partial failureのログと以前のstateを残し、再実行で回復できます。利用者sourceをrollbackせず、大きな一括transactionも行いません。不正な既存context/provenanceは自動修復せず監査で停止します。backupを確認して利用者が訂正してください。

## upstreamとpatch

- upstream: https://github.com/sopaco/terrain.git
- version: 0.9.5
- SHA: `8d888ae13a6b1253406cac379c8eb30037c96862`
- Rust MSRV: 1.94
- patchはMarketLens正式patchを基礎に、context path/H2/Unicode補正、OpenAPI gitignore、ACP mode伝播と空白pathのavailability判定を含む3ファイル。
- patch SHA256（LF正規化）: `893efe60ec622ef6741e20d8a81c840124de60b823e842854c789ee9681f40c1`。実sourceから算出し、approval/build manifestへ記録します。

## 検証と制限

Pythonのfixture testsは既存Ubuntu/Windows × Python 3.11/3.13 workflowに含まれます。別のTerrain workflowはUbuntu/Windowsでexact upstream、patch適用範囲、focused Rust tests、release build、behavior smokeを検査します。runtimeのcore/agent/CLI full testsはclean baselineとtest名・failure内容を比較し、新規failureを拒否します。desktop GUIはaidev配布runtimeの対象外です。upstream全体へのformat変更は行いません。

live Codex ACPは通常CIに含めません。実認証・外部送信許可のあるdisposable fixtureで別受入とし、未実施はUNVERIFIEDです。Windows build/CI、通常利用環境への導入、実LLM生成の完了はsource実装と区別し、現在の結果はSTATUSに記録します。

submodule入力、symlink/reparse/hardlinkを含む入力・生成先は初版では停止します。read-pack-fileはupstreamの圧縮packに基づく探索であり、live sourceの厳密転記ではありません。自動redaction、watch daemon、Git hook、Litho/SDD自動生成、plugin frameworkはありません。
