from asyncio import create_subprocess_exec

import logging
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
PODMAN = get_bin('podman')


async def async_check_output(*args: str | Path, cwd: Path | str) -> str:
    logger.debug(f'Running {args}')
    p = await create_subprocess_exec(*args, cwd=cwd, stdin=DEVNULL, stdout=PIPE)
    await p.wait()
    if p.returncode:
        logger.error(f'Process exited with code {p.returncode}')
        raise ValueError
    return (await p.stdout.read()).decode()
