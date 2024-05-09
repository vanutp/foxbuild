import os
import tempfile

import shutil


import logging
from pathlib import Path
from tempfile import TemporaryDirectory

from foxbuild.config import config
from foxbuild.const import SANDBOX_HOME
from foxbuild.utils import PODMAN, async_check_output

logger = logging.getLogger(__name__)


class Sandbox:
    FORCE_ENV = {
        'HOME': SANDBOX_HOME,
        'NIX_REMOTE': 'daemon',
    }
    KEEP_PERMS = ['/tmp']

    _ro_binds: list[tuple[str, str]]
    _rw_binds: list[tuple[str, str]]
    _env: dict[str, str]
    _uid: int
    _gid: int
    _workdir: str | None
    _do_overlay: bool
    _tmpfses: list[str]
    _other_args: list[str]
    unsafe_run_as_root: bool
    _container_tmp: Path

    _is_shutdown: bool

    def __init__(
        self,
        *,
        overlay_nix_cache: bool = False,
        writable_nix_cache: bool = False,
        workdir: str = None,
        image: str = None,
    ):
        if writable_nix_cache and overlay_nix_cache:
            raise ValueError

        self._is_shutdown = False

        global_profile = str(config.global_profile_dir)
        self._ro_binds = [
            ('/nix/store', '/nix/store'),
            ('/nix/var/nix/daemon-socket', '/nix/var/nix/daemon-socket'),
            (global_profile, '/profile'),
            (f'{global_profile}/bin/sh', '/bin/sh'),
            (f'{global_profile}/bin/env', '/usr/bin/env'),
        ]
        self._container_tmp = Path(tempfile.mkdtemp())
        self._rw_binds = [(self._container_tmp, f'{SANDBOX_HOME}/.local/share/containers')]
        self.clear_env()
        self._uid = 1000
        self._gid = 100
        self._workdir = workdir
        self._do_overlay = False
        self._tmpfses = ['/tmp', '/var/tmp', '/dev/shm', '/run/user/1000']
        self._image = image or 'empty'
        self.unsafe_run_as_root = False

        self._other_args = [
            '--url=unix:///run/podman/podman.sock',
            'run',
            '--rm',
            '--cap-add=SYS_ADMIN',
        ]

        NIX_CACHE_BIND = (str(config.nix_cache_dir), f'{SANDBOX_HOME}/.cache/nix')
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
            'PATH': '/bin:/profile/bin',
        }

    def add_envs(self, envs: dict[str, str]):
        for k, v in envs.items():
            if k == 'PATH':
                self._env[k] = v + ':' + self._env['PATH']
            elif k not in self.FORCE_ENV:
                self._env[k] = v

    def build_cmd_prefix(self) -> list[str]:
        if self._is_shutdown:
            raise ValueError('Sandbox is shut down')
        res = [PODMAN, *self._other_args]
        for tmpfs in self._tmpfses:
            res.extend(('--mount', f'type=tmpfs,destination={tmpfs}'))
        if self._workdir:
            res.extend(('-w', self._workdir))
        for src, dst in self._ro_binds:
            res.extend(('-v', f'{src}:{dst}:ro'))
        for src, dst in self._rw_binds:
            res.extend(('-v', f'{src}:{dst}'))
        for k, v in self._env.items():
            res.extend(('-e', f'{k}={v}'))

        res.append(self._image)
        if not self.unsafe_run_as_root:
            res.extend(
                ('bwrap-wrapper', str(self._uid), str(self._gid), str(self._do_overlay))
            )
        logger.debug(f'Generated sandbox prefix {res}')
        return res

    async def cleanup(self):
        self.unsafe_run_as_root = True
        prefix = self.build_cmd_prefix()
        self._is_shutdown = True
        dirs = (x.relative_to(self._container_tmp) for x in self._container_tmp.glob('*'))
        dirs = (os.path.join(f'{SANDBOX_HOME}/.local/share/containers', x) for x in dirs)
        self.clear_env()
        await async_check_output(
            *prefix,
            'rm',
            '-rf',
            *dirs,
            cwd=config.empty_dir,
        )
        self._container_tmp.rmdir()
