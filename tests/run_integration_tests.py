import os
import sys
from integration.test_metadata_consistency import run_tests


def main():
    print("Starting integration tests...")
    return run_tests()


if __name__ == "__main__":
    sys.exit(main())
