import pytest

from leapp import reporting
from leapp.libraries.actor import updategrubcore
from leapp.libraries.common import testutils
from leapp.libraries.stdlib import api, CalledProcessError
from leapp.reporting import Report

UPDATE_OK_TITLE = 'GRUB core successfully updated'
UPDATE_FAILED_TITLE = 'GRUB core update failed'


def raise_call_error(args=None):
    raise CalledProcessError(
        message='A Leapp Command Error occurred.',
        command=args,
        result={'signal': None, 'exit_code': 1, 'pid': 0, 'stdout': 'fake', 'stderr': 'fake'}
    )


class run_mocked(object):
    def __init__(self, raise_err=False):
        self.called = 0
        self.args = []
        self.raise_err = raise_err

    def __call__(self, *args):
        self.called += 1
        self.args.append(args)
        if self.raise_err:
            raise_call_error(args)


@pytest.mark.parametrize('devices', [['/dev/vda'], ['/dev/vda', '/dev/vdb']])
def test_update_grub(monkeypatch, devices):
    monkeypatch.setattr(reporting, "create_report", testutils.create_report_mocked())
    monkeypatch.setattr(updategrubcore, 'run', run_mocked())
    updategrubcore.update_grub_core(devices)
    assert reporting.create_report.called
    assert UPDATE_OK_TITLE == reporting.create_report.reports[1]['title']
    assert all(dev in reporting.create_report.reports[1]['summary'] for dev in devices)


@pytest.mark.parametrize('devices', [['/dev/vda'], ['/dev/vda', '/dev/vdb']])
def test_update_grub_failed(monkeypatch, devices):
    monkeypatch.setattr(reporting, "create_report", testutils.create_report_mocked())
    monkeypatch.setattr(updategrubcore, 'run', run_mocked(raise_err=True))
    updategrubcore.update_grub_core(devices)
    assert reporting.create_report.called
    assert UPDATE_FAILED_TITLE == reporting.create_report.reports[0]['title']
    assert all(dev in reporting.create_report.reports[0]['summary'] for dev in devices)


def test_update_grub_success_and_fail(monkeypatch):
    monkeypatch.setattr(reporting, "create_report", testutils.create_report_mocked())

    def run_mocked(args):
        if args == ['grub2-install', '/dev/vdb']:
            raise_call_error(args)
        else:
            assert args == ['grub2-install', '/dev/vda']

    monkeypatch.setattr(updategrubcore, 'run', run_mocked)

    devices = ['/dev/vda', '/dev/vdb']
    updategrubcore.update_grub_core(devices)

    assert reporting.create_report.called
    assert UPDATE_FAILED_TITLE == reporting.create_report.reports[0]['title']
    assert '/dev/vdb' in reporting.create_report.reports[0]['summary']
    assert UPDATE_OK_TITLE == reporting.create_report.reports[1]['title']
    assert '/dev/vda' in reporting.create_report.reports[1]['summary']


def test_update_grub_negative(current_actor_context):
    current_actor_context.run()
    assert not current_actor_context.consume(Report)
