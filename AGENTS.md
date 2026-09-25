# aidevの作業指示

## 配置と根拠

- ソースcheckoutは `src/` にPython実装・patch・qualification、`docs/` に操作・仕様・状態文書を置く。導入済みreleaseはインストーラーが作る平坦な配置であり、checkoutの構造と混同しない。
- 現行実装・テスト・CLI引数を優先し、`docs/STATUS.md` の受入結果は記録時点の証拠として読む。source完了、通常環境への導入、Windows実機受入を別々に扱う。

## 開始時

- Windows対応・Windows引き継ぎを依頼された場合は、Git rootを確認し、その直下の `WINDOWS_HANDOFF.md` を先に読む。具体的な操作は今回の利用者依頼と実効権限に従う。
- このrepoはaidev本体。Ubuntu基盤一式のrepoではない。既存の共通台帳・provider・利用者repoを無断で移植・変更しない。
- Git状態と既存差分を確認する。0.2.0という版や過去のgreenだけでWindows対応完了と判定しない。

## 開発と検証

- Python 3.11以降の標準ライブラリを基本とし、Ubuntuとの互換性を保つ。
- W-01〜W-03は0.2.0で修正・CI確認済みのhistorical regression。関連修正時は再現ケースと失敗時の保全を確認し、Windows実機受入と区別する。
- `tools/windows_handoff.py verify` は内容一致とGit追跡・clean状態・期待HEADを区別する。`reproduce` は隔離fixtureでの回帰確認。修正前の再現失敗（exit 1）やWindows以外での `UNVERIFIED`（exit 2）を成功扱いしない。
- 既存テストはGit rootで `python -X utf8 -B -W error::ResourceWarning -m unittest discover -s tests -v`。`python` は実測したPython絶対パスへ置き換える。
- fixture試験、Windows API試験、実provider、Codex接続、通常利用環境への反映を分けて報告する。
- 詳細ログ・生成物は既存の `verification/` 除外を使う。共有する要約には秘密・顧客データを含めない。

## 完了時

- 挙動や受入条件の変更に合わせて `docs/WINDOWS.md`、`docs/STATUS.md`、引き継ぎ資料を更新する。受領対象の変更を検証した後に `tools/windows_handoff.py manifest` でinventoryを更新する。
- manifest更新は検証の代わりではない。受領前にmanifestを作り直して不一致を隠さない。
- 公開や通常利用環境への反映は、今回の利用者依頼で許可された対象・範囲に限る。

## Terrain 0.3.0

- Terrainの契約は `docs/TERRAIN.md`、現行実装は `src/terrain_provider.py` / `src/terrain_runtime.py`、upstream変更は `src/terrain-0.9.5-aidev.patch` とtestsを確認する。
- Terrainはderived navigation layer。重要な主張・編集対象はlive source/tests/schemasで確認する。既存3provider経路はoptional Terrainから独立させる。
- doctor/dry-runの書込み禁止、repo-local registry、明示的なbuild-contextとdownload承認、既存AGENTS・source・backupの保全を維持する。
- Rust patchはexact upstreamへ適用し、focused testsとbehavior smokeを必須にする。Windows CIとlive ACPをfixture成功から推定しない。
