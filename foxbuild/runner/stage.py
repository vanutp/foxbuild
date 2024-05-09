import os.path
import os.path
from asyncio import create_subprocess_exec

import json
import logging
import re
import shutil
from hashlib import sha1
from pathlib import Path
from subprocess import PIPE, DEVNULL
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

from foxbuild.config import config, OperationMode
from foxbuild.const import DEFAULT_IMAGE, SANDBOX_WORKDIR
from foxbuild.runner.utils import checkout_repo
from foxbuild.sandbox import Sandbox
from foxbuild.schemas import StageResult
from foxbuild.schemas.foxfile import StageDef, WorkflowDef, EnvSettings
from foxbuild.utils import async_check_output, NIX, BASH, JQ

if TYPE_CHECKING:
    from foxbuild.runner.runner import Runner

logger = logging.getLogger(__name__)


class StageRunner:
    runner: 'Runner'
    workflow: WorkflowDef
    stage: StageDef
    host_workdir: Path
    sandbox: Sandbox | None

    def __init__(
        self,
        workflow_stage_key: str,
        runner: 'Runner',
        workflow: WorkflowDef,
        stage: StageDef,
    ):
        if runner.host_workdir is None:
            self.host_workdir = (
                config.runs_dir
                / runner.run_info.provider
                / runner.run_info.run_id
                / workflow_stage_key
            )
            self.host_workdir.mkdir(parents=True)
        else:
            self.host_workdir = runner.host_workdir
        self.runner = runner
        self.workflow = workflow
        self.stage = stage
        self.sandbox = None

    @property
    def env(self) -> EnvSettings:
        res = EnvSettings()

        def set_prop(name, default):
            if (stage_value := getattr(self.stage, name)) is not None:
                resolved = stage_value
            elif (root_value := getattr(self.runner.foxfile, name)) is not None:
                resolved = root_value
            else:
                resolved = default
            setattr(res, name, resolved)

        set_prop('use_flake', False)
        set_prop('nixpkgs', None)
        set_prop('packages', None)
        set_prop('image', DEFAULT_IMAGE)
        return res

    @property
    def use_sandbox(self):
        return config.always_use_sandbox or self.env.image != DEFAULT_IMAGE

    async def exec_maybe_sandboxed(
        self, *args: str, stdout=None, stderr=None, env=None
    ):
        if self.use_sandbox:
            cmd_workdir = config.empty_dir
            prefix = self.sandbox.build_cmd_prefix()
            self.sandbox.add_envs(env)
            env = {}
        else:
            cmd_workdir = self.host_workdir
            prefix = []
        try:
            return await create_subprocess_exec(
                *prefix,
                *args,
                cwd=cmd_workdir,
                stdin=DEVNULL,
                stdout=stdout,
                stderr=stderr,
                env=env,
            )
        finally:
            if self.use_sandbox:
                self.sandbox.clear_env()

    async def check_maybe_sandboxed(self, *args: str) -> str:
        p = await self.exec_maybe_sandboxed(*args, stdout=PIPE, stderr=None)
        await p.wait()
        if p.returncode:
            logger.error(f'Process exited with code {p.returncode}')
            raise ValueError
        return (await p.stdout.read()).decode()

    def gen_nix_shell(self):
        for package in self.env.packages:
            if not re.fullmatch(r'[a-zA-Z_][\w\-]+', package):
                raise ValueError
        packages = ' '.join(self.env.packages)
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

    async def get_shell_variables(self, profile_name: str | None):
        if self.env.use_flake:
            cmd = [self.env.use_flake]
        else:
            cmd = [
                '--impure',
                '--expr',
                self.gen_nix_shell(),
            ]

        if profile_name:
            env_file = config.profiles_dir / (profile_name + '.rc')
            if env_file.is_file():
                return json.loads(env_file.read_text())

        with TemporaryDirectory() as tempdir:
            os.chmod(tempdir, 0o777)
            tmp_profile = os.path.join(tempdir, 'profile')
            if self.use_sandbox:
                self.sandbox.add_rw_bind(tempdir, tempdir)
            rc = await self.check_maybe_sandboxed(
                NIX,
                'print-dev-env',
                '--profile',
                tmp_profile,
                *cmd,
            )
            if self.use_sandbox:
                self.sandbox.remove_rw_bind(tempdir, tempdir)
            if profile_name:
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
            await self.check_maybe_sandboxed(BASH, '-c', f'{rc}\n{JQ} -n env')
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

        if profile_name:
            env_file.write_text(json.dumps(env))

        return env

    def get_profile_filename(self) -> str | None:
        if self.runner.foxfile.nix_paths is None or self.env.use_flake is False:
            return None
        paths = []
        for entry in self.runner.foxfile.nix_paths:
            if '*' in entry:
                paths.extend(
                    (
                        str(x.relative_to(self.host_workdir))
                        for x in self.host_workdir.glob(entry)
                    )
                )
            else:
                paths.append(entry)
        paths.sort()
        hashes = sha1()
        for filename in paths:
            p = self.host_workdir / filename
            if not p.is_file():
                continue
            hashes.update(filename.encode())
            hashes.update(sha1(p.read_bytes()).digest())
        return hashes.hexdigest()

    async def run(self) -> StageResult:
        try:
            if self.runner.run_info:
                await checkout_repo(self.runner.run_info, self.host_workdir)

            if self.use_sandbox:
                self.sandbox = Sandbox(
                    overlay_nix_cache=True,
                    workdir=SANDBOX_WORKDIR,
                    image=self.env.image,
                )
                self.sandbox.add_rw_bind(str(self.host_workdir), SANDBOX_WORKDIR)

            env = await self.get_shell_variables(self.get_profile_filename())

            p = await self.exec_maybe_sandboxed(
                BASH,
                '-c',
                'set -e\n' + self.stage.run,
                env=env,
                stdout=PIPE,
                stderr=PIPE,
            )
            await p.wait()

            return StageResult(
                exit_code=p.returncode,
                stdout=(await p.stdout.read()).decode(),
                stderr=(await p.stderr.read()).decode(),
            )
        finally:
            await self.cleanup()

    async def _remove_workdir_if_needed(self):
        if config.mode == OperationMode.standalone:
            effective_workdir = (
                SANDBOX_WORKDIR if self.use_sandbox else self.host_workdir
            )
            dirs = (
                x.relative_to(self.host_workdir) for x in self.host_workdir.glob('*')
            )
            dirs = (os.path.join(effective_workdir, x) for x in dirs)
            self.sandbox.clear_env()
            try:
                self.sandbox.unsafe_run_as_root = True
                await self.check_maybe_sandboxed(
                    'rm',
                    '-rf',
                    *dirs,
                )
            finally:
                self.sandbox.unsafe_run_as_root = False
            self.host_workdir.rmdir()

    async def cleanup(self):
        if self.use_sandbox:
            await self.sandbox.cleanup()
