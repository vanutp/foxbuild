from typing import TYPE_CHECKING

from foxbuild.runner.stage import StageRunner
from foxbuild.schemas import WorkflowResult
from foxbuild.schemas.foxfile import WorkflowDef

if TYPE_CHECKING:
    from foxbuild.runner.runner import Runner


class WorkflowRunner:
    runner: 'Runner'
    workflow: WorkflowDef
    workflow_idx: int

    def __init__(self, runner: 'Runner', workflow: WorkflowDef, workflow_idx: int):
        self.runner = runner
        self.workflow = workflow
        self.workflow_idx = workflow_idx

    async def run(self) -> WorkflowResult:
        results = {}
        for i, stage_name in enumerate(self.workflow.stages):
            stage = self.runner.foxfile.stages[stage_name]
            workflow_stage_key = f'{self.workflow_idx}_{i}'
            stage_runner = StageRunner(
                workflow_stage_key, self.runner, self.workflow, stage
            )
            results[stage_name] = await stage_runner.run()
        return WorkflowResult(stages=results)
