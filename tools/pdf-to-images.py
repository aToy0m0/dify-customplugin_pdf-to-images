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
        file.blobの型に応じて適切な処理を行う
        """
        if isinstance(file.blob, bytes):
            # バイナリデータの場合（comfyui, mineru等のパターン）
            logger.info("Processing file.blob as binary data")
            file_bytes = io.BytesIO(file.blob)
            return fitz.open(stream=file_bytes, filetype="pdf")
            
        elif isinstance(file.blob, str):
            # ファイルパス/URLの場合（llama_parse等のパターン）
            logger.info(f"Processing file.blob as string path/URL: {file.blob}")
            
            if file.blob.startswith(('http://', 'https://')):
                # HTTP URLの場合
                logger.info("Downloading PDF from HTTP URL")
                response = requests.get(file.blob)
                response.raise_for_status()
                file_bytes = io.BytesIO(response.content)
                return fitz.open(stream=file_bytes, filetype="pdf")
                
            elif file.blob.startswith('/files/'):
                # Dify内部ファイルURLの場合
                logger.info("Processing Dify internal file URL")
                files_url = os.getenv('FILES_URL', 'http://localhost:80')
                full_url = f"{files_url}{file.blob}"
                logger.info(f"Constructed full URL: {full_url}")
                
                try:
                    response = requests.get(full_url, timeout=30)
                    response.raise_for_status()
                    file_bytes = io.BytesIO(response.content)
                    return fitz.open(stream=file_bytes, filetype="pdf")
                except requests.exceptions.ConnectionError as e:
                    logger.error(f"Connection failed to {full_url}: {e}")
                    # フォールバック: 他のポートを試行
                    fallback_urls = [
                        f"http://localhost:8000{file.blob}",
                        f"http://localhost:5000{file.blob}",
                        f"http://localhost:3000{file.blob}",
                        f"http://127.0.0.1:80{file.blob}",
                    ]
                    
                    for fallback_url in fallback_urls:
                        try:
                            logger.info(f"Trying fallback URL: {fallback_url}")
                            response = requests.get(fallback_url, timeout=10)
                            response.raise_for_status()
                            file_bytes = io.BytesIO(response.content)
                            return fitz.open(stream=file_bytes, filetype="pdf")
                        except Exception as fallback_error:
                            logger.info(f"Fallback URL {fallback_url} failed: {fallback_error}")
                            continue
                    
                    raise Exception(f"All file URL attempts failed. Original error: {e}")
                except Exception as e:
                    logger.error(f"HTTP request failed: {e}")
                    raise
                
            else:
                # ローカルファイルパスの場合
                logger.info("Processing as local file path")
                try:
                    return fitz.open(file.blob)
                except Exception as e:
                    logger.error(f"Failed to open file directly: {e}")
                    # 最後の手段: file.blobをそのまま試す（llama_parseパターン）
                    logger.info("Trying to use file.blob as direct file path (llama_parse pattern)")
                    return fitz.open(file.blob)
                
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
