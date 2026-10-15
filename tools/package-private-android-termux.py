#!/usr/bin/env python3
"""Add a locally generated Zelda library to the already built LASRecomp APK.

Runs in native Termux, never in proot. No Switch game data or libraries are
uploaded; the resulting signed APK stays on the user's Android device.
"""
import argparse
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
GAME = ROOT / "build/private-android-lasgame-termux/liblasgame.so"
APK_ENTRY = "lib/arm64-v8a/liblasgame.so"
REQUIRED_APK = (
    "AndroidManifest.xml",
    "classes.dex",
    "lib/arm64-v8a/libSDL3.so",
    "lib/arm64-v8a/libmain.so",
    "lib/arm64-v8a/liblasrecomp_runtime.so",
    "lib/arm64-v8a/liblasrecomp_prepare.so",
)
SIGNATURE_SUFFIXES = (".RSA", ".DSA", ".EC", ".SF")


def fail(message):
    raise SystemExit("ERRO: " + message)


def command(name):
    path = shutil.which(name)
    if not path:
        fail(f"ferramenta {name} ausente. No Termux: pkg install zipalign apksigner openjdk-21")
    return path


def run(*args):
    print("Executando:", args[0], "...", flush=True)
    subprocess.run(args, check=True)


def game_library_valid(path):
    if not path.is_file() or path.stat().st_size < 1024:
        fail(f"liblasgame.so nao encontrada: {path}. Aguarde a compilacao terminar.")
    with path.open("rb") as fd:
        hdr = fd.read(64)
    if hdr[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<H", hdr, 18)[0] != 183:
        fail("liblasgame.so nao e ELF Android ARM64 (AArch64).")
    nm = shutil.which("llvm-nm") or shutil.which("nm")
    if not nm:
        fail("llvm-nm nao encontrado; verifique clang/llvm no Termux")
    proc = subprocess.run([nm, "-D", "--defined-only", str(path)], text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode or not any(line.split()[-1] == "lasgame_tables"
                                  for line in proc.stdout.splitlines() if line.split()):
        fail("liblasgame.so sem simbolo exportado lasgame_tables")


def verify_apk(archive):
    with zipfile.ZipFile(archive, "r") as apk:
        names = set(apk.namelist())
        missing = [name for name in REQUIRED_APK if name not in names]
        if missing:
            fail("APK base incompleto, faltam: " + ", ".join(missing))
        if APK_ENTRY in names:
            fail("APK base ja inclui liblasgame.so: use o APK publico sem codigo de jogo")
        if apk.testzip() is not None:
            fail("APK base danificado (erro de CRC)")


def prepare_base(path, temp):
    if not path.is_file():
        fail(f"APK ou ZIP do GitHub nao encontrado: {path}")
    if path.suffix.lower() == ".apk":
        verify_apk(path)
        return path
    if path.suffix.lower() != ".zip":
        fail("Informe o APK base ou o ZIP do artefato do GitHub Actions")
    with zipfile.ZipFile(path) as artifact:
        apks = [name for name in artifact.namelist() if name.lower().endswith(".apk")
                and not name.endswith("/")]
        if len(apks) != 1:
            fail("O ZIP do GitHub deve conter exatamente um APK")
        output = temp / "base.apk"
        with artifact.open(apks[0]) as src, output.open("wb") as dst:
            shutil.copyfileobj(src, dst, 1024 * 1024)
    verify_apk(output)
    return output


def strip_old_signature(name):
    upper = name.upper()
    if not upper.startswith("META-INF/"):
        return False
    part = upper.rsplit("/", 1)[-1]
    return part == "MANIFEST.MF" or part.startswith("SIG-") or part.endswith(SIGNATURE_SUFFIXES)


def inject(base_apk, unsigned, game_so):
    # Rebuild rather than editing an already v2/v3-signed ZIP in place:
    # this strips its obsolete APK Signing Block and old v1 signatures.
    with zipfile.ZipFile(base_apk, "r") as src, zipfile.ZipFile(unsigned, "w", allowZip64=True) as dst:
        for info in src.infolist():
            if strip_old_signature(info.filename):
                continue
            with src.open(info, "r") as inp, dst.open(info, "w") as out:
                shutil.copyfileobj(inp, out, 1024 * 1024)
        info = zipfile.ZipInfo(APK_ENTRY)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.file_size = game_so.stat().st_size
        info.external_attr = 0o100644 << 16
        with game_so.open("rb") as inp, dst.open(info, "w") as out:
            shutil.copyfileobj(inp, out, 1024 * 1024)


def main():
    parser = argparse.ArgumentParser(description="Preparar APK privado LASRecomp + Zelda ARM64 no Termux")
    parser.add_argument("base", type=Path, help="APK publico do GitHub Actions ou ZIP do artefato")
    parser.add_argument("--game-so", type=Path, default=GAME, help="liblasgame.so gerada no aparelho")
    parser.add_argument("--output", type=Path, default=Path("/storage/emulated/0/Download/LASRecomp-Zelda-PRIVADO.apk"),
                        help="Caminho do APK privado assinado")
    args = parser.parse_args()
    if not os.path.isdir("/data/data/com.termux/files/usr") or os.uname().machine != "aarch64":
        fail("execute no Termux ARM64, fora do Ubuntu/proot")
    game = args.game_so.expanduser().resolve()
    base = args.base.expanduser().resolve()
    output = args.output.expanduser().resolve()
    game_library_valid(game)
    if output in (game, base):
        fail("Saida do APK nao pode substituir o jogo nem o APK base")
    zipalign = command("zipalign")
    apksigner = command("apksigner")
    keytool = command("keytool")
    output.parent.mkdir(parents=True, exist_ok=True)
    build = ROOT / "build"
    build.mkdir(parents=True, exist_ok=True)
    need = 3 * (game.stat().st_size + base.stat().st_size) + (512 * 1024 * 1024)
    free = shutil.disk_usage(build).free
    if free < need:
        fail(f"armazenamento insuficiente: livre {free // (1024**2)} MiB; "
             f"estimado minimo {need // (1024**2)} MiB")
    keystore = Path.home() / ".lasrecomp-android-debug.keystore"
    with tempfile.TemporaryDirectory(prefix="lasrecomp-private-", dir=build) as d:
        temp = Path(d)
        actual_base = prepare_base(base, temp)
        unsigned = temp / "unsigned.apk"
        aligned = temp / "aligned.apk"
        signed = temp / "signed.apk"
        print("[1/4] Inserindo a biblioteca privada do Zelda sem alterar os originais", flush=True)
        inject(actual_base, unsigned, game)
        print("[2/4] Alinhando APK", flush=True)
        run(zipalign, "-f", "4", str(unsigned), str(aligned))
        if not keystore.exists():
            print("[3/4] Criando chave debug privada local", flush=True)
            run(keytool, "-genkeypair", "-noprompt", "-keystore", str(keystore),
                "-storepass", "android", "-keypass", "android", "-alias", "androiddebugkey",
                "-keyalg", "RSA", "-keysize", "2048", "-validity", "10000",
                "-dname", "CN=LASRecomp Android Debug,O=RetroAura,C=BR")
            keystore.chmod(0o600)
        else:
            print("[3/4] Reutilizando chave debug local", flush=True)
        print("[4/4] Assinando e verificando APK privado", flush=True)
        run(apksigner, "sign", "--ks", str(keystore), "--ks-key-alias", "androiddebugkey",
            "--ks-pass", "pass:android", "--key-pass", "pass:android",
            "--out", str(signed), str(aligned))
        run(apksigner, "verify", "--verbose", str(signed))
        with zipfile.ZipFile(signed) as apk:
            if APK_ENTRY not in apk.namelist() or not set(REQUIRED_APK).issubset(apk.namelist()):
                fail("Verificacao final: faltam bibliotecas no APK assinado")
        # Download/ is emulated shared storage (a different mount from Termux).
        # os.replace(signed, output) raises EXDEV across those mounts.
        # Copy to a temporary sibling, then atomically rename inside Download/.
        output_tmp = None
        try:
            with tempfile.NamedTemporaryFile(prefix=".lasrecomp-private-",
                                             suffix=".apk.partial",
                                             dir=output.parent,
                                             delete=False) as staged:
                output_tmp = Path(staged.name)
                with signed.open("rb") as source:
                    shutil.copyfileobj(source, staged, 1024 * 1024)
            run(apksigner, "verify", "--verbose", str(output_tmp))
            os.replace(output_tmp, output)
            output_tmp = None
        finally:
            if output_tmp is not None:
                output_tmp.unlink(missing_ok=True)
    print("APK PRIVADO PRONTO:", output, flush=True)
    print("Este APK inclui codigo do seu jogo: NAO envie/publice no GitHub.")
    print("Se ja instalou outro APK com assinatura diferente, o Android exigira desinstala-lo primeiro.")
    print("O primeiro boot ainda precisa ser testado; isto nao comprova que Zelda roda.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, subprocess.CalledProcessError, zipfile.BadZipFile) as exc:
        fail(str(exc))
