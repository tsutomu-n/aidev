# Windows 11で導入して使う

aidev 0.2.0にはWindows用のロック、子プロセス管理、インストーラーとprovider登録機能があります。WSL・Ubuntuの承認台帳・管理者権限・シンボリックリンク作成権限を前提にしません。**この変更を作成した環境はUbuntuです。Windows実機と実providerを通した受入は未確認です。** 以下は実機で確認しながら進める手順です。

**開発引き継ぎ：既知の導入不具合3件が未修正です。** Windows側で仕上げる場合は、ソースに含む [/home/tn/projects/aidev/WINDOWS_HANDOFF.md](WINDOWS_HANDOFF.md) の依頼文・修正順序から始めてください。以下は修正後に照合する操作案であり、現行版を通常利用環境へ導入する前に既知の問題を解消します。

## 1. 必要なものを確認する

Windows 11、Python 3.11以降、Python Launcherの `py -3`、Git、uvを用意します。provider用Pythonは既存基盤と同じ3.13を指定します。PowerShellで次を確認してください。

```powershell
py -3 --version
git --version
uv --version
```

この文書の変数に入るパスは、そのWindows端末で取得する絶対パスです。Ubuntuの作業パスをWindowsへ転記しません。

## 2. aidevを配置する

**0.2.0のソースを受け取ったフォルダー**をPowerShellで開いて実行します。ソース変更だけでは既存インストールは更新されません。GitHubへ未公開の変更を使う場合、古いmainのcloneだけではこの機能は入りません。

```powershell
$AidevSource = (Get-Location).Path
py -3 -X utf8 (Join-Path $AidevSource 'aidev.py') --version
py -3 -X utf8 (Join-Path $AidevSource 'install.py')
$Aidev = Join-Path $env:LOCALAPPDATA 'aidev\bin\aidev.cmd'
& $Aidev --version
```

期待する表示は `aidev 0.2.0` です。入口は設定値 `%LOCALAPPDATA%\aidev\bin\aidev.cmd`、releaseと同梱文書は `%LOCALAPPDATA%\aidev\releases` に置きます。実際の配置先はインストーラーにも表示されます。既存の管理対象を更新する場合だけ、インストールコマンドに `--upgrade` を付けます。旧releaseの保持と利用者変更の保全を意図した設計ですが、現行候補には導入時の競合と途中失敗後の復旧に不具合があります。開発引き継ぎのW-02/W-03を先に解消してください。

次は**現在のPowerShellだけ**のPATH設定です。永続PATH・レジストリ・PowerShell実行ポリシーはインストーラーでは変更しません。

```powershell
$env:PATH = "$(Split-Path $Aidev);$env:PATH"
aidev --version
```

## 3. providerを準備する

指定版の既存環境がある場合は再導入せず、次節へ進みます。未導入の場合のコマンドは次のとおりです。これらはインターネットからpackageと依存関係をダウンロードします。aidev自身は自動実行しません。

```powershell
uv tool install --python 3.13 'serena-agent==1.7.0'
uv tool install --python 3.13 'graphifyy==0.9.55'
uv tool install --python 3.13 'code-review-graph==2.3.8'
```

導入が失敗したら、そのproviderの出力を確認します。別の版に置き換えて成功扱いにはしません。Python言語サーバー、TypeScript向けNode.js等の追加要件と、Windowsでのprovider内部処理は各providerの検証対象です。

uvはWindowsでは公開コマンドをコピーして配置します。その隣にproviderのPythonがあるとは限りません。専用環境の配置先を `uv tool dir` で取得します。[uv公式のtool管理](https://docs.astral.sh/uv/concepts/tools/)

## 4. provider環境を検査・登録する

```powershell
$AidevTools = (uv tool dir).Trim()
$AidevSetup = @(
    'setup',
    '--serena-python', (Join-Path $AidevTools 'serena-agent\Scripts\python.exe'),
    '--graphify-python', (Join-Path $AidevTools 'graphifyy\Scripts\python.exe'),
    '--crg-python', (Join-Path $AidevTools 'code-review-graph\Scripts\python.exe')
)
& $Aidev @AidevSetup
```

`PLAN` と3providerの実行ファイル・Python・版が表示されたら、意図した環境か確認します。この段階では指定した実行ファイルの版・package metadataを検査しますが、登録ファイルは作りません。uv以外の専用venvを使う場合は、各 `--*-python` にその環境のPython絶対パスを指定してください。同じ `Scripts` フォルダーに対応するproviderのexeが必要です。

表示された3providerをこの利用者のaidevで使うことを承認する操作は次です。

```powershell
& $Aidev @AidevSetup --approve
```

`REGISTERED` と、実際の登録ファイルの絶対パスが表示されます。登録先の設定値は `%LOCALAPPDATA%\aidev\foundation.json` です。実行ファイルとPythonのhash、必要な版を保存します。実行ファイルが変わった場合は停止し、再検査後に `--approve --replace` で登録を更新します。元の登録内容はbackupに残ります。

この登録はaidev専用です。Ubuntu共通台帳、Codexの信頼設定、他のSkillの能力台帳を変更・代替しません。旧台帳を持つUbuntuでは、専用登録がなければ従来の台帳確認を継続します。破損した専用登録がある場合は旧台帳へ自動的に切り替えません。

## 5. 対象repoを初期化する

解析したいGitリポジトリのルートでPowerShellを開きます。

```powershell
(Get-Location).Path
git rev-parse --show-toplevel
git status --short
aidev init --dry-run
aidev init
aidev doctor --json
```

`--dry-run` は設定変更予定の確認です。`init` がrepo設定と索引を作り、`doctor` の `LOCAL_READY` がローカル検査の通過です。登録されたSerena/CRGのexe絶対パスをMCP設定に記録するため、uvの公開コマンド用PATHへの依存を避けられます。既存の異なるMCP設定は上書きせず停止します。

次にそのrepoから新規Codexセッションを開き、MCP接続と実際の定義・参照・影響照会を確認してください。aidevは `codex_mcp: UNVERIFIED` を維持します。これをWindows実機受入の成功と取り違えないでください。対象repoを別端末へ移した場合、絶対パスを含む設定と登録を実機に合わせて再確認します。

## 6. Windows実機での検証

ソースを置いたフォルダーで、providerの実解析をしない回帰テストを実行できます。テストが作るrepo・インストール先・登録先は一時フォルダーです。

```powershell
py -3 -X utf8 -B -W error::ResourceWarning -m unittest discover -s tests -v
```

Windowsでは実際の排他ロック、Job Objectによる孫プロセス終了、junction拒否、空白・日本語を含む配置先、cmdランチャー、導入・更新・利用者変更保全を検査します。symlink作成権限がない場合はsymlinkだけのテストをskipし、管理者権限不要のjunctionテストは実行します。GitHub ActionsにもUbuntu/Windowsの同じテストを用意していますが、workflow追加だけでは実行済みになりません。

このテストのprovider部分はfixtureです。実providerでの導入・`setup`・`init`・編集後の再初期化・`doctor`・Codex照会の成功を別途確認してください。Job Objectへの所属に失敗する制限環境ではproviderを起動せず停止します。[MicrosoftのJob Objects仕様](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)

## 制限と復旧

- ネットワーク共有上のrepo、異なるユーザー・セッションから同じrepoを同時更新する運用は受入対象外です。通常の利用者アカウントのローカルディスクで使ってください。
- WindowsのACLはOSの継承設定を使います。Unixの `0700` と同等の権限制御を `chmod` が提供するという意味ではありません。共有ディレクトリへの配置は避けてください。
- 設定先・出力先のjunction、symlink、その他のreparse pointは拒否します。OneDrive等のreparse pointを含む配置で停止したら、通常のローカルディレクトリを使用します。
- タイムアウト・中断では子プロセス一式を終了し、providerログをrepo内に保存します。Jobへの所属前はbootstrapが待機し、providerが先に子を生成する競合を防ぎます。
- `py` が見つからない場合はPython Launcherの導入を確認します。`py -3` の選択するPythonは3.11以降が必要です。
- 全3providerが前提です。1つだけ成功しても通常利用可能とは判定しません。自動承認、外部LLM呼出し、watcher、Git hook、自動commit/pushは追加していません。
