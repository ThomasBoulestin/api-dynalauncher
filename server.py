
from flask import Flask, render_template, request, send_from_directory
from serv.models import db, ensure_schema
from serv.websocket_api import socketio, job_manager
from jsonrpcserver import method, Result, Success, dispatch
from colorama import Fore, Back, Style, init
from engineio.async_drivers import gevent
from os import system
import argparse

VERSION = "2.0.8"


ART = f"""
           _____ _____      _____                    _                            _               
     /\   |  __ \_   _|    |  __ \                  | |                          | |              
    /  \  | |__) || |______| |  | |_   _ _ __   __ _| |     __ _ _   _ _ __   ___| |__   ___ _ __ 
   / /\ \ |  ___/ | |______| |  | | | | | '_ \ / _` | |    / _` | | | | '_ \ / __| '_ \ / _ \ '__|
  / ____ \| |    _| |_     | |__| | |_| | | | | (_| | |___| (_| | |_| | | | | (__| | | |  __/ |   
 /_/    \_\_|   |_____|    |_____/ \__, |_| |_|\__,_|______\__,_|\__,_|_| |_|\___|_| |_|\___|_|   
                                    __/ |                                                         
                                   |___/     {VERSION}"""

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
    # Ensure existing databases are upgraded with new columns
    ensure_schema()


parser = argparse.ArgumentParser(description='')
# Optional positional argument
parser.add_argument('--port', type=int, default=5568,
                    help='server port to use')
parser.add_argument('--noIntelMpiCoreAllocation', action='store_true',
                    help='disable Intel MPI core allocation and pinning logic (jobs will run without CPU affinity)')
ARGS = parser.parse_args()


socketio.init_app(app, cors_allowed_origins='*',
                  async_mode='gevent', logger=False)

# Configure job_manager with command line options
job_manager.configure(
    disable_intel_mpi_core_allocation=ARGS.noIntelMpiCoreAllocation)

job_manager.set_context(app)

# Display core allocation status
if ARGS.noIntelMpiCoreAllocation:
    print()
    print(Fore.YELLOW + "═══ CORE ALLOCATION DISABLED ═══" + Style.RESET_ALL)
    print(Fore.YELLOW + "Intel MPI core pinning is disabled" + Style.RESET_ALL)
    print(Fore.YELLOW + "Jobs will run without CPU affinity constraints" + Style.RESET_ALL)
    print(Fore.YELLOW + "═══════════════════════════════════" + Style.RESET_ALL)
    print()


if __name__ == '__main__':

    # print(args.lic_server)

    system("title " + f"api-dynalauncher {VERSION}")

    port = ARGS.port
    host = '0.0.0.0'

    print()
    print(Fore.GREEN + f'Listening on ' + Fore.RED + f'{host}:{port}')
    print(Fore.GREEN + f'License server ' +
          Fore.RED + f'LSTC_LICENSE_SERVER env var')
    print(Style.RESET_ALL)

    try:
        socketio.run(app, host=host, port=port, debug=False)
    except OSError:
        print()
        print(Fore.RED + f'Server is already running on port {port}')
        print(Style.RESET_ALL)
