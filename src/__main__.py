

from .storage import file_parser, number_of_files
from .app import veritrakk

app = veritrakk()
app.run