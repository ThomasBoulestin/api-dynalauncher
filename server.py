
from flask import Flask, render_template, request, send_from_directory
from serv.models import db
from serv.websocket_api import socketio, job_manager
from jsonrpcserver import method, Result, Success, dispatch
from colorama import Fore, Back, Style, init
from engineio.async_drivers import gevent
from serv.job_manager import LICENSE_SERVER
from os import system


ART = """
           _____ _____      _____                    _                            _               
     /\   |  __ \_   _|    |  __ \                  | |                          | |              
    /  \  | |__) || |______| |  | |_   _ _ __   __ _| |     __ _ _   _ _ __   ___| |__   ___ _ __ 
   / /\ \ |  ___/ | |______| |  | | | | | '_ \ / _` | |    / _` | | | | '_ \ / __| '_ \ / _ \ '__|
  / ____ \| |    _| |_     | |__| | |_| | | | | (_| | |___| (_| | |_| | | | | (__| | | |  __/ |   
 /_/    \_\_|   |_____|    |_____/ \__, |_| |_|\__,_|______\__,_|\__,_|_| |_|\___|_| |_|\___|_|   
                                    __/ |                                                         
                                   |___/     2.0.1"""

init()
print(Fore.BLUE + ART + Style.RESET_ALL)


app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config['SECRET_KEY'] = 'secret!'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///DynaLauncher.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

with app.app_context():
    db.create_all()


socketio.init_app(app, cors_allowed_origins='*',
                  async_mode='gevent', logger=False)
job_manager.set_context(app)


if __name__ == '__main__':
    system("title " + "api-dynalauncher 2.0.1")

    port = 5558
    host = '0.0.0.0'

    print()
    print(Fore.GREEN + f'Listening on ' + Fore.RED + f'{host}:{port}')
    print(Style.RESET_ALL)

    LICENSE_SERVER = "colas41096"

    try:
        socketio.run(app, host=host, port=port, debug=False)
    except OSError:
        print()
        print(Fore.RED + f'Server is already running on port {port}')
        print(Style.RESET_ALL)
