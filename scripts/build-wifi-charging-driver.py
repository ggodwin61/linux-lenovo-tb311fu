#!/usr/bin/env python3
"""Allow the stock TB311FU Wi-Fi driver to initialize in a Linux charging boot.

Only the mode-8 early return in init_module is changed. Kernel ABI, charging,
firmware, NVRAM handling and all normal initialization remain unchanged.
"""
from pathlib import Path
import hashlib
import json
import struct

root = Path(__file__).resolve().parent.parent
source = root / 'vendor-input/modules/wlan_drv_gen4m_6768.ko'
original = source.read_bytes()
supported = {
    'ba66e406efe3d39cbc1a0fc777853585db8f5ed03558a3967ca84c5223a1056d': 'original supported stock driver',
    # ZUI 17.5.36.508: .text offset, init_module and mode-8 guard verified
    # by disassembly; the guard is identical to the original supported build.
    '4b3f2bd89a6b075dce37d6afd598ebb45ffff88e2f002f839ec87ffd1638fcd0': 'ZUI 17.5.36.508',
}
expected = hashlib.sha256(original).hexdigest()
if expected not in supported:
    raise SystemExit('Unexpected vendor driver; refuse to patch another build')
# ELF .text file offset 0x3e000 + init_module symbol 0x84ffc + 0x88.
# b.ne init_module+0x140 -> b init_module+0x140 (same branch destination).
offset = 0xc3084
before = struct.pack('<I', 0x540005c1)
after = struct.pack('<I', 0x1400002e)
if original[offset:offset+4] != before:
    raise SystemExit('Unexpected charging-mode guard instruction')
patched = original[:offset] + after + original[offset+4:]
output = root / 'dist/wifi/wlan_drv_gen4m_6768.ko'
output.parent.mkdir(parents=True, exist_ok=True)
output.write_bytes(patched)
manifest = {'source_sha256': expected, 'output_sha256': hashlib.sha256(patched).hexdigest(),
            'source_build': supported[expected],
            'file_offset': hex(offset), 'original_instruction': before.hex(),
            'patched_instruction': after.hex(), 'kernel': '6.6.142-pmos-minimal+',
            'reason': 'Permit Wi-Fi initialization when chosen/atag,boot reports charging boot mode 8'}
(root / 'dist/wifi/charging-driver.json').write_text(json.dumps(manifest, indent=2)+'\n')
print(json.dumps(manifest, indent=2))
