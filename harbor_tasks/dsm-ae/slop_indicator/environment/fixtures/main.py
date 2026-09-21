"""search CLI seed — agent extends this."""
import argparse
from pathlib import Path

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--pattern", required=True)
    args = ap.parse_args()
    # TODO: implement search
    print("not implemented")

if __name__ == "__main__":
    main()
