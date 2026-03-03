from pathlib import Path

working_dir = Path.cwd()
data_dir = working_dir / 'veritrakk' / 'data'

files = []

def file_parser():
    for x in data_dir.iterdir(): 
        files.append(x.name)

    print(files)
        
