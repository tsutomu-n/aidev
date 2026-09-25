# Ubuntu通常環境の受入済みGitスナップショット

判定は **UBUNTU_NORMAL_ACCEPTED**。Ubuntu 25.10 x86_64 / Python 3.14.3の当該環境における通常導入と合成fixtureの受入記録です。導入・受入は完了し、この文書の保存時には再インストール、環境調査、実LLM再試験を行っていません。

## Gitと導入物の対応

実装・回帰test・パッチ・qualification・運用文書はcommit `01c3bd5372a2566ff3e7fcd421d4de26af1efacb` に保存されています。導入前HEAD `e1173234ffbfa51d2b2fa8cfa5100550ff127ca7` だけでは完成状態を表しません。既存commitには別件の [/home/tn/projects/aidev/docs/FALLBACK_RESUME.md](FALLBACK_RESUME.md) も含まれます。この保存作業で追加したものではなく、既存履歴・内容を維持しています。

| 識別対象 | 保存済み値 |
|---|---|
| 実LLMを確認したrelease | `ceaf905fc016a8fdca25` |
| 最終導入release | `71b21028a1e02f1f0455` |
| runtime identity | `eed5176dea5da0b99fd40199b97476bde5bd6baf2ba885923438a6e191de1fca` |
| qualification SHA256 | `d2fc0a6d669f1183da3dd408ae6431e1e70c12f040784abad38293e16b427a8a` |
| 通常launcher | `/home/tn/.local/bin/aidev` |
| 最終launcher実体 | `/home/tn/.local/share/aidev/releases/71b21028a1e02f1f0455/aidev.py` |

両releaseの差分は配布文書5件のみで、Pythonコード・patch・qualification・依存hashは同一という受入記録です。Git保存時は最終receiptとcheckoutの配布15ファイルのhash一致を確認しました。通常環境の再診断や実LLMの独立再検証はしていません。

この文書と受領inventoryの追加は配布対象外です。通常releaseの再作成・切替は不要です。[/home/tn/projects/aidev/docs/STATUS.md](STATUS.md) の未commit等の記載とローカル原本は、受入実施時点の履歴として残します。現在のGit確定状態はこの文書とGit履歴で区別してください。

## 保存する検証要約

| 検証 | 受入時の結果 |
|---|---|
| Python全suite | 92件中90成功、Windows専用2skip |
| 旧3ファイル移行 | 既知hash照合・元ファイル保全・管理リンク化成功 |
| 変更・競合・失敗 | 利用者変更拒否、中断再開、復旧fixtureのbytes/modes/link先一致 |
| 移設後qualification | protocol、実Codex policy、OS拒否、MCP起動、中断復旧が全PASS |
| 初回／更新生成 | 各1回、実sessionの `gpt-6-astra / medium` を確認 |
| 再利用 | 同一入力・生成物だけのcommit後ともreused、ACP/app-server起動なし |
| 更新と内容 | source変更後stale検出、検索・読取り・主要記述のsource/tests/schema照合成功 |
| 保全 | 生成前後source差分0、監視対象の通常設定・依存保全、観測process残存0 |
| 最終doctor | TERRAIN_READY |

Windows実機・この変更に対するCI・別の利用者repoの初期化は未実施です。通常環境のrollback自体も未実施。生成contextは圧縮packにない実装本体・test coverageを未確認として残します。HTTPS内容・短命離脱processの完全捕捉は保証せず、shell sandboxはMCP・hooksの作用全体を防ぐものではありません。

## 再現に使うsourceと手順

以下は別途再現する際の手順であり、今回のGit保存作業では実行していません。新しい環境への導入・依存取得・実LLM送信は別途許可と検証が必要です。

1. 上記commitと本保存commitを含むcheckoutを使い、受領inventoryを期待する完全HEADで照合します。[/home/tn/projects/aidev/tools/windows_handoff.py](../tools/windows_handoff.py) の `verify --expected-head` は内容・Git追跡・clean状態を確認し、実機受入を代替しません。
2. Python 3.11以降の実体を確認し、Git rootで標準の回帰suiteを実行します。受入時に使用した実体でのコマンドは次のとおりです。

```sh
/home/tn/.local/share/uv/python/cpython-3.14.3-linux-x86_64-gnu/bin/python3.14 -X utf8 -B -W error::ResourceWarning -m unittest discover -s tests -v
```

3. Terrainのexact upstream `8d888ae13a6b1253406cac379c8eb30037c96862` と [/home/tn/projects/aidev/src/terrain-0.9.5-aidev.patch](../src/terrain-0.9.5-aidev.patch) を組み合わせます。build・focused tests・behavior smokeは [/home/tn/projects/aidev/tools/terrain_ci.py](../tools/terrain_ci.py) と [/home/tn/projects/aidev/docs/TERRAIN.md](TERRAIN.md) に従います。今回の導入では再buildせず既存binaryをコピーしました。
4. ACP 1.11.0の既存配布JSへ [/home/tn/projects/aidev/src/codex-acp-1.11.0-context.patch](../src/codex-acp-1.11.0-context.patch) を適用します。変更前entry SHA256は `3527bdaf90a219175c742576963e6d9e943e4ea5fbdbc3e04e7f57f9a9e11343`、変更後は `d38570bf20023bbf32f89b007bafee3f0af9fa34a0eab60b445955ee595ccbc0`。版表示だけでは受入済みとは扱いません。
5. 依存tree・固定Codex/Node・MCP入口は [/home/tn/projects/aidev/src/context-qualification.json](../src/context-qualification.json) に記録されています。この記録は当該端末の絶対パスとhashに結び付きます。別配置では全gateを別出力先で検証してからqualificationを発行し、手編集で起動拒否を迂回しません。
6. 別途実LLM受入を行う場合は、秘密のない新規fixture・同モデルとeffortで初回生成→同一入力再利用→生成物のみcommit後再利用→機能変更とstale確認→更新生成→検索・意味確認・最終doctorの順とします。生成前後source、実効権限、所有process終了を別々に確認します。Git保存だけのためにこの工程を繰り返す必要はありません。

Gitに含むのは実装・patch・回帰test・手順・要約です。実バイナリ、依存package一式、認証情報、生ログ、実機用検証helperと復旧前ファイルはローカル保全のままです。したがってclone単独で別端末のqualificationや通常環境復元まで完結する配布キットではありません。

## ローカル証拠と復旧

原本は [/home/tn/projects/aidev/verification/normal-install-20260922T114000Z](/home/tn/projects/aidev/verification/normal-install-20260922T114000Z) に保全します。Git追跡対象外であり、cloneには含まれません。

- 受入原本：[/home/tn/projects/aidev/verification/normal-install-20260922T114000Z/RESULT.md](/home/tn/projects/aidev/verification/normal-install-20260922T114000Z/RESULT.md)
- 最終receipt：[/home/tn/projects/aidev/verification/normal-install-20260922T114000Z/final-install.json](/home/tn/projects/aidev/verification/normal-install-20260922T114000Z/final-install.json)
- 復旧前ファイル：[/home/tn/projects/aidev/verification/normal-install-20260922T114000Z/deployment-before](/home/tn/projects/aidev/verification/normal-install-20260922T114000Z/deployment-before)
- 復旧helper：[/home/tn/projects/aidev/verification/normal-install-20260922T114000Z/deployment.py](/home/tn/projects/aidev/verification/normal-install-20260922T114000Z/deployment.py)

復旧は切替後記録との一致を確認し、今回の入口・管理リンク・登録だけを戻す設計です。並行変更があれば停止し、依存や旧releaseを削除しません。今回のGit確定は復旧実行の指示ではありません。

## 最終配布sourceのSHA256

以下は最終receiptから転記し、Git保存時にcheckoutと照合した値です。署名ではありません。

| 配布source | SHA256 |
|---|---|
| [/home/tn/projects/aidev/src/aidev.py](../src/aidev.py) | `cc02bad6e198920ae683d463949c067e0c6ee981da71fc4ed3140d38a042da1e` |
| [/home/tn/projects/aidev/src/provider_probe.py](../src/provider_probe.py) | `60e678c549258bc309322cdf2661cb375ef32dcc90c4859803190f0dff894256` |
| [/home/tn/projects/aidev/src/provider_build.py](../src/provider_build.py) | `9a66675768ae52cc20a8735c615f33c108e2d5b61cb41b822701caa2f7b7134e` |
| [/home/tn/projects/aidev/src/platform_support.py](../src/platform_support.py) | `efd6e1dd80c332c39b09f4491c46f2104f9b5f14f5162e7dc65c07361b64728f` |
| [/home/tn/projects/aidev/README.md](../README.md) | `48407767ac97d0bb21a8b4f9205bd73a71212ae409b947f9c2f0f8b5865e71e0` |
| [/home/tn/projects/aidev/docs/USER_GUIDE.md](USER_GUIDE.md) | `8846fae07d739729402657d5515fe84b7a90da368af619aac3f14ea27340f8d7` |
| [/home/tn/projects/aidev/docs/TECHNICAL.md](TECHNICAL.md) | `c66888851ee509bd92ee94bf3f6661a0a07fc867538f0edc69ecfd86f4d387da` |
| [/home/tn/projects/aidev/docs/STATUS.md](STATUS.md) | `e01858ac07eb40f3e1bffb16f848a898c06b368299a92294ebb1fc841923d3d3` |
| [/home/tn/projects/aidev/docs/WINDOWS.md](WINDOWS.md) | `024c15ee5361f7c98ebba77e72bdadbe03fbbf2542d8cb88ad2a49066f96007d` |
| [/home/tn/projects/aidev/src/terrain_provider.py](../src/terrain_provider.py) | `57770d434ef03e45c754c06265dae464207ee8c9aabc743f149f8a352940d358` |
| [/home/tn/projects/aidev/src/terrain_runtime.py](../src/terrain_runtime.py) | `a23646f59c4ed073dd145c44d5ab5123de3a269d8c341aa63d89389c60b5667d` |
| [/home/tn/projects/aidev/src/terrain-0.9.5-aidev.patch](../src/terrain-0.9.5-aidev.patch) | `893efe60ec622ef6741e20d8a81c840124de60b823e842854c789ee9681f40c1` |
| [/home/tn/projects/aidev/docs/TERRAIN.md](TERRAIN.md) | `7f7cd26047ac1e8b0102c8efafd9546705b9d91e9be0eed3ac62727539ee7251` |
| [/home/tn/projects/aidev/src/context-qualification.json](../src/context-qualification.json) | `d2fc0a6d669f1183da3dd408ae6431e1e70c12f040784abad38293e16b427a8a` |
| [/home/tn/projects/aidev/src/codex-acp-1.11.0-context.patch](../src/codex-acp-1.11.0-context.patch) | `5b65e1905dffda01b0be9a00d7527156ed987fd42ae32051958ef9165837e883` |
