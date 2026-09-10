# aidev 0.1.1 技術仕様

この文書は [https://github.com/tsutomu-n/aidev/blob/main/aidev.py](https://github.com/tsutomu-n/aidev/blob/main/aidev.py)、[https://github.com/tsutomu-n/aidev/blob/main/provider_probe.py](https://github.com/tsutomu-n/aidev/blob/main/provider_probe.py)、[https://github.com/tsutomu-n/aidev/blob/main/provider_build.py](https://github.com/tsutomu-n/aidev/blob/main/provider_build.py)、[https://github.com/tsutomu-n/aidev/blob/main/install.py](https://github.com/tsutomu-n/aidev/blob/main/install.py) の現行ソースを基準とします。稼働版と検証範囲は [https://github.com/tsutomu-n/aidev/blob/main/STATUS.md](https://github.com/tsutomu-n/aidev/blob/main/STATUS.md) に分けます。

## 責務と依存

| 構成 | 責務 |
|---|---|
| aidev本体 | Git root確認、事前検査、設定merge、backup、順次解析、状態と鮮度診断 |
| provider_probe | 各uv tool環境のPythonでinstalled schema・拡張子・保存先を読み取る |
| provider_build | CRGの `build_or_update_graph` APIを `postprocess="minimal"` で呼び、構造化結果を検査する |
| installer | 管理対象のhash確認、release配置、入口symlinkの切替、旧release保持 |
| 既存共通基盤 | provider承認・整合性とCLI実体。aidevから承認を書き換えない |

本体はPython 3.11以降の標準ライブラリを使い、Linuxの `fcntl.flock` とプロセスグループ制御に依存します。Windows対応の汎用CLIではありません。providerの内部APIやschemaを参照するため、Serena 1.7.0、Graphify 0.9.55、CRG 2.3.8を要求します。

追加する能力は `symbol_semantics: [serena]`、`architecture_relationships: [graphify]`、`change_impact: [crg]` の3つ固定です。共通Routerの最小能力選択と、この初期化プリセットを区別します。任意のprovider組合せを選ぶ個別rolloutの代替にはしません。

## 初期化の流れ

1. 起動cwdがGit rootそのものか確認し、root directoryに排他的な非待機flockを取る。ロックファイルは作らない。
2. 共通台帳の正常な承認済み3provider、PATH上のCLI版、保存先overrideを確認する。
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

現行installerは4ファイル（本体、probe、build wrapper、README）のhashからrelease識別子を作り、`$HOME/.local/share/aidev/releases` に配置します。このdirectoryは初回導入または旧版からの更新時に作成されます。`installation.json` に収録ファイルhashを記録し、完全なreleaseへ入口symlinkをatomicに切り替えます。補助symlinkの更新を含む全操作が一括transactionという意味ではありません。

`--upgrade` は旧0.1.0の既知hash、または管理releaseのmanifestと実体が一致する場合だけ進みます。既存利用者変更は上書きしません。旧releaseは保持しますが、rollback/uninstallサブコマンドはありません。利用者・shell・global MCP設定は変更しません。

## 保守時の確認

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -W error::ResourceWarning -m unittest discover -s tests -v
python3 -B aidev.py --help
python3 -B aidev.py init --help
python3 -B aidev.py doctor --help
python3 -B install.py --help
```

既存20テストは一時Git repoとproviderのmockで、保全・再実行・鮮度・部分失敗・timeoutなどを確認します。実providerやinstaller更新経路の受入とは別です。provider版を変える場合は、probe/API・設定・実索引・実照会の互換性を対象環境で確認し、版の定数だけを書き換えて完了としません。
