from leapp import reporting
from leapp.exceptions import StopActorExecutionError
from leapp.libraries.stdlib import api
from leapp.models import XFSInfoFacts

RHEL_9_TO_10_BACKUP_RESTORE_LINK = 'https://red.ht/rhel_9_to_10_backup_restore_xfs'


def process():
    xfs_info_facts = _get_xfs_info_facts()

    invalid_bigtime = []
    invalid_crc = []
    for xfs_info in xfs_info_facts.mountpoints:
        if not _has_valid_bigtime(xfs_info):
            api.current_logger().debug(
                'Mountpoint {} has invalid bigtime'.format(xfs_info.mountpoint)
            )
            invalid_bigtime.append(xfs_info.mountpoint)

        if not _has_valid_crc(xfs_info):
            api.current_logger().debug(
                'Mountpoint {} has invalid crc'.format(xfs_info.mountpoint)
            )
            invalid_crc.append(xfs_info.mountpoint)

    if invalid_bigtime or invalid_crc:
        _inhibit_upgrade(invalid_bigtime, invalid_crc)

        return

    api.current_logger().debug('All XFS system detected are valid.')


def _get_xfs_info_facts():
    msgs = api.consume(XFSInfoFacts)

    xfs_info_facts = next(msgs, None)
    if xfs_info_facts is None:
        raise StopActorExecutionError('Could not retrieve XFSInfoFacts!')

    if next(msgs, None):
        api.current_logger().warning(
            'Unexpectedly received more than one XFSInfoFacts message.')

    return xfs_info_facts


def _has_valid_bigtime(xfs_info):
    return xfs_info.meta_data.get('bigtime', '') == '1'


def _has_valid_crc(xfs_info):
    return xfs_info.meta_data.get('crc', '') == '1'


def _inhibit_upgrade(invalid_bigtime, invalid_crc):
    title = 'Upgrade to RHEL 10 inhibited due to incompatible XFS filesystems.'
    summary = ''.join([
        (
            'Some XFS filesystems on this system are incompatible with RHEL 10'
            ' requirements. Specifically, the following issues were found:\n'
        ),
        ('XFS filesystems without "bigtime" feature: {}\n'.format(
            ', '.join(invalid_bigtime)) if invalid_bigtime else ''),
        ('XFS filesystems without "crc": {}\n'.format(
            ', '.join(invalid_crc)) if invalid_crc else ''),
    ])

    bigtime_remediation = (
        'Enable the "bigtime" feature on v5 filesystems using the command:\n'
        '\n\txfs_admin -O bigtime=1 <filesystem_device>\n\n'
        'Note: For older v5 filesystems this step can only be done offline '
        'right now (i.e. without the filesystem mounted).\n'
    )

    crc_remediation = (
        'Migrate filesystems to new version of XFS\n'
        'For root filesystems, a clean installation is recommended to ensure'
        ' compatibility. For data filesystems, perform a backup, reformat,'
        ' and restore procedure. Refer to official documentation for detailed'
        ' guidance.\n'
    )

    remediation_hint = ''.join([
        'To address these issue:\n',
        '\n',
        (bigtime_remediation if invalid_bigtime else ''),
        '\n',
        (crc_remediation if invalid_crc else ''),
    ])

    reporting.create_report([
        reporting.Title(title),
        reporting.Summary(summary),
        reporting.ExternalLink(
            title='Guidance on upgrading XFS filesystems for RHEL 10',
            url=RHEL_9_TO_10_BACKUP_RESTORE_LINK
        ),
        reporting.Severity(reporting.Severity.HIGH),
        reporting.Groups([reporting.Groups.INHIBITOR]),
        reporting.Remediation(hint=remediation_hint),
    ])
