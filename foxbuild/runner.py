import os.path
from asyncio import create_subprocess_exec
from time import time

import json
import re
import shutil
import subprocess
import yaml
from pathlib import Path
from pydantic import BaseModel
from subprocess import PIPE, DEVNULL


class Foxfile(BaseModel):
    # nixpkgs: str
    use_flake: bool | str = False
    packages: list[str] | None = None
    script: str


BASH = subprocess.check_output('which bash', shell=True).decode().strip()
NIX = subprocess.check_output('which nix', shell=True).decode().strip()
JQ = subprocess.check_output('which jq', shell=True).decode().strip()
GIT = subprocess.check_output('which git', shell=True).decode().strip()


async def async_check_output(*args: str, cwd: Path) -> str:
    p = await create_subprocess_exec(*args, cwd=cwd, stdin=DEVNULL, stdout=PIPE)
    await p.wait()
    if p.returncode:
        raise ValueError
    return (await p.stdout.read()).decode()


def gen_nix_shell(foxfile: Foxfile):
    for package in foxfile.packages:
        if not re.fullmatch(r'[a-zA-Z_][\w\-]+', package):
            raise ValueError
    packages = ' '.join(foxfile.packages)
    return '''
        let 
          pkgs = import (fetchTarball "https://github.com/NixOS/nixpkgs/archive/nixpkgs-unstable.tar.gz") {};
        in
          pkgs.mkShell {
            nativeBuildInputs = with pkgs; [__PACKAGES__];
          }
    '''.replace(
        '__PACKAGES__', packages
    )


async def get_shell_variables(foxfile: Foxfile, workdir: Path):
    if foxfile.use_flake is True:
        foxfile.use_flake = '.'
    if foxfile.use_flake:
        cmd = [foxfile.use_flake]
    else:
        cmd = [
            '--impure',
            '--expr',
            gen_nix_shell(foxfile),
        ]
    rc = await async_check_output(
        NIX,
        'print-dev-env',
        '--profile',
        '.nixprofile',
        *cmd,
        cwd=workdir,
    )

    env = json.loads(
        await async_check_output(BASH, '-c', f'{rc}\n{JQ} -n env', cwd=workdir)
    )

    if (
        (nix_build_top := env.get('NIX_BUILD_TOP'))
        and '/nix-shell.' in nix_build_top
        and os.path.isdir(nix_build_top)
    ):
        shutil.rmtree(nix_build_top)

    for var in ('NIX_BUILD_TOP', 'TMP', 'TMPDIR', 'TEMP', 'TEMPDIR', 'terminfo'):
        if var in env:
            del env[var]

    return env


async def clone_repo(workdir: Path, token: str, repo_name: str, sha: str):
    await async_check_output(
        GIT,
        'clone',
        f'https://x-access-token:{token}@github.com/{repo_name}.git',
        '.',
        cwd=workdir,
    )
    await async_check_output(
        GIT,
        'switch',
        '-d',
        sha,
        cwd=workdir,
    )


async def run_check(workdir: Path):
    file = workdir / 'foxfile.yml'
    if not file.is_file():
        return False, [{'stdout': 'Foxfile not found'}]
    foxfile = Foxfile.model_validate(yaml.safe_load(file.read_text()))
    s = time()
    env = await get_shell_variables(foxfile, workdir)
    print(f'Env import took {time() - s}')
    res = []
    is_ok = True
    p = await create_subprocess_exec(
        BASH,
        '-c',
        foxfile.script,
        cwd=workdir,
        env=env,
        stdout=PIPE,
        stderr=PIPE,
        stdin=DEVNULL,
    )
    await p.wait()
    res.append(
        {
            'exit_code': p.returncode,
            'stdout': (await p.stdout.read()).decode(),
            'stderr': (await p.stderr.read()).decode(),
        }
    )
    if p.returncode:
        is_ok = False
    return is_ok, res
