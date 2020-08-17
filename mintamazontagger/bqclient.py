import logging

from mintapi.api import Mint, MINT_ROOT_URL

from mintamazontagger.my_progress import no_progress_factory
from mintamazontagger.currency import micro_usd_to_usd_float

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

UPDATE_TRANS_ENDPOINT = '/updateTransaction.xevent'


class BigQueryClient():
    def __init__(
            self,
            progress_factory=no_progress_factory):
        self.progress_factory = progress_factory

        self.mintapi = None

    def close(self):
        if self.mintapi:
            self.mintapi.close()
            self.mintapi = None

    def get_mintapi(self):
        if self.mintapi:
            return self.mintapi
