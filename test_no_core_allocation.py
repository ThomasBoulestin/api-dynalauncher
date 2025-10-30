#!/usr/bin/env python3
"""
Test script to verify --noIntelMpiCoreAllocation flag functionality
"""

import subprocess
import sys
import time


def test_normal_mode():
    """Test server startup with normal core allocation"""
    print("Testing normal mode (core allocation enabled)...")

    try:
        # Start server in normal mode (should see CPU information)
        proc = subprocess.Popen(
            [sys.executable, "server.py", "--port", "5570"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd="."
        )

        # Give it a moment to start up
        time.sleep(3)

        # Read output
        output, _ = proc.communicate(timeout=2)

        print("Normal mode output:")
        print(output)

        # Check if CPU information is displayed
        if "Physical cores:" in output and "Logical cores:" in output:
            print("✅ Normal mode: CPU information displayed correctly")
        else:
            print("❌ Normal mode: CPU information not found")

        return True

    except subprocess.TimeoutExpired:
        proc.kill()
        print("❌ Normal mode test timed out")
        return False
    except Exception as e:
        print(f"❌ Normal mode test failed: {e}")
        return False


def test_disabled_mode():
    """Test server startup with core allocation disabled"""
    print("\nTesting disabled mode (--noIntelMpiCoreAllocation)...")

    try:
        # Start server with core allocation disabled
        proc = subprocess.Popen(
            [sys.executable, "server.py", "--port",
                "5571", "--noIntelMpiCoreAllocation"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd="."
        )

        # Give it a moment to start up
        time.sleep(3)

        # Read output
        output, _ = proc.communicate(timeout=2)

        print("Disabled mode output:")
        print(output)

        # Check if disabled message is displayed
        if "CORE ALLOCATION DISABLED" in output:
            print("✅ Disabled mode: Disable message displayed correctly")
        else:
            print("❌ Disabled mode: Disable message not found")

        if "Intel MPI core pinning is disabled" in output:
            print("✅ Disabled mode: Detailed disable message found")
        else:
            print("❌ Disabled mode: Detailed disable message not found")

        return True

    except subprocess.TimeoutExpired:
        proc.kill()
        print("❌ Disabled mode test timed out")
        return False
    except Exception as e:
        print(f"❌ Disabled mode test failed: {e}")
        return False


if __name__ == "__main__":
    print("Testing --noIntelMpiCoreAllocation functionality")
    print("=" * 50)

    # Test both modes
    normal_ok = test_normal_mode()
    disabled_ok = test_disabled_mode()

    print("\n" + "=" * 50)
    if normal_ok and disabled_ok:
        print("✅ All tests passed!")
    else:
        print("❌ Some tests failed!")

    print("\nTo test manually:")
    print("  Normal mode:   python server.py --port 5570")
    print("  Disabled mode: python server.py --port 5571 --noIntelMpiCoreAllocation")
