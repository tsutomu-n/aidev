# aidevの作業指示

## 開始時

- Windows対応・Windows引き継ぎを依頼された場合は、Git rootを確認し、その直下の `WINDOWS_HANDOFF.md` を先に読む。具体的な操作は今回の利用者依頼と実効権限に従う。
- このrepoはaidev本体。Ubuntu基盤一式のrepoではない。既存の共通台帳・provider・利用者repoを無断で移植・変更しない。
- Git状態と既存差分を確認し、現在のsource/testsを正とする。0.2.0という版や過去のgreenだけでWindows対応完了と判定しない。

## 開発と検証

- Python 3.11以降の標準ライブラリを基本とし、Ubuntuとの互換性を保つ。
- 現行の既知不具合はW-01〜W-03。修正時は再現ケースと失敗時の保全を確認する。
- `tools/windows_handoff.py verify` は受領内容の確認、`reproduce` は隔離fixtureでの既知不具合再現。後者のexit 1は修正前に期待される結果で、隠さない。
- 既存テストはGit rootで `python -X utf8 -B -W error::ResourceWarning -m unittest discover -s tests -v`。`python` は実測したPython絶対パスへ置き換える。
- fixture試験、Windows API試験、実provider、Codex接続、通常利用環境への反映を分けて報告する。
- 詳細ログ・生成物は既存の `verification/` 除外を使う。共有する要約には秘密・顧客データを含めない。

## 完了時

- 実装に合わせてWindows手順、STATUS、引き継ぎ資料を更新する。必要な確認後に `tools/windows_handoff.py manifest` で受領用inventoryを更新する。
- manifest更新は検証の代わりではない。受領前にmanifestを作り直して不一致を隠さない。
- 公開や通常利用環境への反映は、今回の利用者依頼で許可された対象・範囲に限る。
