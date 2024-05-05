import logging
import os.path
from asyncio import create_subprocess_exec
from time import time

import json
import re
import shutil
import yaml
from hashlib import sha1
from pathlib import Path
from pydantic import BaseModel, field_validator
from subprocess import PIPE, DEVNULL
from tempfile import TemporaryDirectory

from foxbuild.config import config
from foxbuild.utils import async_check_output, NIX, BASH, JQ, GIT, get_sandbox_prefix

logger = logging.getLogger(__name__)


class Foxfile(BaseModel):
    # nixpkgs: str
    use_flake: str = False
    nix_paths: list[str] = ['flake.nix', 'flake.lock', 'shell.nix']
    packages: list[str] | None = None
    script: str

    @field_validator('use_flake', mode='before')
    @classmethod
    def v_use_flake(cls, v: str | bool):
        if v is True:
            return '.'
        else:
            return v


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


async def get_shell_variables(foxfile: Foxfile, host_workdir: Path, profile_name: str):
    if foxfile.use_flake:
        cmd = [foxfile.use_flake]
    else:
        cmd = [
            '--impure',
            '--expr',
            gen_nix_shell(foxfile),
        ]

    env_file = config.profiles_dir / (profile_name + '.rc')
    if env_file.is_file():
        env = json.loads(env_file.read_text())
    else:
        sandbox_workdir = '/home/build/repo'
        rw_binds = [(str(host_workdir), sandbox_workdir)]
        if config.use_sandbox:
            workdir = config.empty_dir
        else:
            workdir = host_workdir

        with TemporaryDirectory() as tempdir:
            os.chmod(tempdir, 0o777)
            if config.use_sandbox:
                prefix = get_sandbox_prefix(
                    overlay_nix_cache=True,
                    rw_binds=rw_binds + [(tempdir, tempdir)],
                    workdir=sandbox_workdir,
                )
            else:
                prefix = []

            tmp_profile = os.path.join(tempdir, 'profile')
            rc = await async_check_output(
                *prefix,
                NIX,
                'print-dev-env',
                '--profile',
                tmp_profile,
                *cmd,
                cwd=workdir,
            )

            # Already built, will just be symlinked and added to gcroots. Can be run on host
            await async_check_output(
                NIX,
                'build',
                '--out-link',
                str(config.profiles_dir / profile_name),
                tmp_profile,
                cwd=config.empty_dir,
            )

        if config.use_sandbox:
            prefix = get_sandbox_prefix(
                overlay_nix_cache=True,
                rw_binds=rw_binds,
                workdir=sandbox_workdir,
            )
        else:
            prefix = []

        env = json.loads(
            await async_check_output(
                *prefix, BASH, '-c', f'{rc}\n{JQ} -n env', cwd=workdir
            )
        )

        if (
            not config.use_sandbox
            and (nix_build_top := env.get('NIX_BUILD_TOP'))
            and '/nix-shell.' in nix_build_top
            and os.path.isdir(nix_build_top)
        ):
            shutil.rmtree(nix_build_top)

        for var in ('NIX_BUILD_TOP', 'TMP', 'TMPDIR', 'TEMP', 'TEMPDIR', 'terminfo'):
            if var in env:
                del env[var]

        env_file.write_text(json.dumps(env))

    return env


async def clone_repo(workdir: Path, token: str, repo_name: str, sha: str):
    repo_path = config.repos_dir / repo_name
    if repo_path.is_dir():
        await async_check_output(
            GIT,
            'fetch',
            cwd=repo_path,
        )
    else:
        repo_path.mkdir(parents=True)
        await async_check_output(
            GIT,
            'clone',
            '--bare',
            f'https://x-access-token:{token}@github.com/{repo_name}.git',
            '.',
            cwd=repo_path,
        )
    await async_check_output(
        GIT,
        'clone',
        str(repo_path),
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


def get_profile_filename(foxfile: Foxfile, workdir: Path) -> str:
    paths = []
    for entry in foxfile.nix_paths:
        if '*' in entry:
            paths.extend(workdir.glob(entry))
        else:
            paths.append(entry)
    paths.sort()
    hashes = sha1()
    for filename in paths:
        p = workdir / filename
        if not p.is_file():
            continue
        hashes.update(filename.encode())
        hashes.update(sha1(p.read_bytes()).digest())
    return hashes.hexdigest()


async def run_check(host_workdir: Path):
    file = host_workdir / 'foxfile.yml'
    if not file.is_file():
        return False, [{'stdout': 'Foxfile not found', 'stderr': ''}]
    foxfile = Foxfile.model_validate(yaml.safe_load(file.read_text()))
    s = time()
    env = await get_shell_variables(
        foxfile, host_workdir, get_profile_filename(foxfile, host_workdir)
    )
    print(f'Env import took {time() - s}')
    res = []
    is_ok = True

    if config.use_sandbox:
        sandbox_workdir = '/home/build/repo'
        rw_binds = [(str(host_workdir), sandbox_workdir)]
        workdir = config.empty_dir
        prefix = get_sandbox_prefix(
            overlay_nix_cache=True,
            rw_binds=rw_binds,
            env=env,
            workdir=sandbox_workdir,
        )
    else:
        workdir = host_workdir
        prefix = []
    p = await create_subprocess_exec(
        *prefix,
        BASH,
        '-c',
        foxfile.script,
        cwd=workdir,
        env=env if not config.use_sandbox else None,
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
