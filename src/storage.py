from pathlib import Path

working_dir = Path.cwd()
data_dir = working_dir / 'veritrakk' / 'data'

files = []

def file_parser():
    for x in data_dir.iterdir(): 
        files.append(x.name)

    print(files)
        

# print(file_path)
# def file_parser():
#     with open("/c/Users/17195/Desktop/Westbound Designs/veritrakk/data/test_proc.txt") as f:
#         print(f.readlines())
