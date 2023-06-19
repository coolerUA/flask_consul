import json
import random
from time import sleep
import uuid
import atexit
import os
import socket, struct
import requests
from flask import Flask

import consul

from logging.config import dictConfig

dictConfig({
    'version': 1,
    'formatters': {'default': {
        'format': '[%(asctime)s] %(levelname)s in %(module)s: %(message)s',
    }},
    'handlers': {'wsgi': {
        'class': 'logging.StreamHandler',
        'stream': 'ext://sys.stdout',
        'formatter': 'default'
    }},
    'root': {
        'level': 'INFO',
        'handlers': ['wsgi']
    }
})


def get_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(0)
    try:
        # doesn't even have to be reachable
        s.connect(('10.254.254.254', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

def get_default_gateway_linux():
    with open("/proc/net/route") as fh:
        for line in fh:
            fields = line.strip().split()
            if fields[1] != '00000000' or not int(fields[3], 16) & 2:
                continue
            return socket.inet_ntoa(struct.pack("<L", int(fields[2], 16)))


if os.getenv('CONSUL') != None:
    CONSUL = os.getenv('CONSUL')
else: 
    CONSUL=get_default_gateway_linux()

BASE_CONSUL_URL = 'http://' +  CONSUL + ':8500'
HOSTNAME = os.getenv('HOSTNAME')

config = {'default':'config'}
prev_config = {'default':'config'}
changed = 0
SERVICE_ADDRESS = get_ip()

PORT = 8080 
UUID=str(uuid.uuid5(uuid.NAMESPACE_DNS, str(SERVICE_ADDRESS) + ":" + str(PORT) + ":" + HOSTNAME))

c = consul.Consul(host=CONSUL)

app = Flask(__name__)

@app.route('/')
def home():
    global config
    global prev_config
    global changed
    if changed == 1:
        ad = f'<br>configuration changed. new configuration: {config} | prev config: {prev_config}'
        if config != {}:
            prev_config = config
        changed = 0
    else:
        ad = f'configuration NOT changed: {config}'
    return f"Hello World, <br> I`m {HOSTNAME} from {SERVICE_ADDRESS} {PORT} {UUID} <br> my config: {config} | {ad}"


@app.route('/health')
def hello_world():
    data = {
        'status': 'healthy'
    }
    global config
    global prev_config
    global changed
    try:
        _, resp = c.kv.get('PythonApp/config', wait='2s')
        resp_config = resp['Value']
        if resp_config != prev_config:
            changed = 1
            config = resp_config
    except Exception as e:
        # config = {}
        app.logger.debug(f'Get config from consul failed: {e}')
    return json.dumps(data)

@app.route('/register')
def register():
    url = BASE_CONSUL_URL + '/v1/agent/service/register'
    data = {
        'Name': 'PythonApp',
        'ID': UUID,
        'Tags': ['flask'],
        'Address': SERVICE_ADDRESS,
        'Port': PORT,
        'Check': {
            'http': 'http://{address}:{port}/health'.format(address=SERVICE_ADDRESS, port=PORT),
            'interval': '10s'
        }
    }
    res = requests.put(
        url,
        data=json.dumps(data)
    )
    return res

def cleanup():
    try:
        sleep(int(random.randrange(1,5)))
        url = BASE_CONSUL_URL + '/v1/agent/service/deregister/' + UUID
        data = {
            'service_id': UUID,
        }

        res = requests.put(
            url,
            data=json.dumps(data)
        )
        app.logger.debug(f'Service registration parameters: {data} | {res.status_code} : {res.text}')
        return f'Response: {res.text} | status_code: {res.status_code}'
    except Exception as e:
        app.logger.debug(f'{e}')
atexit.register(cleanup)

if __name__ == '__main__':
    sleep(1)
    status = ""
    while status != 200:
        try:
            app.logger.debug(f'Registering on consul')
            status = register().status_code
            sleep(int(random.randrange(1,5)))
        except Exception as e:
            app.logger.debug(f'ERROR::::: {e}')
    app.run(debug=True, host="0.0.0.0", port=PORT)