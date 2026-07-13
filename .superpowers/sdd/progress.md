# 見開き分割改善 進捗台帳

Plan: docs/superpowers/plans/2026-07-13-spread-split-improvement.md
Branch: feature/spread-split-improvement
Base commit: bdf8b8b

## タスク
- Task 1: 黒マスク検出 detect_side_masks — complete (commits bdf8b8b..50cb7d8, review clean)
- Task 2: 黒マスクトリミング crop_side_masks — complete (commits 50cb7d8..b0e9983, review clean)
- Task 3: process_spread 再構成 — complete (commits b0e9983..30f862c, review clean after docstring fix)
- Task 4: job_manager 人数カウント切替 — complete (commits 30f862c..67a9c0a, review clean)

## Minor findings (最終レビューで要триアージ)
- Task1: pixel_lum が単純RGB平均（知覚輝度でない）— 色付き帯でわずかにズレる可能性。設計由来。
- Task1: dark判定の等号ニュアンス（> / < と「以上/以下」コメントの軽微不一致）。設計由来。
- Task1: 極端に狭い画像(width<13px)で安全弁とMIN_MASK_WIDTHが矛盾しうる理論上エッジ。
- Task1: テスト網羅（右側の細い帯／片側だけ広い黒帯の安全弁）の明示テストなし。
- Task2: crop_side_masks の非対称クロップ単体テストなし（統合テストで補完見込み）。
- Task3: 黒マスク検出の例外フォールバックの単体テストなし（最終レビューで要否триアージ）。

## 最終レビュー結果（opus）: マージ可（Critical/Important なし）
- M-1(後回し): 単ページでストライプ誤検出時、非分割でも remove_stripe が走り中央帯が抜かれうる（本PR以前からの既存挙動、スコープ外）。将来 remove_stripe も should_split 連動を検討。
- M-2(後回し): detect_side_masks 内の image.convert("RGB") が二重（軽微冗長）。
- 既知Minor 4件すべて「後回し可」判定。全4タスク complete。
