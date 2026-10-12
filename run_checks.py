from pathlib import Path
import subprocess
import sys
root = Path(__file__).resolve().parent
failed = []
for test in [root / "selftest.py", *sorted(root.glob("TEST_*.py"))]:
    result = subprocess.run([sys.executable, str(test)], cwd=root)
    print(test.name, "PASS" if result.returncode == 0 else "FAIL", flush=True)
    if result.returncode:
        failed.append(test.name)
print("FAILED: " + ", ".join(failed) if failed else "ALL CHECKS PASSED")
sys.exit(bool(failed))
