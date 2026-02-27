from pathlib import Path
project_root = Path.cwd()
file_path = project_root / "data" / "test_proc.txt"

# print(file_path)
def file_parser():
    # with open(file_path) as f:
    #     print(f.readlines())
    print(file_path)