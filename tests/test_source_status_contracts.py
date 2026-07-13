from pathlib import Path
from runpy import run_path

_HERE = Path(__file__).resolve().parent
for _name in ("source_status_contracts_legacy.py", "market_intelligence_contracts.py"):
    for _key, _value in run_path(str(_HERE / _name)).items():
        if _key.startswith("test_"):
            globals()[_key] = _value
