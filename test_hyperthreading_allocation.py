"""
Test script to demonstrate hyper-threading aware core allocation
"""
from colorama import Fore, Style
from serv.job_manager import CoreAllocator
from unittest.mock import MagicMock
import sys
sys.path.insert(0, 'c:\\Users\\BOULEST\\Documents\\api-dynalauncher')

# We need to mock the dependencies
sys.modules['flask'] = MagicMock()
sys.modules['flask_socketio'] = MagicMock()
sys.modules['serv.models'] = MagicMock()


def test_hyperthreading_allocation():
    """Test core allocation with and without hyper-threading"""

    print("=" * 70)
    print("Hyper-Threading Aware Core Allocation Test")
    print("=" * 70)

    # Create allocator (will detect real system)
    allocator = CoreAllocator()

    print(f"\n{Fore.CYAN}System Configuration:{Style.RESET_ALL}")
    print(f"  Physical cores: {allocator.physical_cores}")
    print(f"  Logical cores: {allocator.logical_cores}")
    print(
        f"  Hyper-threading: {'Enabled' if allocator.hyper_threading_enabled else 'Disabled'}")

    # Test allocation with different ncpu values
    print(f"\n{Fore.CYAN}Testing Core Allocation:{Style.RESET_ALL}")
    print("-" * 70)

    test_cases = [
        (1, 4),   # Job 1: 4 cores requested
        (2, 2),   # Job 2: 2 cores requested
        (3, 8),   # Job 3: 8 cores requested
    ]

    for job_id, ncpu in test_cases:
        print(
            f"\n{Fore.YELLOW}Job {job_id}: Requesting {ncpu} cores{Style.RESET_ALL}")

        if allocator.hyper_threading_enabled:
            expected_allocation = ncpu * 2
            print(
                f"  Expected allocation (HT enabled): {expected_allocation} logical cores")
        else:
            expected_allocation = ncpu
            print(
                f"  Expected allocation (HT disabled): {expected_allocation} cores")

        allocated = allocator.allocate_cores(
            job_id=job_id,
            pid=10000 + job_id,
            num_cores=ncpu
        )

        if allocated:
            print(f"  ✓ Allocated: {len(allocated)} cores → {allocated}")
            if allocator.hyper_threading_enabled:
                print(
                    f"  → Covers {len(allocated) // 2} physical cores with both threads")
        else:
            print(f"  ✗ Allocation failed - not enough cores available")

    # Show allocation status
    print(f"\n{Fore.CYAN}Current Allocation Status:{Style.RESET_ALL}")
    print("-" * 70)
    status = allocator.get_core_allocation_status()
    print(f"  Total logical cores: {status['logical_cores']}")
    print(f"  Available cores: {status['available_cores']}")
    print(
        f"  Allocated cores: {status['logical_cores'] - status['available_cores']}")

    # Show which cores are allocated to which job
    print(f"\n{Fore.CYAN}Detailed Core Mapping:{Style.RESET_ALL}")
    allocated_by_job = {}
    for core in status['cores']:
        if core['job_id'] is not None:
            if core['job_id'] not in allocated_by_job:
                allocated_by_job[core['job_id']] = []
            allocated_by_job[core['job_id']].append(core['index'])

    for job_id, cores in sorted(allocated_by_job.items()):
        print(f"  Job {job_id}: {len(cores)} cores → {cores}")
        if allocator.hyper_threading_enabled:
            print(f"           ({len(cores) // 2} physical cores)")

    # Cleanup - release all cores
    print(f"\n{Fore.CYAN}Cleanup:{Style.RESET_ALL}")
    for job_id in allocated_by_job.keys():
        released = allocator.release_cores(job_id)
        print(f"  Released {len(released)} cores from Job {job_id}")

    print("\n" + "=" * 70)
    print(f"{Fore.GREEN}Key Benefits of HT-Aware Allocation:{Style.RESET_ALL}")
    print("  ✓ Jobs get full physical cores (both HT threads)")
    print("  ✓ Better performance - no thread contention")
    print("  ✓ More accurate core accounting")
    print("  ✓ Prevents over-subscription of physical cores")
    print("=" * 70)


if __name__ == "__main__":
    test_hyperthreading_allocation()
