"""search product seed — multi-checkpoint growth."""
import argparse
from pathlib import Path

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--pattern", required=True)
    args = ap.parse_args()
    print("not implemented")

if __name__ == "__main__":
    main()
