from asyncio.windows_events import NULL
from pathlib import Path
from tkinter.tix import Select
from datetime import datetime

working_dir = Path.cwd()
data_dir = working_dir / 'data'

prcss_files = []
file_names = []

def save_root(new_root, file_name):
    with open(data_dir / "root.txt", 'w') as f:
        f.writelines(new_root)
        f.writelines("\n" + file_name)

def read_root_and_file():
    with open(data_dir / "root.txt", 'r') as f:
        c_and_f = f.readlines()
    return c_and_f

def has_child(list,item):
    index = list.index(item)
    try:
        if "[>]" in list[index + 1] and "[>]" not in list[index]:
            return True
        else:
            return False
    except IndexError:
        return False
 
def file_parser_selected(new_path):
    file_names = []
    files = list(new_path.glob("*.prcss"))    

    for x in files:
        file_names.append(x.name)

    return file_names

def file_parser():
    files = list(data_dir.glob("*.prcss"))    

    for x in files:
        file_names.append(x.name)

    return file_names
        
def file_reader(path,file_name):
        with open(path / file_name, 'r') as f:
            data = f.readlines()
        return data

def number_of_files(files):
    count = 0
    for x in files:
        count = count + 1
    return count

def strip_date_tag(s: str) -> str:
    """Remove |[d=...] completion timestamp from a line string."""
    idx = s.find('|[d=')
    if idx != -1:
        return s[:idx]
    return s

#Appends the [S] status prefix to the specified line in the .prcss file
def set_S(label, path, file_name):
    with open(path / file_name, 'r') as f:
        data = f.readlines()
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Find and modify the line matching the label
    modified_data = []
    for line in data:
        stripped_line = line.strip()
        stripped_no_date = strip_date_tag(stripped_line)
        if "[>]" in stripped_line:
            stripped_no_child = stripped_no_date.replace("[>]|","")
            if stripped_no_child == label:
                if "[S]" in line:
                    modified_data.append(line)
                else:
                    modified_data.append(f"[S]|{line.rstrip()}|[d={timestamp}]\n")
            else:
                modified_data.append(line)

        elif stripped_no_date == label:
            # Add [S] prefix with | delimiter
            if line.startswith("[S]"):
                # Already has [S], keep as is
                modified_data.append(line)
            else:
                # Add [S] prefix and completion timestamp
                modified_data.append(f"[S]|{line.rstrip()}|[d={timestamp}]\n")
        else:
            modified_data.append(line)
    
    # Write back to file
    with open(path / file_name, 'w') as f:
        f.writelines(modified_data)

#Returns True if label contains [S] status prefix     
def has_S(label, file_name):
    with open(data_dir / file_name, 'r') as f:
        data = f.readlines()
    for line in data:
        stripped_line = line.strip()
        if "[S]" in stripped_line:
            return True
    return False

def remove_S(label, path, file_name):
    with open(path / file_name, 'r') as f:
        data = f.readlines()
    
    # Find and modify the line matching the label
    modified_data = []
    for line in data:
        stripped_line = line.strip()
        stripped_no_date = strip_date_tag(stripped_line)
        if "[>]" in stripped_line:
            stripped_no_child = stripped_no_date.replace("[>]|","")
            if stripped_no_child == label:
                if "[S]" in line:
                    clean = strip_date_tag(line.replace("[S]|","").rstrip()) + "\n"
                    modified_data.append(clean)
                else:
                    modified_data.append(line)
            else:
                modified_data.append(line)

        elif stripped_no_date == label:
            if "[S]" in stripped_no_date:
                clean = strip_date_tag(line.replace("[S]|","").rstrip()) + "\n"
                modified_data.append(clean)
            else:
                modified_data.append(line)
        else:
            modified_data.append(line)
    
    # Write back to file
    with open(path / file_name, 'w') as f:
        f.writelines(modified_data)