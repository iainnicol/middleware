import contextlib
import json

from middlewared.utils import osc

from middlewared.test.integration.utils import run_on_runner, RunOnRunnerException


def target_login_test(portal_ip, target_name):
    if osc.IS_LINUX:
        return target_login_test_linux(portal_ip, target_name)
    else:
        return target_login_test_freebsd(portal_ip, target_name)


def target_login_test_linux(portal_ip, target_name):
    try:
        run_on_runner(['iscsiadm', '-m', 'node', '--targetname', target_name, '--portal', portal_ip, '--login'])
    except RunOnRunnerException:
        return False
    else:
        run_on_runner(['iscsiadm', '-m', 'node', '--targetname', target_name, '--portal', portal_ip, '--logout'])
        return True


@contextlib.contextmanager
def iscsi_client_freebsd():
    started = run_on_runner(['service', 'iscsid', 'onestatus'], check=False).returncode == 0
    if started:
        yield
    else:
        run_on_runner(['service', 'iscsid', 'onestart'])
        try:
            yield
        finally:
            run_on_runner(['service', 'iscsid', 'onestop'])


def target_login_impl_freebsd(portal_ip, target_name):
    run_on_runner(['iscsictl', '-A', '-p', portal_ip, '-t', target_name])
    cp = run_on_runner(['iscsictl', '-L', '--libxo', 'json'])
    connected_clients = json.loads(cp.stdout.decode(errors='ignore'))
    assert any(
        session.get('state') == 'Connected' for session in connected_clients.get('iscsictl', {}).get('session', [])
        if session.get('name') == target_name
    ) is True, cp.stdout


def target_login_test_freebsd(portal_ip, target_name):
    with iscsi_client_freebsd():
        try:
            target_login_impl_freebsd(portal_ip, target_name)
        except AssertionError:
            return False
        else:
            run_on_runner(['iscsictl', '-R', '-t', target_name])
            return True
