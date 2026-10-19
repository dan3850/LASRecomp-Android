#!/usr/bin/env python3
"""Resolve pinned GPL RadialGamePad / AndroidX dependencies for Termux.

No Gradle / x86_64 Android SDK executables needed. Files are downloaded once,
verified as ZIP artifacts, and reused from the persistent Termux cache.
Manifest format: '<type>\t<absolute path>\t<Android resource namespace>'.
"""
import os
import pathlib
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

MAVEN = (
    "https://dl.google.com/dl/android/maven2",
    "https://repo.maven.apache.org/maven2",
    "https://jitpack.io",
)

# Deliberately pinned. Includes the original RadialGamePad, its direct runtime
# dependencies and the AndroidX/core Kotlin JVM runtime used by those classes.
# AndroidX AAR resources are compiled separately by aapt2 in the parent script.
ARTIFACTS = (
    ("com.github.swordfish90", "radialgamepad", "2.0.0", "aar"),
    ("androidx.core", "core", "1.9.0", "aar"),
    ("androidx.core", "core-ktx", "1.9.0", "aar"),
    ("androidx.customview", "customview", "1.1.0", "aar"),
    ("androidx.appcompat", "appcompat", "1.5.1", "aar"),
    ("androidx.appcompat", "appcompat-resources", "1.5.1", "aar"),
    ("androidx.annotation", "annotation", "1.5.0", "jar"),
    ("androidx.collection", "collection", "1.2.0", "jar"),
    ("androidx.activity", "activity", "1.5.1", "aar"),
    ("androidx.fragment", "fragment", "1.5.4", "aar"),
    ("androidx.lifecycle", "lifecycle-runtime", "2.5.1", "aar"),
    ("androidx.lifecycle", "lifecycle-runtime-ktx", "2.5.1", "aar"),
    ("androidx.lifecycle", "lifecycle-common", "2.5.1", "jar"),
    ("androidx.lifecycle", "lifecycle-viewmodel", "2.5.1", "aar"),
    ("androidx.lifecycle", "lifecycle-viewmodel-ktx", "2.5.1", "aar"),
    ("androidx.lifecycle", "lifecycle-livedata-core", "2.5.1", "aar"),
    ("androidx.lifecycle", "lifecycle-livedata-core-ktx", "2.5.1", "aar"),
    ("androidx.savedstate", "savedstate", "1.2.0", "aar"),
    ("androidx.savedstate", "savedstate-ktx", "1.2.0", "aar"),
    ("androidx.arch.core", "core-common", "2.1.0", "jar"),
    ("androidx.arch.core", "core-runtime", "2.1.0", "aar"),
    ("androidx.versionedparcelable", "versionedparcelable", "1.1.1", "aar"),
    ("androidx.cursoradapter", "cursoradapter", "1.0.0", "aar"),
    ("androidx.drawerlayout", "drawerlayout", "1.1.1", "aar"),
    ("androidx.coordinatorlayout", "coordinatorlayout", "1.2.0", "aar"),
    ("androidx.vectordrawable", "vectordrawable", "1.1.0", "aar"),
    ("androidx.vectordrawable", "vectordrawable-animated", "1.1.0", "aar"),
    ("androidx.transition", "transition", "1.4.1", "aar"),
    ("androidx.interpolator", "interpolator", "1.0.0", "aar"),
    ("androidx.loader", "loader", "1.0.0", "aar"),
    ("androidx.viewpager", "viewpager", "1.0.0", "aar"),
    ("androidx.recyclerview", "recyclerview", "1.2.1", "aar"),
    ("androidx.emoji2", "emoji2", "1.2.0", "aar"),
    ("androidx.emoji2", "emoji2-views-helper", "1.2.0", "aar"),
    ("androidx.startup", "startup-runtime", "1.1.1", "aar"),
    ("androidx.tracing", "tracing", "1.1.0", "aar"),
    ("androidx.concurrent", "concurrent-futures", "1.1.0", "jar"),
    ("androidx.profileinstaller", "profileinstaller", "1.2.0", "aar"),
    ("org.jetbrains.kotlin", "kotlin-stdlib", "1.6.21", "jar"),
    ("org.jetbrains.kotlin", "kotlin-stdlib-common", "1.6.21", "jar"),
    ("org.jetbrains.kotlin", "kotlin-stdlib-jdk7", "1.6.21", "jar"),
    ("org.jetbrains.kotlin", "kotlin-stdlib-jdk8", "1.6.21", "jar"),
    ("org.jetbrains.kotlinx", "kotlinx-coroutines-core-jvm", "1.6.4", "jar"),
    ("org.jetbrains.kotlinx", "kotlinx-coroutines-android", "1.6.4", "jar"),
    ("org.jetbrains", "annotations", "13.0", "jar"),
)

def fetch(group, name, version, extension, cache):
    relative = "/".join((group.replace(".", "/"), name, version,
                         f"{name}-{version}.{extension}"))
    target = cache / relative
    if target.is_file() and zipfile.is_zipfile(target):
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    errors = []
    for base in MAVEN:
        url = f"{base}/{relative}"
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "LASRecomp-Android-Termux/1.0"})
            with urllib.request.urlopen(req, timeout=45) as response:
                with tempfile.NamedTemporaryFile(dir=target.parent,
                                                 delete=False) as tmp:
                    temp_name = tmp.name
                    while True:
                        chunk = response.read(256 * 1024)
                        if not chunk:
                            break
                        tmp.write(chunk)
            if not zipfile.is_zipfile(temp_name):
                os.unlink(temp_name)
                raise ValueError("arquivo nao e ZIP/JAR/AAR")
            os.replace(temp_name, target)
            return target
        except (OSError, ValueError, urllib.error.URLError) as exc:
            errors.append(f"{base}: {exc}")
            if 'temp_name' in locals() and os.path.exists(temp_name):
                os.unlink(temp_name)
    raise RuntimeError(f"Falha ao obter {relative}: " + "; ".join(errors))

def main():
    if len(sys.argv) != 2:
        raise SystemExit("Uso: neo_radial_deps.py DIRETORIO_CACHE")
    cache = pathlib.Path(sys.argv[1]).expanduser().resolve()
    for group, name, version, extension in ARTIFACTS:
        target = fetch(group, name, version, extension, cache)
        package = "-"
        if extension == "aar":
            with zipfile.ZipFile(target) as archive:
                try:
                    manifest = archive.read("AndroidManifest.xml")
                    found = re.search(rb'\bpackage\s*=\s*["\\']([^"\\']+)', manifest)
                    package = found.group(1).decode("utf-8") if found else group
                except KeyError:
                    package = group
            if name == "radialgamepad" and package == group:
                package = "com.swordfish.radialgamepad.library"
        print(f"{extension}\t{target}\t{package}", flush=True)

if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERRO: dependencias Neo: {error}", file=sys.stderr)
        raise SystemExit(1)
