#!/data/data/com.termux/files/usr/bin/python3
"""Extrai as funcoes reais associadas ao 30/60 FPS do Zelda, somente leitura.

Utiliza main_table.c para identificar a funcao que contem cada endereco;
enderecos de instrucao/labels nao precisam ser entradas de funcao.
Nao altera codigo gerado, jogos, mods, caches nem APK.
"""
from bisect import bisect_right
from pathlib import Path
import os
import re
import sys

root = Path(os.environ.get("LASRECOMP_WORKSPACE", str(Path.home() / "lasrecomp-android-gen")))
directory = root / "build/gamecode/main"
table_file = directory / "main_table.c"
destination = Path("/storage/emulated/0/Download/LASRecomp/framepace-funcoes.txt")
if not table_file.is_file():
    sys.exit(f"ERRO: tabela do codigo gerado nao encontrada: {table_file}")

table = table_file.read_text(encoding="utf-8", errors="replace")
match = re.search(r"const uint64_t main_fn_addrs\[\]\s*=\s*\{(.*?)\};", table, re.S)
if not match:
    sys.exit("ERRO: main_fn_addrs ausente na tabela do jogo.")
starts = [int(v, 16) for v in re.findall(r"0x([0-9a-fA-F]+)ull", match.group(1))]
if not starts or starts != sorted(set(starts)):
    sys.exit("ERRO: tabela de funcoes invalida.")

# Include the interval setter, the previously inspected frame-timer, the
# directly called timing helper and the two instruction sites from Stable60.
targets = [
    ("frame timer", 0x700000c910),
    ("swap-interval setter", 0x7000017800),
    ("frame-timer helper", 0x700101f820),
    ("counter address (not necessarily a function)", 0x700101fb7c),
    ("Stable60 instruction #1", 0x7001019608),
    ("Stable60 instruction #2", 0x7001019628),
]
locations = {}
for description, address in targets:
    i = bisect_right(starts, address) - 1
    if i < 0:
        continue
    entry = starts[i]
    upper = starts[i + 1] if i + 1 < len(starts) else None
    if upper is not None and address >= upper:
        continue
    locations.setdefault(entry, []).append((description, address))

files = sorted(directory.glob("main_[0-9][0-9][0-9].c"))
if not files:
    sys.exit(f"ERRO: nao existem arquivos main_###.c em {directory}")

definition = re.compile(r"(?m)^void f_([0-9a-f]+)\(Cpu \*c\) \{[ \t]*$")
end_function = re.compile(r"(?m)^}[ \t]*$")
found = {}
for path in files:
    data = path.read_text(encoding="utf-8", errors="replace")
    for fn_match in definition.finditer(data):
        addr = int(fn_match.group(1), 16)
        if addr not in locations or addr in found:
            continue
        end = end_function.search(data, fn_match.end())
        if end:
            found[addr] = (path.name, data[fn_match.start():end.end()])

lines = [
    "Extraido dos arquivos privados ja gerados; somente leitura.",
    "Os nomes f_... representam o inicio das funcoes; enderecos no meio nao viram novas funcoes.",
    f"Workspace: {directory}",
    "",
]
for entry, entries in locations.items():
    lines.append(f"===== f_{entry:x} =====")
    lines.extend(f"Alvo: {label}: 0x{address:x}" for label, address in entries)
    if entry in found:
        filename, body = found[entry]
        lines.append("Arquivo: " + filename)
        lines.append(body)
    else:
        lines.append("ATENCAO: funcao nao encontrada nos arquivos C gerados.")
    lines.append("")
not_found = [entry for entry in locations if entry not in found]
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("ARQUIVO GERADO:", destination)
print(f"Funcoes localizadas: {len(found)}/{len(locations)}")
for entry in not_found:
    print(f"AVISO: f_{entry:x} ausente no codigo gerado")
print("Nenhum codigo, mod, objeto ou APK foi alterado.")
