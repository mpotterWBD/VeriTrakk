from asyncio.windows_events import NULL
from pathlib import Path
from tkinter.tix import Select
from datetime import datetime
import re

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
    return re.sub(r'\|\[d=[^\]]*\]', '', s)

def strip_note_tag(s: str) -> str:
    """Remove |[n=...] note from a line string."""
    idx = s.find('|[n=')
    if idx != -1:
        return s[:idx]
    return s

def get_note_from_line(s: str) -> str:
    """Extract note content from a raw line string."""
    idx = s.find('|[n=')
    if idx != -1:
        after = s[idx + 4:]
        end = after.rfind(']')
        if end != -1:
            return after[:end]
    return ""

def get_note_for_label(label: str, path, file_name: str) -> str:
    """Return the saved note for the given label, or '' if none."""
    try:
        with open(path / file_name, 'r') as f:
            data = f.readlines()
    except OSError:
        return ""
    for line in data:
        stripped = line.strip()
        stripped_no_date = strip_date_tag(stripped)
        stripped_no_note = strip_note_tag(stripped_no_date)
        if "[>]" in stripped_no_note:
            clean = stripped_no_note.replace("[S]|", "").replace("[>]|", "").strip()
        else:
            clean = stripped_no_note.replace("[S]|", "").strip()
        if clean == label:
            return get_note_from_line(stripped)
    return ""

def read_all_notes(path, file_name) -> dict:
    """Return a dict mapping clean label -> note for all lines in the file that have notes."""
    notes = {}
    try:
        with open(path / file_name, 'r') as f:
            data = f.readlines()
    except OSError:
        return notes
    for line in data:
        stripped = line.strip()
        note = get_note_from_line(stripped)
        if not note:
            continue
        stripped_no_date = strip_date_tag(stripped)
        stripped_no_note = strip_note_tag(stripped_no_date)
        if "[>]" in stripped_no_note:
            clean = stripped_no_note.replace("[S]|", "").replace("[>]|", "").strip()
        else:
            clean = stripped_no_note.replace("[S]|", "").strip()
        if clean:
            notes[clean] = note
    return notes

def set_note(label: str, note: str, path, file_name: str) -> None:
    """Set or clear the note for the given label in the .prcss file."""
    with open(path / file_name, 'r') as f:
        data = f.readlines()
    modified_data = []
    for line in data:
        stripped = line.strip()
        stripped_no_date = strip_date_tag(stripped)
        stripped_no_note = strip_note_tag(stripped_no_date)
        if "[>]" in stripped_no_note:
            clean = stripped_no_note.replace("[S]|", "").replace("[>]|", "").strip()
        else:
            clean = stripped_no_note.replace("[S]|", "").strip()
        if clean == label:
            line_no_note = strip_note_tag(line.rstrip())
            if note:
                modified_data.append(f"{line_no_note}|[n={note}]\n")
            else:
                modified_data.append(f"{line_no_note}\n")
        else:
            modified_data.append(line)
    with open(path / file_name, 'w') as f:
        f.writelines(modified_data)

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
        stripped_no_note = strip_note_tag(stripped_no_date)
        if "[>]" in stripped_line:
            stripped_no_child = stripped_no_note.replace("[>]|","")
            if stripped_no_child == label:
                if "[S]" in line:
                    modified_data.append(line)
                else:
                    modified_data.append(f"[S]|{line.rstrip()}|[d={timestamp}]\n")
            else:
                modified_data.append(line)

        elif stripped_no_note == label:
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
        stripped_no_note = strip_note_tag(stripped_no_date)
        if "[>]" in stripped_line:
            stripped_no_child = stripped_no_note.replace("[>]|","")
            if stripped_no_child == label:
                if "[S]" in line:
                    clean = strip_date_tag(line.replace("[S]|","").rstrip()) + "\n"
                    modified_data.append(clean)
                else:
                    modified_data.append(line)
            else:
                modified_data.append(line)

        elif stripped_no_note == label:
            if "[S]" in stripped_no_note:
                clean = strip_date_tag(line.replace("[S]|","").rstrip()) + "\n"
                modified_data.append(clean)
            else:
                modified_data.append(line)
        else:
            modified_data.append(line)
    
    # Write back to file
    with open(path / file_name, 'w') as f:
        f.writelines(modified_data)

# ---------------------------------------------------------------------------
# Threshold tag helpers
# ---------------------------------------------------------------------------

def get_threshold_from_line(s: str) -> tuple[str, str]:
    """Return (upper, lower) threshold strings from a raw line, or ('', '') if absent."""
    ut = ""
    lt = ""
    m = re.search(r'\[UT=([^\]]*)\]', s)
    if m:
        ut = m.group(1)
    m = re.search(r'\[LT=([^\]]*)\]', s)
    if m:
        lt = m.group(1)
    return ut, lt

def strip_threshold_tags(s: str) -> str:
    """Remove [UT=...] and [LT=...] tags from a string."""
    s = re.sub(r'\[UT=[^\]]*\]', '', s)
    s = re.sub(r'\[LT=[^\]]*\]', '', s)
    return s

def read_all_thresholds(path, file_name) -> dict:
    """Return a dict mapping clean label -> (upper, lower) for lines with threshold tags."""
    thresholds = {}
    try:
        with open(path / file_name, 'r') as f:
            data = f.readlines()
    except OSError:
        return thresholds
    for line in data:
        stripped = line.strip()
        ut, lt = get_threshold_from_line(stripped)
        if not ut and not lt:
            continue
        stripped_clean = strip_threshold_tags(strip_note_tag(strip_date_tag(stripped)))
        clean = stripped_clean.replace("[S]|", "").replace("[>]|", "").replace("[PASS]", "").replace("[FAIL]", "").strip()
        if clean:
            thresholds[clean] = (ut, lt)
    return thresholds

def get_threshold_for_label(label: str, path, file_name: str) -> tuple[str, str]:
    """Return (upper, lower) threshold for a given label, or ('', '') if none."""
    try:
        with open(path / file_name, 'r') as f:
            data = f.readlines()
    except OSError:
        return "", ""
    for line in data:
        stripped = line.strip()
        stripped_clean = strip_threshold_tags(strip_note_tag(strip_date_tag(stripped)))
        clean = stripped_clean.replace("[S]|", "").replace("[>]|", "").replace("[PASS]", "").replace("[FAIL]", "").strip()
        if clean == label:
            return get_threshold_from_line(stripped)
    return "", ""

def set_pass_fail(label: str, result: str, path, file_name: str) -> None:
    """Write [PASS] or [FAIL] result tag and [S] completion onto the matching line."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    with open(path / file_name, 'r') as f:
        data = f.readlines()
    modified_data = []
    for line in data:
        stripped = line.strip()
        stripped_clean = strip_threshold_tags(strip_note_tag(strip_date_tag(stripped)))
        clean = stripped_clean.replace("[S]|", "").replace("[>]|", "").replace("[PASS]", "").replace("[FAIL]", "").strip()
        if clean == label:
            base = line.rstrip()
            base = re.sub(r'^\[S\]\|', '', base)
            base = re.sub(r'\|\[d=[^\]]*\]', '', base)
            base = re.sub(r'\[PASS\]|\[FAIL\]', '', base)
            base = base.strip()
            modified_data.append(f"[S]|{base}[{result}]|[d={timestamp}]\n")
        else:
            modified_data.append(line)
    with open(path / file_name, 'w') as f:
        f.writelines(modified_data)

def remove_pass_fail(label: str, path, file_name: str) -> None:
    """Remove [S], [PASS]/[FAIL], and date tag from the matching threshold line, restoring it."""
    with open(path / file_name, 'r') as f:
        data = f.readlines()
    modified_data = []
    for line in data:
        stripped = line.strip()
        stripped_clean = strip_threshold_tags(strip_note_tag(strip_date_tag(stripped)))
        clean = stripped_clean.replace("[S]|", "").replace("[>]|", "").replace("[PASS]", "").replace("[FAIL]", "").strip()
        if clean == label:
            base = line.rstrip()
            base = re.sub(r'^\[S\]\|', '', base)
            base = re.sub(r'\|\[d=[^\]]*\]', '', base)
            base = re.sub(r'\[PASS\]|\[FAIL\]', '', base)
            modified_data.append(f"{base.strip()}\n")
        else:
            modified_data.append(line)
    with open(path / file_name, 'w') as f:
        f.writelines(modified_data)