from collections import deque
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
from time import sleep
import time
from typing import Tuple, Optional
from threading import Event, Thread, Lock
import psutil

from flask import Flask
from flask_socketio import SocketIO

from serv.models import SqlJob, db
from colorama import Fore, Back, Style, init
from typing import List, Dict
import sys

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)


class CoreAllocator:
    """Manages CPU core allocation for jobs

    Tracks physical and logical cores, hyper-threading status,
    and allocates cores to jobs to prevent over-subscription.
    """

    def __init__(self) -> None:
        """Initialize core allocator with system CPU information"""
        self.physical_cores = psutil.cpu_count(logical=False)
        self.logical_cores = psutil.cpu_count(logical=True)
        self.hyper_threading_enabled = self.logical_cores > self.physical_cores

        # List of core dictionaries: {'index': int, 'job_id': Optional[int], 'pid': Optional[int]}
        self.cores = [
            {'index': i, 'job_id': None, 'pid': None}
            for i in range(self.logical_cores)
        ]

        # Lock for thread-safe core allocation
        self.lock = Lock()

        print(
            Fore.GREEN + "CPU Information:" + Style.RESET_ALL +
            f"\n  Physical cores: {self.physical_cores}" +
            f"\n  Logical cores: {self.logical_cores}" +
            f"\n  Hyper-threading: {'Enabled' if self.hyper_threading_enabled else 'Disabled'}"
        )

    def allocate_cores(self, job_id: int, pid: int, num_cores: int) -> Optional[List[int]]:
        """Allocate cores for a job

        :param job_id: Job ID requesting cores
        :param pid: Process ID of the job
        :param num_cores: Number of physical cores requested (will allocate 2x if HT enabled)
        :return: List of allocated core indices, or None if not enough cores available
        """
        with self.lock:
            # If hyper-threading is enabled, allocate 2x the cores
            cores_to_allocate = num_cores * 2 if self.hyper_threading_enabled else num_cores

            # Find available cores
            available_cores = [
                core for core in self.cores if core['job_id'] is None]

            if len(available_cores) < cores_to_allocate:
                print(
                    Fore.YELLOW +
                    f"Warning: Not enough cores available. Requested: {num_cores} ({'HT: ' + str(cores_to_allocate) if self.hyper_threading_enabled else cores_to_allocate}), Available: {len(available_cores)}" +
                    Style.RESET_ALL
                )
                return None

            # Allocate the requested number of cores
            allocated_indices = []
            for i in range(cores_to_allocate):
                core = available_cores[i]
                core['job_id'] = job_id
                core['pid'] = pid
                allocated_indices.append(core['index'])

            ht_info = f" (HT: {num_cores} physical = {cores_to_allocate} logical)" if self.hyper_threading_enabled else ""
            print(
                Fore.CYAN +
                f"Allocated cores {allocated_indices[0]}-{allocated_indices[-1]} to job {job_id} (PID: {pid}){ht_info}" +
                Style.RESET_ALL
            )

            return allocated_indices

    def allocate_specific_cores(self, job_id: int, pid: int, core_indices: List[int]) -> Optional[List[int]]:
        """Attempt to allocate specific cores for a job (used for restore after restart)

        :param job_id: Job ID requesting cores
        :param pid: Process ID of the job
        :param core_indices: List of specific core indices to allocate
        :return: List of allocated core indices if successful, or None if cores unavailable
        """
        with self.lock:
            # Check if all requested cores are available
            for idx in core_indices:
                if idx >= len(self.cores):
                    print(
                        Fore.YELLOW +
                        f"Warning: Core index {idx} out of range (max: {len(self.cores)-1})" +
                        Style.RESET_ALL
                    )
                    return None
                if self.cores[idx]['job_id'] is not None:
                    print(
                        Fore.YELLOW +
                        f"Warning: Requested core {idx} already allocated to job {self.cores[idx]['job_id']}" +
                        Style.RESET_ALL
                    )
                    return None

            # All requested cores are available - allocate them
            for idx in core_indices:
                self.cores[idx]['job_id'] = job_id
                self.cores[idx]['pid'] = pid

            print(
                Fore.CYAN +
                f"Allocated specific cores {core_indices} to job {job_id} (PID: {pid})" +
                Style.RESET_ALL
            )

            return core_indices

    def release_cores(self, job_id: int) -> List[int]:
        """Release cores allocated to a job

        :param job_id: Job ID to release cores for
        :return: List of released core indices
        """
        with self.lock:
            released_indices = []
            for core in self.cores:
                if core['job_id'] == job_id:
                    released_indices.append(core['index'])
                    core['job_id'] = None
                    core['pid'] = None

            if released_indices:
                print(
                    Fore.LIGHTMAGENTA_EX +
                    f"Released cores {released_indices[0]}-{released_indices[-1]} from job {job_id}" +
                    Style.RESET_ALL
                )

            return released_indices

    def get_available_cores_count(self) -> int:
        """Get number of currently available cores"""
        with self.lock:
            return sum(1 for core in self.cores if core['job_id'] is None)

    def get_core_allocation_status(self) -> Dict:
        """Get current core allocation status

        :return: Dictionary with allocation information
        """
        with self.lock:
            return {
                'physical_cores': self.physical_cores,
                'logical_cores': self.logical_cores,
                'hyper_threading_enabled': self.hyper_threading_enabled,
                'available_cores': self.get_available_cores_count(),
                'cores': [dict(core) for core in self.cores]  # Return copy
            }


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
    :return: [used, max] as integers, or [-2, 0] on error
    """

    exe = resource_path(r"dyna-tools/lstc_qrun.exe")
    command = [exe, "-r"]

    if server:
        command.extend(["-s", server])

    try:
        process = subprocess.run(
            command, capture_output=True, check=False, timeout=2
        )
        stdout_as_str = process.stdout.decode("utf-8")
        stdout_split = stdout_as_str.split()

        # Validate output has expected format (at least 5 tokens)
        if len(stdout_split) < 5:
            print(
                f"ERROR: Unexpected lstc_qrun output format (got {len(stdout_split)} tokens) for server '{server or 'default'}'")
            return [-2, 0]

        # Parse: output format has max at position -3 and used at -5
        max_ = int(stdout_split[-3])
        used = int(stdout_split[-5])

        return [used, max_]

    except (subprocess.TimeoutExpired, OSError) as e:
        print(
            f"ERROR: Failed to execute lstc_qrun for server '{server or 'default'}': {e}")
        return [-2, 0]
    except (ValueError, IndexError) as e:
        print(
            f"ERROR: Failed to parse lstc_qrun output for server '{server or 'default'}': {e}")
        return [-2, 0]
    except UnicodeDecodeError as e:
        print(
            f"ERROR: Failed to decode lstc_qrun output for server '{server or 'default'}': {e}")
        return [-2, 0]


def get_qrun_jobs(server="") -> List[Dict]:
    """Return LsDyna license server running jobs informations using lstc_qrun.exe

    :param server: Name or IP of the lic server. If "", LSTC_LICENSE_SERVER
                   env variable is used
    :return: List of job dictionaries, or [] on error
    """

    exe = resource_path(r"dyna-tools/lstc_qrun")
    command = [exe]

    if server:
        command.extend(["-s", server])

    try:
        process = subprocess.run(
            command, capture_output=True, check=False, timeout=2
        )
        stdout_as_str = process.stdout.decode("utf-8")

        out_list = []
        read = False

        for line in stdout_as_str.splitlines():
            if "----------------" in line:
                read = True
                continue

            tokens = line.split()
            if len(tokens) < 5:
                read = False
                continue

            if read:
                try:
                    # Validate we have enough tokens (need at least 9: user, host, program, 4 date/time, procs, jobs)
                    if len(tokens) >= 9:
                        out_list.append(
                            {
                                "user": tokens[0],
                                "host": tokens[1],
                                "program": tokens[2],
                                "started": " ".join([tokens[3], tokens[4], tokens[5], tokens[6]]),
                                "procs": tokens[7],
                                "josbs": tokens[8]
                            }
                        )
                    else:
                        print(
                            f"Warning: Skipping line with insufficient tokens ({len(tokens)}): {line.strip()}")
                except (IndexError, ValueError) as e:
                    print(
                        f"Warning: Failed to parse qrun job line: {line.strip()} - {e}")
                    continue

        return out_list

    except (subprocess.TimeoutExpired, OSError) as e:
        print(
            f"ERROR: Failed to execute lstc_qrun for server '{server or 'default'}': {e}")
        return []
    except UnicodeDecodeError as e:
        print(
            f"ERROR: Failed to decode lstc_qrun output for server '{server or 'default'}': {e}")
        return []


def qkill_job(host, server="") -> [bool, str]:
    """Terminate a job on the LsDyna license server using lstc_qkill

    :param host: Host identifier for the job to kill
    :param server: Name or IP of the lic server. If "", LSTC_LICENSE_SERVER
                   env variable is used
    :return: Tuple of (success: bool, message: str)
    """

    exe = resource_path(r"dyna-tools/lstc_qkill")
    command = [exe, host]

    if server:
        command.extend(["-s", server])

    try:
        process = subprocess.run(
            command, capture_output=True, check=False, timeout=1
        )
        stdout_as_str = process.stdout.decode("utf-8")

        # Check for success
        if "Program queued for termination" in stdout_as_str:
            return True, stdout_as_str

        # Check for specific error conditions
        error_messages = [
            "procid@machine",
            "License server cannot find",
            "You are not authorized to terminate this job"
        ]

        for error in error_messages:
            if error in stdout_as_str:
                return False, stdout_as_str

        # Unknown response format
        return False, f"Unexpected lstc_qkill response: {stdout_as_str}"

    except (subprocess.TimeoutExpired, OSError) as e:
        error_msg = f"Failed to execute lstc_qkill for host '{host}' on server '{server or 'default'}': {e}"
        print(f"ERROR: {error_msg}")
        return False, error_msg
    except UnicodeDecodeError as e:
        error_msg = f"Failed to decode lstc_qkill output: {e}"
        print(f"ERROR: {error_msg}")
        return False, error_msg


class JobManager:
    """JobManager object managing jobs.
     /!\\ Needs to be initialized with set_context(app) method. /!\\

    :param SocketIO socketio: global socketio to communicate with the ws API.
    """

    def __init__(self, socketio: SocketIO) -> None:
        self.socketio = socketio
        self.jobs = {}
        self.app = None

        # Configuration options
        self.disable_intel_mpi_core_allocation = False

        # Initialize core allocator
        self.core_allocator = CoreAllocator()

        self.queue_manager = QueueManager(socketio, self)

    def configure(self, disable_intel_mpi_core_allocation: bool = False) -> None:
        """Configure JobManager options

        :param disable_intel_mpi_core_allocation: If True, disable Intel MPI core allocation and pinning
        """
        self.disable_intel_mpi_core_allocation = disable_intel_mpi_core_allocation

        if disable_intel_mpi_core_allocation:
            print(
                Fore.YELLOW +
                "Intel MPI core allocation disabled - jobs will not be pinned to specific cores" +
                Style.RESET_ALL
            )

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

        # Configure a watchdog thread to monitor dead processes
        watchdog = Thread(
            target=job_watchdog_task, name="job_watchdog_task", args=[self], daemon=True
        )
        watchdog.start()

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
            sender=j_json["sender"],
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

        # Note: Cores are now released when job status changes to terminal state (Finished/Error/Stopped)
        # not when removed from manager. The stop() method has a safety fallback if needed.

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

    def get_core_allocation_status(self) -> Dict:
        """Get current CPU core allocation status

        :return: Dictionary with core allocation information
        """
        return self.core_allocator.get_core_allocation_status()

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

        # CPU core allocation
        self.allocated_cores: Optional[List[int]] = None

        self.working_dir = Path(self.sq_job.input).parent.absolute()

        # If its the first start of job
        if not j_connect:
            # Allocate cores BEFORE starting the process so we can use them in mpiexec command
            # Use a temporary PID of 0 since we don't have the actual PID yet
            # Only allocate cores if Intel MPI core allocation is enabled
            if not self.job_manager.disable_intel_mpi_core_allocation:
                self.allocated_cores = self.job_manager.core_allocator.allocate_cores(
                    job_id=self.sq_job.id,
                    pid=0,  # Temporary, will be updated after process starts
                    num_cores=self.sq_job.ncpu
                )

            # Build the command with allocated cores (if core allocation is enabled)
            command = self.sq_job.command
            if (self.allocated_cores and
                not self.job_manager.disable_intel_mpi_core_allocation and
                    "mpiexec" in command):
                command = command.replace(
                    "mpiexec",
                    f"mpiexec -genv I_MPI_PIN=1 -genv I_MPI_PIN_PROCESSOR_LIST={self.allocated_cores[0]}-{self.allocated_cores[-1]}"
                )

            process = subprocess.Popen(
                "cmd /c " + command + " > stdout 2>&1",
                cwd=self.working_dir,
                creationflags=subprocess.CREATE_BREAKAWAY_FROM_JOB
                | subprocess.CREATE_NO_WINDOW,
            )

            # Wait and find the actual LS-DYNA process PID (not cmd.exe or mpiexec)
            pid_to_write = process.pid
            dyna_process_found = False

            # Retry logic: wait up to 10 seconds for LS-DYNA process to start
            for attempt in range(20):  # 20 attempts x 0.5s = 10 seconds max
                sleep(0.5)
                try:
                    parent = psutil.Process(process.pid)
                    children = parent.children(recursive=True)

                    # Search for LS-DYNA process by name pattern
                    for p in children:
                        try:
                            proc_name = p.name().lower()
                            # Look for common LS-DYNA executable names
                            if any(name in proc_name for name in ['ls-dyna', 'lsdyna', 'dyna', 'mpp']):
                                pid_to_write = p.pid
                                dyna_process_found = True
                                print(
                                    Fore.GREEN +
                                    f"Found LS-DYNA process: {proc_name} (PID: {pid_to_write})" +
                                    Style.RESET_ALL
                                )
                                break
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            continue

                    if dyna_process_found:
                        break

                except psutil.NoSuchProcess:
                    print(
                        Fore.YELLOW +
                        f"Warning: Parent process died during startup (attempt {attempt+1}/20)" +
                        Style.RESET_ALL
                    )
                    break

            if not dyna_process_found:
                print(
                    Fore.RED +
                    f"ERROR: Could not find LS-DYNA process for job {self.sq_job.id}. " +
                    f"Using fallback PID: {pid_to_write}" +
                    Style.RESET_ALL
                )
                # Log all children for debugging
                try:
                    parent = psutil.Process(process.pid)
                    children = parent.children(recursive=True)
                    print(
                        f"Available child processes: {[(p.pid, p.name()) for p in children]}")
                except:
                    pass

            # Update the allocated cores with the actual PID (only if core allocation is enabled)
            if self.allocated_cores and not self.job_manager.disable_intel_mpi_core_allocation:
                with self.job_manager.core_allocator.lock:
                    for core in self.job_manager.core_allocator.cores:
                        if core['job_id'] == self.sq_job.id and core['pid'] == 0:
                            core['pid'] = pid_to_write

            # Write PID and allocated cores to file
            with open(
                os.path.join(self.working_dir, "pid"), "w", encoding="utf-8"
            ) as file:
                file.write(f"{pid_to_write}\n")
                if self.allocated_cores and not self.job_manager.disable_intel_mpi_core_allocation:
                    file.write(json.dumps(
                        {"cores": self.allocated_cores}) + "\n")

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

    def release_cores(self) -> None:
        """Release allocated cores when job ends"""
        if self.allocated_cores is not None:
            self.job_manager.core_allocator.release_cores(self.sq_job.id)
            self.allocated_cores = None
            # Clear from database as well
            with self.app.app_context():
                try:
                    query = SqlJob.query.filter_by(id=self.sq_job.id).one()
                    query.allocated_cores = None
                    db.session.commit()
                except:
                    pass

    def stop(self) -> None:
        """Stop the child watchdog Thread and try to delete itself from the parent JobManager"""

        self.watchdog.stop()
        try:
            self.watchdog.join()
        except:
            pass

        # Safety fallback: release cores if they haven't been released yet
        # (cores should normally be released when job ends, not when removed from manager)
        if self.allocated_cores is not None:
            print(
                Fore.YELLOW +
                f"Warning: Cores still allocated at stop() for job {self.sq_job.id}, releasing as fallback" +
                Style.RESET_ALL
            )
            self.release_cores()

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
                        old_status = self.status
                        self.status = j_json["status"]
                        query.status = j_json["status"]

                        # Release cores when job reaches a terminal state
                        terminal_states = ["Finished", "Error", "Stopped"]
                        if self.status in terminal_states and old_status not in terminal_states:
                            # Release cores outside of this context to avoid nested context issues
                            # We'll do it after commit
                            pass

                    if "started" in j_json:
                        query.started = j_json["started"]

                    if "allocated_cores" in j_json:
                        query.allocated_cores = j_json["allocated_cores"]

                try:
                    db.session.commit()

                    # Release cores after commit if status changed to terminal state
                    if "status" in j_json:
                        terminal_states = ["Finished",
                                           "Error", "Stopped", "sw1"]
                        if self.status in terminal_states and self.allocated_cores is not None:
                            # Check if cores were just released by this status change
                            # (avoid double-release if status updates multiple times)
                            self.release_cores()
                except Exception as e:
                    print(
                        Fore.RED +
                        f"ERROR: Failed to commit database for job {self.sq_job.id}: {e}" +
                        Style.RESET_ALL
                    )

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
                "allocated_cores": self.allocated_cores,
            },
            sort_keys=True,
            indent=4,
        )


class StdoutFileHandler(FileSystemEventHandler):
    """Handler pour surveiller les modifications du fichier stdout"""

    def __init__(self, watchdog_thread):
        self.watchdog_thread = watchdog_thread
        self.last_modified = time.time()

    def on_modified(self, event):
        if event.src_path.endswith('stdout') or 'stdout' in event.src_path:
            # Debounce: éviter les notifications multiples rapides
            now = time.time()
            if now - self.last_modified > 0.1:  # 100ms debounce
                self.last_modified = now
                self.watchdog_thread.trigger_read()


class StdoutWatchdogThread(Thread):
    """Watchdog to read stdout file content and communicate infos to parent Job object

    Uses watchdog library to monitor file changes instead of polling.

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
        self.read_event = Event()  # Event déclenché par watchdog

        # Initialiser le file watcher
        self.file_handler = StdoutFileHandler(self)
        self.observer = Observer()
        self.observer.schedule(self.file_handler, wd, recursive=False)

    def trigger_read(self):
        """Déclenché quand le fichier stdout est modifié"""
        self.read_event.set()

    def stop(self) -> None:
        """Stop the Thread loop and file observer"""
        self.running = False
        try:
            self.observer.stop()
            self.observer.join(timeout=2)
        except:
            pass
        self.exit.set()
        self.read_event.set()  # Débloquer si en attente

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

        # Read PID and potentially core allocation from pid file
        with open(os.path.join(self.working_dir, "pid"), "r", encoding="utf-8") as file:
            lines = file.readlines()

            # First line is always the PID
            pid_line = lines[0].strip()
            self.job.sq_job.pid = int(pid_line)

            # Only restore cores if this is a reconnection (j_connect=True)
            # For new jobs, cores are already allocated in __init__
            # Skip core allocation entirely if disabled
            if self.j_connect and not self.job.job_manager.disable_intel_mpi_core_allocation:
                # Try to restore cores from multiple sources (in order of priority)
                restored_cores = None

                # 1. Try from pid file (second line)
                if len(lines) > 1:
                    try:
                        cores_data = json.loads(lines[1].strip())
                        restored_cores = cores_data.get('cores', [])
                    except (json.JSONDecodeError, KeyError, ValueError):
                        pass

                # 2. Fallback to database if pid file doesn't have cores
                if not restored_cores and self.job.sq_job.allocated_cores:
                    try:
                        restored_cores = json.loads(
                            self.job.sq_job.allocated_cores)
                        print(
                            Fore.YELLOW +
                            f"Restoring cores from database for job {self.job.sq_job.id}" +
                            Style.RESET_ALL
                        )
                    except (json.JSONDecodeError, ValueError):
                        pass

                # Try to allocate the same cores that were previously allocated
                if restored_cores:
                    allocated = self.job.job_manager.core_allocator.allocate_specific_cores(
                        job_id=self.job.sq_job.id,
                        pid=self.job.sq_job.pid,
                        core_indices=restored_cores
                    )
                    if allocated:
                        self.job.allocated_cores = allocated
                        print(
                            Fore.GREEN +
                            f"Restored core allocation {allocated[0]}-{allocated[-1]} for job {self.job.sq_job.id}" +
                            Style.RESET_ALL
                        )
                    else:
                        # Fallback: allocate any available cores
                        self.job.allocated_cores = self.job.job_manager.core_allocator.allocate_cores(
                            job_id=self.job.sq_job.id,
                            pid=self.job.sq_job.pid,
                            num_cores=self.job.sq_job.ncpu
                        )
                else:
                    # No saved core data - allocate new cores
                    self.job.allocated_cores = self.job.job_manager.core_allocator.allocate_cores(
                        job_id=self.job.sq_job.id,
                        pid=self.job.sq_job.pid,
                        num_cores=self.job.sq_job.ncpu
                    )

            json_f = {"pid": int(pid_line), "status": "Starting"}
            if not self.j_connect:
                self.job.sq_job.started = int(time.time())
                json_f["started"] = int(time.time())
            self.job.update_db(json_f)

        # Write allocated cores back to pid file and database for future restarts
        # (For new jobs, this is redundant but ensures consistency)
        # Only write cores if core allocation is enabled
        if (self.job.allocated_cores is not None and
                not self.job.job_manager.disable_intel_mpi_core_allocation):
            with open(os.path.join(self.working_dir, "pid"), "w", encoding="utf-8") as file:
                file.write(f"{self.job.sq_job.pid}\n")
                file.write(json.dumps(
                    {"cores": self.job.allocated_cores}) + "\n")

            # Save to database as well
            self.job.update_db(
                {"allocated_cores": json.dumps(self.job.allocated_cores)})

        # ------------------------------------------------------------------------------
        #                          File reader loop with watchdog
        # ------------------------------------------------------------------------------

        # Démarrer l'observer après avoir récupéré le PID
        try:
            self.observer.start()
            print(
                Fore.CYAN +
                f"File watcher started for job {self.job.sq_job.id}" +
                Style.RESET_ALL
            )
        except Exception as e:
            print(
                Fore.YELLOW +
                f"Warning: Could not start file watcher for job {self.job.sq_job.id}: {e}" +
                Style.RESET_ALL
            )

        # Actual byte position of the reader
        pos = 0

        # current job time to increment and compare
        actual_time = 0

        while self.running:
            json_f = {}

            if not os.path.isfile(os.path.join(self.working_dir, "stdout")):
                time.sleep(1)
                continue

            pos, actual_time, to_add, json_f = self.readFile(pos, actual_time)

            # Mise à jour seulement si changements
            if to_add or json_f:
                self.job.update_db(json_f)
                self.job.update_shell(to_add)

            # Attendre notification du watchdog OU timeout de 5s (sécurité)
            # Si le fichier est modifié, read_event est déclenché immédiatement
            # Sinon, timeout après 5s pour vérifier quand même
            self.read_event.wait(timeout=5)
            self.read_event.clear()

            if not psutil.pid_exists(self.job.sq_job.pid):
                break

        # Lecture finale après sortie de boucle
        pos, actual_time, to_add, json_f = self.readFile(pos, actual_time)

        if to_add or json_f:
            self.job.update_db(json_f)
            self.job.update_shell(to_add)

        # self.job.stop()

    def readFile(self, pos, actual_time):
        """Read and parse stdout file content

        Optimized version that accumulates all changes and performs a single DB update.
        """
        with open(os.path.join(self.working_dir, "stdout"), "rb") as file:
            file.seek(pos)
            to_add = deque()

            # Accumulate ALL changes here - single DB transaction at the end
            updates = {}
            new_actual_time = actual_time

            while line_coded := file.readline():
                if line_coded == b"\x00":
                    pos = file.tell()
                    continue

                # Decode with fallback to UTF-16LE
                try:
                    line = line_coded.decode("utf-8").replace("\n", "")
                except (UnicodeDecodeError, ValueError):
                    line = line_coded.decode(
                        "utf-16le", errors="ignore").replace("\n", "")

                if len(line) > 0:
                    line += "\n"
                to_add.append(line)

                pos = file.tell()

                # === Status detection ===
                if "Livermore  Software  Technology  Corporation" in line:
                    if self.job.sq_job.status != "Running":
                        updates["status"] = "Running"

                # === Mass metrics ===
                if "added mass          =" in line and self.job.sq_job.a_mass is None:
                    try:
                        a_mass = float(line.split()[-1])
                        self.job.sq_job.a_mass = a_mass
                        updates["a_mass"] = a_mass
                    except (IndexError, ValueError) as e:
                        print(
                            f"Warning: Could not parse added mass from line: {line.strip()}")

                if "percentage increase =" in line and self.job.sq_job.pct_mass is None:
                    try:
                        pct_mass = float(line.split()[-1])
                        self.job.sq_job.pct_mass = pct_mass
                        updates["pct_mass"] = pct_mass
                    except (IndexError, ValueError):
                        print(
                            f"Warning: Could not parse pct_mass from line: {line.strip()}")

                # === Termination time ===
                if "termination time" in line and self.job.sq_job.end is None:
                    try:
                        e_time = float(line.split()[-1])
                        self.job.sq_job.end = e_time
                        updates["end"] = e_time
                    except (IndexError, ValueError):
                        pass

                # === Current time / Progress ===
                if "write d3plot file" in line or "flush i/o buffers" in line:
                    try:
                        c_time = float(line.split()[2])
                        if c_time > new_actual_time:
                            self.job.sq_job.current = c_time
                            updates["current"] = c_time
                            new_actual_time = c_time
                    except (IndexError, ValueError):
                        pass

                if "failed at time" in line:
                    try:
                        c_time = float(line.split()[-1])
                        if c_time > new_actual_time:
                            self.job.sq_job.current = c_time
                            updates["current"] = c_time
                            new_actual_time = c_time
                    except (IndexError, ValueError):
                        pass

                # === Error detection (factorized) ===
                error_patterns = ["error analysis", "E r r o r",
                                  "BAD TERMINATION", "Segmentation Violation"]
                if any(pattern in line for pattern in error_patterns):
                    updates["status"] = "Error"

                # === Normal termination ===
                if "N o r m a l" in line and self.job.status not in ["sw1"]:
                    if self.job.update_status:
                        updates["status"] = self.job.update_status
                    else:
                        updates["status"] = "Finished"
                        if self.job.sq_job.end:
                            updates["current"] = self.job.sq_job.end

        return pos, new_actual_time, to_add, updates


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
