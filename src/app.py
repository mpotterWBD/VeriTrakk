from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Label, Select
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from .storage import file_parser

class veritrakk(App):
    CSS_PATH = "veritrakk.tcss"
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("b", "back", "Back")
    ]


    TITLE = "WELCOME TO VERITRAKK"

    def compose(self) -> ComposeResult:

        with Horizontal():
            left = Container(id="left")
            left.border_title = "SELECT PROCESSES"
            with left:

                select_proc = Select(((x,x) for x in file_parser()),id="process_select",compact=True)
                yield select_proc
       
        yield Header()
        yield Footer()
    
    def on_select_changed(self, event: Select.Changed) -> None:
        if(event.select.id == "process_select"):
            self.query_one("#left").display = "none"

    def action_back(self) -> None:
        select_proc = self.query_one("#process_select")
        left = self.query_one("#left")
        left.display = "block"
        self.call_after_refresh(select_proc.focus)
      
veritrakk().run()