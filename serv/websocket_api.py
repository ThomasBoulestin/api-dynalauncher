import json
import os
from pathlib import Path
import signal
from typing import List
from flask_socketio import SocketIO, emit, send
from sqlalchemy import desc, true
from serv.models import SqlJob, db
from serv.job_manager import JobManager, get_lic_count, get_qrun_jobs, qkill_job
from colorama import Fore, Back, Style, init

from jsonrpcserver import method, Result, Success, dispatch, Error


socketio = SocketIO()
job_manager = JobManager(socketio)


def sqlJobRequestToList(sql_job_list) -> List[dict]:
    """ Convert a SQL-Alchemy query obj to a list
    :param sql_job_list: SQL-Alchemy query obj
    """

    return [{
        "id": j.id,
        "input": j.input.strip(),
        "solver": j.solver.strip(),
        "command": j.command.strip(),
        "ncpu": j.ncpu,
        "memory": j.memory if j.memory else "",
        "status": j.status.strip() if j.status else "",
        "progress": j.progress,
        "started": j.started,
        "ETA": j.ETA,
        "elapsed": j.elapsed,
        "current": j.current,
        "end": j.end,
        "pid": j.pid,
        "expr": j.expr,
        "a_mass": j.a_mass,
        "pct_mass": j.pct_mass,
    } for j in sql_job_list]


def clean_folder(folder, clean_all=True):
    """Clean folder prior to a Job start
    :param folder: path to the directory
    :param clean_all default=True: clean everything or just necessery files for a restart
    """

    except_files = ['pid', 'stdout', 'd3kil']

    for file in except_files:
        try:
            os.remove(os.path.join(folder, file))
        except OSError:
            pass

    for file in os.listdir(folder):
        delete_file = True
        file = os.path.join(folder, file)

        if clean_all:
            for ext in [".dyn",  ".key", ".k"]:
                if ext in file:
                    delete_file = False
                    break

            if delete_file:
                try:
                    os.remove(file)
                except OSError:
                    pass


@socketio.on("message")
def handle_message(request):
    if response := dispatch(request):
        send(response, json=False)


@method
def fileExists(input) -> Result:

    if(os.path.isfile(input)):
        return Success(True)
    else:
        return Success(False)



@method
def getFullJobList() -> Result:
    jbs = SqlJob.query.order_by(desc(SqlJob.id)).limit(-1)
    return Success(sqlJobRequestToList(jbs))


@method
def getLicCount() -> Result:
    s = get_lic_count()
    s.append(job_manager.queue_manager.get_cpu_count())
    return Success(s)

@method
def getQrunJobs() -> Result:
    s = get_qrun_jobs()
    return Success(s)

@method
def qKillJob(host) -> Result:
    b, message = qkill_job(host)
    return Success({"success" : b, "message": message})

@method
def isjobRunning(input):
    if job_manager.check_if_running(input):
        return Success(True)
    else:
        return Success(False)


@method
def startJob(job_data, clean_all=True):
    working_dir = Path(job_data['input']).parent.absolute()
    if job_manager.check_if_running(job_data['input']):
        return Error(10, "Job is already running.")

    clean_folder(working_dir, clean_all=clean_all)
    j = job_manager.add_job(job_data)

    socketio.emit("message", json.dumps({"jsonrpc": "2.0", "method": "addJob",
                                        "params": {"job": j}}), broadcast=True
                  )

    return Success(j)


@method
def cleanFolder(input):
    working_dir = Path(input).parent.absolute()
    clean_folder(working_dir, clean_all=True)
    return Success


@method
def getQueue():
    return Success(job_manager.queue_manager.jobs)


@method
def isInQueue(input):
    if job_manager.queue_manager.check_if_in_queue(input):
        return Success(True)
    else:
        return Success(False)


@method
def addToQueue(job_data):
    if job_manager.queue_manager.check_if_in_queue(job_data['input']):
        return Error(10, "Job is already in queue.")

    j = job_manager.queue_manager.add_job(job_data)

    socketio.emit("message", json.dumps({"jsonrpc": "2.0", "method": "setQueue",
                                         "params": {"jobs": job_manager.queue_manager.jobs}}), broadcast=True
                  )

    return Success(j)


@method
def removeFromQueue(position):
    j = job_manager.queue_manager.remove_job(position)
    socketio.emit("message", json.dumps({"jsonrpc": "2.0", "method": "setQueue",
                                        "params": {"jobs": job_manager.queue_manager.jobs}}), broadcast=True
                  )
    return Success(j)


@method
def switchPositionQueue(initial, new):
    j = job_manager.queue_manager.change_position(initial, new)

    if j == -1:
        return Error(10, "Can't switch position.")
    else:
        socketio.emit("message", json.dumps({"jsonrpc": "2.0", "method": "setQueue",
                                             "params": {"jobs": job_manager.queue_manager.jobs}}), broadcast=True
                      )
        return Success(j)


@method
def setNcpuQueue(id, ncpu):
    j = job_manager.queue_manager.set_ncpu(id, ncpu)
    if j == -1:
        return Error(10, "Can't set NCPU.")
    else:
        socketio.emit("message", json.dumps({"jsonrpc": "2.0", "method": "setQueue",
                                             "params": {"jobs": job_manager.queue_manager.jobs}}), broadcast=True
                      )
        return Success(j)


@method
def isFolderEmpty(input_file):
    working_dir = Path(input_file).parent.absolute()
    if "d3plot" in os.listdir(working_dir):
        return Success(False)
    else:
        return Success(True)


@method
def sendD3kill(id, payload):
    is_running = int(id) in job_manager.jobs
    if is_running:
        if job_manager.jobs[int(id)].status == "starting":
            return Error(10, f"Job {id}: Please wait to send d3kil.")
        else:
            job_manager.jobs[id].write_d3kil(payload)
            return Success()
    else:
        return Error(20, f"Job {id} is not running.")


@method
def KillProcessByJobId(id):
    try:
        os.kill(job_manager.jobs[int(id)].sq_job.pid, signal.SIGTERM)
        print(Fore.RED + "Job" + Style.RESET_ALL +
              f" - {str(job_manager.jobs[int(id)].sq_job.pid)}" + Fore.RED + " Killed" + Style.RESET_ALL)
        return Success()

    except:
        return Error(10)


@method
def getRunningShells():
    l = {}

    for job in job_manager.jobs.values():
        l[job.sq_job.id] = ({
            "id": job.sq_job.id,
            "input": job.sq_job.input.strip(),
            "solver": job.sq_job.solver.strip(),
            "command": job.sq_job.command.strip(),
            "ncpu": job.sq_job.ncpu,
            "memory": job.sq_job.memory if job.sq_job.memory else "",
            "status": job.sq_job.status.strip() if job.sq_job.status else "",
            "status": job_manager.jobs[job.sq_job.id].status.strip() if job_manager.jobs[job.sq_job.id].status else "",
            "progress": job.sq_job.progress,
            "started": job.sq_job.started,
            "ETA": job.sq_job.ETA,
            "elapsed": job.sq_job.elapsed,
            "current": job.sq_job.current,
            "end": job.sq_job.end,
            "pid": job.sq_job.pid,
            "expr": job.sq_job.expr,
            "a_mass": job.sq_job.a_mass,
            "pct_mass": job.sq_job.pct_mass,
            "stdout": ''.join(job.get_shell_content())
        })

    return Success(l)


@method
def removeShell(id):
    if int(id) in job_manager.jobs:
        job_manager.remove_from_manager(int(id))

        socketio.emit("message", json.dumps({"jsonrpc": "2.0", "method": "removeShell",
                                             "params": {"id": id}}), broadcast=True
                      )

    return Success(id)
