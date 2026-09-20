# aidev 0.3.0 技術仕様

入口：[/home/tn/projects/aidev/README.md](README.md) ／ 操作手順：[/home/tn/projects/aidev/USER_GUIDE.md](USER_GUIDE.md)

この文書は同じcheckoutの [/home/tn/projects/aidev/aidev.py](aidev.py)、[/home/tn/projects/aidev/provider_probe.py](provider_probe.py)、[/home/tn/projects/aidev/provider_build.py](provider_build.py)、[/home/tn/projects/aidev/install.py](https://github.com/tsutomu-n/aidev/blob/feat/terrain-integration/install.py) を基準とします。mainと0.3.0 featureの内容は異なります。検証したHEADと受入範囲は [/home/tn/projects/aidev/STATUS.md](STATUS.md) に記録します。installerへのリンクは配布対象外のsourceへの参照です。

## 責務と依存

| 構成 | 責務 |
|---|---|
| aidev本体 | Git root確認、事前検査、設定merge、backup、順次解析、状態と鮮度診断 |
| provider_probe | 各uv tool環境のPythonでinstalled schema・拡張子・保存先を読み取る |
| provider_build | CRGの `build_or_update_graph` APIを `postprocess="minimal"` で呼び、構造化結果を検査する |
| installer | 管理対象のhash確認、release配置、OS別ランチャーの切替、旧release保持 |
| 既存共通基盤 | provider承認・整合性とCLI実体。aidevから承認を書き換えない |

本体はPython 3.11以降の標準ライブラリを使います。OS依存処理は [/home/tn/projects/aidev/platform_support.py](platform_support.py) に分離し、Ubuntuは `fcntl.flock` / process group、Windowsは名前付きsemaphore / Job Objectを使います。Windows実機受入は未確認です。providerの内部APIやschemaを参照するため、Serena 1.7.0、Graphify 0.9.55、CRG 2.3.8を要求します。

追加する能力は `symbol_semantics: [serena]`、`architecture_relationships: [graphify]`、`change_impact: [crg]` の3つ固定です。共通Routerの最小能力選択と、この初期化プリセットを区別します。任意のprovider組合せを選ぶ個別rolloutの代替にはしません。

## 初期化の流れ

1. 起動cwdがGit rootそのものか確認し、root directoryに対応するOS別の排他的な非待機ロックを取る。ロックファイルは作らない。
2. 専用登録があれば登録された3providerの承認・実行ファイルhash・CLI版を確認する。専用登録がないUbuntuでは従来の共通台帳とPATH上のCLI版を確認する。保存先overrideも拒否する。
3. installed parserの拡張子・package manifest名を取得し、Gitが認識する対象ファイルを列挙する。
4. 設定・保存先・追跡済み生成物・既存Serena schemaを検査し、変更予定と変更前byteを用意する。dry-runはここで `PLAN` を返す。
5. 設定の並行変更を再確認し、backupのGit除外を先に保証する。変更する既存textを保存し、ファイルごとにatomic replaceする。
6. 対象コードなしなら `WAITING_FOR_CODE` を保存する。コードありならfingerprintと成果物を比較し、一致する `LOCAL_READY` は索引再利用で終える。
7. `INITIALIZING` を保存し、Serena index、Graphify AST抽出、CRG build/updateを順に実行する。途中経過を `steps` に保存する。
8. 部分失敗・索引欠落・実行中のコード増減や内容変更を検出する。成功時だけ最終fingerprintと成果物を記録して `LOCAL_READY` にする。

一般エラーがすべてstateの `FAILED` に変換されるわけではありません。事前検査・apply等で失敗した場合は以前のstateや部分適用が残ることがあります。終了コードとエラー本文も確認してください。

## 設定とローカル状態

導入先は利用者が指定するため、以下は実在パスの例ではなく、コードに渡すrepo-relative識別子です。実際の絶対パスはdry-runの `files_to_change` と実行結果の `root` / `backup` で確認します。

```text
共有を検討する設定:
  .codex/config.toml
  .codex/dev-capabilities.json
  .gitignore
  .graphifyignore
  .code-review-graphignore
  .serena/project.yml
ローカル管理・Git除外:
  .aidev/.gitignore
  .aidev/state.json
  .aidev/backups/<実行識別子>/changes.json
  .aidev/logs/serena.log
  .aidev/logs/graphify.log
  .aidev/logs/crg.log
  .serena/runtime/serena_config.yml
  .serena/cache/<language>/document_symbols.pkl
  .serena/cache/<language>/raw_document_symbols.pkl
  graphify-out/graph.json
  .code-review-graph/graph.db
```

JSONとして書くSerena設定はYAMLとしても読める形式です。既存projectの不足言語を自動追加せず停止します。既存TOMLは不足するサーバー節を追記し、同名serverのcommand/args/env/enabled_toolsの相違や明示無効化は衝突とします。既存の追加timeout・tool承認フィールドは維持しますが、新しい自動承認は生成しません。

新規ファイルは通常0600、新規directoryは0700で作成し、既存ファイルのmodeを維持します。既存directory全体の権限を矯正する処理ではありません。backupは変更した既存textだけを保存し、変更一覧には `existed` と `after_sha256` を記録します。

## 鮮度と成果物の検査

`fingerprint` は対象ファイルのpath・内容とGit/解析ignore、Serena project/runtime設定の内容をSHA-256へ投入します。対象集合はinstalled Graphify/CRGの解析対象と対応言語の集合から作り、Git除外、依存、build、代表的秘密ファイル名を除きます。mtimeや件数だけでは鮮度を判断しません。policyとMCP設定はfingerprintに直接含まず、毎回planによる整合確認を行います。

GraphifyはJSONのnodes配列とファイルhash、CRGはread-only immutable SQLiteでquick_check・nodes/edgesの論理内容を確認します。CRGの `updated_at` は論理hashから除外します。未checkpointの非空WALがあれば停止します。Serenaは言語ごとの2つのpickleをopcodeとして解析し、末尾STOPまでの構造を確認します。pickleを実行しません。この検査は全symbolや全参照の意味的な網羅性の保証ではありません。

`doctor` はproviderの版照会とprobeを実行しますが、解析server・index buildは起動しません。repoへの書込みなしで、state、設定、fingerprint、成果物を照合します。initの排他ロックは取らず、別プロセスによるその後の変更を保証しません。

## 失敗処理と外部作用

子プロセスはshellを介さず、cwdを対象rootへ固定し、`PYTHONPATH` / `PYTHONHOME` を除去します。timeout・中断時はプロセスグループへTERM、必要ならKILLを送り、最新出力をローカルログへ保存します。既定600秒は各providerのbuild段階の上限であり、全処理の総時間上限ではありません。

Serena等の終了0でも部分失敗の出力を検出します。CRG wrapperは `status` がokでも `errors` または `warnings` があれば失敗させ、成功時も `AIDEV_CRG_RESULT=` の構造化結果を本体で照合します。

設定・出力のsymlink/hardlink、追跡済み解析生成物、Serenaの独自hook/backend/追加workspace、CRG保存先override等は停止条件です。Serena自身の言語サーバー内で完結する内部symlinkは例外です。`CRG_REPO_ROOT`、`CRG_DATA_DIR`、`CRG_HOME`、`GRAPHIFY_OUT`、`GRAPHIFY_FORCE` の有効値がある場合も停止します。

外部LLM抽出・embeddingを行わず、Graphifyはcode-only/no-cluster、CRGはminimal後処理です。ただしSerenaの初回言語サーバー取得はあり得ます。repo指定はproviderの強制隔離sandboxではありません。

## installerの契約

現行installerは13ファイル（既存9ファイルとTerrain用2 modules・patch・操作文書）のhashからrelease識別子を作り、`$HOME/.local/share/aidev/releases` に配置します。このdirectoryは初回導入または旧版からの更新時に作成されます。`installation.json` に収録ファイルhashを記録し、完全なreleaseへUbuntuは入口symlink、WindowsはUTF-8のcmdランチャーをatomicに切り替えます。Windowsの保存先設定値は `%LOCALAPPDATA%\aidev` です。補助symlinkの更新を含む全操作が一括transactionという意味ではありません。

`--upgrade` は旧0.1.0の既知hash、または管理releaseのmanifestと実体が一致する場合に進みます。release manifestには実行Pythonの絶対パス・検証済み版・launcher形式も含み、Windows launcherはそのPythonをUTF-8 cmdから直接起動します。`py` / PATHへの実行時fallbackはありません。ロック取得後と公開直前にentryの種類・内容・link先を再照合し、初回は存在しない宛先への作成だけを許可します。更新は旧entryを専用退避先へrenameしてから、空の宛先へ公開します。競合時は上書きせず停止します。

`installation-progress.json` はインストーラー自身が作った未完了処理だけを記録します。source検証・コピー・entry公開の失敗後、記録と完成releaseを照合できる同一source/同一Pythonの再実行は通常installで再開できます。所有記録のない旧partial、変更済みrelease、利用者entryは自動復旧しません。旧release、entry backup、失敗したstaging以外の利用者データを削除するrollback/uninstallはありません。

## 保守時の確認

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -W error::ResourceWarning -m unittest discover -s tests -v
python3 -B aidev.py --help
python3 -B aidev.py init --help
python3 -B aidev.py doctor --help
python3 -B install.py --help
```

coreの20テストは一時Git repoとproviderのmockで、保全・再実行・鮮度・部分失敗・timeoutなどを確認します。実providerやinstaller更新経路の受入とは別です。provider版を変える場合は、probe/API・設定・実索引・実照会の互換性を対象環境で確認し、版の定数だけを書き換えて完了としません。

## Windowsと専用provider登録

[/home/tn/projects/aidev/WINDOWS.md](WINDOWS.md) に操作契約を記載しています。`setup` は指定された専用Pythonと同じ環境のCLIを検査し、`--approve` がある場合だけaidev専用の登録を保存します。`--replace` で更新する際は元のbytesをbackupします。従来のUbuntu共通台帳やCodexの承認設定は変更しません。専用登録はmodule台帳の移植ではなく、aidev自身の起動契約です。

登録はCLIとPythonのpath/hashとprovider版を確認します。providerの依存ファイル全体をhash固定する仕組みではありません。専用登録を使うrepoのMCP commandは登録済みexeの絶対パスです。Windowsではvenvの `Scripts/python.exe` をそのまま使い、実体解決によってvenvを失わないようにします。JSON/TOMLとprovider JSONの文字コードはUTF-8です。Windowsのjunction/reparse pointも設定・出力先のリンク拒否対象に含めます。

Windowsの子プロセスはJob Objectへの所属確認後にproviderを起動し、Jobを閉じる際に子孫も終了します。所属失敗時に無管理のprovider実行へfallbackしません。Ubuntuもtimeout時は親の終了後に残る子孫へSIGKILLを送ります。Windowsのlauncherは導入時に検証したPython絶対パスを使用し、code pageを退避・UTF-8へ切替・復元して引数と終了コードを保全します。

## Terrain namespace

`aidev.py`はTerrain commandの場合だけ専用moduleをimportします。`terrain_runtime.py`がpin・patch identity・download/build・approval/hash・behavior smoke、`terrain_provider.py`がrepo-local registry・fingerprint・AGENTS・backup・生成gate・doctor・read toolsを担当します。generic plugin frameworkは導入していません。

Terrain doctorは既存doctorと異なりprovider processを一切起動せず、保存runtime recordと現在のhashをPythonで検査します。生成処理は既存directory lock/process group/Job Objectを再利用し、Terrain起動時のHOME副作用を一時HOMEへ隔離します。入力はGitのnonignored列挙と実内容hash、出力はpack/context/meta hashで照合します。具体的なschema・CLI・migrationと制限は [/home/tn/projects/aidev/TERRAIN.md](TERRAIN.md) を参照してください。
