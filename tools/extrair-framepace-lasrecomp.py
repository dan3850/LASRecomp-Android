#!/data/data/com.termux/files/usr/bin/python3
"""Extract ONLY the generated Zelda frame-pacing functions for review.

Does not change any source, cache, mod, game code or APK.
"""
from pathlib import Path
import os
import re
import sys

root = Path(os.environ.get("LASRECOMP_WORKSPACE", str(Path.home() / "lasrecomp-android-gen")))
source_dir = root / "build" / "gamecode" / "main"
destination = Path("/storage/emulated/0/Download/LASRecomp/framepace-funcoes.txt")
if not source_dir.is_dir():
    sys.exit(f"ERRO: pasta do codigo gerado nao encontrada: {source_dir}")

target_names = {"f_700000c910", "f_700101fb7c"}
target_sites = ("0x7001019608", "0x7001019628")
definition = re.compile(r"(?m)^void (f_[0-9a-f]+)\(Cpu \*c\) \{\s*$")
end_function = re.compile(r"(?m)^}\s*$")
found = set()
sections = [
    "Extracao somente-leitura do codigo recompilado; nenhum arquivo do jogo foi modificado.",
    "Funcoes: f_700000c910 (frame pacing), f_700101fb7c (contador GPU),",
    "e funcoes contendo os dois pontos do Stable 60fps v2.",
    "",
]
files = sorted(source_dir.glob("main_[0-9][0-9][0-9].c"))
if not files:
    sys.exit(f"ERRO: nao foram encontrados main_###.c em {source_dir}")
references = []
for path in files:
    body = path.read_text(encoding="utf-8", errors="replace")
    for match in definition.finditer(body):
        end = end_function.search(body, match.end())
        if not end:
            continue
        fn = match.group(1)
        snippet = body[match.start():end.end()]
        wanted = fn in target_names or (
            "rt_mod_nop" in snippet and any(site in snippet for site in target_sites)
        )
        if wanted:
            found.add(fn)
            sections.extend([f"===== {path.name}: {fn} =====", snippet, ""])
    for lineno, line in enumerate(body.splitlines(), 1):
        if any(name + "(c)" in line for name in target_names):
            references.append(f"{path.name}:{lineno}: {line.strip()[:260]}")

sections.append("===== chamadas aos alvos (primeiras 80) =====")
sections.extend(references[:80])
sections.append("")
missing = target_names - found
if missing:
    sections.append("FUNCOES NAO LOCALIZADAS: " + ", ".join(sorted(missing)))
    sections.append("Verifique se esse workspace foi gerado com a versao correta do jogo.")
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_text("\n".join(sections) + "\n", encoding="utf-8")
print(f"ARQUIVO GERADO: {destination}")
print(f"Funcoes encontradas: {', '.join(sorted(found)) if found else 'nenhuma'}")
print("Nenhuma compilacao ou alteracao no projeto foi feita.")
