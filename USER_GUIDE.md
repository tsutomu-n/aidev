# aidev ジュニアSE向け操作マニュアル

入口へ戻る：[/home/tn/projects/aidev/README.md](README.md)

ターミナルでコマンドを実行できる方が、導入から解析準備、日常の更新、障害の切り分けまで進めるための手順です。ソース0.2.0を基準にしています。

Windows 11の導入・登録は [/home/tn/projects/aidev/WINDOWS.md](WINDOWS.md) を先に進めてください。以下のshell例はUbuntu向けです。

## 目次

1. [役割と用語](#basics)
2. [導入・更新](#install)
3. [対象リポジトリを初期化する](#first-run)
4. [Codexで使えるか確認する](#codex-check)
5. [日常の操作](#daily)
6. [表示と終了コード](#results)
7. [トラブル対応](#troubleshooting)
8. [バックアップと取り消し](#recovery)
9. [先輩・管理者への相談](#support)

<a id="basics"></a>
## 1. 役割と用語

アプリのソースコードを解析し、関数の定義・参照・変更の影響を調べるための準備を行います。アプリの雛形を作る機能ではありません。

| 用語 | 意味 |
|---|---|
| リポジトリ（repo） | Gitで管理しているプロジェクト |
| ルート | そのリポジトリの一番上のフォルダー。`git rev-parse --show-toplevel` で確認できる |
| CLI | ターミナルからコマンドで操作するツール |
| 索引（index） | コードを検索するために作る解析データ。コードが変わると更新が必要 |
| provider | 解析を担当するツール。aidevでは下記3つを使う |
| Serena | 関数・クラスなどの定義や参照を調べる |
| Graphify | コードの構成や関係を抽出する |
| CRG | code-review-graphの略。コードの関係から変更影響の調査を助ける |
| MCP | Codexなどが外部ツールを呼び出すための接続方式 |
| 共通基盤 | 承認台帳と、あらかじめ導入された解析ツールの組合せ |

**aidev本体の配置先と、解析するプロジェクトは別です。** この環境で本体のソースは `/home/tn/projects/aidev`。`aidev init` は解析したいプロジェクトで実行します。

以下のコマンドはUbuntuのターミナルで、1ブロックずつ結果を見て実行してください。コード内の `/absolute/path/to/your-repo` は説明用の未作成パスです。実際の対象リポジトリの絶対パスへ置き換えます。他の利用者のHOMEや配置先が異なる場合も実環境に合わせてください。

<a id="install"></a>
## 2. 導入・更新

### 2.1 前提を確認する

管理者が共通基盤を導入・承認済みであることが前提です。未導入ならここで管理者に準備を依頼してください。既存共通基盤を使わない場合は、[/home/tn/projects/aidev/WINDOWS.md](WINDOWS.md) の `setup` 登録を使えます。Ubuntuの専用venvでは各 `bin/python` の絶対パスを指定します。

次は読取り確認です。どのフォルダーでも実行できます。

```sh
python3 --version
git --version
command -v serena graphify code-review-graph
serena --version
graphify --version
code-review-graph --version
python3 /home/tn/.local/share/dev-capabilities/core/catalog.py list
```

| 確認対象 | 次へ進める条件 |
|---|---|
| Python | 3.11以降 |
| Git | バージョンが表示される |
| Serena / Graphify / CRG | それぞれ1.7.0 / 0.9.55 / 2.3.8がPATHから実行できる |
| 共通台帳 | `approved_modules` に `serena`・`graphify`・`crg` がある |
| provider実行環境 | 管理者が各providerを既存uv tool環境に導入済み |

バージョンが新しければ使える、とは限りません。aidevは指定版と実体を初期化時に再検査し、不一致なら停止します。エラーを通すためだけに台帳を編集しないでください。

### 2.2 aidevを初めて入れる

この環境では `/home/tn/projects/aidev` に取得済みです。未取得の環境で、その配置先が存在しない場合に限り次を使います。

```sh
git clone https://github.com/tsutomu-n/aidev.git /home/tn/projects/aidev
```

本体のソースからインストールします。配置先の親フォルダーが未作成なら `mkdir -p` で用意します。

```sh
cd /home/tn/projects/aidev
mkdir -p /home/tn/.local/bin /home/tn/.local/share
python3 /home/tn/projects/aidev/install.py
/home/tn/.local/bin/aidev --version
```

期待結果はインストール完了と `aidev 0.2.0` です。入口は `/home/tn/.local/bin/aidev`、管理先は `/home/tn/.local/share/aidev` です。既存コマンドがあるというエラーなら、削除せず次の更新手順を確認します。

続いて短い名前で実行できるか確認します。

```sh
aidev --version
```

見つからない場合は当面 `/home/tn/.local/bin/aidev` を使えます。以下の `aidev` もこの絶対パスに置き換えてください。恒久的なPATH設定は普段の環境管理手順に従います。

### 2.3 既存aidevを更新する

取得済みソースとインストール済みコマンドは別物です。まずソースの状態・版を確認し、必要なソース更新はチームのGit運用に従います。

```sh
git -C /home/tn/projects/aidev status --short --branch
python3 -B /home/tn/projects/aidev/aidev.py --version
/home/tn/.local/bin/aidev --version
```

導入したいソースが揃ったら実行します。

```sh
python3 /home/tn/projects/aidev/install.py --upgrade
/home/tn/.local/bin/aidev --version
```

管理対象の旧版だけを更新し、旧releaseは保持します。管理外のコマンドやインストール済みファイルの利用者変更があれば停止します。Gitでソースを更新しただけではインストール版は変わりません。

Windows launcherは導入を実行した確認済みPythonの絶対パスを固定し、消失時に別Pythonへfallbackしません。導入/upgrade中の競合、利用者変更、所有記録のない旧partialは上書きせず停止します。installer所有の中断だけは同じsource・同じPythonで通常installを再実行して復旧できます。実機での旧版upgrade受入は未実施です。検証範囲は [/home/tn/projects/aidev/STATUS.md](STATUS.md) を確認してください。

<a id="first-run"></a>
## 3. 対象リポジトリを初期化する

### 3.1 作業場所と対象を確認する

```sh
cd /absolute/path/to/your-repo
pwd
git rev-parse --show-toplevel
git status --short
```

`pwd` とGit rootが同じ対象を示していれば進めます。Gitリポジトリでない場合は、正しいcloneへ移動します。新規プロジェクトなら、目的のフォルダーか確認してから利用者が `git init` で用意します。

未commitの変更がある場合は自分・他の人の作業を把握し、初期化中のコード編集や別の解析処理を止めます。既存変更の破棄は不要です。秘密情報・顧客データ・生成物について、対象repoのGit除外と解析ignoreも確認します。aidevは任意の機密データを自動識別する検査ではありません。

### 3.2 変更予定を見る

```sh
aidev init --dry-run
```

成功するとJSONで `status: PLAN`、`writes: false` が表示されます。

| 項目 | 確認すること |
|---|---|
| `root` | 初期化したいリポジトリの絶対パスか |
| `files_to_change` | 変更予定の設定ファイル。意図しない設定変更がないか |
| `source_files` | 解析対象数。想定外に0ならコード・言語・除外を確認 |
| `languages` | 検出した対応言語が想定と一致するか |

この段階では設定を書き換えず、索引構築もしません。`files_to_change` は全索引・ログの生成予定一覧ではありません。0件でも索引の更新が必要な場合があります。

### 3.3 実行して結果を確認する

```sh
aidev init
```

設定変更、変更前テキストのバックアップ、Serena → Graphify → CRGの解析を行います。設定が同じでコードと索引の鮮度も一致していれば、既存索引を再利用します。

既定の時間上限は**各providerの処理ごとに600秒**です。大きいrepoで不足するときは、原因を確認してから延長できます。総所要時間の上限ではありません。

```sh
aidev init --timeout 1800
```

`LOCAL_READY` が出たら診断します。

```sh
aidev doctor
```

再び `LOCAL_READY` ならローカル準備は完了です。`WAITING_FOR_CODE` は対象コード追加待ちなので、コードを用意してから再実行します。別の表示なら [結果一覧](#results) を確認してください。

初回Serena解析では言語サーバーの取得が発生する場合があります。完全オフライン動作は保証していません。aidevの索引構築は外部LLM抽出・embeddingを行いません。Codex利用時の通信は別です。

### 3.4 変更内容を確認する

```sh
git status --short
git diff --stat
git diff
```

`git diff` に新規の未追跡ファイルの内容は出ません。`git status --short` の `??` も確認し、該当ファイルをエディターで読みます。

追加するMCP設定、解析設定、Git除外などの詳細は [/home/tn/projects/aidev/TECHNICAL.md](TECHNICAL.md) にあります。索引・ログ・バックアップはローカル管理です。aidevはcommit・pushをしません。設定をGitへ含めるかはチームで判断し、一括stageで元の作業を巻き込まないようにします。

<a id="codex-check"></a>
## 4. Codexで使えるか確認する

導入済み・利用可能なCodex CLIを使います。対象repoルートのターミナルで次を実行し、新規セッションを開きます。

```sh
codex
```

表示される標準の信頼確認に従います。その後、**Codexの入力欄**で `/mcp` を入力します。これはターミナルのコマンドではありません。セッション内で利用できるMCPサーバーとツールを確認する操作です。[OpenAI公式のコマンド説明](https://learn.chatgpt.com/docs/developer-commands?surface=cli)も参照できます。

aidevが設定するMCPはSerenaとCRGです。GraphifyはCLIで索引を作るため、GraphifyがMCP一覧にないこと自体は異常ではありません。

実在する関数を1つ選び、次のように依頼します。「対象の関数名」は置き換えてください。

```text
ソースを変更せずに、Serenaで「対象の関数名」の定義と参照元を調べてください。
根拠となるファイルの絶対パスを示し、実際にツールを呼べたかも説明してください。
```

```text
ソースを変更せずに、CRGでその関数を変更した場合の影響候補を調べてください。
実際のコードと照合し、未確認の範囲を分けてください。
```

返された定義・呼出元をエディターで開いて確認します。単なる文字列検索だけで答えた場合は、MCPによる実照会を確認できていません。

完了の目安は「doctorが成功」「Serena・CRGの実照会が成功」「回答の根拠がsourceと一致」の3点です。`codex_mcp: UNVERIFIED` はaidevが接続を検査していないという表示なので、実照会後も自動で検証済みに変わりません。アプリのテストや解析の網羅性の保証も別です。

<a id="daily"></a>
## 5. 日常の操作

| タイミング | 操作 |
|---|---|
| 作業開始・コード編集後・branch切替後 | 対象repoで `aidev doctor` |
| コード・設定・索引の変化が理由の `NEEDS_INIT` | 原因を確認し `aidev init` → `aidev doctor` |
| 新しいclone・worktree | その作業先で初回手順を行う。既存の解析stateをコピーしない |
| コードのないrepo | 対応コードを追加後に `aidev init` |
| aidev本体を更新 | [本体の更新手順](#install)。対象コードの索引更新とは別 |

変更を監視するwatcherやGit hookは追加しません。個別providerだけを選ぶoptionもありません。索引更新が必要な場合は3providerを順番に処理します。

<a id="results"></a>
## 6. 表示と終了コード

| 表示 | 意味 | 次の行動 |
|---|---|---|
| `PLAN` | dry-run成功 | 予定を確認してinit |
| `LOCAL_READY` | ローカル設定・索引の照合成功 | Codexで接続と実照会を確認 |
| `WAITING_FOR_CODE` | 空repoの設定完了、コード待ち | 対応コード追加後にinit |
| `NEEDS_INIT` | 設定・コード・索引に不足や変化 | 表示された理由を確認 |
| `INITIALIZING` | 保存state上の解析途中 | 処理中なら待つ。中断後ならログを確認 |
| `FAILED` | 保存stateに記録された初期化失敗 | エラーとproviderログを確認 |
| `ERROR` | doctorのJSONエラー応答 | `error` を確認 |
| `codex_mcp: UNVERIFIED` | Codex接続はaidevの検査対象外 | セッションで実照会 |

機械処理向けには次を使います。直後の `echo $?` が直前のコマンドの終了コードを表示します。

```sh
aidev doctor --json
echo $?
```

終了0は成功（dry-run・コード待ちのinitも含む）、終了1はdoctorの要初期化、終了2はエラーです。空repoのdoctorは `NEEDS_INIT`・終了1になり得ます。空repoの設定失敗とは限りません。

`init --json` はありません。通常のinitエラーは標準エラーに表示され、すべてがstateの `FAILED` に記録されるわけではありません。最新の終了コードとエラー本文を優先してください。

<a id="troubleshooting"></a>
## 7. トラブル対応

エラー後は同じコマンドを連打せず、理由と表示されたログの絶対パスを確認します。

| 症状 | 確認・対応 |
|---|---|
| `aidev: command not found` | `/home/tn/.local/bin/aidev --version` を試す。未導入なら導入手順へ |
| repoルートで実行するよう表示 | 表示された絶対パスに移動し、`pwd` とGit rootを再確認 |
| 共通基盤なし・承認や整合性のエラー | 管理者へ前提確認を依頼。台帳の強制編集はしない |
| providerの版不一致・uv環境なし | 指定版と導入方法を管理者に確認。最新化だけで解決しようとしない |
| MCP・能力選択・Serena設定の衝突 | 既存設定の意図を確認。3provider一括設定が合わなければ管理者の個別導入手順を使う |
| 環境overrideのエラー | 表示された変数の設定理由を確認。必要な既存設定を無条件で解除しない |
| 未対応言語・対象0件 | Python/JavaScript/TypeScriptの存在と除外を確認。混在repoの全言語解析は保証しない |
| timeout・途中失敗 | ログで原因を確認し、修正後に同じinit。時間不足なら `--timeout 1800` |
| 処理中のコード変更 | 編集・別解析が止まっていることを確認して再実行 |
| CRGの非空WALエラー | 利用中サーバーを通常手順で終了して再確認。DBやWALを手動削除しない |
| 追跡済み生成物・symlink/hardlinkのエラー | 管理方法と参照先を確認し相談。追跡解除やリンク削除で強行しない |
| doctor成功だがMCPが使えない | 対象repoの新規セッションか確認。MCPのエラーと実照会を切り分ける |
| installerが利用者変更・管理外と表示 | 現在の配置を保全して相談。上書き・削除しない |

ログはproviderごとに再実行時に上書きされます。必要な失敗記録は再実行前に確認・手元へ保全してください。ログは内容確認前に外部へ貼らないでください。

<a id="recovery"></a>
## 8. バックアップと取り消し

初期化結果の `backup:` は、変更前の既存テキストと変更一覧の保存先です。索引・ソース全体のバックアップではありません。失敗で結果が表示されなかった場合は、技術仕様に示すrepo内のバックアップ保存先を確認します。

**自動rollback・uninstallコマンドはありません。** 取り消しが必要なら次の順で担当者と確認します。

1. 初期化と関連する解析処理を止め、現在の設定と利用者変更を保全する。
2. バックアップの変更一覧・変更前テキスト・現在のファイルを比較する。
3. 一覧の `existed` で元からあったファイルか、新規作成かを判別する。
4. 初期化後の利用者変更を残し、戻す必要のある設定だけを個別に復元する。
5. `git status --short` とdiffを確認する。aidevを使い続けるならdoctorで再診断する。

複数ファイル一括のtransactionではなく、途中失敗では部分適用が残る場合があります。再実行は厳密な途中再開ではなく、状態を再確認して必要な一連の処理をやり直します。索引・ログの一括削除やGitの追跡解除を復旧に混ぜないでください。

<a id="support"></a>
## 9. 先輩・管理者への相談

次を整理すると切り分けが早くなります。共有先に渡せる内容だけを記載してください。

```text
目的：導入 / 初期化 / 索引更新 / 接続確認 / 復旧
対象repoの絶対パス：
aidevのバージョン：
実行したコマンド：
表示されたstatus・終了コード・エラー：
直前の変更：branch切替、コード編集、ツール更新など
ログの絶対パスと、秘密を除いた必要箇所：
Codexの実照会：未実施 / 成功 / 失敗（内容）
```

providerの内部契約や保存先は [/home/tn/projects/aidev/TECHNICAL.md](TECHNICAL.md)、受入の未確認事項は [/home/tn/projects/aidev/STATUS.md](STATUS.md) を参照してください。

入口へ戻る：[/home/tn/projects/aidev/README.md](README.md)
