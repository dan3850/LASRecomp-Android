# Zelda Android performance work

For Zelda performance or nxnative adaptation work on
`experimental/zelda-links-awakening-ryujinx-nativeaot`, read
[`docs/zelda-performance-handoff.md`](docs/zelda-performance-handoff.md)
before making changes. Keep that handoff current after each delivered task,
and report remaining work to the user. Clearly distinguish implementation,
host validation, user feedback and measured Android results.

Preserve the working ScarletNX path, Stable60, AOT artifacts and build caches.
Do not change stable branches, run `git clean`, delete caches, regenerate the
game AOT without a demonstrated need, remove correctness checks or skip
required graphics. The user builds in Termux and tests on a RedMagic 11 Pro;
give exact incremental build commands after validated code is published.
Do not claim an FPS gain from host tests. Keep each change reversible and
retain a comparison against the last user-approved build.
