import os

from leapp.libraries.stdlib import api

from leapp.models import KernelModule, UpgradeInitramfsTasks

_INCLUDE_KERNEL_MODULES = ['ext4', '=drivers/hid']


def _create_kernel_modules():
    modules_base_path = api.get_actor_folder_path('modules')
    if modules_base_path:
        modules_base_path = os.path.abspath(modules_base_path)
        for module in os.listdir(modules_base_path):
            km = KernelModule(name=module, module_path=os.path.join(modules_base_path, module))
            yield UpgradeInitramfsTasks(include_kernel_modules=[km])


def _add_existing_kernel_modules():
    for module in _INCLUDE_KERNEL_MODULES:
        km = KernelModule(name=module)
        yield UpgradeInitramfsTasks(include_kernel_modules=[km])


def process():
    api.produce(*tuple(_create_kernel_modules()))
    api.produce(*tuple(_add_existing_kernel_modules()))
