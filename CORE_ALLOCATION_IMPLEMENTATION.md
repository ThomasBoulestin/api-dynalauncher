# CPU Core Allocation Feature - Implementation Summary

## Overview

Added CPU core allocation functionality to the JobManager to track and manage CPU core assignments for LS-DYNA jobs. **Core allocations are now persisted to the pid file and restored after server restarts.**

## Changes Made

### 1. New Class: `CoreAllocator`

Located in `job_manager.py`, this class manages CPU core allocation:

**Features:**

- Detects physical cores, logical cores, and hyper-threading status at startup
- Maintains a list of all CPU cores with their allocation status
- Thread-safe allocation/deallocation using locks
- Tracks which job and PID is using each core
- **NEW: Supports allocating specific cores (for restore after restart)**

**Key Methods:**

- `__init__()`: Detects CPU information and initializes core tracking
- `allocate_cores(job_id, pid, num_cores)`: Allocates cores to a job
- `allocate_specific_cores(job_id, pid, core_indices)`: **NEW** - Allocates specific cores (used for restoration)
- `release_cores(job_id)`: Releases all cores from a job
- `get_available_cores_count()`: Returns number of free cores
- `get_core_allocation_status()`: Returns complete allocation status

### 2. JobManager Updates

**`__init__` method:**

- Added `self.core_allocator = CoreAllocator()` to initialize core tracking

**`remove_from_manager` method:**

- Added `self.core_allocator.release_cores(job_id)` to release cores when job is removed

**New method:**

- `get_core_allocation_status()`: Public API to get core allocation info

### 3. Job Class Updates

**`__init__` method:**

- Added `self.allocated_cores: Optional[List[int]] = None` property to store allocated core indices

**`stop` method:**

- Added core release logic when job stops:

```python
if self.allocated_cores is not None:
    self.job_manager.core_allocator.release_cores(self.sq_job.id)
    self.allocated_cores = None
```

**`to_json` method:**

- Added `allocated_cores` to JSON output

### 4. StdoutWatchdogThread Updates

**`run` method:**

- After PID is detected from file, cores are allocated
- **NEW: If reconnecting (`j_connect=True`), attempts to restore previously allocated cores from pid file**
- **NEW: Writes allocated cores back to pid file for future restarts**

Allocation logic:

```python
# Read PID and core allocation from pid file
with open(pid_file, "r") as f:
    lines = f.readlines()
    pid = int(lines[0].strip())

    # If reconnecting and core data exists, try to restore same cores
    if len(lines) > 1 and self.j_connect:
        cores_data = json.loads(lines[1].strip())
        requested_cores = cores_data.get('cores', [])
        # Attempt to allocate the same cores
        allocated = allocate_specific_cores(job_id, pid, requested_cores)
    else:
        # New job - allocate any available cores
        allocated = allocate_cores(job_id, pid, num_cores)

# Write allocation back to pid file
with open(pid_file, "w") as f:
    f.write(f"{pid}\n")
    f.write(json.dumps({"cores": allocated}) + "\n")
```

### 5. PID File Format

**NEW: Enhanced pid file format to store core allocation**

The pid file now contains two lines:

```
<PID>
{"cores": [<list of allocated core indices>]}
```

Example:

```
12345
{"cores": [0, 1, 2, 3]}
```

This allows the system to restore the exact same core allocation when reconnecting to jobs after a server restart.

### 6. Database Storage

**NEW: Core allocation is also persisted to the database**

Added `allocated_cores` field to the `SqlJob` model:

- Type: `VARCHAR(500)` - stores JSON array of core indices
- Example: `"[0, 1, 2, 3]"`
- Updated automatically when cores are allocated or released
- Used as fallback if pid file doesn't contain core data
- Cleared (set to `NULL`) when job stops

The `ensure_schema()` function automatically adds this column to existing databases.

**Restoration Priority:**

1. **First**: Try to restore from pid file (second line)
2. **Fallback**: If pid file missing cores, restore from database
3. **Last resort**: Allocate new cores if both sources fail

### 7. Import Updates

- Added `Optional` to typing imports
- Added `Lock` to threading imports

## Usage

### At Startup

The JobManager automatically:

1. Detects CPU configuration (physical/logical cores, HT status)
2. Prints CPU information to console
3. Initializes core tracking list

### When Job Starts (New Job)

1. Job process is spawned
2. PID is written to pid file (first line only)
3. Watchdog thread starts and reads PID
4. Cores are allocated based on `ncpu` parameter
5. **Allocated cores are written to pid file (second line as JSON)**
6. Allocation is stored in `job.allocated_cores`

### When Server Restarts (Reconnecting to Running Job)

1. JobManager detects running job by checking if PID exists
2. Creates Job object with `j_connect=True`
3. Watchdog reads pid file:
   - First line: PID
   - **Second line: Previously allocated cores (JSON)**
4. **Attempts to allocate the same cores using `allocate_specific_cores()`**
5. If those cores are available: restores exact allocation ✓
6. If those cores are occupied: allocates different available cores
7. **Updates pid file with final allocation**

### When Job Ends

1. Job stop() is called
2. Cores are released back to available pool
3. Core tracking is updated

### Monitoring

Access allocation status via:

```python
status = job_manager.get_core_allocation_status()
# Returns:
# {
#     'physical_cores': 24,
#     'logical_cores': 32,
#     'hyper_threading_enabled': True,
#     'available_cores': 28,
#     'cores': [
#         {'index': 0, 'job_id': 1, 'pid': 1234},
#         {'index': 1, 'job_id': 1, 'pid': 1234},
#         {'index': 2, 'job_id': None, 'pid': None},
#         ...
#     ]
# }
```

## Thread Safety

All core allocation operations are protected by a `threading.Lock` to ensure thread-safe access in the multi-threaded environment.

## Error Handling

- If not enough cores are available, allocation returns `None` and prints a warning
- Job can still run, but won't have core affinity set
- Cores are automatically released when job stops for any reason
- **NEW: If specific cores cannot be restored after restart, system allocates different cores**
- **NEW: Invalid JSON in pid file falls back to normal allocation**

## Console Output

The system prints color-coded messages:

- Green: CPU information at startup, successful core restoration
- Cyan: Core allocation/release operations
- Yellow: Warnings when cores unavailable or restoration fails

## Testing

Three test files created:

- `test_core_allocation.py`: Full integration test (requires all dependencies)
- `test_core_simple.py`: Simple standalone CPU detection test
- `test_core_persistence.py`: **NEW** - Demonstrates pid file format and restoration logic

Your system shows:

- Physical cores: 24
- Logical cores: 32
- Hyper-threading: Enabled

## Benefits of Persistence

✓ **Same cores re-assigned after server restart** - Jobs maintain their core allocation  
✓ **Maintains core affinity** - Running jobs keep the same CPU cores  
✓ **Prevents allocation changes** - No shuffling of cores during restart  
✓ **Graceful degradation** - Falls back to new allocation if cores unavailable
