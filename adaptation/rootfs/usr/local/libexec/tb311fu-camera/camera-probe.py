#!/usr/bin/env python3
"""TB311FU vendor camera bring-up; identification is not image capture.

Run as root on the tablet. Serializes with display/codec maintenance.
The original 6.6 module dispatch was checked with Ghidra before using this ABI.
Never loads camera_isp_4_t before mdp_drv_mt6768: that dereferences NULL.
"""
import argparse
import ctypes as C
import fcntl
import hashlib
import json
import mmap
import os
from pathlib import Path
import platform
import subprocess


# Complete, coherent driver sets; the newer set differs only in build metadata.
MODULE_PROFILES = ({'mdp_drv_mt6768': {'sha256': 'ba808663704a3943535bf1d89c14526b7c8285584ebc6dcfaaeeeb3a387202a0',
                     'note_sha256': 'fa8fa452136d2d4b4e8ee4de1bbc96c877eb239ddb603ef37f08e922b5646827'},
  'imgsensor_isp4_t': {'sha256': '32b9d78f02d4dc943e903d72c4112c13455fdd8790c20d0e6fcc479526c329bc',
                       'note_sha256': 'ee838c06460299f530dec070117b6dbc3e50823cfa66896f329c0fb7f8f97f74'},
  'camera_isp_4_t': {'sha256': 'ee672f62fbc9672be42be489cff56d70e9e1ac1708f8c84ed45234b3821d6c1c',
                     'note_sha256': 'bdfab08b9f4c25ae3e6a269cd28b063c064819376c5a4eaf2a9bcbe006d49dd5'},
  'camera_mem': {'sha256': '7985c7419f9c9234a7e0c13f15334585ef974f766e3a8cc8ad9233a68a86ddea',
                 'note_sha256': 'eca56daec5fa07d14b81c9fd365dbca2d44db7a1bde9046a309ae782c7e6c92b'}},
 {'mdp_drv_mt6768': {'sha256': '9e6370ddf8e184cba2f7c89b71171a00d7ecaf98df14a1e9af77d4480edbfce7',
                     'note_sha256': '28a7351d5e0caa18c81bee97a8d9339ebf2f726caebf68c37874c26647f04ca9'},
  'imgsensor_isp4_t': {'sha256': '0f9559e081ac2afc1a4f55d3928012cb2d502b46dde7c807c01f82cb96c91145',
                       'note_sha256': '86b4d8de80eb7aaa023f4be0e7e2b2c1f50b513c5d66ea79194d5795bcf69b1e'},
  'camera_isp_4_t': {'sha256': 'f72ac69af415847c988db58619cbba166e64a3b29b54cd5ad52eacdbbcabaa10',
                     'note_sha256': '93a5b7a371acc327bffab0c5b5661c611ff690aba3e4470c1682e1bd1c07f61e'},
  'camera_mem': {'sha256': '0355b599d2603354d4be370d148ca56c16370e3d93f7d8247c0aea96e3473694',
                 'note_sha256': 'ed76d9267259ce345c5a77ebfdfc6703f6d572c98a95a30590c05b5f7c4a9f0e'}})


def verify_modules():
    directory = Path('/lib/modules') / platform.release() / 'extra/mediatek'
    actual = {name: hashlib.sha256((directory / (name + '.ko')).read_bytes()).hexdigest()
              for name in MODULE_PROFILES[0]}
    for profile in MODULE_PROFILES:
        if all(actual[name] == expected['sha256'] for name, expected in profile.items()):
            for name, expected in profile.items():
                note = Path('/sys/module') / name / 'notes/.note.gnu.build-id'
                if note.exists() and hashlib.sha256(note.read_bytes()).hexdigest() != expected['note_sha256']:
                    raise RuntimeError(f'Loaded camera driver does not match verified profile: {name}')
            return tuple(profile)
    raise RuntimeError('Unverified camera driver set; refusing hardware access')



def require_capture_memory():
    values = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key, _, value = line.partition(':')
        if key == 'MemAvailable':
            values[key] = int(value.split()[0])
    # The vendor ISP has an unsafe init failure path; do not load it under pressure.
    if values.get('MemAvailable', 0) < 512 * 1024:
        raise RuntimeError('Not enough free memory for camera capture; close applications first')
    if not Path('/sys/module/camera_isp_4_t').exists():
        blocks = 0
        for line in Path('/proc/buddyinfo').read_text().splitlines():
            counts = [int(value) for value in line.split()[4:]]
            blocks += sum(count << (order - 5) for order, count in enumerate(counts) if order >= 5)
        if blocks < 16:
            raise RuntimeError('Not enough free memory for camera capture; restart before opening the camera')


class Feature(C.Structure):
    _fields_ = [('camera', C.c_uint32), ('feature', C.c_uint32),
                ('data', C.c_void_p), ('length', C.c_void_p)]


class CamBuffer(C.Structure):
    _fields_ = [('fd', C.c_int32), ('iova', C.c_uint64),
                ('username', C.c_char * 64), ('secure', C.c_bool),
                ('secure_handle', C.c_uint32)]


def feature(fd, camera, number, size=4, payload=None):
    data = C.create_string_buffer(size) if payload is None else C.create_string_buffer(payload, size)
    length = C.c_uint32(size)
    arg = Feature(camera, number, C.addressof(data), C.addressof(length))
    fcntl.ioctl(fd, 0xc018690f, arg)
    return data.raw[:length.value]


def load(name):
    subprocess.run(['modprobe', name], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--isp', action='store_true', help='also open/close ISP')
    parser.add_argument('--buffers', action='store_true', help='also map/unmap DMA buffer')
    args = parser.parse_args()
    if os.geteuid() or platform.machine() != 'aarch64':
        raise SystemExit('Run as root on the aarch64 TB311FU')
    if platform.release() != '6.6.142-pmos-minimal+':
        raise SystemExit('Kernel ABI has not been verified')
    dt = Path('/sys/firmware/devicetree/base/model').read_bytes()
    if b'MT8786' not in dt:
        raise SystemExit(f'Unexpected platform: {dt!r}')
    with open('/run/lock/tb311fu-gpu-video', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        verify_modules()
        load('imgsensor_isp4_t')
        verify_modules()
        report = {'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                  'kernel': platform.release(), 'capture_working': False, 'sensors': []}
        fd = os.open('/dev/kd_camera_hw', os.O_RDWR | os.O_CLOEXEC)
        try:
            for camera in (0, 1):
                index = int.from_bytes(feature(fd, camera, 0xc23), 'little', signed=True)
                item = {'camera': camera, 'driver_index': index}
                if index < 0:
                    raise RuntimeError(f'Sensor not detected: {item}')
                try:
                    feature(fd, camera, 0xc21)
                    item['open'] = True
                    sensor_id = feature(fd, camera, 0xbe1)
                    item['sensor_id'] = hex(int.from_bytes(sensor_id, 'little'))
                finally:
                    feature(fd, camera, 0xc22)
                report['sensors'].append(item)
                print(json.dumps(item), flush=True)
        finally:
            os.close(fd)
        if args.isp or args.buffers:
            load('mdp_drv_mt6768')
            load('camera_isp_4_t')
            isp = os.open('/dev/camera-isp', os.O_RDWR | os.O_CLOEXEC)
            try:
                with mmap.mmap(isp, 0x8000, flags=mmap.MAP_SHARED, prot=mmap.PROT_READ,
                               offset=0x1a040000) as regs:
                    report['seninf_top'] = regs[:32].hex()
            finally:
                os.close(isp)
            report['isp_open_close'] = True
        if args.buffers:
            load('camera_mem')
            heap = os.open('/dev/dma_heap/mtk_mm-uncached', os.O_RDWR | os.O_CLOEXEC)
            buf = C.create_string_buffer(24)
            import struct
            buf.raw = struct.pack('QIIQ', 8 * 1024 * 1024, 0, os.O_RDWR | os.O_CLOEXEC, 0)
            try:
                fcntl.ioctl(heap, 0xc0184800, buf)
            finally:
                os.close(heap)
            dmafd = struct.unpack('QIIQ', buf.raw)[1]
            cm = os.open('/dev/camera-mem', os.O_RDWR | os.O_CLOEXEC)
            node = CamBuffer(dmafd, 0, b'tb311fu-camera-probe', False, 0)
            mapped = False
            try:
                fcntl.ioctl(cm, 0xc0584900, node)
                mapped = True
                report['buffer_iova'] = hex(node.iova)
                if not node.iova:
                    raise RuntimeError('Empty camera DMA mapping')
            finally:
                if mapped:
                    fcntl.ioctl(cm, 0x40584901, node)
                os.close(cm)
                os.close(dmafd)
        print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
