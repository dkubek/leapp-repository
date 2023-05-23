import os
from collections import defaultdict

from leapp import reporting
from leapp.libraries.stdlib import api
from leapp.models import TargetInitramfsTasks, UpgradeInitramfsTasks

DRACUT_MOD_DIR = '/usr/lib/dracut/modules.d/'
SUMMARY_FMT = (
    'The requested {kind} modules for the initramfs are in conflict.'
    ' At least one {kind} module is specified to be installed from'
    ' multiple paths. The list of conflicting {kind} module names'
    ' with paths is listed below: {conflicts}'
)


def _printable_modules(conflicts):
    list_separator_fmt = '\n    - '
    for name, paths in conflicts.items():
        paths = sorted([str(i) for i in paths])
        output = ['{}{}: {}'.format(list_separator_fmt, name, paths)]
    return ''.join(output)


def _treat_path_dracut(dmodule):
    """
    In case the path is not set, set the expected path of the dracut module.
    """

    if not dmodule.module_path:
        return os.path.join(DRACUT_MOD_DIR, dmodule.name)
    return dmodule.module_path


def _treat_path_kernel(kmodule):
    """
    In case the path of a kernel module is not set, indicate that the module is
    taken from the current system.
    """

    if not kmodule.module_path:
        return kmodule.name + ' (system)'
    return kmodule.module_path


def _detect_modules_conflicts(msgtype, kind):
    """
    Return dict of modules with conflicting tasks

    In this case when a module should be applied but different sources are
    specified. E.g.:
       include modules X where,
         msg A)  X
         msg B)  X from custom path
    """

    msgattr = None
    if kind == 'dracut':
        msgattr = 'include_dracut_modules'
        treat_path_fn = _treat_path_dracut
    elif kind == 'kernel':
        msgattr = 'include_kernel_modules'
        treat_path_fn = _treat_path_kernel

    modules = defaultdict(set)
    for msg in api.consume(msgtype):
        for module in getattr(msg, msgattr):
            modules[module.name].add(treat_path_fn(module))
    return {key: val for key, val in modules.items() if len(val) > 1}


def process():
    groups = [('upgrade', 'kernel', UpgradeInitramfsTasks), ('upgrade', 'dracut', UpgradeInitramfsTasks),
              ('target', 'dracut', TargetInitramfsTasks)]
    for (msgname, kind, msgtype) in groups:
        conflicts = _detect_modules_conflicts(msgtype, kind)
        if conflicts:
            report = [
                reporting.Title('Conflicting requirements of {kind} modules for the {msgname} initramfs'.format(
                    kind=kind, msgname=msgname)),
                reporting.Summary(SUMMARY_FMT.format(kind=kind, conflicts=_printable_modules(conflicts))),
                reporting.Severity(reporting.Severity.HIGH),
                reporting.Groups([reporting.Groups.SANITY]),
                reporting.Groups([reporting.Groups.INHIBITOR]),
            ]
            reporting.create_report(report)
