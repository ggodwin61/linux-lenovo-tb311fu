# Camera and document scanning

The native camera backend is experimental and device-specific. It uses the
vendor ISP interface rather than providing a general V4L2/libcamera camera.
Do not remove its kernel, module-hash, loaded-driver, sensor, or memory checks.

On the tested TB311FU with ZUI 17.5.36.508 vendor modules, the GC05A2 front
sensor and SC820CS rear sensor both captured frames successfully. The latter
reports driver index 0 and ID `0xd154`; it differs from the GC08A8 rear sensor
supported by the original capture code. Sensor identities remain explicit
allowlists. Unknown variants are rejected.

The matching vendor driver's `get_info` and `get_resolution` routines identify
the front preview as GRBG, 1296x972 on two lanes, and the rear preview as BGGR,
1632x1224 on four lanes. Treating both as RGGB put red into green channels.
The preview now decodes each sensor's layout and no longer applies aggressive
scene-wide gray-world gains. Twelve independent synthetic channel tests and
the front sensor's hardware color bars passed. This corrects channel ordering;
it is not factory-calibrated color processing.

SC820CS also needs its driver-specific streaming-resume feature (`0xc20`)
after preview setup, followed by streaming-suspend (`0xc1f`) during cleanup.
The exact vendor feature table and streaming-control routine were checked
before using these commands. Its test-pattern mode was not validated and is
rejected; the GC05A2 color-bar selector was verified separately. Normal rear
frames were validated using image statistics without viewing the scene.

The original and newer versions of all four camera modules were compared
section by section. Code, data, symbol tables, and relocations were identical;
only `.modinfo` and the build-id note differed. Both complete driver sets
have explicit hash profiles, including checks against loaded build-id notes.
Unknown or mixed sets remain rejected.

## Setup

Install `python-pyqt6`, `python-numpy`, and `zram-generator` with the Plasma
profile. The overlay includes compressed RAM swap, sized at half RAM, and a
sudoers template for the selected account. Stage the overlay with
`scripts/stage-rootfs.py` so `@USER@` is rendered. Camera helpers and their
parent directories must be root-owned and not writable by the desktop user;
the rendered sudoers file must be root-owned with mode `0440` and pass
`visudo -c`. Only the two exact isolated Python camera-preview commands
receive passwordless access. Normal administrator commands still require
the account password.

The vendor ISP initialization has an unsafe failure path: an allocation
failure under memory pressure was followed by a watchdog fault referencing
the unloaded driver. Compressed swap is configured to reduce memory pressure,
and the helper rejects startup with insufficient available memory or too
few contiguous blocks. These are mitigations, not a repair of the vendor
driver's cleanup path. Do not repeatedly retry a failed driver load.

## Apps

**Camera** starts on the rear camera and saves JPEG photos. **Switch camera**
selects the front or rear sensor; stale frames are discarded while switching.
The rear starts at 90 degrees and the front at 270 degrees; manual rotation
is remembered separately for each sensor during the app session.
**Document Scanner** uses the same backend: rotate the preview if necessary, select
**Add page** for each page, and choose **Save PDF**. **Remove last** removes
the most recent captured page. The default save location is
`Documents/Scans`. Pages are fitted to A4 without stretching, and the PDF
is committed atomically after export succeeds.

This is a basic image-to-PDF workflow. The front preview is 648x486 pixels and
the rear preview is 816x612 pixels;
check document legibility before relying on a scan. It has no OCR or
automatic perspective correction. A synthetic two-page export was checked
with Poppler and visually rendered; normal-user camera preview and page
addition/removal also passed an off-screen GUI test with both sensors.

The rear camera hardware supports autofocus, but the current capture backend
does not control the lens actuator or run an autofocus algorithm. The front
camera is fixed-focus. Captured frames should not be described as autofocus-
validated. See [Lenovo's camera specifications](https://psref.lenovo.com/syspool/Sys/PDF/Lenovo_Tablets/Lenovo_Tab/Lenovo_Tab_Spec.html?ver=e79372a9-438b-426a-b627-4042fba68dd0).

References for sensor layout and test patterns:

- [GC05A2 upstream driver](https://linux.googlesource.com/linux/kernel/git/torvalds/linux/+/077ab8985ee278c3d8618182d335b0f0cd919e16/drivers/media/i2c/gc05a2.c)
- [GC05A2 datasheet](https://lists.infradead.org/pipermail/linux-mediatek/attachments/20240413/0eaf8425/attachment-0001.pdf)
- [MediaTek sensor format enums](https://android.googlesource.com/kernel/mediatek/+/android-mtk-3.18/drivers/misc/mediatek/imgsensor/inc/kd_imgsensor_define.h)
