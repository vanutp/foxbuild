import logging
from asyncio import create_subprocess_exec

import os
import subprocess
from pathlib import Path
from subprocess import DEVNULL, PIPE

from foxbuild.config import config

logger = logging.getLogger(__name__)


def get_bin(name: str) -> str:
    abspath = subprocess.check_output(f'which {name}', shell=True).decode().strip()
    if Path(abspath).is_symlink():
        return os.readlink(abspath)
    else:
        return name


BASH = get_bin('bash')
NIX = get_bin('nix')
JQ = get_bin('jq')
GIT = get_bin('git')
if config.use_sandbox:
    UNSHARE = get_bin('unshare')
    BWRAP = get_bin('bwrap')


async def async_check_output(*args: str, cwd: Path | str) -> str:
    logger.debug(f'Running {args}')
    p = await create_subprocess_exec(*args, cwd=cwd, stdin=DEVNULL, stdout=PIPE)
    await p.wait()
    if p.returncode:
        logger.error(f'Process exited with code {p.returncode}')
        raise ValueError
    return (await p.stdout.read()).decode()


def get_sandbox_prefix(
    *,
    overlay_nix_cache: bool = False,
    writable_nix_cache: bool = False,
    ro_binds: list[tuple[str, str]] = None,
    rw_binds: list[tuple[str, str]] = None,
    env: dict[str, str] = None,
    workdir: str = None,
) -> list[str]:
    if writable_nix_cache and overlay_nix_cache:
        raise ValueError

    if not ro_binds:
        ro_binds = []
    global_profile = str(config.global_profile_dir)
    ro_binds.extend(
        [
            ('/nix/store', '/nix/store'),
            ('/nix/var/nix/daemon-socket', '/nix/var/nix/daemon-socket'),
            (global_profile, '/profile'),
            (f'{global_profile}/bin/sh', '/bin/sh'),
            (f'{global_profile}/bin/env', '/usr/bin/env'),
            (f'{global_profile}/etc', '/etc'),
        ]
    )
    if not rw_binds:
        rw_binds = []
    if not env:
        env = {}
    env = {'PATH': '/profile/bin', 'HOME': '/home/build', 'NIX_REMOTE': 'daemon'} | env
    unshare = ['pid']
    uid = 1000
    gid = 100
    add_caps = []
    wrapper_cmd = []

    NIX_CACHE_BIND = (str(config.nix_cache_dir), '/home/build/.cache/nix')
    if overlay_nix_cache:
        add_caps.extend(
            [
                'CAP_SETPCAP',
                'CAP_DAC_OVERRIDE',
                'CAP_SYS_ADMIN',
                'CAP_SETUID',
                'CAP_SETGID',
            ]
        )
        wrapper_cmd = ['bwrap-wrapper']
        uid = 0
        gid = 0
        ro_binds.append(NIX_CACHE_BIND)
    elif writable_nix_cache:
        rw_binds.append(NIX_CACHE_BIND)

    res = [
        BWRAP,
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
    if overlay_nix_cache:
        res = [UNSHARE, '-r', '--map-auto', '--'] + res
    if workdir:
        res.extend(('--chdir', workdir))
    for src, dst in ro_binds:
        res.extend(('--ro-bind', src, dst))
    for src, dst in rw_binds:
        res.extend(('--bind', src, dst))
    for _, dst in ro_binds + rw_binds:
        dst = dst.rsplit('/', 1)[0]
        while dst not in ['', '/tmp']:
            res.extend(('--chmod', '0755', dst))
            dst = dst.rsplit('/', 1)[0]
    for k, v in env.items():
        res.extend(('--setenv', k, v))
    for ns in unshare:
        res.append(f'--unshare-{ns}')
    res.extend(('--uid', str(uid)))
    res.extend(('--gid', str(gid)))
    for cap_add in add_caps:
        res.extend(('--cap-add', cap_add))

    res.append('--')
    res.extend(wrapper_cmd)

    return res
