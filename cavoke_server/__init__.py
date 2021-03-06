import logging
import os
import sys
from logging import NullHandler

import firebase_admin
import requests
import urllib.parse as urlparse
from firebase_admin import credentials, firestore

from cavoke_server.settings import SECRET_PATH
from cavoke_server.secret.secret_settings import TELEGRAM_BOT_CHAT, TELEGRAM_BOT_TOKEN, FIREBASE_JSON_FILE

__author__ = "Alex Kovrigin (a.kovrigin0@gmail.com)"
__license__ = "MIT"
__version__ = "0.0.1"


logging.getLogger(__name__).addHandler(NullHandler())

# initialize firebase
try:
    cred = credentials.Certificate(os.path.join(SECRET_PATH, FIREBASE_JSON_FILE))
    firebase_admin.initialize_app(cred)
except ValueError:
    pass
db = firestore.client()


def add_stderr_logger(level=logging.DEBUG):
    """
    Helper for quickly adding a StreamHandler to the logger. Useful for
    debugging.
    Returns the handler after adding it.
    """
    logger = logging.getLogger(__name__)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.debug("Added a stderr logging handler to logger: %s", __name__)
    return handler


# ... Clean up.
del NullHandler


def notifyAdmin(message: str):
    """
    Notifies moderator(-s)
    :param message: message to send
    """
    # send message via telegram
    try:
        telegram_request = requests.get(
            'https://api.telegram.org/bot' + TELEGRAM_BOT_TOKEN +
            '/sendMessage?chat_id=' + TELEGRAM_BOT_CHAT +
            '&text= ' + urlparse.quote(message))
    except:
        sys.stderr.write('[!!!] Error when sending request to telegram.\n')
    else:
        if not telegram_request.json()['ok']:
            sys.stderr.write('[!!!] Error when sending message to telegram. See full response:\n')
            sys.stderr.write(telegram_request.text + '\n')
