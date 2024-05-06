import logging

from foxbuild.config import config
from foxbuild.utils import UNSHARE, BWRAP

logger = logging.getLogger(__name__)


class Sandbox:
    FORCE_ENV = {
        'HOME': '/home/build',
        'NIX_REMOTE': 'daemon',
    }
    KEEP_PERMS = ['/tmp']

    _ro_binds: list[tuple[str, str]]
    _rw_binds: list[tuple[str, str]]
    _env: dict[str, str]
    _unshare: list[str]
    _uid: int
    _gid: int
    _add_caps: list[str]
    _host_wrapper_cmd: list[str]
    _workdir: str | None
    _do_overlay: bool
    _other_args: list[str]

    def __init__(
        self,
        *,
        overlay_nix_cache: bool = False,
        writable_nix_cache: bool = False,
        workdir: str = None,
    ):
        if writable_nix_cache and overlay_nix_cache:
            raise ValueError

        global_profile = str(config.global_profile_dir)
        self._ro_binds = [
            ('/nix/store', '/nix/store'),
            ('/nix/var/nix/daemon-socket', '/nix/var/nix/daemon-socket'),
            (global_profile, '/profile'),
            (f'{global_profile}/bin/sh', '/bin/sh'),
            (f'{global_profile}/bin/env', '/usr/bin/env'),
            (f'{global_profile}/etc', '/etc'),
        ]
        self._rw_binds = []
        self.clear_env()
        self._unshare = ['pid']
        self._uid = 1000
        self._gid = 100
        self._add_caps = [
            'CAP_SETPCAP',
            'CAP_DAC_OVERRIDE',
            'CAP_SYS_ADMIN',
            'CAP_SETUID',
            'CAP_SETGID',
        ]
        self._host_wrapper_cmd = []
        self._workdir = workdir
        self._do_overlay = False

        self._other_args = [
            '--proc',
            '/proc',
            '--dev',
            '/dev',
            '--perms',
            '0777',
            '--tmpfs',
            '/tmp',
            '--die-with-parent',
            '--clearenv',
        ]

        NIX_CACHE_BIND = (str(config.nix_cache_dir), '/home/build/.cache/nix')
        if overlay_nix_cache:
            self._ro_binds.append(NIX_CACHE_BIND)
            self._do_overlay = True
        elif writable_nix_cache:
            self._rw_binds.append(NIX_CACHE_BIND)

    def add_rw_bind(self, src: str, dst: str):
        self._rw_binds.append((src, dst))

    def remove_rw_bind(self, src: str, dst: str):
        self._rw_binds.remove((src, dst))

    def clear_env(self):
        self._env = self.FORCE_ENV.copy()
        self._env |= {
            'PATH': '/profile/bin',
        }

    def add_envs(self, envs: dict[str, str]):
        for k, v in envs.items():
            if k not in self.FORCE_ENV:
                self._env[k] = v

    def build_cmd_prefix(self) -> list[str]:
        res = [UNSHARE, '-r', '--map-auto', '--', BWRAP, *self._other_args]
        if self._workdir:
            res.extend(('--chdir', self._workdir))
        for src, dst in self._ro_binds:
            res.extend(('--ro-bind', src, dst))
        for src, dst in self._rw_binds:
            res.extend(('--bind', src, dst))
        for _, dst in self._ro_binds + self._rw_binds:
            dst = dst.rsplit('/', 1)[0]
            while dst:
                if dst not in self.KEEP_PERMS:
                    res.extend(('--chmod', '0755', dst))
                dst = dst.rsplit('/', 1)[0]
        for k, v in self._env.items():
            res.extend(('--setenv', k, v))
        for ns in self._unshare:
            res.append(f'--unshare-{ns}')
        res.extend(('--uid', '0'))
        res.extend(('--gid', '0'))
        for cap_add in self._add_caps:
            res.extend(('--cap-add', cap_add))

        res.append('--')
        res.extend(
            ('bwrap-wrapper', str(self._uid), str(self._gid), str(self._do_overlay))
        )
        logger.debug(f'Generated sandbox prefix {res}')
        return res
