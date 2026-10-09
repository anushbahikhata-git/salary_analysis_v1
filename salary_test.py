from pathlib import Path
import json

from src.extraction.cam_extraction_v2 import (
    analyze_transactions
)


# ============================================================
# CONFIG
# ============================================================

CAM_FILE = Path(
    "data/input/Yuvraj singh chauhan new cam-State Bank of India00000040914526721Savings.xlsx"
)


# ============================================================
# TEST
# ============================================================

def main():

    print("=" * 60)
    print("SALARY DETECTION TEST")
    print("=" * 60)

    print(f"\nCAM file:")
    print(CAM_FILE)

    if not CAM_FILE.exists():

        print(
            f"\nERROR: File not found:\n{CAM_FILE}"
        )

        return

    try:

        result = analyze_transactions(
            CAM_FILE
        )

        print("\nRESULT")
        print("-" * 60)

        print(
            json.dumps(
                result,
                indent=4,
                ensure_ascii=False
            )
        )

    except Exception as e:

        print("\nERROR")
        print("-" * 60)

        print(
            f"{type(e).__name__}: {e}"
        )

        raise


if __name__ == "__main__":
    main()