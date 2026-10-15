# Bun Source And Relinking

OpenAlma redistributes the official, unmodified Windows x64 baseline Bun
1.3.14 executable. It runs as a separate process, not as code linked into
OpenAlma. The installer includes its notices; these source materials are
separate downloads for developers who want to inspect, modify or relink Bun.

## Corresponding Sources

`bun-sources.json` records immutable source revisions and notice paths. The
three accompanying `*-source.tar.gz` files contain the complete upstream Bun,
patched WebKit and TinyCC trees, including their build scripts and licenses.
`BUN-SHA256SUMS` records the staged files' SHA256 hashes. Other dependency pins
and patches are in Bun's `scripts/build/deps/`, `patches/` and lockfiles; its
build tools retrieve those dependencies, including Rust and npm dependencies.
This is not an offline build kit.

The Bun source revision is `0d9b296af33f2b851fcbf4df3e9ec89751734ba4`;
WebKit is `5488984d20e0dbfe4be2c3ba8fb18eb81a5e0e8b`; TinyCC is
`12882eee073cfe5c7621bcfadf679e1372d4537b`. Sources and this document must be
published beside every installer that distributes this runtime. Do not publish
only the installer or rely on an expiring Actions artifact for source access.

## Rebuild With Modified Libraries

Follow the included Bun `docs/project/building-windows.mdx` and
`CONTRIBUTING.md` for the pinned version, not current-main instructions. Windows
requires bootstrap Bun, Visual Studio 2022 C++ tools/Windows SDK, LLVM 21.1.8,
Rust/Cargo, NASM, Python 3, Go, Perl, Ruby and Node. The scripts provision pinned
Zig and other build dependencies. Local WebKit additionally needs its documented
Make/Cygwin tools. This is a substantial developer build, never an installer step.

Extract Bun, and place the extracted matching WebKit tree at `vendor/WebKit`
inside it, or set `BUN_WEBKIT_PATH` to that tree. Keep Bun's TinyCC patch in
`patches/tinycc/tcc.h.patch`; the build scripts apply it to their pinned source.
Modify the library sources as desired. From Bun's source directory, load its
Visual Studio shell and use the local-WebKit build profile:

```powershell
.\scripts\vs-shell.ps1
bun scripts/build.ts --profile=release-local --baseline=on --lto=off --asan=off
```

For a CPU-baseline rebuild, the pinned Bun `scripts/build/deps/webkit.ts`
invocation of WebKit's `build-icu.ps1` must also forward `-Baseline` when
`cfg.baseline` is true; its upstream invocation omits this flag. Preserve that
change in any build recipe rather than silently using a Haswell ICU build.
See the matching WebKit `build-icu.ps1` and Bun's local WebKit build definition.

This command and the ICU adjustment are source-derived, not a build-verified
recipe. Native source/relink and third-party-notice review remain public-release
checks; staging artifacts alone does not certify license completeness. Do not
promise a byte-identical rebuild: rebuilding with modified libraries is the goal.
OpenAlma's own object files are not needed to rebuild the separate Bun executable.
