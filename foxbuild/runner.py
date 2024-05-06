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
from foxbuild.exceptions import ConfigurationError
from foxbuild.sandbox import Sandbox
from foxbuild.utils import async_check_output, NIX, BASH, JQ, GIT

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


class Runner:
    SANDBOX_WORKDIR = '/home/build/repo'

    _foxfile: Foxfile | None
    _host_workdir: Path
    _cmd_workdir: str | Path
    _sandbox: Sandbox | None

    def __init__(self, host_workdir: Path):
        self._host_workdir = host_workdir
        self._foxfile = None
        self._sandbox = None

    def get_sandbox_prefix(self) -> list[str]:
        return self._sandbox.build_cmd_prefix() if config.use_sandbox else []

    def gen_nix_shell(self):
        for package in self._foxfile.packages:
            if not re.fullmatch(r'[a-zA-Z_][\w\-]+', package):
                raise ValueError
        packages = ' '.join(self._foxfile.packages)
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

    async def get_shell_variables(self, profile_name: str):
        if self._foxfile.use_flake:
            cmd = [self._foxfile.use_flake]
        else:
            cmd = [
                '--impure',
                '--expr',
                self.gen_nix_shell(),
            ]

        env_file = config.profiles_dir / (profile_name + '.rc')
        if env_file.is_file():
            return json.loads(env_file.read_text())

        with TemporaryDirectory() as tempdir:
            os.chmod(tempdir, 0o777)
            tmp_profile = os.path.join(tempdir, 'profile')
            self._sandbox.add_rw_bind(tempdir, tempdir)
            rc = await async_check_output(
                *self.get_sandbox_prefix(),
                NIX,
                'print-dev-env',
                '--profile',
                tmp_profile,
                *cmd,
                cwd=self._cmd_workdir,
            )
            self._sandbox.remove_rw_bind(tempdir, tempdir)
            # Already built, will just be symlinked and added to gcroots. Can be run on host
            await async_check_output(
                NIX,
                'build',
                '--out-link',
                str(config.profiles_dir / profile_name),
                tmp_profile,
                cwd=config.empty_dir,
            )

        env = json.loads(
            await async_check_output(
                *self.get_sandbox_prefix(),
                BASH,
                '-c',
                f'{rc}\n{JQ} -n env',
                cwd=self._cmd_workdir,
            )
        )

        if (
            (nix_build_top := env.get('NIX_BUILD_TOP'))
            and '/nix-shell.' in nix_build_top
            and os.path.isdir(nix_build_top)
        ):
            shutil.rmtree(nix_build_top)

        for var in (
            'NIX_BUILD_TOP',
            'TMP',
            'TMPDIR',
            'TEMP',
            'TEMPDIR',
            'terminfo',
        ):
            if var in env:
                del env[var]

        env_file.write_text(json.dumps(env))

        return env

    async def clone_repo(self, token: str, repo_name: str, sha: str):
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
            cwd=self._host_workdir,
        )
        await async_check_output(
            GIT,
            'switch',
            '-d',
            sha,
            cwd=self._host_workdir,
        )

    def get_profile_filename(self) -> str:
        paths = []
        for entry in self._foxfile.nix_paths:
            if '*' in entry:
                paths.extend(
                    (
                        str(x.relative_to(self._host_workdir))
                        for x in self._host_workdir.glob(entry)
                    )
                )
            else:
                paths.append(entry)
        paths.sort()
        hashes = sha1()
        for filename in paths:
            p = self._host_workdir / filename
            if not p.is_file():
                continue
            hashes.update(filename.encode())
            hashes.update(sha1(p.read_bytes()).digest())
        return hashes.hexdigest()

    async def run_check(self):
        file = self._host_workdir / 'foxfile.yml'
        if not file.is_file():
            raise ConfigurationError('Foxfile not found')
        self._foxfile = Foxfile.model_validate(yaml.safe_load(file.read_text()))

        if config.use_sandbox:
            self._cmd_workdir = config.empty_dir
            self._sandbox = Sandbox(
                overlay_nix_cache=True, workdir=self.SANDBOX_WORKDIR
            )
            self._sandbox.add_rw_bind(str(self._host_workdir), self.SANDBOX_WORKDIR)
        else:
            self._cmd_workdir = self._host_workdir

        s = time()
        env = await self.get_shell_variables(self.get_profile_filename())
        print(f'Env import took {time() - s}')
        res = []
        is_ok = True

        self._sandbox.add_envs(env)

        p = await create_subprocess_exec(
            *self.get_sandbox_prefix(),
            BASH,
            '-c',
            self._foxfile.script,
            cwd=self._cmd_workdir,
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

    async def cleanup(self):
        if self._host_workdir.parent == config.runs_dir:
            effective_workdir = (
                self.SANDBOX_WORKDIR if config.use_sandbox else self._host_workdir
            )
            dirs = (x.relative_to(self._host_workdir) for x in self._host_workdir.glob('*'))
            dirs = (os.path.join(effective_workdir, x) for x in dirs)
            self._sandbox.clear_env()
            await async_check_output(
                *self.get_sandbox_prefix(),
                'rm',
                '-rf',
                *dirs,
                cwd=config.empty_dir,
            )
            self._host_workdir.rmdir()
