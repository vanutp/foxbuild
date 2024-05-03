import logging
import uvicorn

from foxbuild.config import config
from foxbuild.web import app

logging.basicConfig(
    format='%(asctime)s %(levelname)s: %(message)s',
    level=logging.INFO,
)

uvicorn.run(app, host=config.host, port=config.port)
