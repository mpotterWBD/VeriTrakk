from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Label
from textual.containers import Container, Horizontal, VerticalScroll

class veritrakk(App):
    CSS_PATH = "veritrakk.tcss"
    BINDINGS = [("q", "quit", "Quit")]
    TITLE = "WELCOME TO VERITRAKK"

    def compose(self) -> ComposeResult:

        with Horizontal():
            left = Container(id="left")
            left.border_title = "SELECT PROCESSES"
            yield left
            yield Container(id="right")
            
        yield Header()
        yield Footer()
      
 

veritrakk().run()