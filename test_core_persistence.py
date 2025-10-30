"""
Test script to demonstrate core allocation persistence in pid file
"""
import json
import os
import tempfile


def test_pid_file_format():
    """Demonstrate the pid file format with core allocation"""

    print("=" * 60)
    print("Core Allocation Persistence Test")
    print("=" * 60)

    # Create a temporary directory to simulate job working directory
    with tempfile.TemporaryDirectory() as temp_dir:
        pid_file = os.path.join(temp_dir, "pid")

        # Simulate writing pid file with core allocation
        print("\n1. Initial job start - writing PID and cores to file:")
        job_pid = 12345
        allocated_cores = [0, 1, 2, 3]

        with open(pid_file, "w", encoding="utf-8") as f:
            f.write(f"{job_pid}\n")
            f.write(json.dumps({"cores": allocated_cores}) + "\n")

        print(f"   PID: {job_pid}")
        print(f"   Allocated cores: {allocated_cores}")

        # Show file content
        print("\n2. Content of pid file:")
        with open(pid_file, "r", encoding="utf-8") as f:
            content = f.read()
            print("   ---")
            for line in content.splitlines():
                print(f"   {line}")
            print("   ---")

        # Simulate reading pid file after restart
        print("\n3. After restart - reading from pid file:")
        with open(pid_file, "r", encoding="utf-8") as f:
            lines = f.readlines()

            # First line is PID
            restored_pid = int(lines[0].strip())
            print(f"   Restored PID: {restored_pid}")

            # Second line is core allocation
            if len(lines) > 1:
                cores_data = json.loads(lines[1].strip())
                restored_cores = cores_data.get('cores', [])
                print(f"   Restored cores: {restored_cores}")

                # Verify
                if restored_pid == job_pid and restored_cores == allocated_cores:
                    print("\n✓ Successfully restored PID and core allocation!")
                else:
                    print("\n✗ Restoration failed!")
            else:
                print("   No core allocation data found")

    print("\n" + "=" * 60)
    print("Benefits of persistence:")
    print("  - Same cores re-assigned after server restart")
    print("  - Maintains core affinity for running jobs")
    print("  - Prevents core allocation changes during restart")
    print("=" * 60)


if __name__ == "__main__":
    test_pid_file_format()
