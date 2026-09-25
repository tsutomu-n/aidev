# Codex → Devin フォールバック作業：再開用メモ

保存: 2026-09-22 19:49 JST / 作成: Devin Desktop内エージェント（Adaptive / SWE-2 Max）
状態: 作業中断。次回はこのファイルと `git status` から再開する。

> 注: 正本 `/home/tn/projects/aidev/.ai_memory/HANDOFF.md` は既存内容が
> `handoff_atomic_write.py --check-current` で
> 「pre-canonical v12 Open Items has an invalid `Next action`」と判定され、
> 更新していない（現行内容・backupとも保全）。このファイルは再開用の
> 非正本メモであり、canonical HANDOFF契約の代用品ではない。

## 目的

Codex CLI停止時に、保存済み情報とGit実物からDevinが既存変更を保全して
作業を再開・編集・検証・引継ぎできる最小構成を成立させる。
完全複製は目的ではない。

## 対象・現状

- host `ubuntu` / user `tn` / repo `/home/tn/projects/aidev`
- branch `main` / HEAD `5d5969c5e292e1f68072599c78515762474a50fa`
- 作業ツリー: このファイル（untracked）以外 clean
- Codex: `codex-cli 0.155.1`、`/home/tn/.local/bin/codex`
  → `/home/tn/.codex/packages/standalone/releases/0.155.1-x86_64-unknown-linux-musl/bin/codex`
  - shell function `/home/tn/.local/share/codex-easy/shell.sh` 経由
  - model `gpt-6-astra` / approval `never` / sandbox `danger-full-access`
- Devin CLI: `3000.11.1`、`/home/tn/.local/bin/devin`
  → `/home/tn/.local/share/devin/cli/_versions/3000.11.1/bin/devin`
  - **未ログイン**: `devin -p ...` は `Not logged in` で終了（認証は未承認）
- Devin Desktop内エージェント: このセッション。repoのread/edit/exec/testは動作

## 実施済み

### 診断（1回目セッション）

- CLI実体・版・shell wrapper・Codex実効設定（config.toml）を実測
- `skills-audit` 診断: Codex側disabled SkillがDevinでは `[user,model]` 公開
  （例: `skills-audit`, `find-skills`, `session-link`）
- Codex SessionStart hook（codex-continuity）はDevinへ継承されない
- Devinは `read_config_from` 未指定で全import有効。`/home/tn/.codex/.windsurfrules`
  （`rtk` prefix規則）や `/home/tn/.codex/.claude/skills/playwright-cli` が追加適用
- repoテスト: `/usr/bin/python3 -X utf8 -B -W error::ResourceWarning
  -m unittest discover -s tests -v` → 76 tests OK（Windows専用2件skip）

### 切り分け・隔離切替試験（2回目セッション）

- `respect_gitignore`: user-only、既定false、未設定 → CLI層は拒否しない
- `include_gitignored_files`: `@`補完のみ、アクセス許可とは別
- Desktop `read` ツールがgitignoreパスを独自拒否。
  `/home/tn/projects/aidev/.ai_memory` へのread scope承認後も同じ拒否
  → 拒否元は Desktop file tool層。CLI設定・OS権限ではない
- 独立CLI `devin rules list`: `global_rules [Windsurf]`（内容は空）と
  `AGENTS [Standard]`（repo `AGENTS.md`）の2件のみ。
  `.codex/.windsurfrules` は通常起動時には載らず、診断中の探索でlazy-loadされた
- 隔離試験: `/tmp/aidev-fallback-acceptance-20260922`（ローカルclone）
  - staged/unstaged/untrackedを用意→保全を確認
  - `aidev.py` VERSION を `0.3.0-fallback-acceptance` に変更（隔離内のみ）
  - `aidev.py --version` と focused unittest（1件）合格
  - 結果: `/tmp/aidev-fallback-acceptance-20260922/FALLBACK_HANDOFF.md`
- 元repo・Codex設定・共有Skill・既存HANDOFFは一切未変更

## 未実施・ブロック

- canonical HANDOFFの読取り: Desktop read層が拒否（scope承認でも解除されず）
- 独立 `devin` CLIセッション: 未ログインで開始不能 → `devin auth login` 要承認
- Codex復帰試験: 未実施（Codex可用性を前提にしない方針）
- OpenAI全体障害時の継続: 未成立。model公開Skill（`askpro`等）がCodex/OpenAIを
  再呼び出しし得る。repo-local configに個別Skill disableの文書化手段なし
- 既存HANDOFFの修復: 非対応形式のためhelperが拒否。修復方針の指示待ち

## 次回の再開手順

1. `/home/tn/projects/aidev` で `git status --short --branch` とHEADを確認
   （期待: `main`, `5d5969c`, untracked `FALLBACK_RESUME.md` のみ）
2. このファイルを読み、隔離試験結果
   `/tmp/aidev-fallback-acceptance-20260922/FALLBACK_HANDOFF.md` を確認
3. 承認を得たら `devin auth login` → 独立CLIで通常起動を確認
4. canonical HANDOFFの修復方針を確認（既存v12の `Next action` 修正 or 新規書換）
5. HANDOFF読取り→Git照合→隔離で変更・検証→保存→Codex復帰の受入を実施

## 運用注意

- `.ai_memory/` は `.gitignore` 対象。Devinのread toolは拒否するが、
  shell/validator経由での無断迂回はしない（ユーザー指示）
- `codex plugin list` はremote catalogへ接続する。外部通信を避ける診断では使わない
- Skill一括移動・共有Skill一括変更・wrapper新設は初期要件にしない
