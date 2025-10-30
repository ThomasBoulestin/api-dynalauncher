"""
Simple standalone test for CPU core detection
"""
import psutil
from colorama import Fore, Style


def test_cpu_info():
    """Test CPU information detection"""

    print("=" * 60)
    print("CPU Core Detection Test")
    print("=" * 60)

    physical_cores = psutil.cpu_count(logical=False)
    logical_cores = psutil.cpu_count(logical=True)
    hyper_threading = logical_cores > physical_cores

    print(f"\n{Fore.GREEN}CPU Information:{Style.RESET_ALL}")
    print(f"  Physical cores: {physical_cores}")
    print(f"  Logical cores: {logical_cores}")
    print(f"  Hyper-threading: {'Enabled' if hyper_threading else 'Disabled'}")

    # Simulate core allocation
    cores = [
        {'index': i, 'job_id': None, 'pid': None}
        for i in range(logical_cores)
    ]

    print(f"\n{Fore.CYAN}Simulating core allocation:{Style.RESET_ALL}")

    # Allocate 4 cores to job 1
    num_to_allocate = min(4, logical_cores)
    for i in range(num_to_allocate):
        cores[i]['job_id'] = 1
        cores[i]['pid'] = 1234
    print(f"  Allocated cores 0-{num_to_allocate-1} to Job 1")

    available = sum(1 for c in cores if c['job_id'] is None)
    print(f"  Available cores: {available}/{logical_cores}")

    # Show allocation
    print(f"\n{Fore.CYAN}Current allocation:{Style.RESET_ALL}")
    for core in cores[:8]:  # Show first 8 cores
        status = f"Job {core['job_id']}" if core['job_id'] else "Free"
        print(f"  Core {core['index']}: {status}")
    if logical_cores > 8:
        print(f"  ... and {logical_cores - 8} more cores")

    print("\n" + "=" * 60)
    print("Test completed!")
    print("=" * 60)


if __name__ == "__main__":
    test_cpu_info()
