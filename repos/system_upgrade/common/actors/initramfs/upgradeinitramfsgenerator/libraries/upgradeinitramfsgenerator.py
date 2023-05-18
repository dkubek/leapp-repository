import os
import shutil
from distutils.version import LooseVersion

from leapp.exceptions import StopActorExecutionError
from leapp.libraries.common import dnfplugin, mounting
from leapp.libraries.common.config.version import get_target_major_version
from leapp.libraries.stdlib import api, CalledProcessError, run
from leapp.models import RequiredUpgradeInitramPackages  # deprecated
from leapp.models import UpgradeDracutModule  # deprecated
from leapp.models import (
    BootContent,
    InstalledTargetKernelVersion,
    TargetOSInstallationImage,
    TargetUserSpaceInfo,
    TargetUserSpaceUpgradeTasks,
    UpgradeInitramfsTasks,
    UsedTargetRepositories
)
from leapp.utils.deprecation import suppress_deprecation

INITRAM_GEN_SCRIPT_NAME = 'generate-initram.sh'
DRACUT_DIR = '/dracut'


def _get_target_kernel_modules_dir(context):
    # TODO(dkubek): This does not work as the message in produces in the Upgrade phase
    # target_kernel = next(api.consume(InstalledTargetKernelVersion))

    kernel_version = None
    try :
        results = context.call(['rpm', '-qa', 'kernel'], split=True)

        versions = map(lambda _: _.replace('kernel-', ''), results['stdout'])
        api.current_logger().debug(
            'Versions detected {versions}.'
            .format(versions=versions))
        sorted_versions = sorted(versions, key=LooseVersion, reverse=True)
        kernel_version = next(iter(sorted_versions), None)
    except CalledProcessError:
        raise StopActorExecutionError(
            'Cannot get version of the installed kernel.',
            details={'Problem': 'Could not query the currently installed kernel through rmp.'})

    if not kernel_version:
        raise StopActorExecutionError(
            'Cannot get version of the installed kernel.',
            details={'Problem': 'A rpm query for the available kernels did not produce any results.'})


    api.current_logger().debug(
        'Detected highest kernel version is {kernel_version}.'
        .format(kernel_version=kernel_version))

    return kernel_version


def _reinstall_leapp_repository_hint():
    """
    Convenience function for creating a detail for StopActorExecutionError with a hint to reinstall the
    leapp-repository package
    """
    return {
        'hint': 'Try to reinstall the `leapp-repository` package.'
    }


# TODO(dkubek): Merge copy_dracut_modules and copy_kernel_modules into a single function
def copy_dracut_modules(context, modules):
    """
    Copy dracut modules into the target userspace.

    If duplicated requirements to copy a dracut module are detected,
    log the debug msg and skip any try to copy a dracut module into the
    target userspace that already exists inside DRACTUR_DIR.
    """
    try:
        context.remove_tree(DRACUT_DIR)
    except EnvironmentError:
        pass
    for module in modules:
        if not module.module_path:
            continue
        dst_path = os.path.join(DRACUT_DIR, os.path.basename(module.module_path))
        if os.path.exists(context.full_path(dst_path)):
            # we are safe to skip it as we now the module is from the same path
            # regarding the actor checking all initramfs tasks
            api.current_logger().debug(
                'The {name} dracut module has been already installed. Skipping.'
                .format(name=module.name))
            continue
        try:
            context.copytree_to(module.module_path, dst_path)
        except shutil.Error as e:
            api.current_logger().error('Failed to copy dracut module "{name}" from "{source}" to "{target}"'.format(
                name=module.name, source=module.module_path, target=context.full_path(DRACUT_DIR)), exc_info=True)
            raise StopActorExecutionError(
                message='Failed to install dracut modules required in the initram. Error: {}'.format(str(e))
            )


def copy_kernel_modules(context, modules):
    """
    Copy kernel modules into the target userspace.

    If duplicated requirements to copy a dracut module are detected,
    log the debug msg and skip any try to copy a dracut module into the
    target userspace that already exists inside DRACTUR_DIR.
    """

    kernel_modules_dir = _get_target_kernel_modules_dir(context)
    dst_dir = os.path.join(kernel_modules_dir, 'extra', 'leapp')
    if not os.path.exists(context.full_path(dst_dir)):
        os.makedirs(context.full_path(dst_dir))

    for module in modules:
        if not module.module_path:
            continue

        dst_path = os.path.join(dst_dir, os.path.basename(module.module_path))
        if os.path.exists(context.full_path(dst_path)):
            api.current_logger().debug(
                'The {name} kernel module has been already installed. Skipping.'
                .format(name=module.name))
            continue

        copy_fn = context.copytree_to
        if os.path.isfile(module.module_path):
            copy_fn = context.copy_to

        try:
            copy_fn(module.module_path, dst_path)
        except shutil.Error as e:
            api.current_logger().error('Failed to copy kernel module "{name}" from "{source}" to "{target}"'.format(
                name=module.name, source=module.module_path, target=context.full_path(dst_dir)), exc_info=True)
            raise StopActorExecutionError(
                message='Failed to install kernel modules required in the initram. Error: {}'.format(str(e))
            )


@suppress_deprecation(UpgradeDracutModule)
def _get_dracut_modules():
    return list(api.consume(UpgradeDracutModule))


def _install_initram_deps(packages):
    used_repos = api.consume(UsedTargetRepositories)
    target_userspace_info = next(api.consume(TargetUserSpaceInfo), None)

    dnfplugin.install_initramdisk_requirements(
        packages=packages,
        target_userspace_info=target_userspace_info,
        used_repos=used_repos)


# duplicate of _copy_files from userspacegen.py
def _copy_files(context, files):
    """
    Copy the files/dirs from the host to the `context` userspace

    :param context: An instance of a mounting.IsolatedActions class
    :type context: mounting.IsolatedActions class
    :param files: list of files that should be copied from the host to the context
    :type files: list of CopyFile
    """
    for file_task in files:
        if not file_task.dst:
            file_task.dst = file_task.src
        if os.path.isdir(file_task.src):
            context.remove_tree(file_task.dst)
            context.copytree_to(file_task.src, file_task.dst)
        else:
            context.copy_to(file_task.src, file_task.dst)


# TODO(pstodulk): think about possibility to split this part to different actor
# # reasoning: the environment could be prepared automatically and actor
# # developers will be able to do additional modifications before the initrd
# # will be really generated. E.g. multipath: config files will be copied
# # and another actor can securely updated configuration before the initrd
# # will be generated. same could be from user's POV - they are not allowed to
# # modify our actors, but they could need to do additional actions inside the
# # env as well.
@suppress_deprecation(RequiredUpgradeInitramPackages)
def prepare_userspace_for_initram(context):
    """
    Prepare the target userspace container to be able to generate init ramdisk

    This includes installation of rpms that are not installed yet. Copying
    files from the host to container, ... So when we start the process of
    the upgrade init ramdisk creation, the environment will be prepared with
    all required data and utilities.

    Note: preparation of dracut modules are handled outside of this function
    """
    packages = set()
    files = []
    _cftuples = set()

    def _update_files(copy_files):
        # add just uniq CopyFile objects to omit duplicate copying of files
        for cfile in copy_files:
            cftuple = (cfile.src, cfile.dst)
            if cftuple not in _cftuples:
                _cftuples.add(cftuple)
                files.append(cfile)

    generator_script = api.get_actor_file_path(INITRAM_GEN_SCRIPT_NAME)
    if not generator_script:
        raise StopActorExecutionError(
            message='Mandatory script to generate initram not available.',
            details=_reinstall_leapp_repository_hint()
        )
    context.copy_to(generator_script, os.path.join('/', INITRAM_GEN_SCRIPT_NAME))
    for msg in api.consume(TargetUserSpaceUpgradeTasks):
        packages.update(msg.install_rpms)
        _update_files(msg.copy_files)
    for message in api.consume(RequiredUpgradeInitramPackages):
        packages.update(message.packages)
    # install all required rpms first, so files installed/copied later
    # will not be overwritten during the dnf transaction
    _install_initram_deps(packages)
    _copy_files(context, files)


def generate_initram_disk(context):
    """
    Function to actually execute the init ramdisk creation.

    Includes handling of specified dracut modules from the host when needed.
    The check for the 'conflicting' dracut modules is in a separate actor.
    """
    env = {}
    if get_target_major_version() == '9':
        env = {'SYSTEMD_SECCOMP': '0'}

    # TODO(pstodulk): Add possibility to add particular drivers
    # Issue #645
    modules = {
        'dracut': _get_dracut_modules(),  # deprecated
        'kernel': [],
    }
    files = set()
    for task in api.consume(UpgradeInitramfsTasks):
        modules['dracut'].extend(task.include_dracut_modules)
        modules['kernel'].extend(task.include_kernel_modules)
        files.update(task.include_files)

    api.current_logger().debug('Kernel Modules: {}'.format(modules['kernel']))


    # TODO(dkubek): Merge into single function
    copy_dracut_modules(context, modules['dracut'])
    copy_kernel_modules(context, modules['kernel'])

    # FIXME: issue #376
    context.call([
        '/bin/sh', '-c',
        'LEAPP_ADD_DRACUT_MODULES="{dracut_modules}" LEAPP_KERNEL_ARCH={arch} '
        'LEAPP_ADD_KERNEL_MODULES="{kernel_modules}" '
        'LEAPP_DRACUT_INSTALL_FILES="{files}" {cmd}'.format(
            dracut_modules=','.join([mod.name for mod in modules['dracut']]),
            kernel_modules=','.join([mod.name for mod in modules['kernel']]),
            arch=api.current_actor().configuration.architecture,
            files=' '.join(files),
            cmd=os.path.join('/', INITRAM_GEN_SCRIPT_NAME))
    ], env=env)

    copy_boot_files(context)


def create_upgrade_hmac_from_target_hmac(original_hmac_path, upgrade_hmac_path, upgrade_kernel):
    # Rename the kernel name stored in the HMAC file as the upgrade kernel is named differently and the HMAC file
    # refers to the real target kernel
    with open(original_hmac_path) as original_hmac_file:
        hmac_file_lines = [line for line in original_hmac_file.read().split('\n') if line]
        if len(hmac_file_lines) > 1:
            details = ('Expected the target kernel HMAC file to containing only one HMAC line, '
                       'found {0}'.format(len(hmac_file_lines)))
            raise StopActorExecutionError('Failed to prepare HMAC file for upgrade kernel.',
                                          details={'details': details})

        # Keep only non-empty strings after splitting on space
        hmac, dummy_target_kernel_name = [fragment for fragment in hmac_file_lines[0].split(' ') if fragment]

    with open(upgrade_hmac_path, 'w') as upgrade_kernel_hmac_file:
        upgrade_kernel_hmac_file.write('{hmac}  {kernel}\n'.format(hmac=hmac, kernel=upgrade_kernel))


def copy_boot_files(context):
    """
    Function to copy the generated initram and corresponding kernel to /boot - Additionally produces a BootContent
    message with their location.
    """
    curr_arch = api.current_actor().configuration.architecture
    kernel = 'vmlinuz-upgrade.{}'.format(curr_arch)
    initram = 'initramfs-upgrade.{}.img'.format(curr_arch)

    kernel_hmac = '.{0}.hmac'.format(kernel)
    kernel_hmac_path = os.path.join('/boot', kernel_hmac)

    content = BootContent(
        kernel_path=os.path.join('/boot', kernel),
        initram_path=os.path.join('/boot', initram),
        kernel_hmac_path=kernel_hmac_path
    )

    context.copy_from(os.path.join('/artifacts', kernel), content.kernel_path)
    context.copy_from(os.path.join('/artifacts', initram), content.initram_path)

    kernel_hmac_path = context.full_path(os.path.join('/artifacts', kernel_hmac))
    create_upgrade_hmac_from_target_hmac(kernel_hmac_path, content.kernel_hmac_path, kernel)

    api.produce(content)


def process():
    userspace_info = next(api.consume(TargetUserSpaceInfo), None)
    target_iso = next(api.consume(TargetOSInstallationImage), None)
    with mounting.NspawnActions(base_dir=userspace_info.path) as context:
        with mounting.mount_upgrade_iso_to_root_dir(userspace_info.path, target_iso):
            prepare_userspace_for_initram(context)
            generate_initram_disk(context)
