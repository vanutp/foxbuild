import yaml
from pathlib import Path
from pydantic import ValidationError
from tempfile import TemporaryDirectory
from yaml import YAMLError

from foxbuild.config import config, OperationMode
from foxbuild.exceptions import ConfigurationError
from foxbuild.runner.utils import checkout_repo
from foxbuild.runner.workflow import WorkflowRunner
from foxbuild.schemas import StandaloneRunInfo, RunResult
from foxbuild.schemas.foxfile import Foxfile


class Runner:
    foxfile: Foxfile | None
    host_workdir: Path | None
    run_info: StandaloneRunInfo | None

    def __init__(self, host_workdir: Path | None, run_info: StandaloneRunInfo | None):
        if host_workdir and run_info or not host_workdir and not run_info:
            raise ValueError(
                'One and only one of host_workdir and run_info must be set'
            )
        if config.mode == OperationMode.standalone and run_info is None:
            raise ValueError('run_info must be set in standalone mode')
        self.foxfile = None
        self.host_workdir = host_workdir
        self.run_info = run_info

    def load_foxfile(self, repo_root: Path):
        file = repo_root / 'foxfile.yml'
        if not file.is_file():
            raise ConfigurationError('Foxfile not found')
        try:
            self.foxfile = Foxfile.model_validate(yaml.safe_load(file.read_text()))
        except (YAMLError, ValidationError) as e:
            raise ConfigurationError(str(e))

    async def run(self) -> RunResult:
        if self.host_workdir:
            self.load_foxfile(self.host_workdir)
        else:
            with TemporaryDirectory() as path:
                await checkout_repo(self.run_info, path)
                self.load_foxfile(Path(path))

        results = {}
        for i, (workflow_name, workflow) in enumerate(self.foxfile.workflows.items()):
            workflow_runner = WorkflowRunner(self, workflow, i)
            results[workflow_name] = await workflow_runner.run()
        return RunResult(workflows=results)
