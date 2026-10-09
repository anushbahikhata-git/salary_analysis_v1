from pathlib import Path

from src.graph.income_graph import income_graph


CAM_FILE = Path(
    "data/input/Harwansh-State Bank of India00000033995164086Savings.xlsx"
)


result = income_graph.invoke(
    {
        "cam_path": str(CAM_FILE)
    }
)


print("\n==============================")
print("INCOME GRAPH RESULT")
print("==============================")

print("\nIncome Decision:")
print(
    result.get(
        "income_decision"
    )
)

print("\nValidation:")
print(
    result.get(
        "validation"
    )
)

print("\nCAM Result:")
print(
    result.get(
        "cam_result"
    )
)