#!/usr/bin/env python3
"""Read-only audit of Mario's __nnmusl_init_dso support in this checkout.

Searches source files without requiring ripgrep, verifies which source files
reference the import, and reports likely resolver and bootstrap locations.
Does not modify the repository or claim runtime resolution from text matches.
"""
from pathlib import Path
import argparse

EXTENSIONS={".c",".cc",".cpp",".h",".hpp",".S",".s",".py",".rs",".txt",".md",".cmake"}
EXCLUDE={".git","build",".gradle",".cxx","node_modules","third_party","vendor"}
TERMS=("__nnmusl_init_dso","nnmusl","init_dso","JUMP_SLOT","DT_JMPREL","dlsym(","resolve_import","relocation")
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,default=Path("."))
    p.add_argument("--max-matches",type=int,default=100)
    a=p.parse_args()
    root=a.root.resolve()
    print(f"REPOSITORY={root}")
    counts={t:0 for t in TERMS}
    printed=0
    scanned=0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in EXTENSIONS:
            continue
        if any(part in EXCLUDE or part.startswith(".git") for part in path.relative_to(root).parts):
            continue
        if path.stat().st_size>2_000_000:
            continue
        scanned+=1
        try:
            lines=path.read_text(encoding="utf-8",errors="replace").splitlines()
        except OSError:
            continue
        for line_no,line in enumerate(lines,1):
            matches=[term for term in TERMS if term.lower() in line.lower()]
            if not matches: continue
            for term in matches: counts[term]+=1
            if printed<a.max_matches:
                print(f"MATCH {path.relative_to(root)}:{line_no}: {line.strip()[:200]}")
                printed+=1
    print(f"FILES_SCANNED={scanned}")
    for term,count in counts.items(): print(f"COUNT {term}={count}")
    print("NX_NNMUSL_SOURCE_AUDIT_OK")
    print("NOTE: textual matches cannot prove the runtime's symbol resolver behavior.")

if __name__=="__main__":
    main()
