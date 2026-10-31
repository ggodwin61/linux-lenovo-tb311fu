#!/usr/bin/env python3
"""Check the static assumptions of the ZUI 17.5.36.508 display profile.

Requires pyelftools. This does not replace on-device display validation.
"""
import argparse
import hashlib
import json
from pathlib import Path

from elftools.elf.elffile import ELFFile
from elftools.elf.relocation import RelocationSection

ROOT = Path(__file__).resolve().parent.parent
PROFILE = {
    'mediatek-drm': (
        'ca2f33ad438c9fc4f6ad6b439d31bda96b36e1c44f1294f8e1234d8a8e5240dd',
        '6fdc3c39c576e8b8ac7f9d3a4d888c76bb22740d8f5fc56d5c909d2e153fd126'),
    'mtk-cmdq-drv-ext': (
        '12d9a40424f0c3e0b6549a77bced63333e5e73432e077421a8fafaa7d5a60242',
        'f95b7e0b2a38f4ba6b2bb4009f822fb98d9bbb41abd566241297bcfdca2da1a0'),
    'cmdq-platform-mt6768': (
        'ee417cd29c3f928e9fcd6fceac231f08ba5a5c210dbe6e22a467797aeea30a5a',
        'f986740349ce5618105dcbc6f2570f715458298784c974347b59052043fb0411'),
}


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def symbol(elf, name):
    found = elf.get_section_by_name('.symtab').get_symbol_by_name(name)
    require(found and len(found) == 1, f'Missing or ambiguous symbol: {name}')
    return found[0]


def code(elf, name, before=0):
    sym = symbol(elf, name)
    section = elf.get_section(sym['st_shndx'])
    offset = sym['st_value'] - section['sh_addr']
    return section.data()[offset - before:offset + sym['st_size']]


def relocation_target(elf, table_name, offset):
    table = symbol(elf, table_name)
    for section in elf.iter_sections():
        if not isinstance(section, RelocationSection) or section['sh_info'] != table['st_shndx']:
            continue
        for rel in section.iter_relocations():
            if rel['r_offset'] == table['st_value'] + offset:
                target = elf.get_section(section['sh_link']).get_symbol(rel['r_info_sym'])
                return target['st_shndx'], target['st_value'] + rel['r_addend']
    raise SystemExit(f'Missing relocation: {table_name}+{offset}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--modules', type=Path, default=ROOT / 'vendor-input/ramdisk/lib/modules')
    parser.add_argument('--scanout', type=Path, default=ROOT / 'build/modules/scanout/tb311fu_scanout.ko')
    parser.add_argument('--report', type=Path, default=ROOT / 'build/display-static-check.json')
    args = parser.parse_args()
    checked = {}
    for name, (expected, note) in PROFILE.items():
        path = args.modules / f'{name}.ko'
        require(hashlib.sha256(path.read_bytes()).hexdigest() == expected,
                f'Unsupported binary: {path}')
        with path.open('rb') as stream:
            elf = ELFFile(stream)
            actual_note = hashlib.sha256(elf.get_section_by_name('.note.gnu.build-id').data()).hexdigest()
            require(actual_note == note, f'Unexpected build-id note: {path}')
        checked[name] = {'sha256': expected, 'build_id_note_sha256': note}
    with (args.modules / 'mediatek-drm.ko').open('rb') as stream, args.scanout.open('rb') as helper:
        drm, scanout = ELFFile(stream), ELFFile(helper)
        require(code(drm, 'mtk_fb_get_gem_obj') == bytes.fromhex('006440f9c0035fd6'),
                'Framebuffer GEM pointer is not the expected +0xc8 load')
        stub = bytes.fromhex('e0031f2ac0035fd6')
        for name in ('mtk_fb_wait', 'dummy_helper_prepare_fb'):
            require(code(drm, name) == stub, f'{name} is no longer the expected no-op')
        require(symbol(drm, 'mtk_plane_helper_funcs')['st_size'] == 80,
                'Unexpected plane-helper table size')
        prepare = symbol(drm, 'dummy_helper_prepare_fb')
        require(relocation_target(drm, 'mtk_plane_helper_funcs', 0) ==
                (prepare['st_shndx'], prepare['st_value']), 'Unexpected prepare_fb callback')
        require(code(drm, 'dummy_helper_prepare_fb', 4)[:4] == code(scanout, 'prepare_fb', 4)[:4],
                'The replacement prepare_fb has a different KCFI type ID')
    with (args.modules / 'cmdq-platform-mt6768.ko').open('rb') as stream:
        elf = ELFFile(stream)
        require(symbol(elf, 'platform_fp')['st_size'] == 88, 'Unexpected CMDQ callback table size')
        callbacks = {
            0: 'cmdq_thread_module_dispatch', 8: 'cmdq_event_module_dispatch',
            16: 'cmdq_util_hw_id', 24: 'cmdq_test_get_subsys_list',
            40: 'cmdq_util_hw_name', 48: 'cmdq_thread_ddr_module',
            56: 'cmdq_mbox_hw_trace_thread', 64: 'cmdq_error_irq_debug',
            72: 'cmdq_check_tf', 80: 'cmdq_get_mdp_min_thread',
        }
        for offset, name in callbacks.items():
            target = symbol(elf, name)
            require(relocation_target(elf, 'platform_fp', offset) ==
                    (target['st_shndx'], target['st_value']), f'Unexpected CMDQ callback at +{offset}')
    report = {'profile': 'ZUI 17.5.36.508', 'static_checks': 'passed',
              'hardware_validation': 'pending', 'modules': checked,
              'note': 'Also run the vendor ABI check. Hash, callback and KCFI checks do not prove runtime compatibility.'}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print('Display static checks passed; on-device validation is still required')


if __name__ == '__main__':
    main()
