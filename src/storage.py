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
    
    # Find and modify the line matching the label
    modified_data = []
    for line in data:
        stripped_line = line.strip()
        if stripped_line == label:
            # Add [S] prefix with | delimiter
            # Keep existing prefixes like [<] for subprocesses
            if line.startswith("[S]"):
                # Already has [S], keep as is
                modified_data.append(line)
            else:
                # Add [S] prefix
                modified_data.append(f"[S]|{line}")
        else:
            modified_data.append(line)
    
    # Write back to file
    with open(data_dir / file_name, 'w') as f:
        f.writelines(modified_data)
     



