# Display driver profiles

The display startup helpers accept exact vendor binaries and verify the
build-id notes of loaded drivers. CMDQ platform/controller files must match
as a pair. A supported on-disk file does not authorize a different driver
already loaded from a boot ramdisk.

The original profile is retained. The ZUI `17.5.36.508` profile passed static
checks and a native Arch boot on TB311FU with `6.6.142-pmos-minimal+` on
2026-10-30. KWin enabled the internal panel at 1200x1920, 60 Hz, using atomic
modesetting and OpenGL ES 3.1 through Panfrost on the Mali-G52. This validates
startup and compositor rendering; suspend/resume and long-term scanout
reliability remain untested.

## Static checks

With the extracted early modules in `vendor-input/ramdisk/lib/modules/`,
the kernel built, and the scanout module built:

```sh
python3 scripts/check-vendor-abi.py build/kernel --report build/abi.json
python3 scripts/check-display-driver.py
```

The display checker requires Python `pyelftools`. It verifies whole-file
hashes, build-id note hashes, the framebuffer GEM-pointer accessor at
offset `0xc8`, the no-op framebuffer wait/prepare callbacks, the plane
helper table's prepare callback, its KCFI type against the replacement
callback, and the CMDQ platform callback table's relocations. It writes
`build/display-static-check.json`.

Disassembly of this build also shows:

- `mtk_drm_remove` gets the DRM device from the first pointer in the
  platform device's private data, as the scanout helper expects.
- `mtk_drm_gem_init` passes the allocated object's base to
  `drm_gem_object_init`.
- `mtk_gem_prime_import` calls `drm_gem_prime_import_dev`; the configured
  kernel's implementation assigns the shared dma-buf reservation to
  `obj->resv`.
- The configured kernel has a 200-byte `drm_framebuffer` and an 80-byte
  `drm_plane_helper_funcs`, with `prepare_fb` at offset zero. The helper's
  framebuffer size assertions and callback type check pass.

These checks cover the existing helper's binary assumptions, not every
possible runtime interaction. The broader stock-module audit found an
unresolved `calc_eff_hook` import in `mtk_em.ko`; it must not be included
as a required boot module without resolving that dependency.

## Runtime checks and remaining validation

The native installation required legacy LZ4 for both replacement ramdisks:
the retained Lenovo recovery fragment also uses legacy LZ4, and the kernel's
legacy decoder does not accept a following gzip stream as another LZ4 block.
Early modules were loaded explicitly in dependency order; the minimal
BusyBox modprobe path attempted some consumers before their providers.

The desktop account needs the `video`, `input`, `render`, `audio`, and
`netdev` groups. Without display-device permissions KWin started with a
placeholder output even though the panel connector was present. The Arch
launcher also creates missing bind-mount targets before entering systemd.

Test the exact matching module files and early-boot ramdisk together.
Display startup, the native panel mode, and Panfrost rendering passed.
Scanout fence/error counters and display suspend/resume still need testing.
Unknown hashes and
loaded-driver mismatches remain hard failures; do not bypass the guards
to make a test proceed.
