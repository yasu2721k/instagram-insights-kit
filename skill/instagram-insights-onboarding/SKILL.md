---
name: instagram-insights-onboarding
description: Instagramアカウントをプロアカウント化し、Facebookページ連携、Meta API認証、Googleスプレッドシートへのインサイト自動収集まで一段ずつ伴走する。新しい利用者への導入、接続診断、停止した収集の復旧で使う。
---

# Instagramデータ収集セットアップ

利用者が迷わないよう、現在地を確認して「今する操作」を一度に1〜3個だけ案内する。本人しか完了できないログイン、同意、権限付与は画面の意味と確認箇所を説明し、本人の完了報告または取得結果を確認してから次へ進む。パスワード、アクセストークン、アプリシークレット、Google認証JSONの本文をチャットへ貼らせない。

## 最初に行うこと

1. キットの導入先（collector.pyのあるフォルダー）のSTART-HERE.mdを読む。スキルのscripts/onboarding_state.pyはインストール先から絶対パスに解決し、`python3 <スキル絶対パス>/scripts/onboarding_state.py status --workspace <導入先フォルダ>` を実行する。状態ファイルがなければ `init` する。
2. 未完了の最初の段階を特定する。
3. プロアカウント化・Facebookページ連携は [references/meta-account-setup.md](references/meta-account-setup.md)、Meta API認証は [references/meta-api-setup.md](references/meta-api-setup.md)、Google Sheetsと自動実行は [references/google-and-automation.md](references/google-and-automation.md) の該当箇所だけ読む。
4. UI名やMeta権限名が資料と異なる場合は、公式ドキュメントで現行仕様を確認する。推測で別メニューを押させない。

## 段階

順序は `professional_account` → `facebook_page` → `meta_app` → `instagram_asset` → `long_lived_token` → `google_sheet` → `collector_config` → `first_sync` → `automation` → `health_check`。

各段階は、利用者の申告だけで済む項目と、APIまたは生成物で検証できる項目を区別する。検証可能な項目は実測してから `complete` にする。`first_sync` は投稿データが取得でき、対象スプレッドシートへテスト行またはタブが作成され、読み戻せた時だけ完了。`automation` はジョブを登録しただけでなく、少なくとも手動相当の一回が正常終了してログ保存先を確認できた時だけ完了。

```bash
python3 <スキル絶対パス>/scripts/onboarding_state.py complete --workspace <導入先フォルダ> --step <段階名> --evidence '<秘密を含まない根拠>'
```

## 境界

- 通常投稿・ストーリーズの公開、DM送信、広告操作はこのスキルの範囲外。
- MetaやGoogleの外部アプリ公開・App Review申請は、単一事業者が自分の資産へ接続するローカル導入とは分けて扱う。第三者へSaaSとして提供する場合は、審査・プライバシーポリシー・データ削除導線を別途設計する。
- トークンや秘密情報は `.env` またはOSの秘密管理へ保存し、状態ファイル・Git・スプレッドシートへ書かない。
- 配布版は新規の専用スプレッドシートを作る。自動生成タブには人の入力を混ぜず、手入力は別タブにする。
- Instagramのストーリーズは取得開始前へ完全には遡れない。開始後に定期収集して履歴を積むものとして説明する。
- 有料契約やMeta広告費は不要な構成を既定とする。課金が必要になる選択へ進む前は本人確認を取る。

## 完了報告

アカウント名、スプレッドシートURL、収集開始時刻、次回自動実行、取得できる指標、取得開始日より前に遡れない項目、認証更新方法、エラー確認先を短くまとめる。秘密値は含めない。
