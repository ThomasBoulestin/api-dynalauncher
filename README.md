![DynaLauncher](https://github.com/ThomasBoulestin/api-dynalauncher/blob/main/images/asciiArt.png?raw=true)

# API - DynaLauncher

**API - DynaLauncher** is the server component of DynaLauncher. \
It's not meant to be used on its own.
Rather, it's an interface to lauch / control LsDyna jobs.

The prefered interface to this API is [front - dynalauncher](https://github.com/ThomasBoulestin/front-dynalauncher "front - dynalauncher")

The api is a WebSocket API running by default on port 5558, you must ensure that your firewall allow connections to this port if you plan to access the api from another machine.

For the moment, it works on windows but its not hard to make it run also on Linux (more details at the end)

## Installation

### <u>Option 1:</u> Using released versions

Download **_.exe_** file from releases and execute it.

### <u>Option 2:</u> Run from sources files

Just run **_server.py_** file

### <u>Option 3:</u> Build from sources

There is a **_bundle.bat_** file including a command to package the app with specific parameters.

## API References

The api uses JsonRPC 2.0 specification, more infos here: [JsonRPC 2.0](https://www.jsonrpc.org/specification "JsonRPC 2.0")

Every interractions to the JobManager within the API are defined in **_websocket_api.py_**

## Structure

The API works as following

1. A JobManager manage jobs
2. Within the JobManager, there is a queue manager managing queued jobs.
3. The JobManager is capable of starting, stoping jobs

A Job is started like this:

1. A command is run to start the job and redirect the stdout to a file.
2. A Thread is started to check stdout file periodicly and report any changes to the Job and database.

Background running Threads:

1. Every 30s the queue manager check if he can start the first job in his job list.
2. Every 3 second, a watchdog health-check each jobs in job manager and mark them as stopped if there is a problem.

## TODO: Linux compatibility

As far as I know, the only change needed to make it running on Linux is the part where the Job is started and the stdout redirected.

```python
process = subprocess.Popen(
    "cmd /c " + self.sq_job.command + "> stdout 2>&1",
    cwd=self.working_dir,
    creationflags=subprocess.CREATE_BREAKAWAY_FROM_JOB
    | subprocess.CREATE_NO_WINDOW,
)
```

## Contributing

Pull requests are welcome. For major changes, please open an issue first
to discuss what you would like to change.

## License

[MIT](https://choosealicense.com/licenses/mit/)
