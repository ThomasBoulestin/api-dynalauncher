"""
Test script for CPU core allocation functionality
"""
from serv.job_manager import CoreAllocator
import sys
sys.path.insert(0, 'c:\\Users\\BOULEST\\Documents\\api-dynalauncher')


def test_core_allocator():
    """Test the CoreAllocator class"""

    print("=" * 60)
    print("Testing CoreAllocator")
    print("=" * 60)

    # Create allocator
    allocator = CoreAllocator()

    # Get initial status
    status = allocator.get_core_allocation_status()
    print(f"\nInitial status:")
    print(f"  Physical cores: {status['physical_cores']}")
    print(f"  Logical cores: {status['logical_cores']}")
    print(f"  Hyper-threading: {status['hyper_threading_enabled']}")
    print(f"  Available cores: {status['available_cores']}")

    # Test allocation
    print("\n" + "-" * 60)
    print("Test 1: Allocate 4 cores to job 1")
    cores1 = allocator.allocate_cores(job_id=1, pid=1234, num_cores=4)
    print(f"Allocated cores: {cores1}")
    print(f"Available cores: {allocator.get_available_cores_count()}")

    # Test allocation 2
    print("\n" + "-" * 60)
    print("Test 2: Allocate 2 cores to job 2")
    cores2 = allocator.allocate_cores(job_id=2, pid=5678, num_cores=2)
    print(f"Allocated cores: {cores2}")
    print(f"Available cores: {allocator.get_available_cores_count()}")

    # Show detailed status
    print("\n" + "-" * 60)
    print("Current allocation status:")
    status = allocator.get_core_allocation_status()
    for core in status['cores']:
        if core['job_id'] is not None:
            print(
                f"  Core {core['index']}: Job {core['job_id']} (PID: {core['pid']})")

    # Test release
    print("\n" + "-" * 60)
    print("Test 3: Release cores from job 1")
    released = allocator.release_cores(job_id=1)
    print(f"Released cores: {released}")
    print(f"Available cores: {allocator.get_available_cores_count()}")

    # Test over-allocation
    print("\n" + "-" * 60)
    print(f"Test 4: Try to allocate more cores than available")
    print(
        f"Available: {allocator.get_available_cores_count()}, Requesting: {allocator.get_available_cores_count() + 1}")
    cores_fail = allocator.allocate_cores(
        job_id=3, pid=9999, num_cores=allocator.get_available_cores_count() + 1)
    print(f"Result: {cores_fail}")

    # Final status
    print("\n" + "-" * 60)
    print("Final allocation status:")
    status = allocator.get_core_allocation_status()
    print(f"  Available cores: {status['available_cores']}")
    allocated_cores = [core for core in status['cores']
                       if core['job_id'] is not None]
    if allocated_cores:
        for core in allocated_cores:
            print(
                f"  Core {core['index']}: Job {core['job_id']} (PID: {core['pid']})")
    else:
        print("  No cores currently allocated")

    print("\n" + "=" * 60)
    print("Tests completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    test_core_allocator()
