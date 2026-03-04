from .storage import file_parser
from .app import veritrakk

app = veritrakk()
app.run

file_parser()