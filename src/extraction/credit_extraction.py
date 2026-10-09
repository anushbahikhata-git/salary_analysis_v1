# src/extraction/credit_extraction.py

from pathlib import Path
import fitz


def extract_credit_report_text(
    file_path: Path
) -> str:

    document = fitz.open(file_path)

    pages = []

    for page_number, page in enumerate(document):

        text = page.get_text()

        if text.strip():

            pages.append(
                f"""
--- PAGE {page_number + 1} ---

{text}
"""
            )

    document.close()

    return "\n".join(pages)