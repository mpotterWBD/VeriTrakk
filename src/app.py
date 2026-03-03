from textual.app import App, ComposeResult
from textual.widgets import Label

class veritrakk(App):
    CSS_PATH = "veritrakk.tcss"
    BINDINGS = [("q", "quit", "Quit")]

    def compose(self) -> ComposeResult:
        
        TEXT = "THESE ARE WORDS"
        label = Label(TEXT)
        label.border_title = "WELCOME TO VERITRAKK"
        yield(label)
 

veritrakk().run()