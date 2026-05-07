"""
Patch Ryu SDN framework for Python 3.10+ compatibility.

Ryu uses collections.Callable, collections.Iterable, etc. which were removed
in Python 3.10. This script finds all ryu source files and rewrites them.
Run once after pip install ryu.
"""
import pathlib
import sys

REPLACEMENTS = [
    ("collections.Callable",       "collections.abc.Callable"),
    ("collections.Iterable",       "collections.abc.Iterable"),
    ("collections.Iterator",       "collections.abc.Iterator"),
    ("collections.Mapping",        "collections.abc.Mapping"),
    ("collections.MutableMapping", "collections.abc.MutableMapping"),
    ("collections.MutableSequence","collections.abc.MutableSequence"),
    ("collections.Sequence",       "collections.abc.Sequence"),
    ("collections.Set",            "collections.abc.Set"),
    ("collections.MutableSet",     "collections.abc.MutableSet"),
    ("collections.Generator",      "collections.abc.Generator"),
    ("collections.Coroutine",      "collections.abc.Coroutine"),
    ("collections.Awaitable",      "collections.abc.Awaitable"),
]

def find_ryu_root():
    try:
        import ryu as _ryu
        return pathlib.Path(_ryu.__file__).parent
    except ImportError:
        # Try site-packages
        for p in sys.path:
            candidate = pathlib.Path(p) / "ryu"
            if candidate.is_dir():
                return candidate
    return None

def patch_file(path: pathlib.Path) -> int:
    text = path.read_text(encoding="utf-8", errors="ignore")
    changed = 0
    for old, new in REPLACEMENTS:
        if old in text:
            text = text.replace(old, new)
            changed += 1
    if changed:
        path.write_text(text, encoding="utf-8")
    return changed

def patch_wsgi_already_handled(ryu_root: pathlib.Path):
    """Fix ALREADY_HANDLED removed from eventlet.wsgi in newer eventlet versions."""
    wsgi = ryu_root / "app" / "wsgi.py"
    if not wsgi.exists():
        return
    text = wsgi.read_text(encoding="utf-8")
    old = "    from eventlet.wsgi import ALREADY_HANDLED\n    _ALREADY_HANDLED = ALREADY_HANDLED"
    new = (
        "    try:\n"
        "        from eventlet.wsgi import ALREADY_HANDLED as _ALREADY_HANDLED\n"
        "    except ImportError:\n"
        "        _ALREADY_HANDLED = []"
    )
    if old in text:
        wsgi.write_text(text.replace(old, new), encoding="utf-8")
        print("  patched app/wsgi.py (ALREADY_HANDLED removed in newer eventlet)")


def main():
    ryu_root = find_ryu_root()
    if ryu_root is None:
        print("ryu not found in sys.path — install it first with: pip install ryu")
        sys.exit(1)

    print(f"Patching ryu at: {ryu_root}")
    total_files = 0
    for py_file in ryu_root.rglob("*.py"):
        n = patch_file(py_file)
        if n:
            print(f"  patched {py_file.relative_to(ryu_root)} ({n} replacements)")
            total_files += 1

    patch_wsgi_already_handled(ryu_root)

    if total_files == 0:
        print("  No patches needed (already clean or ryu already supports this Python).")
    else:
        print(f"\nPatched {total_files} files.")

    # Verify import
    try:
        import importlib
        import ryu  # noqa: F401
        importlib.invalidate_caches()
        print("ryu import: OK")
    except Exception as e:
        print(f"ryu import still failing: {e}")
        print("You may need to manually inspect the error above.")

if __name__ == "__main__":
    main()
