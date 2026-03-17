from asyncio.windows_events import NULL
from pathlib import Path
from tkinter.tix import Select

working_dir = Path.cwd()
data_dir = working_dir / 'data'

prcss_files = []
file_names = []

def file_parser():
    files = list(data_dir.glob("*.prcss"))    

    for x in files:
        file_names.append(x.name)

    return file_names
        
def file_reader(file_name):
        with open(data_dir / file_name, 'r') as f:
            data = f.readlines()
        return data

def number_of_files(files):
    count = 0
    for x in files:
        count = count + 1
    return count

def save_success(label, file_name):
    with open(data_dir / file_name, 'r') as f:
        data = f.readlines()
    for x in data:
        print(x)
        if x == label:
            data.append("[S]")
            print(data)
     



