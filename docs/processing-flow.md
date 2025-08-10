# PDF-to-Images Processing Flow Documentation

## 処理フローチャート

### メイン処理フロー
```mermaid
flowchart TD
    A[Start: _invoke メソッド] --> B{パラメータ検証}
    B -->|エラー| C[エラーメッセージ返却]
    B -->|成功| D[PDFファイルリスト取得]
    D --> E{PDFファイル存在?}
    E -->|No| F[エラー: PDFファイルなし]
    E -->|Yes| G[ファイルループ開始]
    
    G --> H[PDFファイル処理]
    H --> I[_open_pdf_from_file 呼び出し]
    I --> J[PDFドキュメント取得]
    J --> K[ページ数取得]
    K --> L[ページループ開始]
    
    L --> M[ページを画像に変換]
    M --> N[DPI適用してPixmap生成]
    N --> O{フォーマット選択}
    O -->|PNG| P[PNG形式でバイト変換]
    O -->|JPEG| Q[JPEG形式でバイト変換]
    P --> R[create_blob_message生成]
    Q --> R
    R --> S[次のページへ]
    
    S --> T{最後のページ?}
    T -->|No| L
    T -->|Yes| U[次のファイルへ]
    
    U --> V{最後のファイル?}
    V -->|No| H
    V -->|Yes| W[統計情報生成]
    W --> X[JSON結果メッセージ]
    X --> Y[End]
    
    C --> Y
    F --> Y
```

### ファイル処理フロー（_open_pdf_from_file）
```mermaid
flowchart TD
    A[Start: ファイル処理] --> B{file.blob型チェック}
    
    B -->|bytes型| C[✅ バイナリデータ処理]
    C --> D[io.BytesIO作成]
    D --> E[fitz.open実行]
    E --> Z[PDF Document返却]
    
    B -->|str型| F[⚠️ 文字列処理開始]
    F --> G{URLパターン判定}
    
    G -->|http/https| H[📥 HTTP URL処理]
    H --> I[requests.get実行]
    I --> J{ダウンロード成功?}
    J -->|Yes| K[io.BytesIO作成]
    K --> E
    J -->|No| L[❌ ダウンロードエラー]
    L --> ERROR[Exception発生]
    
    G -->|ローカルパス| M[📂 ローカルファイル処理]
    M --> N[fitz.open(path)実行]
    N --> O{ファイル読込成功?}
    O -->|Yes| Z
    O -->|No| P[❌ ファイルアクセスエラー]
    P --> ERROR
    
    G -->|/files/ パス| Q[🔄 Dify内部ファイル処理]
    Q --> R[ベースURL一覧生成]
    R --> S[URLループ開始]
    S --> T[完全URL構築]
    T --> U[HTTP GET実行]
    U --> V{レスポンス確認}
    V -->|200 & データあり| W[✅ 成功]
    W --> X[io.BytesIO作成]
    X --> E
    V -->|失敗| Y[次のURLへ]
    Y --> AA{最後のURL?}
    AA -->|No| S
    AA -->|Yes| BB[❌ 全URL失敗]
    BB --> ERROR
    
    B -->|その他型| CC[❌ サポート外型]
    CC --> ERROR
    
    ERROR --> DD[End: Error]
    Z --> EE[End: Success]
```

## システムアーキテクチャ図

### コンポーネント構成
```mermaid
graph TB
    subgraph "Docker Environment"
        subgraph "Dify Platform"
            DIFY[Dify Core]
            WEB[Dify Web UI]
            API[Dify API Server]
            DAEMON[Plugin Daemon]
        end
        
        subgraph "File Storage"
            FS[File Server]
            VOL[Docker Volumes]
        end
        
        subgraph "Network"
            NGINX[Nginx Proxy]
            NET[Docker Network]
        end
    end
    
    subgraph "Host OS"
        subgraph "Plugin Environment"
            PLUGIN[pdf-to-images.py]
            PYMUPDF[PyMuPDF Library]
            DEPS[Dependencies]
        end
        
        subgraph "Development"
            ENV[.env Config]
            KEYS[Signing Keys]
            PKG[Plugin Package]
        end
    end
    
    subgraph "External"
        USER[User]
        FILES[PDF Files]
        IMAGES[Generated Images]
    end
    
    %% Connections
    USER --> WEB
    WEB --> API
    API --> DAEMON
    DAEMON <--> PLUGIN
    PLUGIN --> PYMUPDF
    PLUGIN <--> FS
    FS --> VOL
    NGINX --> WEB
    NGINX --> API
    PLUGIN --> ENV
    FILES --> PLUGIN
    PLUGIN --> IMAGES
    
    %% Styling
    classDef docker fill:#e1f5fe
    classDef plugin fill:#fff3e0  
    classDef external fill:#f3e5f5
    
    class DIFY,WEB,API,DAEMON,FS,VOL,NGINX,NET docker
    class PLUGIN,PYMUPDF,DEPS,ENV,KEYS,PKG plugin
    class USER,FILES,IMAGES external
```

### データフロー図
```mermaid
sequenceDiagram
    participant User
    participant DifyUI as Dify UI
    participant API as Dify API
    participant Plugin as PDF-to-Images Plugin
    participant PyMuPDF as PyMuPDF Library
    participant FileServer as File Server
    
    User->>DifyUI: Upload PDF & Configure
    DifyUI->>API: Submit conversion request
    API->>Plugin: Invoke tool with parameters
    
    Plugin->>Plugin: Validate parameters
    Plugin->>Plugin: Process file list
    
    loop For each PDF file
        Plugin->>Plugin: Check file.blob type
        
        alt Binary data (bytes)
            Plugin->>PyMuPDF: Open from BytesIO
        else String URL/Path
            alt HTTP URL
                Plugin->>FileServer: Download file
                FileServer-->>Plugin: Binary data
            else Dify internal path
                Plugin->>FileServer: Request /files/* path
                FileServer-->>Plugin: Binary data
            else Local path
                Plugin->>PyMuPDF: Open from file path
            end
        end
        
        PyMuPDF-->>Plugin: PDF Document
        
        loop For each page
            Plugin->>PyMuPDF: Get page pixmap
            PyMuPDF-->>Plugin: Image pixmap
            Plugin->>Plugin: Convert to PNG/JPEG bytes
            Plugin->>API: Send blob message
        end
    end
    
    Plugin->>API: Send completion status
    API->>DifyUI: Return results
    DifyUI->>User: Display converted images
```

## 主要コンポーネントの責務

### 1. PdfToImagesTool クラス
- **役割**: メインのツール実装
- **責務**: 
  - パラメータ検証
  - ファイルリスト処理
  - 変換結果の統合
  - エラーハンドリング

### 2. _open_pdf_from_file メソッド
- **役割**: 動的ファイル処理
- **責務**:
  - file.blob型の判定
  - バイナリデータ処理（優先）
  - HTTP URLダウンロード
  - ローカルファイルアクセス
  - Dify内部ファイルサーバー連携

### 3. _invoke メソッド
- **役割**: メイン変換処理
- **責務**:
  - PDF→画像変換ループ
  - DPI適用とフォーマット選択
  - Blob メッセージ生成
  - 統計情報の集計

### 4. 外部依存関係
- **PyMuPDF (fitz)**: PDF処理とレンダリング
- **requests**: HTTP URL処理
- **io**: バイナリストリーム処理
- **dify_plugin**: Difyプラグインフレームワーク

## エラーハンドリング戦略

### ファイルアクセスエラー
1. **バイナリデータ処理失敗**: 即座にエラー返却
2. **HTTP URL失敗**: タイムアウト・接続エラーをキャッチ
3. **ローカルファイル失敗**: ファイル存在・権限エラーをキャッチ
4. **Dify内部ファイル失敗**: 複数URLでフォールバック試行

### 変換処理エラー
1. **PDF読み込み失敗**: ファイル破損・形式エラーを検出
2. **ページ変換失敗**: 個別ページエラーを分離
3. **メモリ不足**: 大容量ファイルの適切な処理

### 回復可能性
- **ファイル単位**: 1つのPDFが失敗しても他を継続
- **ページ単位**: 1ページが失敗しても他ページを継続  
- **URL フォールバック**: 複数のサーバーURLで自動再試行