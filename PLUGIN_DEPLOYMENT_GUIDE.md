# Difyプラグイン開発・デプロイ完全ガイド

このドキュメントは、Difyプラグインの開発からプロダクション環境への完全デプロイまでの手順をまとめたものです。

## 🔐 1. プラグイン署名キーの作成

### OpenSSLを使用した署名キーペア生成

```bash
# RSA 2048bit キーペアの生成
openssl genpkey -algorithm RSA -pkcs8 -out private_key.pem -pkeyopt rsa_keygen_bits:2048

# 公開キーの抽出
openssl rsa -pubout -in private_key.pem -out public_key.pem

# キーペアの確認
ls -la *.pem
# -rw------- 1 user user 1679 private_key.pem  # プライベートキー（機密）
# -rw-r--r-- 1 user user  451 public_key.pem   # 公開キー
```

### ファイル名の推奨規則
```bash
# プロジェクト固有の名前を付ける
mv private_key.pem my_plugin_name_key.private.pem
mv public_key.pem my_plugin_name_key.public.pem

# 例：PDF変換プラグインの場合
# pdf_converter_key.private.pem
# pdf_converter_key.public.pem
```

## 🏗️ 2. プラグインのパッケージ化と署名

### 基本的なパッケージ化

```bash
# Dify Plugin CLIのダウンロード（初回のみ）
# https://github.com/langgenius/dify-plugin-daemon/releases から対応版をダウンロード
chmod +x dify-plugin-linux-amd64  # Linux
chmod +x dify-plugin-darwin-arm64  # macOS ARM
chmod +x dify-plugin-darwin-amd64  # macOS Intel

# プラグインのパッケージ化
./dify-plugin plugin package ./your-plugin-directory

# 結果：your-plugin-directory.difypkg ファイルが生成される
```

### 署名付きパッケージの作成

```bash
# 署名の追加
./dify-plugin signature sign ./your-plugin.difypkg -p ./your_private_key.pem

# 結果：your-plugin.signed.difypkg ファイルが生成される
```

### 署名の検証（オプション）

```bash
# 署名の検証
./dify-plugin signature verify ./your-plugin.signed.difypkg -k ./your_public_key.pem
```

## 🔧 3. 開発環境のセットアップ

### 環境変数の設定（.env ファイル）

```bash
# プラグインディレクトリに .env ファイルを作成
cat > .env << 'EOF'
# デバッグ接続設定
INSTALL_METHOD=remote
REMOTE_INSTALL_URL=localhost:5003
REMOTE_INSTALL_KEY=your-unique-plugin-key-uuid

# ファイルサーバーURL（Dify構成に応じて調整）
FILES_URL=http://localhost:8000

# その他の設定（必要に応じて）
LOG_LEVEL=INFO
MAX_FILE_SIZE=50MB
TIMEOUT=30
EOF
```

### プラグインキーの生成

```bash
# UUIDv4の生成（プラグインキー用）
python3 -c "import uuid; print(str(uuid.uuid4()))"
# または
uuidgen

# 例：99fa6815-4625-4334-8a68-42f11ab308b7
# これを REMOTE_INSTALL_KEY として使用
```

### デバッグモードの起動

```bash
# 仮想環境をアクティベート
source .venv/bin/activate

# プラグインディレクトリに移動
cd your-plugin-directory

# デバッグサーバー起動
python -m main

# 成功時の出力例：
# INFO:dify_plugin.plugin:Installed tool: your-tool-name
```

## 🌐 4. Dify本体への設定

### 開発モード（デバッグ用）

1. **Dify管理画面にアクセス**
   ```
   http://your-dify-server/admin
   ```

2. **プラグイン管理画面**
   - 「プラグイン」→「開発」メニュー
   - 「新しいプラグインを追加」

3. **開発プラグインの登録**
   ```
   プラグインキー: 99fa6815-4625-4334-8a68-42f11ab308b7
   プラグイン名: your-plugin-name
   接続URL: localhost:5003
   ```

### プロダクションモード（署名済みパッケージ）

1. **署名済みパッケージのアップロード**
   - 「プラグイン」→「インストール」
   - 「ファイルからインストール」
   - `your-plugin.signed.difypkg` をアップロード

2. **サードパーティ署名検証の有効化**
   ```bash
   # Difyの環境変数に追加
   PLUGIN_THIRD_PARTY_SIGNATURE_VERIFICATION=true
   PLUGIN_THIRD_PARTY_PUBLIC_KEY_PATH=/path/to/your_public_key.pem
   ```

## 📁 5. キーファイルの適切な管理

### ディレクトリ構造

```
project-root/
├── plugin-source/
│   ├── tools/
│   ├── provider/
│   ├── manifest.yaml
│   ├── .env                    # Git除外対象
│   └── main.py
├── keys/                       # Git除外対象
│   ├── plugin_name.private.pem # 🚨 機密ファイル
│   └── plugin_name.public.pem
├── build/
│   ├── plugin-name.difypkg
│   └── plugin-name.signed.difypkg
└── .gitignore
```

### .gitignore の推奨設定

```gitignore
# 機密ファイル
*.private.pem
.env
.env.local

# ビルド成果物
*.difypkg
*.signed.difypkg

# その他の除外ファイル
__pycache__/
*.pyc
.venv/
logs/
test-data/
```

### セキュリティのベストプラクティス

```bash
# プライベートキーのパーミッション設定
chmod 600 *.private.pem  # 所有者のみ読み書き可能

# キーファイルの暗号化保存（推奨）
gpg -c your_plugin.private.pem  # パスフレーズで暗号化

# 環境変数での機密情報管理
export PLUGIN_PRIVATE_KEY_PATH=/secure/path/to/private_key.pem
export PLUGIN_PRIVATE_KEY_PASSPHRASE="your-secure-passphrase"
```

## 🚀 6. 自動化スクリプト

### ビルド・署名の自動化

```bash
#!/bin/bash
# build_and_sign.sh

set -e  # エラー時に停止

PLUGIN_DIR="./pdf-to-images"
PRIVATE_KEY="./keys/pdf_converter.private.pem"
BUILD_DIR="./build"

echo "🏗️  プラグインをパッケージ化中..."
./dify-plugin plugin package "$PLUGIN_DIR"

echo "✍️  署名を追加中..."
./dify-plugin signature sign "${PLUGIN_DIR}.difypkg" -p "$PRIVATE_KEY"

echo "📁 ビルドディレクトリに移動中..."
mkdir -p "$BUILD_DIR"
mv "${PLUGIN_DIR}.difypkg" "$BUILD_DIR/"
mv "${PLUGIN_DIR}.signed.difypkg" "$BUILD_DIR/"

echo "✅ ビルド完了！"
ls -la "$BUILD_DIR"
```

### デプロイメントの自動化

```bash
#!/bin/bash
# deploy.sh

DIFY_SERVER="https://your-dify-server.com"
PLUGIN_FILE="./build/pdf-to-images.signed.difypkg"
API_KEY="your-dify-api-key"

echo "🚀 Difyサーバーにデプロイ中..."

curl -X POST "$DIFY_SERVER/api/plugins/install" \
  -H "Authorization: Bearer $API_KEY" \
  -F "plugin=@$PLUGIN_FILE"

echo "✅ デプロイ完了！"
```

## 🔍 7. トラブルシューティング

### よくあるエラーと対処法

#### 「handshake failed, invalid key」
```bash
# 原因：プラグインキーが無効または期限切れ
# 解決：新しいUUIDを生成して .env ファイルを更新

python3 -c "import uuid; print(str(uuid.uuid4()))"
# 生成されたUUIDを REMOTE_INSTALL_KEY に設定
```

#### 「Connection refused」
```bash
# 原因：Difyサーバーへの接続失敗
# 解決：FILES_URL と REMOTE_INSTALL_URL を確認

# Difyサーバーの実際のURLを確認
curl -I http://localhost:8000/health  # ヘルスチェック
netstat -tuln | grep :5003           # ポート5003の確認
```

#### 「Signature verification failed」
```bash
# 原因：署名が無効または公開キーが不正
# 解決：キーペアの再生成と署名のやり直し

# キーペアの再生成
openssl genpkey -algorithm RSA -pkcs8 -out new_private.pem -pkeyopt rsa_keygen_bits:2048
openssl rsa -pubout -in new_private.pem -out new_public.pem

# 再署名
./dify-plugin signature sign plugin.difypkg -p new_private.pem
```

## 📋 8. プロダクション環境チェックリスト

### セキュリティチェック
- [ ] プライベートキーが適切にセキュリティ保護されている
- [ ] .env ファイルがGitにコミットされていない
- [ ] プラグインキーが十分に複雑（UUIDv4）
- [ ] HTTPSを使用している（プロダクション環境）

### 機能チェック  
- [ ] 全ての必須パラメータが適切に検証される
- [ ] エラーハンドリングが適切に実装されている
- [ ] ログ出力が適切なレベルに設定されている
- [ ] メモリリークがない（大容量ファイル処理時）

### ドキュメントチェック
- [ ] README.md が完整している
- [ ] API仕様書が最新版
- [ ] トラブルシューティング情報が網羅されている
- [ ] バージョン情報が正確

## 🔄 9. バージョン管理とリリース

### セマンティックバージョニング

```yaml
# manifest.yaml でのバージョン管理
version: "1.2.3"
# 1: メジャーバージョン（破壊的変更）
# 2: マイナーバージョン（新機能追加）
# 3: パッチバージョン（バグ修正）
```

### リリースプロセス

```bash
# 1. バージョン番号の更新
sed -i 's/version: "1.0.0"/version: "1.0.1"/' manifest.yaml

# 2. CHANGELOG の更新
echo "## v1.0.1 - $(date +%Y-%m-%d)" >> CHANGELOG.md
echo "- Bug fixes and improvements" >> CHANGELOG.md

# 3. Git タグの作成
git tag -a v1.0.1 -m "Release version 1.0.1"
git push origin v1.0.1

# 4. ビルドと署名
./build_and_sign.sh

# 5. GitHub Release の作成（推奨）
gh release create v1.0.1 ./build/*.signed.difypkg --notes "Release notes..."
```

---

**このガイドに従うことで、セキュアで信頼性の高いDifyプラグインを開発・デプロイできます。** 🚀