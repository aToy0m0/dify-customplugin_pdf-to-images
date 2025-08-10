from collections.abc import Generator
from typing import Any
import fitz  # PyMuPDF
import io
import os
import logging
import requests

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage
from dify_plugin.file.file import File
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ToolParameters(BaseModel):
    files: list[File]
    dpi: int = 72
    image_format: str = "PNG"

class PdfToImagesTool(Tool):
    def _open_pdf_from_file(self, file: File):
        """
        Difyファイルオブジェクトから動的にPDFを開く
        公式プラグイン解析に基づく最適化版
        """
        logger.info(f"File processing: {file.filename}, blob type: {type(file.blob)}")
        
        if isinstance(file.blob, bytes):
            # バイナリデータの場合（推奨: comfyui, mineru等のパターン）
            logger.info(f"✅ Processing as binary data ({len(file.blob)} bytes)")
            file_bytes = io.BytesIO(file.blob)
            return fitz.open(stream=file_bytes, filetype="pdf")
            
        elif isinstance(file.blob, str):
            # 文字列の場合（llama_parse等の特殊パターン）
            logger.info(f"⚠️ Processing as string: {file.blob[:100]}...")
            
            # 完全なHTTP/HTTPS URLの場合
            if file.blob.startswith(('http://', 'https://')):
                logger.info("📥 Downloading from HTTP URL")
                try:
                    response = requests.get(file.blob, timeout=30)
                    response.raise_for_status()
                    file_bytes = io.BytesIO(response.content)
                    return fitz.open(stream=file_bytes, filetype="pdf")
                except Exception as e:
                    logger.error(f"❌ HTTP download failed: {e}")
                    raise Exception(f"Cannot download file: {e}")
            
            # ローカルファイルパス（llama_parse style）  
            elif not file.blob.startswith('/files/'):
                logger.info("📂 Attempting local file path")
                try:
                    return fitz.open(file.blob)
                except Exception as e:
                    logger.error(f"❌ Local file access failed: {e}")
                    raise Exception(f"Cannot access file: {file.blob}")
                    
            # Dify内部パスの場合（最後のフォールバック）
            else:  # file.blob.startswith('/files/')
                logger.warning("🔄 Attempting Dify internal file server (fallback)")
                
                # 包括的なベースURL一覧（優先順位順）
                base_urls = [
                    os.getenv('FILES_URL', 'http://localhost'),  # 環境変数優先
                    'http://localhost',           # 標準（ポートなし）
                    'http://localhost:80',        # HTTP標準ポート
                    'http://localhost:8000',      # 開発用ポート
                    'http://localhost:5000',      # Flask標準
                    'http://localhost:3000',      # Node.js標準
                    'http://127.0.0.1',          # IP直接（ポートなし）
                    'http://127.0.0.1:80',       # IP + HTTP標準ポート
                    'http://127.0.0.1:8000',     # IP + 開発ポート
                    'http://dify-web',            # Docker内部ネットワーク
                    'http://nginx',               # Nginx経由
                    'http://api',                 # APIサーバー直接
                    'http://dify-api',            # Dify APIサーバー
                ]
                
                successful_url = None
                last_error = None
                
                for base_url in base_urls:
                    full_url = f"{base_url}{file.blob}"
                    try:
                        logger.info(f"Attempting: {full_url}")
                        response = requests.get(full_url, timeout=15)
                        
                        if response.status_code == 200 and len(response.content) > 0:
                            logger.info(f"✅ Success with: {full_url}")
                            file_bytes = io.BytesIO(response.content)
                            successful_url = full_url
                            return fitz.open(stream=file_bytes, filetype="pdf")
                        else:
                            logger.warning(f"❌ HTTP {response.status_code} from: {full_url}")
                            
                    except requests.exceptions.ConnectionError as e:
                        logger.debug(f"🔌 Connection refused: {full_url}")
                        last_error = e
                        continue
                    except requests.exceptions.Timeout as e:
                        logger.debug(f"⏰ Timeout: {full_url}")
                        last_error = e
                        continue
                    except Exception as e:
                        logger.debug(f"❓ Other error for {full_url}: {type(e).__name__}: {e}")
                        last_error = e
                        continue
                
                # すべて失敗した場合の詳細エラー
                error_msg = (f"❌ Cannot access Dify file server. Tried {len(base_urls)} URLs.\n"
                           f"File path: {file.blob}\n"
                           f"Last error: {type(last_error).__name__}: {last_error}\n"
                           f"💡 Solutions:\n"
                           f"1. Check if Dify file server is running\n"
                           f"2. Set FILES_URL environment variable\n"
                           f"3. Upload files as binary data instead of file paths")
                logger.error(error_msg)
                raise Exception(error_msg)
                
        else:
            raise ValueError(f"Unsupported file.blob type: {type(file.blob)}")
    
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:
        """
        PDFファイルを複数の画像に変換するツール
        
        Args:
            tool_parameters: ツールの入力パラメータを含む辞書:
                - pdf_files (Array[File]): 変換するPDFファイルのリスト
                - dpi (int): 画像の解像度 (デフォルト: 150)
                - image_format (str): 出力画像フォーマット ('PNG' または 'JPEG')
        
        Yields:
            ToolInvokeMessage: 変換された画像ファイルを含むメッセージ
        """
        
        if tool_parameters.get("files") is None:
            yield self.create_text_message("PDFファイルが提供されていません。")
            return
            
        try:
            params = ToolParameters(**tool_parameters)
        except Exception as e:
            yield self.create_text_message(f"パラメータエラー: {str(e)}")
            return
        
        pdf_files = params.files
        dpi = params.dpi
        image_format = params.image_format.upper()
        
        if not pdf_files:
            yield self.create_text_message("PDFファイルが提供されていません。")
            return
        
        # 変換結果を格納するリスト
        converted_images = []
        total_pages = 0
        
        for file_index, pdf_file in enumerate(pdf_files):
            try:
                logger.info(f"PDFファイルを処理中: {pdf_file.filename}")
                logger.info(f"ファイルオブジェクトの属性: {dir(pdf_file)}")
                
                # 動的ファイル処理：file.blobの型に応じて適切に処理
                logger.info(f"File blob type: {type(pdf_file.blob)}")
                logger.info(f"File blob content preview: {str(pdf_file.blob)[:100] if isinstance(pdf_file.blob, str) else f'Binary data: {len(pdf_file.blob)} bytes'}")
                
                pdf_document = self._open_pdf_from_file(pdf_file)
                file_pages = len(pdf_document)
                total_pages += file_pages
                
                yield self.create_text_message(f"PDF {file_index + 1}: {file_pages}ページを処理中...")
                
                # 各ページを画像に変換
                for page_num in range(file_pages):
                    page = pdf_document[page_num]
                    
                    # ページを画像に変換 (DPIを指定)
                    mat = fitz.Matrix(dpi/72, dpi/72)  # 72 DPIがデフォルト
                    pix = page.get_pixmap(matrix=mat)
                    
                    # 画像データをバイト配列に変換
                    if image_format == "PNG":
                        img_data = pix.tobytes("png")
                        mime_type = "image/png"
                        extension = ".png"
                    else:  # JPEG
                        img_data = pix.tobytes("jpeg")
                        mime_type = "image/jpeg"
                        extension = ".jpg"
                    
                    # ファイル名を生成
                    base_filename = os.path.splitext(pdf_file.filename)[0]
                    filename = f"{base_filename}_page_{page_num + 1}{extension}"
                    
                    # 画像ファイルとして保存し、ブロブメッセージを作成
                    yield self.create_blob_message(
                        img_data,
                        meta={
                            "mime_type": mime_type,
                            "filename": filename
                        }
                    )
                    
                    # 変換情報を記録
                    image_info = {
                        "file_index": file_index + 1,
                        "page_number": page_num + 1,
                        "filename": filename,
                        "mime_type": mime_type,
                        "width": pix.width,
                        "height": pix.height,
                        "dpi": dpi
                    }
                    
                    converted_images.append(image_info)
                
                pdf_document.close()
                
            except Exception as e:
                error_msg = f"PDF {file_index + 1}の処理中にエラーが発生しました: {str(e)}"
                logger.error(error_msg)
                yield self.create_text_message(error_msg)
                continue
        
        # 結果の出力
        if converted_images:
            yield self.create_text_message(f"変換完了: {len(converted_images)}枚の画像を生成しました")
            
            # 変換統計情報をJSON形式で返す
            result = {
                "success": True,
                "total_images": len(converted_images),
                "total_pages": total_pages,
                "dpi": dpi,
                "format": image_format,
                "images": converted_images
            }
            
            yield self.create_json_message(result)
        else:
            yield self.create_text_message("変換できるPDFファイルがありませんでした。")
