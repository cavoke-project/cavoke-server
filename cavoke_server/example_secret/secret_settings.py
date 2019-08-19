# SECURITY WARNING: keep the secret key used in production secret!
import os

from cavoke_server.settings import SECRET_PATH

SECRET_KEY = 'YOUR-DJANGO-SECRET-KEY'

# telegram
TELEGRAM_BOT_TOKEN = 'YOUR-TELEGRAM-BOT-TOKEN'
TELEGRAM_BOT_CHAT = 'YOUR-TELEGRAM-CHAT'

# sql
PRODUCTION_DB = {
    'ENGINE': 'pymysql',
    'NAME': 'YOUR-DB-NAME',
    'USER': 'YOUR-DB-USER',
    'PASSWORD': 'YOUR-DB-PASSWORD',
    'HOST': 'YOUR-DB-IP',
    'PORT': 'YOUR-DB-PORT',
    'OPTIONS':  {
        'ssl': {'ca': os.path.join(SECRET_PATH, 'server-ca.pem'),
                'cert': os.path.join(SECRET_PATH, 'client-cert.pem'),
                'key': os.path.join(SECRET_PATH, 'client-key.pem')
                }
          }
}

FIREBASE_JSON_FILE = 'YOUR-FIREBASE-CONFIG-FILE'
