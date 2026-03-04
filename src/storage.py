from pathlib import Path

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
        data = f.read()
    return data

