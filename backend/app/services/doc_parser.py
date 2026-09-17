"""
文档解析服务
支持：PDF（优先 MinerU API，降级 PyPDF）、DOCX（python-docx）、URL（Jina Reader）
"""
import os
import asyncio
import httpx
import logging
import zipfile
from typing import Optional
from ..config import settings

logger = logging.getLogger(__name__)


def _limit_extracted_text(text: str) -> str:
    if len(text) > settings.MAX_EXTRACTED_TEXT_CHARS:
        raise ValueError("文档提取文本超过处理上限")
    return text


def _validate_pdf(file_path: str) -> None:
    from pypdf import PdfReader

    try:
        reader = PdfReader(file_path)
        if reader.is_encrypted:
            raise ValueError("暂不支持加密 PDF")
        if len(reader.pages) > settings.MAX_PDF_PAGES:
            raise ValueError(f"PDF 页数不能超过 {settings.MAX_PDF_PAGES} 页")
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("PDF 文件结构无效或已损坏") from exc


def _validate_docx(file_path: str) -> None:
    max_total = settings.MAX_DOCX_TOTAL_UNCOMPRESSED_MB * 1024 * 1024
    max_entry = settings.MAX_DOCX_SINGLE_ENTRY_MB * 1024 * 1024
    try:
        with zipfile.ZipFile(file_path) as archive:
            entries = archive.infolist()
            if len(entries) > settings.MAX_DOCX_ENTRIES:
                raise ValueError("DOCX 内部文件数量超过处理上限")
            names = {entry.filename for entry in entries}
            if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                raise ValueError("文件不是有效的 DOCX 文档")
            total_size = 0
            for entry in entries:
                if entry.flag_bits & 0x1:
                    raise ValueError("暂不支持加密 DOCX")
                if entry.file_size > max_entry:
                    raise ValueError("DOCX 内部单个文件超过处理上限")
                total_size += entry.file_size
                if total_size > max_total:
                    raise ValueError("DOCX 解压后大小超过处理上限")
                if entry.file_size and entry.file_size / max(entry.compress_size, 1) > settings.MAX_DOCX_COMPRESSION_RATIO:
                    raise ValueError("DOCX 压缩比异常，已拒绝处理")
    except ValueError:
        raise
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError("DOCX 文件结构无效或已损坏") from exc


def validate_document_file(file_path: str, source_type: str) -> None:
    if source_type == "pdf":
        _validate_pdf(file_path)
    elif source_type == "word":
        _validate_docx(file_path)
    else:
        raise ValueError("不支持的文档类型")


async def parse_document(file_path: str, source_type: str) -> str:
    """
    统一入口：根据 source_type 分派解析器
    返回提取的纯文本内容（Markdown 格式）
    """
    if source_type == "pdf":
        return await parse_pdf(file_path)
    elif source_type == "word":
        return await asyncio.to_thread(parse_word, file_path)
    elif source_type == "url":
        return await parse_url(file_path)
    else:
        raise ValueError(f"不支持的文档类型: {source_type}")


# ─────────────────────────────────────────────
#  PDF 解析
# ─────────────────────────────────────────────

async def parse_pdf(file_path: str) -> str:
    """优先调用 MinerU API，失败则降级到本地 PyPDF"""
    await asyncio.to_thread(_validate_pdf, file_path)
    if settings.MINERU_API_KEY:
        try:
            return await _parse_pdf_mineru(file_path)
        except Exception as e:
            logger.warning(f"MinerU 解析失败，降级到 PyPDF: {e}")
    return await asyncio.to_thread(_parse_pdf_local, file_path)


async def _parse_pdf_mineru(file_path: str) -> str:
    """调用 MinerU 云端 API 解析 PDF → Markdown"""
    async with httpx.AsyncClient(timeout=120) as client:
        with open(file_path, "rb") as f:
            files = {"file": (os.path.basename(file_path), f, "application/pdf")}
            headers = {"Authorization": f"Bearer {settings.MINERU_API_KEY}"}
            resp = await client.post(
                f"{settings.MINERU_API_URL}/file-urls/batch",
                files=files,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            # MinerU 返回 task_id，需要轮询结果
            task_id = data.get("data", {}).get("task_id")
            if not task_id:
                raise ValueError("MinerU 未返回 task_id")
            return await _poll_mineru_result(client, task_id, headers)


async def _poll_mineru_result(client: httpx.AsyncClient, task_id: str, headers: dict) -> str:
    import asyncio
    for _ in range(60):  # 最多等待 120 秒
        await asyncio.sleep(2)
        resp = await client.get(
            f"{settings.MINERU_API_URL}/extract-results/{task_id}",
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()
        state = data.get("data", {}).get("state")
        if state == "done":
            markdown_list = data["data"].get("detail", [])
            text = "\n\n".join(
                item.get("md_content", "") for item in markdown_list if item.get("md_content")
            )
            if not text.strip():
                raise ValueError("MinerU 未返回可用文本")
            return _limit_extracted_text(text)
        elif state == "failed":
            raise ValueError(f"MinerU 任务失败: {data}")
    raise TimeoutError("MinerU 解析超时")


def _parse_pdf_local(file_path: str) -> str:
    """本地 PyPDF 解析（备用方案）"""
    try:
        from pypdf import PdfReader
        reader = PdfReader(file_path)
        texts = []
        extracted_chars = 0
        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            if text.strip():
                page_text = f"## 第 {i + 1} 页\n\n{text.strip()}"
                extracted_chars += len(page_text)
                if extracted_chars > settings.MAX_EXTRACTED_TEXT_CHARS:
                    raise ValueError("PDF 提取文本超过处理上限")
                texts.append(page_text)
        return _limit_extracted_text("\n\n".join(texts))
    except Exception as e:
        logger.error(f"PyPDF 解析失败: {e}")
        raise


# ─────────────────────────────────────────────
#  Word 解析
# ─────────────────────────────────────────────

def parse_word(file_path: str) -> str:
    """使用 python-docx 解析 .docx 文件"""
    _validate_docx(file_path)
    from docx import Document
    doc = Document(file_path)
    parts = []

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        # 识别标题样式
        if para.style.name.startswith("Heading"):
            level = para.style.name.replace("Heading ", "")
            try:
                level_num = int(level)
                parts.append(f"{'#' * level_num} {text}")
            except ValueError:
                parts.append(f"## {text}")
        else:
            parts.append(text)

    # 提取表格内容
    for table in doc.tables:
        rows = []
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            rows.append(" | ".join(cells))
        if rows:
            parts.append("\n".join(rows))

    return _limit_extracted_text("\n\n".join(parts))


# ─────────────────────────────────────────────
#  URL 解析（Jina Reader）
# ─────────────────────────────────────────────

async def parse_url(url: str) -> str:
    """
    使用 Jina Reader API (r.jina.ai) 将网页转换为 Markdown
    无需 API Key，直接访问
    """
    jina_url = f"https://r.jina.ai/{url}"
    # URL 已在路由层做 DNS 内网地址校验；这里不跟随第三方重定向，避免绕过校验。
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
        headers = {
            "Accept": "text/plain",
            "X-Return-Format": "markdown",
        }
        async with client.stream("GET", jina_url, headers=headers) as resp:
            resp.raise_for_status()
            content = bytearray()
            async for chunk in resp.aiter_bytes():
                content.extend(chunk)
                if len(content) > settings.max_url_content_bytes:
                    raise ValueError("URL 内容超过大小限制")
            text = bytes(content).decode(resp.encoding or "utf-8", errors="replace")
            return _limit_extracted_text(text)


# ─────────────────────────────────────────────
#  文本分块
# ─────────────────────────────────────────────

def split_text_into_chunks(
    text: str,
    chunk_size: Optional[int] = None,
    overlap: Optional[int] = None,
) -> list[str]:
    """
    将长文本按语义分块
    优先在段落边界切分，保留上下文重叠

    分块大小直接影响出题耗时：块越小，LLM 调用次数越多（每块 2 次调用），
    小机器上很容易超出任务超时。默认值来自 GENERATION_CHUNK_SIZE。
    """
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    chunk_size = chunk_size or settings.GENERATION_CHUNK_SIZE
    overlap = settings.GENERATION_CHUNK_OVERLAP if overlap is None else overlap
    if overlap >= chunk_size:
        overlap = max(0, chunk_size // 10)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        separators=["\n\n", "\n", "。", "！", "？", "；", " ", ""],
        length_function=len,
    )
    chunks = splitter.split_text(text)
    # 过滤过短的无效块
    return [c.strip() for c in chunks if len(c.strip()) >= 50]
