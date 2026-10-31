#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""TB311FU ISP4 camera capture and local preview backend.

Register family reference: BayLibre/MediaTek ISP SENINF and vpavlin/mt8183-camera.
MT6768 CAMSV offsets come from Lenovo camera_isp_4_t.c, not MT8183 offsets.
This is bring-up tooling, not a V4L2/libcamera pipeline.
"""
import argparse
import ctypes as C
import fcntl
import json
import mmap
import os
from pathlib import Path
import runpy
import struct
import time
import sys
import signal
import hashlib

api = runpy.run_path(str(Path(__file__).with_name('camera-probe.py')))
feature = api['feature']
CamBuffer = api['CamBuffer']
load = api['load']

# Sensor identity, preview geometry, and Bayer order verified against the
# matching vendor driver's get_info/get_resolution routines.
SENSOR_PROFILES = {
    (1, 3, 0x5a2): ('GRBG', 1296, 972),
    (0, 1, 0x8a8): ('RGGB', 1632, 1224),
    (0, 0, 0xd154): ('BGGR', 1632, 1224),
}


class Registers:
    def __init__(self, fd, base, size):
        self.mem = mmap.mmap(fd, size, flags=mmap.MAP_SHARED,
                             prot=mmap.PROT_READ | mmap.PROT_WRITE, offset=base)

    def read(self, offset):
        return struct.unpack_from('I', self.mem, offset)[0]

    def write(self, offset, value):
        struct.pack_into('I', self.mem, offset, value)
        self.read(offset)  # drain the device write before dependent operations

    def update(self, offset, mask, value):
        self.write(offset, (self.read(offset) & ~mask) | (value & mask))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--preview', action='store_true')
    parser.add_argument('--frames', type=int, default=0)
    parser.add_argument('--camera', type=int, choices=(0, 1), default=0)
    parser.add_argument('--csi-port', type=int, choices=(0, 1, 2))
    parser.add_argument('--color-bars', action='store_true')
    parser.add_argument('--split', choices=('a', 'b'), default='b')
    parser.add_argument('--pak', type=int, choices=(0, 1, 2, 3), default=0)
    parser.add_argument('--format-register', type=lambda x: int(x, 0), default=1)
    args = parser.parse_args()
    if not args.preview and args.output is None:
        parser.error('--output or --preview is required')
    if args.pak != 0:
        parser.error('Only verified RAW8 transport is supported')
    def stop(*_):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    if os.uname().release != '6.6.142-pmos-minimal+' or os.geteuid() or b'MT8786' not in Path('/sys/firmware/devicetree/base/model').read_bytes():
        raise SystemExit('Requires the verified tablet kernel and root')
    lock = open('/run/lock/tb311fu-gpu-video', 'a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    api['require_capture_memory']()
    modules = api['verify_modules']()
    for name in modules:
        load(name)
    api['verify_modules']()
    sensor = os.open('/dev/kd_camera_hw', os.O_RDWR | os.O_CLOEXEC)
    isp = cm = dma = -1
    regs = []
    blocks = ()
    node = None
    opened = False
    streaming = False
    test_pattern = False
    s = p = v = image = None
    try:
        camera = args.camera
        index = int.from_bytes(feature(sensor, camera, 0xc23), 'little', signed=True)
        if index not in ({0, 1} if camera == 0 else {3}):
            raise RuntimeError(f'Unsupported camera driver index: {index}')
        feature(sensor, camera, 0xc21)
        opened = True
        sensor_id = int.from_bytes(feature(sensor, camera, 0xbe1), 'little')
        profile = SENSOR_PROFILES.get((camera, index, sensor_id))
        if profile is None:
            raise RuntimeError(f'Unexpected sensor ID {sensor_id:x}')
        bayer, w, h = profile
        if args.color_bars and sensor_id != 0x5a2:
            raise RuntimeError('Only the GC05A2 color-bar test pattern has been verified')
        isp = os.open('/dev/camera-isp', os.O_RDWR | os.O_CLOEXEC)
        s = Registers(isp, 0x1a040000, 0x8000)
        p = Registers(isp, 0x11c10000, 0x6000)
        v = Registers(isp, 0x1a050000, 0x1000)
        port = args.csi_port if args.csi_port is not None else (1 if camera == 0 else 0)
        phy_offset = port * 0x2000 if camera == 0 else (0 if args.split == 'a' else 0x1000)
        input_offset = phy_offset
        blocks = (0, 0x1000) if camera == 0 else (0,)
        # Window helpers keep the global SENINF top distinct from each input.
        pr = p.read
        p.read = lambda o: pr(o + phy_offset)
        p.write = lambda o, val: struct.pack_into('I', p.mem, o + phy_offset, val)
        p.update = lambda o, mask, val: p.write(o, (p.read(o) & ~mask) | (val & mask))
        sr = s.read
        s.read = lambda o: sr(o + (input_offset if 0x200 <= o < 0xd00 else 0))
        s.write = lambda o, val: struct.pack_into('I', s.mem, o + (input_offset if 0x200 <= o < 0xd00 else 0), val)
        regs = [s, p, v]
        if v.read(0x3c) != 0x20150120:
            raise RuntimeError('Unexpected CAMSV register family')
        heap = os.open('/dev/dma_heap/mtk_mm-uncached', os.O_RDWR | os.O_CLOEXEC)
        alloc = C.create_string_buffer(struct.pack('QIIQ', 8 << 20, 0, os.O_RDWR | os.O_CLOEXEC, 0), 24)
        try:
            fcntl.ioctl(heap, 0xc0184800, alloc)
        finally:
            os.close(heap)
        dma = struct.unpack('QIIQ', alloc.raw)[1]
        cm = os.open('/dev/camera-mem', os.O_RDWR | os.O_CLOEXEC)
        node = CamBuffer(dma, 0, b'tb311fu-frame', False, 0)
        fcntl.ioctl(cm, 0xc0584900, node)
        if not 0 < node.iova < 1 << 32:
            raise RuntimeError('CAMSV needs an address below 4 GiB')
        image = mmap.mmap(dma, 8 << 20, flags=mmap.MAP_SHARED,
                          prot=mmap.PROT_READ | mmap.PROT_WRITE)
        image[:] = b'\xa5' * (8 << 20)
        packed_width = w * 10 // 8
        bpl = ((packed_width + 15) // 16) * 16

        # CSI0A/B 4D1C: standard MTK lane order D2,D0,CLK,D1,D3.
        for block in blocks:
            p.update(block, 1 | (1 << 5) | (1 << 8) | (1 << 11), (1 << 8) if camera == 1 else ((1 << 11) if block == 0 else 0))
            p.update(block, (1 << 6) | (1 << 9) | (1 << 12), 0 if camera == 1 else ((1 << 6) | (1 << 9) | (1 << 12)))
            eq = ((0x18, 0xf000f0, 0x500050), (0x1c, 0xf0, 0x50)) if port == 1 else ((0x18, 0xf0, 0x50), (0x1c, 0xf00000, 0x500000), (0x20, 0xf00000, 0x500000))
            for reg, mask, value in (*eq, (0xa8, 7, 7), (0x24, 0xff000000, 0x40000000), (0x80, 0x30000, 0)):
                p.update(block + reg, mask, value)
        p.update(0x40, 0xf0, 0x90)
        for block in blocks:
            p.update(block, 8, 8)
        time.sleep(0.00004)
        for block in blocks:
            p.update(block, 4, 4)

        for block in blocks:
            calibration = ((0x18, 0x10001), (0x1c, 1)) if port == 1 else ((0x18, 1), (0x1c, 0x10000), (0x20, 0x10000))
            for reg, mask in calibration:
                p.update(block + reg, mask, mask)
            until = time.monotonic() + 0.005
            while not (p.read(block + 0x48) & (0x38 if port == 1 else 0x29)) and time.monotonic() < until:
                time.sleep(0.00003)
            for reg, mask in calibration:
                p.update(block + reg, mask, 0)

        s.write(0, 0xc00)
        s.write(0x1c if port == 0 else 0x20, 0x80001101 if camera == 1 else (0x80001200 if port == 0 else 0x80000200))
        s.update(8, 0xf, input_offset // 0x1000)
        s.write(0x10, 0)
        s.write(0x824, (s.read(0x824) & 0xffffff) | (0xe4000000 if camera == 1 else 0xc9000000))
        s.write(0x614, 0x67)
        s.write(0x600, 0)
        s.write(0x604, 1)
        s.write(0x200, 1)
        s.update(0x204, 0x60, 0x40)
        s.write(0xa0c, 0)
        s.write(0xa3c, 0xac)
        s.write(0xa44, 3)
        s.update(0xa08, 0xff00, 0x15 << 8)
        s.write(0xa00, (1 << 25) | (1 << 16) | (0x1f if camera == 0 else 0x13))
        s.update(0xa74, 0xc07, 3)
        s.update(0xae8, 0x7ff, 0)
        s.write(0xb20, 0x001dff00)
        s.update(0xa40, 0xff, 0x8)
        s.write(0xa18, 0x8000001a)
        s.update(0xa20, 1, 0)
        s.write(0xa10, 0xffffffff)
        s.write(0xa14, 0xffffffff)
        s.write(0xb10, 0x1f)
        s.update(0x200, 0x80, 0x80)
        s.update(0x200, 0x80, 0)
        s.write(0xd00, 0x80000000 | (2 << 28) | (0x1b << 22) | (0x1f << 16) | (8 << 12) | (1 << 8))
        s.write(0xd3c, 0x101)
        s.update(0xd00, 3, 3)
        s.update(0xd00, 3, 0)
        s.write(0xd2c, 0xc2000)

        # CAMSV1 transports the RAW10 packet bytes; software unpacks the image.
        for reg, val in ((0x500, 0), (0x508, packed_width << 16), (0x50c, h << 16),
                         (0x510, 0x1000), (0x20, 4), (0x20, 0), (0x20, 1)):
            v.write(reg, val)
        deadline = time.monotonic() + 0.1
        while v.read(0x20) != 3 and time.monotonic() < deadline:
            time.sleep(0.001)
        v.write(0x20, 0)
        for reg, val in ((0x18, 0), (0x10, 0x40000005), (0x14, args.format_register), (0x4c, args.pak | 0x10),
                         (0x230, packed_width - 1), (0x234, h - 1), (0x238, 0x1030000 | bpl),
                         (0x23c, 0x80000080), (0xe00, 0), (0x240, 0x4f004), (0x244, 0x2f002), (0x218, 0x61000000), (0x488, 0xffffffff), (0x220, node.iova),
                         (0x500, 0x10003), (0x10, 0x40000015), (0x30, 0x8005), (0x504, 1)):
            v.write(reg, val)
        fcntl.ioctl(sensor, 0xc0186914, struct.pack('IIQQ', camera, 0, 0, 0))
        if args.color_bars:
            feature(sensor, camera, 0xbe3, 16, struct.pack('QQ', 1, 0))
            test_pattern = True
            if sensor_id == 0x5a2:
                # The vendor feature selects solid black (008d=00). GC05A2's
                # documented test selector 0x10 produces actual color bars.
                feature(sensor, camera, 0xbc3, 8, struct.pack('II', 0x008d, 0x10))
        feature(sensor, camera, 3006, 8, struct.pack('Q', 1024))
        feature(sensor, camera, 3004, 8, struct.pack('Q', 2000))
        if sensor_id == 0xd154:
            # SC820CS preview setup leaves streaming disabled. The exact
            # driver's feature table maps 0xc20 to streaming_control(true).
            feature(sensor, camera, 0xc20, 8, struct.pack('Q', 0))
            streaming = True
        print('sensor registers', {hex(a): feature(sensor, camera, 0xbc4, 8, struct.pack('II', a, 0)).hex()
                                  for a in (0x0100, 0x0112, 0x0113, 0x0114, 0x034c, 0x034d, 0x034e, 0x034f)}, file=sys.stderr, flush=True)
        if args.preview:
            import numpy as np
            colors = runpy.run_path(str(Path(__file__).with_name('camera-color.py')))
            emitted = 0
            start = time.monotonic()
            while not args.frames or emitted < args.frames:
                time.sleep(0.04)
                transport = np.frombuffer(image[:bpl*h], dtype=np.uint8).reshape(h, bpl)
                if emitted == 0 and np.count_nonzero(transport[:, :packed_width] != 0xa5) < packed_width * h // 2:
                    if time.monotonic() - start > 3:
                        raise RuntimeError('No image received from the sensor')
                    continue
                rgb = colors['decode_raw10'](image[:bpl*h], w, h, bpl, bayer)
                rgb = colors['render_preview'](rgb)
                ppm = f'P6\n{w//2} {h//2}\n255\n'.encode() + rgb.tobytes()
                sys.stdout.buffer.write(struct.pack('I', len(ppm)))
                sys.stdout.buffer.write(ppm)
                sys.stdout.buffer.flush()
                emitted += 1
            print(json.dumps({'frames': emitted, 'seconds': round(time.monotonic()-start, 3)}), file=sys.stderr, flush=True)
            return
        deadline = time.monotonic() + 3
        done = 0
        while time.monotonic() < deadline:
            status = v.read(0x1c)
            if status & (1 << 10):
                done += 1
                if done >= 3:
                    break
            time.sleep(0.02)
        diagnostics = {'sensor_id': hex(sensor_id), 'iova': hex(node.iova), 'pass1': done,
                       'camsv': {hex(o): hex(v.read(o)) for o in (0x10, 0x14, 0x18, 0x1c, 0x4c, 0x238, 0x444, 0x520, 0x534, 0x538, 0x53c)},
                       'seninf': {hex(o): hex(s.read(o)) for o in (0xa00, 0xa08, 0xa10, 0xa14, 0xa18, 0xa1c, 0xa24, 0xa28, 0xa2c, 0xa30, 0xa34, 0xa38, 0xa3c, 0xd00, 0xd18)}}
        print(json.dumps(diagnostics), file=sys.stderr, flush=True)
        v.write(0x504, 0)
        v.write(0x500, 0)
        time.sleep(0.1)
        pixels = image[:bpl*h]
        changed = sum(value != 0xa5 for value in pixels)
        print(json.dumps({'changed_bytes': changed, 'size': len(pixels)}), file=sys.stderr, flush=True)
        if changed < len(pixels) // 2:
            raise RuntimeError('No complete image acquired')
        args.output.write_bytes(pixels)
        args.output.with_suffix('.json').write_text(json.dumps({'width': w, 'height': h, 'stride': bpl, 'format': 'CSI2-RAW10-MIPI', **diagnostics}, indent=2))
    finally:
        if streaming:
            try:
                feature(sensor, camera, 0xc1f, 8, struct.pack('Q', 0))
            except OSError as error:
                print(f'Could not suspend camera stream: {error}', file=sys.stderr)
        if v is not None:
            v.write(0x504, 0)
            v.write(0x500, 0)
            v.write(0x10, 0x40000000)
            v.write(0x20, 4)
            v.write(0x20, 0)
            v.write(0x20, 1)
            time.sleep(0.02)
            v.write(0x20, 0)
            v.write(0x30, 0)
        if opened:
            if test_pattern:
                feature(sensor, camera, 0xbe3, 16, struct.pack('QQ', 0, 0))
            feature(sensor, camera, 0xc22)
        if s is not None:
            s.write(0x200, 0)
            s.update(0xd00, 1 << 31, 0)
        if p is not None:
            for block in blocks:
                p.update(block, 0xc, 0)
        for reg in regs:
            reg.mem.close()
        if isp >= 0:
            os.close(isp)
        if image is not None:
            image.close()
        if node is not None and node.iova:
            fcntl.ioctl(cm, 0x40584901, node)
        for fd in (cm, dma, sensor):
            if fd >= 0:
                os.close(fd)


if __name__ == '__main__':
    try:
        main()
    except (KeyboardInterrupt, BrokenPipeError):
        pass
