# aidevの利用ガイド

## 何のために使うか

新しいrepoで「定義を探す」「参照を調べる」「構成や変更影響を調べる」ための解析準備をまとめます。アプリを作成する雛形生成器ではありません。共通基盤が導入済みのUbuntu環境で、対象repoを選んで使います。

検証状況は [https://github.com/tsutomu-n/aidev/blob/main/STATUS.md](https://github.com/tsutomu-n/aidev/blob/main/STATUS.md)、導入・更新コマンドは [https://github.com/tsutomu-n/aidev/blob/main/README.md](https://github.com/tsutomu-n/aidev/blob/main/README.md) にあります。

## 初回の操作

1. ターミナルで対象Git repoのルートへ移動します。`pwd` と `git rev-parse --show-toplevel` が同じ場所を示すことを確認します。未commit変更は `git status --short` で確認し、他の解析処理やコード編集と同時に実行しないでください。
2. `aidev --version`、続いて `aidev init --dry-run` を実行します。JSONの `files_to_change` が設定の変更予定です。これは生成予定の全索引・ログ一覧ではありません。既存設定との衝突があれば実行を止めて理由を表示します。
3. 対象とignoreを確認して `aidev init` を実行します。Serena、Graphify、CRGの順に解析します。大きいrepoでは `aidev init --timeout 1800` のように各処理の上限を指定できます。
4. `aidev doctor` を実行します。`LOCAL_READY` ならローカル準備は完了です。
5. 同じrepoルートで新しいCodexセッションを開き、接続を確認します。「この関数の定義と参照を調べて」「この変更の影響を確認して」など実際のコードについて照会し、sourceと一致するか確かめます。設定作成だけでこの確認まで完了とはしません。

任意の顧客データを自動で識別する機密検査ではありません。初期化前に対象repoのGit除外と解析ignoreを確認してください。repo外を指す既存解析ログのリンク等は安全検査で停止することがあります。

## 日常の操作

コードを編集した後、branchを切り替えた後、索引が疑わしいときは `aidev doctor` を使います。更新が必要と表示されたら `aidev init`、続いて `aidev doctor` を実行します。コード・解析設定・成果物が一致する場合は索引を再利用します。古い索引だけを狙って更新する指定はなく、更新時は3providerの処理を順に行います。

新しいcloneやworktreeでは既存の解析stateをコピーしません。その作業先で初期化してください。空repoは `WAITING_FOR_CODE` になり、対応コードを追加してから再度 `init` します。空repoに対する `doctor` は `NEEDS_INIT`（終了1）になり得ます。これは空repoの設定失敗を意味しません。

## 結果の読み方

| 表示 | 意味と次の行動 |
|---|---|
| `PLAN` | dry-run成功。変更予定を確認する |
| `LOCAL_READY` | ローカル設定と索引の照合成功。接続・実照会は別確認 |
| `WAITING_FOR_CODE` | 空repoの設定完了。対応コード追加後に再実行 |
| `NEEDS_INIT` | 設定・コード・索引に不足や変化あり。表示理由を確認してinit |
| `FAILED` | 初期化のstateに記録される失敗。ログと理由を確認 |
| `ERROR` | `doctor --json` のエラー応答。通常のinitエラーは標準エラーへ表示 |
| `codex_mcp: UNVERIFIED` | aidevは現在のCodex接続を検査していない |

終了コードは0が処理成功（空repo・dry-runを含む）、1がdoctorの要初期化、2がエラーです。

```sh
aidev doctor --json
```

JSONを前提にする処理でも終了コードを確認します。`init --json` はありません。

## 困ったとき

| 症状 | 対応 |
|---|---|
| `aidev` が見つからない | `$HOME/.local/bin/aidev` の存在とPATHを確認。未導入ならREADMEの初回手順 |
| Repoルートで実行するよう表示 | 表示された絶対パスへ移動する。配布フォルダーでは実行しない |
| CLI版・共通基盤のエラー | 必要版と台帳状態を確認。強制的な承認変更や自動更新で回避しない |
| 既存MCP・能力選択・Serena設定の衝突 | 既存設定の意図を確認。削除して通すのでなく個別導入を選ぶ |
| 未対応言語 | 自動設定はPython/JavaScript/TypeScript。混在repoも全言語の解析保証はない |
| timeout・途中失敗 | 表示されたローカルログを読む。原因修正後、必要ならtimeoutを延長して同じinitを再実行 |
| CRGのWALエラー | 利用中のサーバーを通常手順で終了して再確認。DBやWALを手動削除しない |
| 追跡済み生成物・リンクのエラー | 現在の管理方法を確認。aidevは追跡解除・リンク削除を自動実行しない |
| doctor成功なのに接続しない | 新規セッション側の接続と対象repoを確認。doctorはMCP health checkではない |

## backupと取り消し

`init` が表示する `backup:` の絶対パスには、変更した既存textと変更一覧があります。索引・コード全体のbackupではありません。`aidev rollback` / `aidev uninstall` は未実装です。

取り消す場合は処理を止め、backupの変更一覧・現在のファイル・初期化後の利用者変更を比較し、必要な設定だけを戻します。新規作成ファイルは元のtextがないためbackup一覧の `existed` を確認します。索引やログの削除、Gitの追跡解除まで一括で行わないでください。

ログはproviderごとに上書きされるので、再実行前に必要な失敗記録を確認します。再実行は途中からの厳密なcheckpoint再開ではなく、状態を再確認して必要な一連の処理をやり直します。
