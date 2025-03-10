import copy
import contextlib
import enum
import os

from middlewared.plugins.container_runtime_interface.utils import normalize_reference
from middlewared.plugins.kubernetes_linux.utils import NVIDIA_RUNTIME_CLASS_NAME
from middlewared.service import CallError
from middlewared.utils import run as _run


CHART_NAMESPACE_PREFIX = 'ix-'
CONTEXT_KEY_NAME = 'ixChartContext'
RESERVED_NAMES = [
    ('ixCertificates', dict),
    ('ixCertificateAuthorities', dict),
    ('ixExternalInterfacesConfiguration', list),
    ('ixExternalInterfacesConfigurationNames', list),
    ('ixVolumes', list),
    (CONTEXT_KEY_NAME, dict),
]


class Resources(enum.Enum):
    CRONJOB = 'cronjobs'
    DEPLOYMENT = 'deployments'
    JOB = 'jobs'
    PERSISTENT_VOLUME_CLAIM = 'persistent_volume_claims'
    POD = 'pods'
    STATEFULSET = 'statefulsets'


def get_action_context(release_name):
    return copy.deepcopy({
        'addNvidiaRuntimeClass': True,
        'nvidiaRuntimeClassName': NVIDIA_RUNTIME_CLASS_NAME,
        'operation': None,
        'isInstall': False,
        'isUpdate': False,
        'isUpgrade': False,
        'storageClassName': get_storage_class_name(release_name),
        'upgradeMetadata': {},
    })


async def add_context_to_configuration(config, context_dict, middleware, release_name):
    context_dict[CONTEXT_KEY_NAME]['kubernetes_config'] = {
        k: v for k, v in (await middleware.call('kubernetes.config')).items()
        if k in ('cluster_cidr', 'service_cidr', 'cluster_dns_ip')
    }
    if 'global' in config:
        config['global'].update(context_dict)
        config.update(context_dict)
    else:
        config.update({
            'global': context_dict,
            **context_dict
        })
    config['release_name'] = release_name
    return config


def get_namespace(release_name):
    return f'{CHART_NAMESPACE_PREFIX}{release_name}'


def get_chart_release_from_namespace(namespace):
    return namespace.split(CHART_NAMESPACE_PREFIX, 1)[-1]


def safe_to_ignore_path(path: str) -> bool:
    # "/" and "/home/keys/" are added for openebs use only, regular containers can't mount "/" as we have validation
    # already in place by docker elsewhere to prevent that from happening
    if path == '/':
        return True

    for ignore_path in (
        '/dev/',  # required by openebs
        '/etc/group',  # required by netdata
        '/etc/os-release',  # required by netdata
        '/etc/passwd',  # required by netdata
        '/home/keys/',  # required by openebs
        '/mnt/',
        '/proc/',  # required by netdata
        '/sys/',  # required by netdata
        '/usr/lib/os-release',  # required by netdata
        '/var/lib/kubelet/',
    ):
        if path.startswith(ignore_path) or path == ignore_path.removesuffix('/'):
            return True

    return False


def is_ix_volume_path(path: str, dataset: str) -> bool:
    release_path = os.path.join('/mnt', dataset, 'releases')
    if not path.startswith(release_path):
        return False

    # path -> /mnt/pool/ix-applications/releases/plex/volumes/ix-volumes/
    app_path = path.replace(release_path, '').removeprefix('/').split('/', 1)[0]
    return path.startswith(os.path.join(release_path, app_path, 'volumes/ix_volumes/'))


def normalize_image_tag(tag: str) -> str:
    # This needs to be done as CRI adds registry-1. prefix which it does not
    # do when we query containerd directly
    try:
        complete_tag = normalize_reference(tag)['complete_tag']
    except CallError:
        return tag
    else:
        if complete_tag.startswith('registry-1.docker.io/'):
            return complete_tag.removeprefix('registry-1.')
        else:
            return complete_tag


def is_ix_namespace(namespace):
    return namespace.startswith(CHART_NAMESPACE_PREFIX)


async def run(*args, **kwargs):
    kwargs['env'] = dict(os.environ, KUBECONFIG='/etc/rancher/k3s/k3s.yaml')
    return await _run(*args, **kwargs)


def get_storage_class_name(release):
    return f'ix-storage-class-{release}'


def get_network_attachment_definition_name(release, count):
    return f'ix-{release}-{count}'


SCALEABLE_RESOURCES = [
    Resources.DEPLOYMENT,
    Resources.STATEFULSET,
]
SCALE_DOWN_ANNOTATION = {
    'key': 'ix\\.upgrade\\.scale\\.down\\.workload',
    'value': ['true', '1'],
}
