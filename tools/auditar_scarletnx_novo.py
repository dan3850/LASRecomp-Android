#!/usr/bin/env python3
"""Read-only compatibility audit for a clean ScarletNX upstream checkout."""
from pathlib import Path
import re
import subprocess
import sys

if len(sys.argv) != 2:
    raise SystemExit("Uso: python3 tools/auditar_scarletnx_novo.py CAMINHO_SCARLETNX")
src = Path(sys.argv[1]).expanduser().resolve()
root = Path(__file__).resolve().parent.parent
if not (src / ".git").exists():
    raise SystemExit(f"Checkout ScarletNX nao encontrado: {src}")
rev = subprocess.check_output(["git", "-C", str(src), "rev-parse", "HEAD"], text=True).strip()
status = subprocess.check_output(["git", "-C", str(src), "status", "--porcelain"], text=True).strip()
print(f"ScarletNX commit: {rev}")
print(f"Checkout limpo: {'SIM' if not status else 'NAO'}")
print("Analise somente leitura; nenhum patch aplicado.")
patches = sorted((root / "tools").glob("patch_scarletnx*.py"))
for script in patches:
    source = script.read_text(errors="replace")
    paths = sorted(set(re.findall(r"""['"]((?:src|dist|cmake)/[^'"\n]+?\.(?:c|h|cpp|hpp|glsl|java|cmake))['"]""", source)))
    absent = [p for p in paths if not (src / p).exists()]
    print(f"{script.name}: referencias={len(paths)} ausentes={len(absent)}")
    for p in absent[:15]:
        print(f"  AUSENTE: {p}")
print("ATENCAO: arquivo existente nao comprova compatibilidade do patch.")
print("Nenhum APK novo deve ser anunciado ate que RomFS, ABI, link e boot sejam validados.")
