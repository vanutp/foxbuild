from pydantic import BaseModel


class StandaloneRunInfo(BaseModel):
    provider: str
    clone_url: str
    repo_name: str
    commit_sha: str
    run_id: str


class StageResult(BaseModel):
    exit_code: int
    stdout: str
    stderr: str


class WorkflowResult(BaseModel):
    stages: dict[str, StageResult | None]


class RunResult(BaseModel):
    workflows: dict[str, WorkflowResult | None]
