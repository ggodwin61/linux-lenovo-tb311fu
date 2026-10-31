# Scripts

- `build-kernel`: build the configured Android Common kernel.
- `build-modules`: build and sign device modules with the kernel key.
- `build-userspace`: compile the boot init and battery library.
- `stage-rootfs.py`: assemble rootfs configuration for a selected account.
- `check-vendor-abi.py`: compare vendor module symbol CRCs.
- `check-display-driver.py`: verify the newer display profile's static binary assumptions (requires pyelftools; see [display notes](../docs/display.md)).
- `build-wifi-charging-driver.py`: patch the matching charging-boot Wi-Fi module.
- `build-adb-root.py`: build USB root adbd from pinned sources.
- `diagnostics/`: DRM capture, touch timing and display tracing on the tablet.
