"""The lock stays in step with requirements.txt (SECURITY.md): every direct requirement is pinned in requirements.lock
within its range and with hashes, and the lock holds no local paths."""
import re
from pathlib import Path

from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[1]


def requirements() -> list[Requirement]:
    lines = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    return [Requirement(line.split("#")[0].strip()) for line in lines if line.split("#")[0].strip()]


def lock() -> tuple[dict[str, str], str]:
    text = (ROOT / "requirements.lock").read_text(encoding="utf-8")
    pins = {m.group(1).lower().replace("_", "-"): m.group(2)
            for m in re.finditer(r"^([A-Za-z0-9_.-]+)==([^\s;\\]+)", text, re.M)}
    return pins, text


def test_every_requirement_is_pinned_in_the_lock_within_its_range():
    pins, _ = lock()
    for req in requirements():
        name = req.name.lower().replace("_", "-")
        assert name in pins, f"{req.name} is missing from requirements.lock: regenerate it (SECURITY.md)"
        assert req.specifier.contains(pins[name], prereleases=True), \
            f"{req.name}=={pins[name]} is outside {req.specifier}: regenerate requirements.lock"


def test_every_pin_has_a_hash_and_no_local_path_leaked():
    pins, text = lock()
    blocks = re.split(r"\n(?=[A-Za-z0-9_.-]+==)", text)
    assert len(pins) > 50 and all("--hash=sha256:" in b for b in blocks if re.match(r"[A-Za-z0-9_.-]+==", b))
    assert not re.search(r"[A-Za-z]:[\\/]|/home/|/Users/|AppData", text)
