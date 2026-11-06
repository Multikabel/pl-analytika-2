from pathlib import Path
import runpy

# Startup never trains or repairs model artifacts. Missing models are handled by UI.
BASE = Path(__file__).resolve().parent
runpy.run_path(str(BASE / "app" / "app.py"), run_name="__main__")
