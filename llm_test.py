from pathlib import Path

from src.extraction.credit_extraction import (
    extract_credit_report_text
)

from src.llm.credit_analyzer import (
    analyze_credit_report
)


credit_file = Path(
    "data/input/Dharmendra credit.pdf"
)


context = extract_credit_report_text(
    credit_file
)

result = analyze_credit_report(
    context
)

print(result)