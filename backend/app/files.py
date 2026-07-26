import asyncio
import shutil
import subprocess
import tempfile
from pathlib import Path

from fastapi import HTTPException, UploadFile
from pypdf import PdfReader


MAX_BYTES = 15 * 1024 * 1024
MAX_PAGES = 40
TEXT_TYPES = {".txt", ".md", ".csv", ".json"}
IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}
MIME_TYPES = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}


async def extract_upload(file: UploadFile) -> tuple[str, list[str]]:
    data, suffix, _ = await read_upload(file)
    return await extract_bytes(data, suffix)


async def read_upload(file: UploadFile) -> tuple[bytes, str, str]:
    data = await file.read(MAX_BYTES + 1)
    await file.close()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "文件不得超过 15 MB")
    suffix = Path(file.filename or "upload").suffix.lower()
    if suffix not in MIME_TYPES:
        raise HTTPException(415, "仅支持 PDF、TXT/MD、PNG、JPG、WEBP 或 TIFF")
    return data, suffix, MIME_TYPES[suffix]


async def extract_bytes(data: bytes, suffix: str) -> tuple[str, list[str]]:
    if suffix in TEXT_TYPES:
        text = decode_text(data)
        return clean_text(text), []
    if suffix == ".pdf":
        return await asyncio.to_thread(extract_pdf, data)
    if suffix in IMAGE_TYPES:
        return await asyncio.to_thread(extract_image, data, suffix)
    raise HTTPException(415, "仅支持 PDF、TXT/MD、PNG、JPG、WEBP 或 TIFF")


def decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise HTTPException(422, "无法识别文本编码；请另存为 UTF-8")


def extract_pdf(data: bytes) -> tuple[str, list[str]]:
    warnings: list[str] = []
    with tempfile.TemporaryDirectory(prefix="castle-pdf-") as temp_dir:
        pdf_path = Path(temp_dir) / "source.pdf"
        pdf_path.write_bytes(data)
        try:
            reader = PdfReader(pdf_path)
        except Exception as exc:
            raise HTTPException(422, "PDF 无法读取或已损坏") from exc
        pages: list[str] = []
        for index, page in enumerate(reader.pages[:MAX_PAGES], start=1):
            try:
                text = page.extract_text() or ""
            except Exception:
                text = ""
            if text.strip():
                pages.append(f"[PAGE {index}]\n{text}")
        if len(reader.pages) > MAX_PAGES:
            warnings.append(f"仅处理前 {MAX_PAGES} 页")
        joined = clean_text("\n\n".join(pages))
        if len(joined) >= 80:
            return joined, warnings
        if not shutil.which("pdftoppm") or not shutil.which("tesseract"):
            warnings.append("扫描 PDF 需要服务器安装 poppler 与 tesseract OCR")
            return joined, warnings
        prefix = Path(temp_dir) / "page"
        command = ["pdftoppm", "-f", "1", "-l", str(min(len(reader.pages), MAX_PAGES)), "-jpeg", "-r", "180", str(pdf_path), str(prefix)]
        subprocess.run(command, check=True, capture_output=True, timeout=120)
        ocr_pages = []
        for index, image_path in enumerate(sorted(Path(temp_dir).glob("page-*.jpg")), start=1):
            ocr_pages.append(f"[PAGE {index}]\n{run_ocr(image_path)}")
        warnings.append("该 PDF 使用 OCR 识别，请仔细核对抽取事实")
        return clean_text("\n\n".join(ocr_pages)), warnings


def extract_image(data: bytes, suffix: str) -> tuple[str, list[str]]:
    if not shutil.which("tesseract"):
        raise HTTPException(503, "图片识别需要服务器安装 tesseract OCR")
    with tempfile.TemporaryDirectory(prefix="castle-image-") as temp_dir:
        image_path = Path(temp_dir) / f"source{suffix}"
        image_path.write_bytes(data)
        text = run_ocr(image_path)
    return clean_text(text), ["图片使用 OCR 识别，请仔细核对抽取事实"]


def run_ocr(path: Path) -> str:
    language = "chi_sim+eng" if tesseract_has_language("chi_sim") else "eng"
    try:
        result = subprocess.run(
            ["tesseract", str(path), "stdout", "-l", language, "--psm", "6"],
            check=True,
            capture_output=True,
            timeout=90,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(422, "OCR 无法识别该图片") from exc
    return result.stdout.decode("utf-8", errors="replace")


def tesseract_has_language(language: str) -> bool:
    try:
        result = subprocess.run(["tesseract", "--list-langs"], capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return language in result.stdout.decode("utf-8", errors="ignore").split()


def clean_text(text: str) -> str:
    lines = [" ".join(line.split()) for line in text.replace("\x00", "").splitlines()]
    return "\n".join(line for line in lines if line)[:120_000]
