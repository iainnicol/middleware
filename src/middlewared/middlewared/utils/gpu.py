import pyudev
import re
import subprocess

from middlewared.service import CallError


RE_PCI_ADDR = re.compile(r'(?P<domain>.*):(?P<bus>.*):(?P<slot>.*)\.')


def get_gpus():
    cp = subprocess.Popen(['lspci', '-D'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = cp.communicate()
    if cp.returncode:
        raise CallError(f'Unable to list available gpus: {stderr.decode()}')

    gpus = []
    gpu_slots = []
    for line in stdout.decode().splitlines():
        for k in (
            'VGA compatible controller',
            'Display controller',
            '3D controller',
        ):
            if k in line:
                gpu_slots.append((line.strip(), k))
                break

    for gpu_line, key in gpu_slots:
        addr = gpu_line.split()[0]
        addr_re = RE_PCI_ADDR.match(addr)

        gpu_dev = pyudev.Devices.from_name(pyudev.Context(), 'pci', addr)
        # Let's normalise vendor for consistency
        vendor = None
        vendor_id_from_db = gpu_dev.get('ID_VENDOR_FROM_DATABASE', '').lower()
        if 'nvidia' in vendor_id_from_db:
            vendor = 'NVIDIA'
        elif 'intel' in vendor_id_from_db:
            vendor = 'INTEL'
        elif 'amd' in vendor_id_from_db:
            vendor = 'AMD'

        devices = []
        critical = False
        for child in filter(lambda c: all(k in c for k in ('PCI_SLOT_NAME', 'PCI_ID')), gpu_dev.parent.children):
            devices.append({
                'pci_id': child['PCI_ID'],
                'pci_slot': child['PCI_SLOT_NAME'],
                'vm_pci_slot': f'pci_{child["PCI_SLOT_NAME"].replace(".", "_").replace(":", "_")}',
            })
            critical |= any(
                k in child.get('ID_PCI_SUBCLASS_FROM_DATABASE', '').lower() for k in ('host bridge', 'memory')
            )

        gpus.append({
            'addr': {
                'pci_slot': addr,
                **{k: addr_re.group(k) for k in ('domain', 'bus', 'slot')},
            },
            'description': gpu_line.split(f'{key}:')[-1].split('(rev')[0].strip(),
            'devices': devices,
            'vendor': vendor,
            'uses_system_critical_devices': critical,
        })

    return gpus
