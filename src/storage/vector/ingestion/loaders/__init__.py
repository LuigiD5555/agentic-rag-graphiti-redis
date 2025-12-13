"""Loader registry helpers."""
from __future__ import annotations

from typing import Any, Sequence, Tuple, Type

from .csv_loader import CSVLoader
from .docx_loader import DocxLoader
from .email_loader import EmailLoader
from .md_loader import MarkdownLoader
from .odf_loader import OpenDocumentLoader
from .pdf_loader import PDFLoader
from .ppt_loader import PowerPointLoader
from .text_loader import PlainTextLoader
from .word_loader import WordLoader
from .xlsx_loader import ExcelLoader
from .py_loader import PythonCodeStructure
from .js_loader import JavaScriptCodeStructure
from .ts_loader import TypeScriptCodeStructure
from .java_loader import JavaCodeStructure
from .go_loader import GoCodeStructure
from .ruby_loader import RubyCodeStructure
from .csharp_loader import CSharpCodeStructure
from .php_loader import PHPCodeStructure
from .c_loader import CCodeStructure

TextLoaderSpec = Tuple[Tuple[str, ...], Type[Any]]
CodeLoaderSpec = Tuple[Tuple[str, ...], Type[Any]]

TEXT_LOADER_SPECS: Sequence[TextLoaderSpec] = [
    ((".pdf",), PDFLoader),
    ((".docx",), DocxLoader),
    ((".doc", ".docm", ".rtf"), WordLoader),
    ((".txt",), PlainTextLoader),
    ((".md",), MarkdownLoader),
    ((".csv",), CSVLoader),
    ((".xlsx", ".xls", ".xlsm", ".xlsb", ".xlt"), ExcelLoader),
    ((".ppt", ".pptx", ".pptm", ".pps", ".ppsx"), PowerPointLoader),
    ((".odt", ".ods", ".odp"), OpenDocumentLoader),
    ((".eml", ".msg"), EmailLoader),
]

CODE_LOADER_SPECS: Sequence[CodeLoaderSpec] = [
    ((".py",), PythonCodeStructure),
    ((".js",), JavaScriptCodeStructure),
    ((".ts", ".tsx"), TypeScriptCodeStructure),
    ((".java",), JavaCodeStructure),
    ((".go",), GoCodeStructure),
    ((".rb",), RubyCodeStructure),
    ((".cs",), CSharpCodeStructure),
    ((".php",), PHPCodeStructure),
    ((".c", ".cpp"), CCodeStructure),
]

__all__ = [
    "PlainTextLoader",
    "TEXT_LOADER_SPECS",
    "CODE_LOADER_SPECS",
]
