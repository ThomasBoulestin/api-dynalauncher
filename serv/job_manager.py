from collections import deque
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
from time import sleep
import time
from typing import Tuple
from threading import Event, Thread
import psutil

from flask import Flask
from flask_socketio import SocketIO

from serv.models import SqlJob, db
from colorama import Fore, Back, Style, init
from typing import List, Dict
import sys


def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)


def get_lic_count(server='') -> List[int]:
    """Return LsDyna license server informations using lstc_qrun.exe
    :param server: Name or IP of the lic server. If "", LSTC_LICENSE_SERVER
                           env variable is used

    return (used, max) as integers
    """

    exe = resource_path(r"dyna-tools/lstc_qrun")
    command = [exe, "-r"]

    if server != "":
        command.append("-s")
        command.append(server)

    try:
        process = subprocess.run(
            command, capture_output=True, check=False
        )
        stdout_as_str = process.stdout.decode("utf-8")
        stdout_split = stdout_as_str.split()
        max_ = int(stdout_split[-3])
        used = int(stdout_split[-5])
    except:
        return [0, 0]

    return [used, max_]


def get_qrun_jobs(server="") -> List[Dict]:
    """Return LsDyna license server running jobs informations using lstc_qrun.exe
    :param server: Name or IP of the lic server. If "", LSTC_LICENSE_SERVER
                           env variable is used
    """

    exe = resource_path(r"dyna-tools/lstc_qrun")
    command = [exe]

    out_list = []

    if server != "":
        command.append("-s")
        command.append(server)

    try:
        process = subprocess.run(
            command, capture_output=True, check=False
        )
        stdout_as_str = process.stdout.decode("utf-8")

        read = False
        for line in stdout_as_str.splitlines():
            if "----------------" in line:
                read = True
                continue

            if len(line.split()) < 5:
                read = False
                continue

            if read:
                l = line.split()
                out_list.append(
                    {
                        "user": l[0],
                        "host": l[1],
                        "program": l[2],
                        "started": " ".join([l[3], l[4], l[5], l[6]]),
                        "procs":  l[7],
                        "josbs":  l[8]
                    }
                )

    except:
        return []

    return out_list


def qkill_job(host, server="") -> [bool, str]:
    """Return LsDyna license server running jobs informations using lstc_qrun.exe
    :param server: Name or IP of the lic server. If "", LSTC_LICENSE_SERVER
                           env variable is used
    """

    exe = resource_path(r"dyna-tools/lstc_qkill")
    command = [exe, host]

    if server != "":
        command.append("-s")
        command.append(server)

    try:
        process = subprocess.run(
            command, capture_output=True, check=False
        )
        stdout_as_str = process.stdout.decode("utf-8")

        if "procid@machine" in stdout_as_str:
            return False, stdout_as_str

        if "License server cannot find" in stdout_as_str:
            return False, stdout_as_str

        if "You are not authorized to terminate this job" in stdout_as_str:
            return False, stdout_as_str

        if "Program queued for termination" in stdout_as_str:
            return True, stdout_as_str

    except:
        return False, "unknown error"

    return False, "unknown error"


class JobManager:
    """JobManager object managing jobs.
     /!\\ Needs to be initialized with set_context(app) method. /!\\

    :param SocketIO socketio: global socketio to communicate with the ws API.
    """

    def __init__(self, socketio: SocketIO) -> None:
        self.socketio = socketio
        self.jobs = {}
        self.app = None

        self.queue_manager = QueueManager(socketio, self)

    def set_context(self, app: Flask) -> None:
        """
        Define object app context

        Check for runnings jobs and change their status if they does not exist anymore,
        create a job object if the job is still running
        """

        self.app = app

        with app.app_context():
            runnings = SqlJob.query.filter_by(status="Running").all()
            for j in runnings:
                if psutil.pid_exists(j.pid):
                    print(
                        Fore.RED
                        + "Trying to connect to already running job"
                        + Style.RESET_ALL
                        + f" - {j.id}"
                        + Style.RESET_ALL
                    )
                    self.connect_to_job(j)
                else:
                    j.status = "Stopped"
                    db.session.commit()

            startings = SqlJob.query.filter_by(status="Starting").all()
            for j in startings:
                if psutil.pid_exists(j.pid):
                    print(
                        Fore.RED
                        + "Trying to connect to already running job"
                        + Style.RESET_ALL
                        + f" - {j.id}"
                        + Style.RESET_ALL
                    )
                    self.connect_to_job(j)
                else:
                    j.status = "Stopped"
                    db.session.commit()

        # # configure a watchdog thread
        # watchdog = Thread(
        #     target=job_watchdog_task, name="job_watchdog_task", args=[self], daemon=True
        # )
        # watchdog.start()

        # elapsed_updater = Thread(
        #     target=elapsed_updater_task,
        #     name="elapsed_updater",
        #     args=[self, app],
        #     daemon=True,
        # )
        # elapsed_updater.start()

        queue_timer_task_updater = Thread(
            target=queue_timer_task, name="queue_timer", args=[self], daemon=True
        )
        queue_timer_task_updater.start()

    def add_job(self, j_json: dict) -> dict:
        """Add job to the manager and start it.

        :param j_json: json containing start infos
                 needs : 'input', 'solver', 'command', 'ncpu', 'expr'

        :return: The input json itself with an 'id' field
        """

        j = SqlJob(
            input=j_json["input"],
            solver=j_json["solver"],
            command=j_json["command"],
            ncpu=int(j_json["ncpu"]),
            expr=j_json["expr"],
            memory=j_json["memory"],
        )

        with self.app.app_context():
            db.session.add(j)
            db.session.commit()

            self.jobs[j.id] = Job(self.socketio, j, self.app, self)
            j_json["id"] = j.id

        return j_json

    def remove_from_manager(self, job_id):
        """delete Job from job manager"""
        try:
            self.jobs[job_id].stop()
            self.jobs[job_id].update_db({"status": "Stopped"})
        except:
            pass

        del self.jobs[job_id]

    def connect_to_job(self, j: SqlJob) -> None:
        """Add job to the manager and start it.
        :param j: SqlJob to connect to
        """
        self.jobs[j.id] = Job(self.socketio, j, self.app, self, j_connect=True)

    def check_if_running(self, input_path: str) -> bool:
        """Check if the Job is running using input path
        :param input_path: Job input path
        """

        for val in self.jobs.values():
            if val.sq_job.input.lower() == input_path.lower():
                if val.watchdog.is_alive():
                    return True

        return False

    def try_to_launch_first_queue_job(self):
        used, max_ = get_lic_count()
        free = max_ - used

        try:
            first_in_queue = self.queue_manager.jobs[0]

            if int(first_in_queue["ncpu"]) <= int(free):
                self.socketio.emit("message", json.dumps({"jsonrpc": "2.0", "method": "addJob",
                                                          "params": {"job": self.add_job(first_in_queue)}}), broadcast=True
                                   )

                self.queue_manager.remove_job(0)

                self.socketio.emit("message", json.dumps({"jsonrpc": "2.0", "method": "setQueue",
                                                         "params": {"jobs": self.queue_manager.jobs}}), broadcast=True
                                   )
        except IndexError:
            return

    def to_json(self) -> dict:
        """Return the JobManager Jobs as a Json dict"""
        out_var = "[\n"
        for var in self.jobs.items():
            out_var += var.to_json() + "\n"

        out_var += "\n]"
        return out_var


def job_watchdog_task(j_m) -> None:
    """Task to be launched as a daemonic Thread

    Infinite loop checking for runnings pids and updating Jobs status

    TODO: make it a class

    """

    while True:
        to_stop = []
        for k in j_m.jobs.keys():

            if j_m.jobs[k].sq_job.pid is not None:
                if (
                    not psutil.pid_exists(j_m.jobs[k].sq_job.pid)
                    and j_m.jobs[k].watchdog.is_alive()
                ):
                    to_stop.append(k)

            try:
                if (
                    j_m.jobs[k].status in [
                        "Finished", "sw1", "Error", "Stopped"]
                    and j_m.jobs[k].watchdog.is_alive()
                ):
                    to_stop.append(k)
            except KeyError:
                pass

        for k in to_stop:
            try:
                if j_m.jobs[k].status in ["Running", "Starting"]:
                    j_m.jobs[k].update_db({"status": "Stopped"})

                sleep(3)
                j_m.jobs[k].stop()
            except KeyError:
                pass

        sleep(5)


def queue_timer_task(j_m: JobManager) -> None:
    """Task to be launched as a daemonic Thread

    Infinite loop trying to launch first queue job

    TODO: make it a class

    """

    while True:
        # print("queue timer")
        j_m.try_to_launch_first_queue_job()
        j_m.socketio.emit("start_queue_timer", (), broadcast=True)
        sleep(30)


# --------------------------------------------------------------------------------------


class Job:
    """Job object to be added to the job manager.
    :param SocketIO socketio: global socketio to communicate with the ws API.
    :param SqlJob sq_job: SQL-Alchemy SqlJob object linked to this job.
    :param Flask app: flask app itself to communicate context to socketio
    /SQL-Alchemy.
    :param job_manager: parent job manager object.
    :param bool j_connect: If the job is a new job or an attempt to connect to
    an already running one.
    :return: The Job itself
    """

    def __init__(
        self,
        socketio: SocketIO,
        sq_job: SqlJob,
        app: Flask,
        job_manager: JobManager,
        j_connect=False,
    ) -> None:
        self.socketio = socketio
        self.sq_job = sq_job
        self.app = app
        self.job_manager = job_manager
        self.j_connect = j_connect  # if we are trying to connect to an existing job

        self.shell_content = deque()

        self.update_status = ""
        self.status = ""

        self.working_dir = Path(self.sq_job.input).parent.absolute()

        # If its the first start of job
        if not j_connect:
            process = subprocess.Popen(
                "cmd /c " + self.sq_job.command + "> stdout 2>&1",
                cwd=self.working_dir,
                creationflags=subprocess.CREATE_BREAKAWAY_FROM_JOB
                | subprocess.CREATE_NO_WINDOW,
            )

            sleep(1)

            pid_to_write = process.pid

            try:
                parent = psutil.Process(process.pid)
                children = parent.children(recursive=True)
                for p in children:
                    # print(p.pid, len(p.children(recursive=True)))
                    if len(p.children(recursive=True)) == 2:
                        # print("    " + str(p.pid))
                        pid_to_write = p.pid

            except psutil.NoSuchProcess:
                print("noprocess")

            with open(
                os.path.join(self.working_dir, "pid"), "w", encoding="utf-8"
            ) as file:
                file.write(str(pid_to_write))

        self.watchdog = StdoutWatchdogThread(
            self, self.working_dir, j_connect=self.j_connect
        )

        # Start Threads
        self.start_stdout_watchdog()

        print(
            Fore.CYAN
            + "Job"
            + Style.RESET_ALL
            + f" - {self.sq_job.id}"
            + Fore.CYAN
            + " Started"
            + Style.RESET_ALL
        )

    def write_d3kil(self, payload: str) -> None:
        """Write a d3kil file into the job dir to communicate with the solver
        :param payload: string to be written in the d3kil file.
        """
        with open(
            os.path.join(self.working_dir, "d3kil"), "w", encoding="utf-8"
        ) as file:
            file.write(payload)

        if "sw1" in payload:
            self.update_status = "sw1"

    def start_stdout_watchdog(self) -> None:
        """Start the Thread who watch stdout file for updates"""
        if not self.watchdog.is_alive():
            self.watchdog.start()

    def stop(self) -> None:
        """Stop the child watchdog Thread and try to delete itself from the parent JobManager"""

        self.watchdog.stop()
        try:
            self.watchdog.join()
        except:
            pass

        # self.job_manager.stop_job(self.sq_job.id)

    def update_shell(self, content: deque) -> None:
        """Send the stdout file content update to the ws API, increment the shell_content local var
        :param content: content to be added
        """
        if len(content) > 0:
            self.shell_content += content
            self.socketio.emit("message", json.dumps({"jsonrpc": "2.0", "method": "appendToShell",
                                                      "params": {"id": self.sq_job.id, "payload": "".join(content)}}), broadcast=True
                               )

    def get_shell_content(self) -> deque:
        """Get the stdout file content of the Job
        :rtype: deque (:str)
        """
        return self.shell_content

    def update_db(self, j_json) -> None:
        """Update SQL-Alchemy sq_job with json content, communicate its content to ws API
        :param j_json: json content
        """

        try:

            with self.app.app_context():
                query = SqlJob.query.filter_by(id=self.sq_job.id).one()

                # Update elapsed and ETA field every seconds
                if not j_json:
                    pass
                    # if query.started is not None and query.current != query.end:
                    #     j_json["elapsed"] = int(time.time() - query.started)
                    #     query.elapsed = j_json["elapsed"]
                    #     if query.ETA is not None:
                    #         query.ETA -= 0.5
                    #         j_json["ETA"] = query.ETA

                else:
                    # compile current and end to make progress
                    if "current" in j_json:

                        if self.status == "Starting":
                            j_json["status"] = "Running"

                        if j_json["current"] is not None:
                            query.current = j_json["current"]

                            if float(j_json["current"]) != 0:
                                try:
                                    pgrs = (
                                        float(j_json["current"])
                                        * 100
                                        / float(self.sq_job.end)
                                    )
                                except TypeError:
                                    pgrs = 0
                                query.progress = pgrs
                                j_json["progress"] = pgrs

                    # compile elapsed and progress to make ETA
                    if "current" in j_json:

                        try:
                            query.ETA = int(
                                (query.elapsed * 100 /
                                 query.progress) - query.elapsed
                            )
                            j_json["ETA"] = query.ETA
                        except TypeError:
                            query.ETA = 0
                            j_json["ETA"] = 0
                        except ZeroDivisionError:
                            query.ETA = 0
                            j_json["ETA"] = 0

                    if "a_mass" in j_json:
                        query.a_mass = float(j_json["a_mass"])

                    if "pct_mass" in j_json:
                        query.pct_mass = float(j_json["pct_mass"])

                    if "end" in j_json:
                        query.end = float(j_json["end"])

                    if "pid" in j_json:
                        query.pid = j_json["pid"]

                    if "status" in j_json:
                        self.status = j_json["status"]
                        query.status = j_json["status"]

                    if "started" in j_json:
                        query.started = j_json["started"]

                try:
                    db.session.commit()
                except:
                    pass

            self.socketio.emit("message", json.dumps({"jsonrpc": "2.0", "method": "update_data",
                                                      "params": {"id": self.sq_job.id, "payload": j_json}}), broadcast=True
                               )
            self.socketio.emit('message', json.dumps({"jsonrpc": "2.0", "method": "update_shell_infos",
                                                      "params": {"id": self.sq_job.id, "input": self.sq_job.input, "status": self.status}}),  broadcast=True
                               )

        except:
            pass

    def to_json(self) -> dict:
        """Return the Job as a Json dict"""
        return json.dumps(
            {
                "id": self.sq_job.id,
            },
            sort_keys=True,
            indent=4,
        )


class StdoutWatchdogThread(Thread):
    """Watchdog to read stdout file content and communicate infos to parent Job object

    :param job: parent Job to communicate with.
    :param wd: Job working directory.
    :param j_connect: If the job is a new job or an attempt to connect to an already running one.
    """

    def __init__(self, job: Job, wd: str, j_connect=False) -> None:
        Thread.__init__(self)
        self.name = f"JOB_{job.sq_job.id}"
        self.daemon = True
        self.running = True
        self.job = job
        self.working_dir = wd
        self.j_connect = j_connect

        self.exit = Event()

    def stop(self) -> None:
        """Stop the Thread loop"""
        self.exit.set()
        self.running = False

    def run(self) -> None:
        """Start the reading loop"""

        # ------------------------------------------------------------------------------
        #                          GET PID in pid file
        # ------------------------------------------------------------------------------

        while (
            not os.path.isfile(os.path.join(
                self.working_dir, "pid")) and self.running
        ):
            time.sleep(0.1)

        with open(os.path.join(self.working_dir, "pid"), "rb") as file:
            try:
                file.seek(-2, os.SEEK_END)
                while file.read(1) != b"\n":
                    file.seek(-2, os.SEEK_CUR)
            except OSError:
                file.seek(0)
            last_line = file.readline().decode("utf-8")
            self.job.sq_job.pid = int(last_line)
            json_f = {"pid": int(last_line), "status": "Starting"}
            if not self.j_connect:
                self.job.sq_job.started = int(time.time())
                json_f["started"] = int(time.time())
            self.job.update_db(json_f)

        # ------------------------------------------------------------------------------
        #                          File reader loop
        # ------------------------------------------------------------------------------

        # Actual byte position of the reader
        pos = 0

        # Sleep time between loops
        sleep_time = 1

        # current job time to increment and compare
        actual_time = 0

        while self.running:
            json_f = {}

            if not os.path.isfile(os.path.join(self.working_dir, "stdout")):
                time.sleep(1)
                continue

            pos, actual_time, to_add, json_f = self.readFile(pos, actual_time)

            self.job.update_db(json_f)
            self.job.update_shell(to_add)
            self.exit.wait(sleep_time)

            if not psutil.pid_exists(self.job.sq_job.pid):
                break

        pos, actual_time, to_add, json_f = self.readFile(pos, actual_time)

        self.job.update_db(json_f)
        self.job.update_shell(to_add)

        self.exit.wait(sleep_time)

        # self.job.stop()

    def readFile(self, pos, actual_time):
        with open(os.path.join(self.working_dir, "stdout"), "rb") as file:
            json_f = {}
            file.seek(pos)
            to_add = deque()

            while line_coded := file.readline():
                json_f = {}

                if line_coded == b"\x00":
                    pos = file.tell()
                    continue

                try:
                    line = line_coded.decode("utf-8").replace("\n", "")
                except ValueError:
                    line = line_coded.decode("utf-16le", errors="ignore").replace(
                        "\n", ""
                    )

                if len(line) > 0:
                    line += "\n"
                to_add.append(line)

                pos = file.tell()

                if (
                    "Livermore  Software  Technology  Corporation" in line
                    and self.job.sq_job.status != "Running"
                ):
                    json_f["status"] = "Running"
                    self.job.update_db(json_f)

                if (
                    "added mass          =" in line
                    and self.job.sq_job.a_mass is None
                ):
                    a_mass = float(line.split()[-1])
                    self.job.sq_job.a_mass = float(a_mass)
                    json_f["a_mass"] = float(a_mass)
                    self.job.update_db(json_f)

                if (
                    "percentage increase =" in line
                    and self.job.sq_job.pct_mass is None
                ):
                    pct_mass = float(line.split()[-1])
                    self.job.sq_job.pct_mass = float(pct_mass)
                    json_f["pct_mass"] = float(pct_mass)
                    self.job.update_db(json_f)

                if "termination time" in line and self.job.sq_job.end is None:
                    try:
                        e_time = float(line.split()[-1])
                        self.job.sq_job.end = float(e_time)
                        json_f["end"] = float(e_time)
                        self.job.update_db(json_f)
                    except ValueError:
                        pass

                if "write d3plot file" in line or "flush i/o buffers" in line:
                    c_time = line.split()[2]
                    if float(c_time) > actual_time:
                        self.job.sq_job.current = float(c_time)
                        json_f["current"] = float(c_time)
                        self.job.update_db(json_f)
                        actual_time = float(c_time)

                if "failed at time" in line:
                    c_time = line.split()[-1]
                    if float(c_time) > actual_time:
                        self.job.sq_job.current = float(c_time)
                        json_f["current"] = float(c_time)
                        self.job.update_db(json_f)
                        actual_time = float(c_time)

                if "error analysis" in line:
                    json_f["status"] = "Error"
                    self.job.update_db(json_f)

                if "E r r o r" in line:
                    json_f["status"] = "Error"
                    self.job.update_db(json_f)

                if "Segmentation Violation" in line:
                    json_f["status"] = "Error"
                    self.job.update_db(json_f)

                if "N o r m a l" in line and self.job.status not in ["sw1"]:
                    if self.job.update_status != "":
                        json_f["status"] = self.job.update_status
                    else:
                        json_f["status"] = "Finished"
                        json_f["current"] = self.job.sq_job.end

                    self.job.update_db(json_f)

        return pos, actual_time, to_add, json_f


class QueueManager:
    def __init__(self, socketio: SocketIO, job_manager: JobManager) -> None:
        self.socketio = socketio
        self.job_manager = job_manager
        self.jobs = []
        self.max_id = 0

    def check_if_in_queue(self, input: str) -> bool:
        for j in self.jobs:
            if j["input"] == input:
                return True

        return False

    def add_job(self, j_json: dict) -> None:
        j_json["position"] = len(self.jobs)
        j_json["id"] = self.max_id
        self.max_id += 1
        self.jobs.append(j_json)

    def remove_job(self, position):
        del self.jobs[position]
        for enum, value in enumerate(self.jobs):
            value["position"] = enum

    def change_position(self, init, new):

        if new == init:
            return -1

        if new < 0:
            new = 0

        if new > len(self.jobs) - 1:
            new = len(self.jobs) - 1

        try:
            self.jobs[init]["position"] = new
            self.jobs[new]["position"] = init
            self.jobs[init], self.jobs[new] = self.jobs[new], self.jobs[init]

            return 1

        except IndexError:
            return -1

    def get_queue_json(self):
        return self.jobs

    def get_positions(self):
        return [job["position"] for job in self.jobs]

    def set_ncpu(self, j_id, ncpu):

        if int(ncpu) == 0:
            return -1

        try:
            for job in self.jobs:
                if int(job["id"]) == int(j_id):
                    job["ncpu"] = int(ncpu)

                    job["command"] = (
                        job["expr"]
                        .replace("$NCPU", str(job["ncpu"]))
                        .replace("$SOLVER", str(job["solver"]))
                        .replace("$INPUT", str(job["input"]))
                        .replace("$MEMORY", str(job["memory"]))
                    )
                    return 1
        except ValueError:
            return -1

    def get_cpu_count(self) -> int:
        count = 0

        for j in self.jobs:
            count += int(j["ncpu"])

        return count
