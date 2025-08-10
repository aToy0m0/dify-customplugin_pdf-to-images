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
from dify_plugin.config.logger_format import plugin_logger_handler
from pydantic import BaseModel

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(plugin_logger_handler)


class ToolParameters(BaseModel):
    files: list[File]
    dpi: int = 72
    image_format: str = "PNG"

class PdfToImagesTool(Tool):
    def _open_pdf_from_file(self, file: File):
        """
        公式プラグインパターンに基づく堅牢なファイル処理
        優先順位: bytes > str (path) > file.url (HTTP)
        """
        logger.info(f"File processing: {file.filename}")
        
        try:
            # パターン1: file.blob が bytes の場合（最も一般的）
            if isinstance(file.blob, bytes):
                logger.info(f"✅ Processing as binary data ({len(file.blob)} bytes)")
                file_bytes = io.BytesIO(file.blob)
                return fitz.open(stream=file_bytes, filetype="pdf")
            
            # パターン2: file.blob が str の場合（ファイルパス）
            elif isinstance(file.blob, str):
                logger.info(f"📂 Processing as file path: {file.blob[:100]}...")
                try:
                    # 直接ファイルパスとしてアクセス（llama_parse style）
                    return fitz.open(file.blob)
                except Exception as path_error:
                    logger.warning(f"File path access failed: {path_error}")
                    # file.blobがパスとして無効な場合、file.urlを試行
                    raise path_error
            
            # パターン3: その他の型の場合
            else:
                logger.warning(f"⚠️ Unsupported blob type: {type(file.blob)}")
                # file.blobが使用できない場合、file.urlにフォールバック
                raise ValueError(f"Unsupported file.blob type: {type(file.blob)}")
                
        except Exception as blob_error:
            # file.blobでの処理に失敗した場合、file.urlを使用（LlamaParse Advanced style）
            if hasattr(file, 'url') and file.url:
                logger.info(f"🔄 Fallback to file.url: {file.url}")
                try:
                    response = requests.get(file.url, timeout=30)
                    response.raise_for_status()
                    logger.info(f"✅ Downloaded {len(response.content)} bytes from URL")
                    file_bytes = io.BytesIO(response.content)
                    return fitz.open(stream=file_bytes, filetype="pdf")
                except Exception as url_error:
                    logger.error(f"URL download failed: {url_error}")
                    raise Exception(f"ファイル処理に失敗: blob処理エラー({blob_error}), URL取得エラー({url_error})")
            else:
                logger.error(f"No file.url available, blob error: {blob_error}")
                raise Exception(f"ファイルにアクセスできません: {blob_error}")
    
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
        
        # 入力パラメータのデバッグ出力
        logger.info(f"Tool invoked with parameters: {list(tool_parameters.keys())}")
        
        files = tool_parameters.get("files")
        if files is None:
            logger.warning("No files parameter provided")
            yield self.create_text_message("PDFファイルが提供されていません。")
            return
        
        logger.info(f"Received {len(files)} files")
        for i, file in enumerate(files):
            logger.info(f"File {i+1}: {file.filename} ({file.mime_type}, {file.size} bytes)")
            if hasattr(file, 'url'):
                logger.info(f"  URL: {file.url}")

            
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
                
                # 公式パターンに基づくファイル処理
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
