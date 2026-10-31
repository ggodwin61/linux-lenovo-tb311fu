# VS Code development

Open `linux-lenovo-tb311fu.code-workspace` on the Linux build computer.
The workspace recommends Python, C/C++, and Remote SSH extensions.
Generated images, firmware inputs, downloads, and local connection settings
are excluded from searches and file watching.

Use **Terminal → Run Task** for kernel, module, and userspace builds or the
vendor ABI, display-profile, and camera color checks. The camera checks
require Python NumPy and run without accessing a camera. **Ctrl+Shift+B** builds userspace
helpers. Kernel tasks use the toolchain paths documented in [Build](build.md);
`KERNEL_SRC`, `CLANG_BIN`, and `KERNEL_OUT` can override their defaults.

For on-device development, use VS Code Remote SSH with the tablet's USB
network address, `172.16.42.1`. Use the regular desktop account, `alarm`,
and configure authentication locally. Hostnames, private keys, and SSH
configuration belong outside version control. Build kernel modules on the
build computer with the matching kernel sources and Android toolchain.

Before publishing changes, review the explicit source-file diff. Generated
images, vendor firmware/modules, device backups, diagnostic logs, and SSH
keys remain local. A source checkout is not a complete flashable installer.
Preserve upstream attribution and the notices in [Licensing](../LICENSES.md).
