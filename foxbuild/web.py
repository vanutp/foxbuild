import logging
from time import time

import httpx
from datetime import datetime
from joserfc import jwt
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from foxbuild.config import config
from foxbuild.runner import Runner

GH_API_BASE = 'https://api.github.com'


def get_token():
    now = int(datetime.now().timestamp()) - 60
    data = {
        'iat': now,
        'exp': now + 60 * 10,
        'iss': config.gh_app_id,
    }
    return jwt.encode({'alg': 'RS256'}, data, config.gh_key)


async def get_clients(
    payload: dict,
) -> tuple[httpx.AsyncClient, httpx.AsyncClient, str]:
    app_client = httpx.AsyncClient(
        base_url=GH_API_BASE,
        headers={'Authorization': f'Bearer {get_token()}'},
    )
    installation_id = payload['installation']['id']
    installation_token_resp = await app_client.post(
        f'/app/installations/{installation_id}/access_tokens'
    )
    installation_token_resp.raise_for_status()
    installation_token = installation_token_resp.json()['token']
    installation_client = httpx.AsyncClient(
        base_url=GH_API_BASE,
        headers={'Authorization': f'Bearer {installation_token}'},
    )
    return app_client, installation_client, installation_token


async def create_check_run(payload: dict, client: httpx.AsyncClient):
    global s
    s = time()
    repo_name = payload['repository']['full_name']
    resp = await client.post(
        f'/repos/{repo_name}/check-runs',
        json={
            'name': 'meow',
            'head_sha': (
                payload['check_run']['head_sha']
                if 'check_run' in payload
                else payload['check_suite']['head_sha']
            ),
        },
    )
    resp.raise_for_status()


async def initiate_check_run(
    payload: dict, client: httpx.AsyncClient, installation_token: str
):
    check_run_id = payload['check_run']['id']
    workdir = config.runs_dir / str(check_run_id)
    workdir.mkdir()
    repo_name = payload['repository']['full_name']
    head_sha = payload['check_run']['head_sha']

    resp = await client.patch(
        f'/repos/{repo_name}/check-runs/{check_run_id}', json={'status': 'in_progress'}
    )
    resp.raise_for_status()

    runner = Runner(workdir)
    try:
        await runner.clone_repo(installation_token, repo_name, head_sha)
        is_ok, result = await runner.run_check()
    except Exception:
        resp = await client.patch(
            f'/repos/{repo_name}/check-runs/{check_run_id}',
            json={
                'status': 'completed',
                'conclusion': 'failure',
                'output': {
                    'title': 'Internal Foxbuild error',
                    'summary': 'not meow :(',
                },
            },
        )
        resp.raise_for_status()
        raise
    finally:
        await runner.cleanup()

    result = '\n\n'.join((x['stdout'] + '\n' + x['stderr']).strip() for x in result)

    resp = await client.patch(
        f'/repos/{repo_name}/check-runs/{check_run_id}',
        json={
            'status': 'completed',
            'conclusion': 'success' if is_ok else 'failure',
            'output': {'title': 'meow', 'summary': 'meowmeow', 'text': result},
        },
    )
    resp.raise_for_status()
    logging.info(f'Total {time() - s}')


async def webhook(request: Request):
    payload = await request.json()
    app_client, installation_client, installation_token = await get_clients(payload)
    event = request.headers['x-github-event']
    if event == 'check_suite':
        if payload['action'] in ('requested', 'rerequested'):
            await create_check_run(payload, installation_client)
    elif event == 'check_run' and payload['check_run']['app']['id'] == config.gh_app_id:
        if payload['action'] == 'created':
            await initiate_check_run(payload, installation_client, installation_token)
        elif payload['action'] == 'rerequested':
            await create_check_run(payload, installation_client)
    return Response(None, 204)


app = Starlette(
    debug=config.debug, routes=[Route('/webhook', webhook, methods=['POST'])]
)
