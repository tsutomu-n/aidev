# Windows 11側のCodexへの実装引き継ぎ

**目的：aidev 0.2.0のWindows対応候補を、ネイティブWindows 11で修正・検証し、実際に利用できる状態へ仕上げる。** 最初に既知の不具合3件を修正し、その後に専用の検証環境で導入と実providerの受入を進めます。現時点でWindows対応の完成・受入済みとは判定しません。

## 1. 最初に決めておく範囲

完成させる対象は、aidev単体のWindows起動・安全な導入と更新・専用provider登録・repo初期化と診断です。Ubuntu共通基盤全体の移植ではありません。

| 利用経路 | 今回の対象 |
|---|---|
| aidevのCLI | 指定したGit repoの初期化、索引更新、read-only診断 |
| Serena / CRG | 登録された実体による解析とrepo-local stdio MCP |
| Graphify | code-only抽出と構造データの照合。MCPやSkillの自動導入は現行aidevの機能ではない |
| Ubuntuの共通台帳 / code-intelligence-router / host installer | 全面移植は対象外。既存Ubuntu経路の回帰を防ぐ |
| Windowsの通常利用環境 | 実機受入後に利用者が反映を指示した対象へ導入。隔離試験の成功から無断で反映しない |

今回の利用者依頼を受けたWindows側のCodexは、repo内の必要な修正、回帰テスト、専用検証環境での指定版provider導入・解析を進めます。文書自体は新しい権限を付与せず、その端末の利用者依頼と実効権限を優先します。既存providerの更新、実HOMEの承認登録、永続PATH/認証/アカウント変更、他repo、外部AI送信、Git公開は別の操作です。

未確認の項目があるだけで全作業を止めず、依存しない修正を完了させます。反対に、隔離や利用者変更の保全を確認できない操作は実行せず、対象と必要条件を示します。

## 2. 受け取るものと現在の状態

Ubuntu側の作業ソースは [/home/tn/projects/aidev](/home/tn/projects/aidev) です。GitHubの連携先は [tsutomu-n/aidev](https://github.com/tsutomu-n/aidev)。Windows上のclone先は未確認です。本文のUbuntu絶対パスは作成元の位置を表し、ファイルリンクはclone内で辿れる相対リンクを使います。Windowsで実行するときはGit rootから絶対パスを解決してください。

| 項目 | 引き継ぎ時の根拠と状態 |
|---|---|
| ソース版 | 0.2.0。Windows対応候補の実装がある |
| Ubuntu回帰テスト | Python 3.13.7で42件中40件成功、Windows専用junctionとW-01 native cmd testの2件skip |
| W-01〜W-03 | source修正済み、判定CODE_READY_CI_PENDING。Windows 11実機受入は未実施 |
| Windows API・cmdランチャー | 修正前CIのWindows 2構成でW-01 native cmd・junction・排他・子孫終了が成功。Windows 11実機は未確認 |
| 実provider | Windowsでの導入・解析・更新・接続は未確認 |
| GitHub Actions | [修正前CI](https://github.com/tsutomu-n/aidev/actions/runs/35083256979) はUbuntu 2構成成功・Windows 2構成失敗。fixtureルート正規化後の4構成は未確認 |
| 公開元のbase commit | `238c0f3d6312915a8bc8c48784b309b21463eaa8`。このcommitだけではWindows対応差分は入らない |

既存のWindows操作案は [/home/tn/projects/aidev/WINDOWS.md](WINDOWS.md)、実装契約は [/home/tn/projects/aidev/TECHNICAL.md](TECHNICAL.md)、検証状態は [/home/tn/projects/aidev/STATUS.md](STATUS.md) にあります。操作案より、この資料の既知不具合と修正順序を先に確認してください。

## 3. Windows側へcloneして内容を照合する

受け渡しbranchは `feat/windows11-handoff` です。**送付側がpushを確認して伝えた完全なcommit hashと、下記branchの内容を照合してcloneします。** 資料だけでなく、0.2.0の実装・追加テスト・CIも同じbranchに含める必要があります。公開後もmainへのmergeやrelease公開は別です。

公開する側は、作業一式と受領manifestを同じcommitへ含め、push後の完全なcommit hashを受け取る側へ伝えます。base commitや版表示だけでは受領確認になりません。送付する具体的な一覧は [/home/tn/projects/aidev/WINDOWS_HANDOFF_MANIFEST.json](WINDOWS_HANDOFF_MANIFEST.json) にあります。

WindowsのPowerShellで、clone先の親フォルダーを開きます。次のブロックは外部コマンドの失敗時に停止し、既存の同名フォルダーを上書きしません。

```powershell
$ErrorActionPreference = 'Stop'
$AidevExpectedHead = (Read-Host '送付側から受け取った完全なcommit hash').Trim()
if ($AidevExpectedHead -notmatch '^[0-9a-f]{40}$') { throw '完全なcommit hashが必要です' }
$AidevRemote = @(git ls-remote --heads https://github.com/tsutomu-n/aidev.git refs/heads/feat/windows11-handoff)
if ($LASTEXITCODE -ne 0 -or $AidevRemote.Count -ne 1) { throw '引き継ぎbranchを取得できません' }
if (($AidevRemote[0] -split '\s+')[0] -ne $AidevExpectedHead) { throw '送付側のcommitとremoteが一致しません' }
if (Test-Path -LiteralPath 'aidev') { throw '既存フォルダーを保全し、別のclone先を選んでください' }
git clone --branch feat/windows11-handoff --single-branch https://github.com/tsutomu-n/aidev.git aidev
if ($LASTEXITCODE -ne 0) { throw 'clone失敗' }
$AidevSource = (Resolve-Path -LiteralPath 'aidev').Path
Set-Location -LiteralPath $AidevSource
$AidevReceivedHead = (git rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $AidevReceivedHead -ne $AidevExpectedHead) { throw 'cloneしたcommitが一致しません' }
Get-Content -LiteralPath (Join-Path $AidevSource 'AGENTS.md') -Encoding utf8
Get-Content -LiteralPath (Join-Path $AidevSource 'WINDOWS_HANDOFF.md') -Encoding utf8
```

次に、自分で確認したPython 3.11以降の実行ファイルを絶対パスで指定します。未確認の `py` / `python` をrepo内から名前だけで実行することは、W-01の検証済み対策になりません。

```powershell
$AidevPython = (Read-Host '確認済みPython 3.11以降のexe絶対パス').Trim()
if (-not [IO.Path]::IsPathRooted($AidevPython) -or -not (Test-Path -LiteralPath $AidevPython -PathType Leaf)) { throw 'Python実体を確認してください' }
& $AidevPython -X utf8 -B (Join-Path $AidevSource 'tools/windows_handoff.py') verify --expected-head $AidevExpectedHead
if ($LASTEXITCODE -ne 0) { throw '受領内容が一致しません。manifestを更新せず原因を確認してください' }
```

`delivery_verified=true` が受領条件です。manifestはUTF-8テキストのCRLFをLFへ正規化して照合し、Git for Windowsの改行変換を許容します。他の変更は一致しません。manifest単独は署名ではないため、送付側のcommit hash、cleanなGit状態、必要ファイルのGit追跡も確認します。**受領時に `manifest` サブコマンドを実行して不一致を消してはいけません。**

修正開始後はHEADと差分が受領時から変わるため、受領時のJSONを残します。内容一致は実機動作の証明ではありません。

## 4. Codexに渡す依頼文

cloneしたrepoを作業場所としてCodexを起動し、以下を依頼してください。これはWindows側での実装依頼文です。

```text
このrepoのaidevをネイティブWindows 11で使える状態へ仕上げてください。
まずGit rootとHEAD、未commit差分、適用されるAGENTS指示、OSとPython実体を確認してください。
Git rootからAGENTS.mdとWINDOWS_HANDOFF.mdを読み、受領検査の結果と未修正項目を確認してください。
既知不具合の再現にはtools/windows_handoff.py reproduceを使えます。修正前のexit 1を隠さないでください。
Ubuntuでの過去の成功や資料の記載を、Windows実機での成功に読み替えないでください。

W-01、W-02、W-03を再現可能なテストで確認し、修正と検証まで実行してください。
起動・ロック・Job Objectの実装方式は固定せず、不変条件を満たす最小の修正を選んでください。
その後、Windowsの排他ロック、Job Object、導入・更新・復旧、Unicodeパスを確認してください。
指定版providerの導入と実解析は、この作業専用の隔離した検証環境で進めてください。
既存のprovider、実HOMEの登録、通常利用のaidev、他repo、永続PATHやCodex設定を無断変更しないでください。
外部LLM送信・課金・credential変更・Git公開は、この依頼に含めません。

Ubuntuとの互換性を保ち、既存差分と利用者データを保全してください。
実測で必要性が分かった範囲の修正を行い、不要な全面作り直しやprovider版の安易な変更は避けてください。
テストfixture、Windows実機、実provider、Codex接続の結果を分けて報告してください。
利用者の接続確認や追加許可が必要な部分は未確認として残し、独立して進められる実装は完了させてください。
最終的にREADME、Windows操作手順、STATUS、この引き継ぎ資料を最終実装と検証結果に合わせて更新してください。
commit・push・PR・merge・releaseと通常利用環境への導入は、別途指示があるまで実行しないでください。
```

## 5. 実行できる再現手順と既知の不具合

受領確認後、通常利用環境へインストールする前に実行します。

```powershell
& $AidevPython -X utf8 -B (Join-Path $AidevSource 'tools/windows_handoff.py') reproduce
$AidevReproExit = $LASTEXITCODE
if ($AidevReproExit -eq 1) { Write-Host '不具合を再現。JSONのFAILを修正対象として扱います' }
elseif ($AidevReproExit -eq 2) { Write-Host '未検証または実行条件のエラー。JSONの理由を確認します' }
elseif ($AidevReproExit -ne 0) { throw '再現ツール自体の失敗' }
```

[/home/tn/projects/aidev/tools/windows_handoff.py](tools/windows_handoff.py) は一時source・一時導入先だけを使います。実HOMEへの導入、provider実行・ダウンロード、承認登録、Git変更は行いません。WindowsではW-01用に一時repo内の無害な同名コマンドを使い、呼び出されたかをmarkerで確認します。W-02はロック前の競合を注入し、W-03はsource検証失敗とrelease準備後の失敗を別々に注入します。

source修正後のUbuntu fixtureではW-01が `UNVERIFIED`、W-02・W-03-source・W-03-publishが `PASS` です。W-01はWindows限定unit testで実際の`.cmd`を起動し、cwdの偽`py`とPATH上の偽`python`を使わないことを確認します。W-03-publishはrelease準備後の例外ではなく、実際のentry公開renameを注入します。remote CI成功までこのツールだけで全受入完了にはしません。


### W-01：ランチャーが起動Pythonを固定していない（優先度高）

対象は [/home/tn/projects/aidev/install.py](install.py) の `windows_launcher()` と `install()` です。裸の `py -3` は廃止し、インストーラー自身で実行中Pythonの絶対パスと3.11以降を検証し、release manifestとUTF-8 cmd launcherへ固定します。cmdはcode pageを退避・切替・復元し、引数と終了コードを保全します。[Microsoftのpath仕様](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/path)

根拠の区分：source fixtureでlauncher bytesとmetadataを確認。Windows実機cmd再現は未実施です。

修正案：導入時に検査したPython実体を、実行時にも明示的に使います。ランチャーやPython選択をカレントディレクトリ/PATHの探索へ戻さない設計にしてください。Python 3.11以降という要件、空白・日本語を含むパス、引数の引用、終了コードの伝播、旧releaseの保持を保ちます。新しいexeや依存packageの追加を先に決める必要はありません。

受入：一時repo内に無害な同名コマンドを置いても起動されないこと。複数Pythonがある環境やPATH変更後でも検査済みのPythonを使うこと。Pythonがなくなった場合は、別の未確認Pythonへ切り替えず明確に停止すること。テストで実行中の `sys.executable` と版を確かめ、matrix指定版とランチャーの実体が食い違わないこと。

### W-02：初回導入の競合で管理外コマンドを上書きする（優先度高）

対象は [/home/tn/projects/aidev/install.py](install.py) です。所有判定はロック取得後へ移し、release準備後と公開直前にentryを再照合します。初回公開は存在しない宛先だけへ行い、更新時は旧entryを専用退避先へ保持してから空の宛先へ公開します。

再現条件：Windowsレイアウトを一時ディレクトリに用意します。`directory_lock()` の取得直前に、別の処理が入口へ利用者のコマンドを書き込みます。現行コードでは `existed=False` のまま、そのコマンドを初期値として受け入れ、後で上書きします。Ubuntu上でWindowsのファイル処理分岐を使った再現試験では `USER_COMMAND_OVERWRITTEN=True` でした。Windows APIそのものの再現結果ではありません。

修正案：所有確認と導入済み/未完了の判定はロック取得後の現状で行います。入口切替直前にも変更を検出します。協調ロックを使わない外部writerに対して保証する範囲を明確にし、単にロックがあることを保全の証明にしないでください。

受入：初回・更新時とも、管理外コマンドや並行した利用者変更を保全して停止すること。事前確認からロック取得まで、release準備中、入口切替前の競合をテストすること。二重installerでも不完全なreleaseへ入口を切り替えないこと。

### W-03：初回導入が途中で失敗すると再実行で復旧できない（優先度中）

対象は [/home/tn/projects/aidev/install.py](install.py) の `stage_release()`、`active_release()`、`install()` です。installer所有の `installation-progress.json` をrelease準備前から記録し、完成releaseとentry公開段階を区別します。

再現条件：一時sourceのPythonファイルに構文エラーを入れて初回導入します。release用ディレクトリ作成後に `SyntaxError` となります。sourceを修復して再実行すると通常実行は「既存配置あり」、`--upgrade` は「管理外コマンド」で停止します。Ubuntu上のWindowsファイル処理分岐で再現済みです。source修復は一時fixture内でのみ行い、実sourceを壊して再現しないでください。

修正案：未完了の導入、正常な管理release、管理外の既存配置を区別します。所有権が確認できる未完了処理だけを安全に再試行できるようにします。既存データを削除して通す処理、無条件の上書きや広いcleanupは不可です。

受入：source検証失敗、コピー失敗、入口の切替失敗、中断後の再試行が可能なこと。管理外の配置はそのまま保全されること。アップグレード失敗時は以前の正常releaseが利用可能なこと。エラーを整形して終了コードを返し、未完了状態を成功として報告しないこと。

## 6. 工程ごとの進め方と判定

1. **環境と差分の確認。** Windows 11のedition/build、PowerShell、Python実体/版、Git、uv、HEADを記録します。既存writer・dirty treeを確認し、必要な実行ツールだけを調べます。起動前にランチャーを読んでください。
2. **既存テストをWindowsで実行。** 実providerなしで現状の失敗を把握します。symlink権限がない場合のskipは許容しますが、junction・ロック・Job Objectの失敗をskipで隠さないでください。
3. **W-01〜W-03の回帰テストと修正。** Windowsの再現テストと、Ubuntuでも実行できるファイル操作テストを適切に分けます。全体テストの件数を増やすこと自体は目的にしません。
4. **OS固有処理の受入。** 別プロセス間の排他、強制終了後のロック再取得、timeout・Ctrl+C・親の終了後に残る孫プロセス、Job所属失敗時の停止を確認します。空白・日本語、junction、複数Python、管理者権限なしの起動を扱います。
5. **専用環境で実providerの受入。** 次節の順で、依存導入から実索引と再更新まで確認します。実HOMEや既存環境を使わずに検証できる隔離先指定が足りなければ、明示optionまたは検証用子プロセス内だけの環境指定を検討してください。OS全体の環境設定は変更しません。
6. **Ubuntuの回帰と資料更新。** Ubuntuで実行できるCIまたは作業環境で確認します。Windowsだけで確認した場合はUbuntu未確認と書きます。既知不具合の解消根拠、実装・利用手順・検証表を最終状態に合わせます。

Windowsの既存テストコマンドは、cloneしたGit rootで実行します。

```powershell
& $AidevPython -X utf8 -B -W error::ResourceWarning -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw '回帰テスト失敗' }
```

3.11/3.13それぞれの試験では `$AidevPython` に対応するPythonの絶対パスを明示してください。ランチャーのPython固定が直った証拠に、このコマンドだけを使ってはいけません。

GitHubの `windows-latest` はWindows 11端末での検証と同一ではありません。CIのOS実体を記録し、Windows 11実機の結果を別に残します。

| 工程 | 進める条件 | 問題がある場合 |
|---|---|---|
| 受領 | expected HEAD・内容・追跡・cleanが一致 | mainへの代替やmanifest再生成はしない |
| 不具合修正 | 再現→修正後の保全/復旧を確認 | 再現不能の理由を記録し、未確認をPASSにしない |
| 実provider試験 | 全保存先が専用環境に限定される | 隔離を先に実装し、実HOMEで試さない |
| Codex接続 | 指定版providerと受入repoが準備済み | 新規セッション操作を明示し、他の修正は継続 |
| 通常利用への反映 | 指定対象・backup・復旧案を利用者が確認 | 隔離受入までの成果を保持して待つ |

## 7. 実providerとCodexの受入

### 対象環境と隔離

Windows 11のedition/build・CPUアーキテクチャ・PowerShell版を記録します。x64で通ってもARM64へ一般化しません。まずローカルディスク、通常権限、空白・日本語を含むパスで受け入れ、UNC/ネットワーク共有・OneDrive・長いパス・追加アーキテクチャは実測した範囲だけ対応表へ記録します。

専用検証ルート内に、provider環境、導入先、承認登録、受入repo、ログを分けます。**現行CLIには任意の隔離先を指定する統一optionがありません。** mockでの保存先差替えを実provider試験にもそのまま使えるとはみなしません。Windows側で保存先を明示する最小の実装または子プロセス用ヘルパーを用意し、実際の解決先を確認してから実providerを動かします。新しいoption名はWindows側の設計で決め、未実装optionを実行手順に書かないでください。

provider自身が使うcache、config、言語サーバーの保存先も確認します。登録先だけの差替えでは隔離完了ではありません。既存の実HOME・台帳・PATH・provider環境のうち影響しうる既知の設定は前後で比較し、全HOMEを再帰的に走査・記録しません。隔離先を削除して完了にせず、証拠と復旧に必要な内容を先に保持します。

### providerと既知のコードによる確認

| provider | 指定package | 必要版 |
|---|---|---|
| Serena | `serena-agent` | 1.7.0 |
| Graphify | `graphifyy` | 0.9.55 |
| CRG | `code-review-graph` | 2.3.8 |

専用Python環境へ指定版を導入し、導入不能ならOS・Python・package・エラーを記録して原因を切り分けます。版の定数だけを書き換えて回避しないでください。外部LLM、embedding、watcher、Git hookは使いません。必要な言語サーバーの取得は実providerの依存準備として識別します。

受入用repoには秘密や顧客コードを入れず、例えば次の関係を持つ小さなコードを用意します。ファイルの絶対パスはWindows側で確定した `$AidevFixture` を基準に解決します。

| fixtureのファイル指定 | 内容 | 期待する照会 |
|---|---|---|
| `Join-Path $AidevFixture 'pricing.py'` | `add_tax(amount)` が `amount + 10` を返す | 関数定義を指せる |
| `Join-Path $AidevFixture 'quote.py'` | `from pricing import add_tax` で `add_tax(100)` を呼ぶ | 呼出し元と依存関係を特定できる |
| `Join-Path $AidevFixture 'fee.ts'` | `export function addFee(value: number) { return value + 5; }` | TypeScript定義を指せる |
| `Join-Path $AidevFixture 'checkout.ts'` | `import { addFee } from './fee'; export const total = addFee(100);` | TypeScriptの参照元を特定できる |

解析前にPythonの戻り値110を確認します。初回受入後にPython側の10を20へ、TypeScript側の5を7へ変更し、内容変更の検出・再索引・該当sourceを用いた照会を確認します。全providerが同じ種類のedgeを出すと仮定せず、各providerの実schemaと能力に応じて期待する定義・参照・構造を照合します。単なるノード数の非ゼロだけでは合格にしません。

順序は `setup` 検査 → 専用の検証登録先への明示登録 → `init --dry-run` → `init` → `doctor --json` → コード編集 → 古い索引の検出 → 再 `init` → 再 `doctor` です。正常な再実行で不要な書換えが起きないこと、失敗時のログとbackupがGitから除外されることも確認します。

`setup --approve` は実HOMEの既存登録へ向けて自動実行しません。隔離した検証登録はfixtureの一部として扱い、通常利用するproviderの承認とは区別します。

最後に受入用repoで新規Codexセッションを開き、MCP接続と定義・参照・影響照会を確認します。現在のセッションから接続を検証できない場合は、必要な利用者操作を短く示して `未確認` とします。`LOCAL_READY` や設定ファイルの存在だけで接続を成功扱いしません。

## 8. 完了条件と証拠の残し方

コード判定はCODE_READY_CI_PENDINGです。W-01のnative evidenceには、生成された`.cmd`を実行して子プロセスのPython絶対パスとmatrix指定版を照合するWindows限定testのPASSを使用します。Ubuntu/Windows × Python 3.11/3.13の4構成のCI成功後にREADY_FOR_MAINを判定します。実providerとCodex MCPはmain merge gateではなく、以下のWindows 0.2.0完全受入の別項目です。現在はUNVERIFIEDを維持します。

| 確認対象 | 完了とする証拠 |
|---|---|
| W-01 | 検査済みPythonの固定、repo内同名コマンドの非実行、Unicodeパスと終了コードの試験結果 |
| W-02 | 指定した競合を再現し、管理外コマンド・利用者変更を保全する回帰テスト |
| W-03 | 途中失敗後の安全な再試行と、既存release保全の回帰テスト |
| Windows 11 | 実OS/build・Python実体と、ロック・Job Object・導入/更新/復旧の実測結果 |
| 実provider | 指定版3providerで設定・初期索引・編集後更新・診断を通した結果 |
| Codex | 新規セッションのMCP接続と実コード照会。実行できなければ未確認のまま残す |
| Ubuntu | 既存台帳経路・導入・回帰テストの確認。未実行なら未確認として報告 |
| 文書 | README・Windows手順・STATUS・本資料が最終実装と一致している |

全項目が揃うまで「Windows 11受入完了」とはしません。ただし接続確認や環境導入に阻害要因がある場合も、独立して完了できるコード修正と検証は進めます。

公開してよい要約は [/home/tn/projects/aidev/STATUS.md](STATUS.md) と本資料へ反映します。ローカルの詳細記録は、Windows側で実測したGit rootから `Join-Path $AidevSource 'verification/windows11'` で解決する保存先へ置けます。この生成物は既存のGit除外対象です。秘密、トークン、顧客コード、不要な環境変数一覧を記録・公開しないでください。

要約には開始時と終了時のHEAD、dirty差分の有無、OS/build/architecture、Python実体/版、provider版、実行コマンドと終了コード、期待結果との一致、skipの理由、未確認・阻害要因を残します。未commit差分で試した場合は、HEADだけを証拠にせず、試したsourceのmanifestと差分の識別も残します。

受入記録の最小書式例です。これは記録例であり、キーをPASSへ書き換えるだけで受入を自動判定する仕組みではありません。

```json
{
  "schema_version": 1,
  "tested_head": null,
  "tested_source_manifest_sha256": null,
  "working_tree_clean": null,
  "os_build": null,
  "architecture": null,
  "python_executable": null,
  "python_version": null,
  "checks": [
    {"id": "W-01", "status": "UNVERIFIED", "command": null, "exit_code": null, "evidence": null},
    {"id": "W-02", "status": "UNVERIFIED", "command": null, "exit_code": null, "evidence": null},
    {"id": "W-03", "status": "UNVERIFIED", "command": null, "exit_code": null, "evidence": null},
    {"id": "windows11_native", "status": "UNVERIFIED", "evidence": null},
    {"id": "providers_real", "status": "UNVERIFIED", "evidence": null},
    {"id": "codex_mcp", "status": "UNVERIFIED", "evidence": null},
    {"id": "ubuntu_regression", "status": "UNVERIFIED", "evidence": null}
  ]
}
```

各statusは `PASS` / `FAIL` / `UNVERIFIED` / `BLOCKED` とし、BLOCKEDには不足する実行条件・次に必要な操作を追記します。履歴としてのUbuntu36件成功、Windowsでの今回の成功、通常利用への導入を同じ記録として扱わないでください。

## 9. 完了時の引き渡しと通常利用への反映

Windows側の完了報告には、変更した内容、W-01〜W-03の前後結果、実機と実providerの結果、未確認事項、通常利用への導入手順を含めます。既知不具合を解消したらSTATUSの記述を更新し、この資料にも解消根拠を残します。

sourceを確定して必要なテストが通った後、次を実行して受領inventoryを更新します。新しい必要ファイルを追加した場合は補助ツールの `FILES` にも含めます。

```powershell
& $AidevPython -X utf8 -B (Join-Path $AidevSource 'tools/windows_handoff.py') manifest
if ($LASTEXITCODE -ne 0) { throw 'manifest生成失敗' }
& $AidevPython -X utf8 -B (Join-Path $AidevSource 'tools/windows_handoff.py') verify
if ($LASTEXITCODE -ne 0) { throw '内容照合失敗' }
```

修正後の `verify` 単独は内容検査です。commit・pushの許可を得て公開した後に、送り先で `verify --expected-head` を実行して引き渡しを確認します。勝手なcommit/pushや履歴書換えでcleanにしないでください。開発用の引き継ぎ資料・再現ツールはsourceの成果物です。インストール先にも必要な案内だけは、同梱文書のリンクから参照できるよう確認します。

通常利用への導入は、利用者が指定した対象への別工程です。現在の入口・release・provider登録を確認し、保持するbackup、失敗時に戻す正確な対象、更新後のversion/doctor確認と新規Codexセッションの手順を提示してから実施します。rollback/uninstallが未実装のままなら、存在しないコマンドを案内しません。隔離環境内のMCP設定は絶対パスを含むため、そのまま通常repoへコピーしません。

## 10. 必須修正の後に検討する改善

- provider登録・Python・解析ルールの変更を索引の再構築判定へ反映する。現行のsource fingerprintには実行環境の識別が含まれません。
- 指定版が導入済みなら `uv tool dir` から登録候補を表示する補助を検討する。検出と承認を分け、自動承認にはしない。
- 導入・更新・復旧のエラーを、利用者が取れる具体的な次の操作へつなげる。

これらは改善候補です。W-01〜W-03と実機受入に必要な修正を優先し、理由なく作業範囲を拡大しないでください。
