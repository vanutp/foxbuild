import sys

import asyncio
import uvicorn

from foxbuild.config import config
from foxbuild.setup_sandbox_env import setup_sandbox_env
from foxbuild.web import app

if len(sys.argv) == 1:
    raise ValueError
if sys.argv[1] == 'setup-sandbox-env':
    asyncio.run(setup_sandbox_env())
elif sys.argv[1] == 'server':
    uvicorn.run(app, host=config.host, port=config.port)
else:
    raise ValueError
