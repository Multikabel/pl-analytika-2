from pathlib import Path
import runpy
import subprocess
import sys

BASE = Path(__file__).resolve().parent
required = [
    BASE / "models" / "fouls_model.joblib",
    BASE / "models" / "corners_model.joblib",
    BASE / "models" / "yellow_cards_model.joblib",
]

if not all(p.exists() for p in required):
    result = subprocess.run(
        [sys.executable, str(BASE / "scripts" / "train_count_models.py")],
        cwd=BASE,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Automatic model training failed:\n"
            + result.stdout[-2000:] + "\n" + result.stderr[-2000:]
        )

runpy.run_path(str(BASE / "app" / "app.py"), run_name="__main__")
