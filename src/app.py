from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Label, Select, Rule
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
        yield Header()

        yield Rule(line_style="double", id="header_rule")

        with Horizontal():
            stage_proc_l = Container(id="stage_proc_l")
            stage_proc_r = Container(id="stage_proc_r")
            stage_proc_l.border_title = "PROCESS TREE"
            stage_proc_r.border_title = "PROCESS DETAILS"

            yield stage_proc_l
            yield stage_proc_r
            select_cont = Container(id="select_cont")
            select_cont.border_title = "SELECT PROCESSES"
            with select_cont:

                select_proc = Select(((x,x) for x in file_parser()),id="process_select",compact=True)
                yield select_proc
         
        yield Footer()
    
    def on_select_changed(self, event: Select.Changed) -> None:
        if(event.select.id == "process_select"):
            self.query_one("#select_cont").display = "none"
            self.query_one("#stage_proc_l").display = "block"
            self.query_one("#stage_proc_r").display = "block"
        # if(self.query_one("#process_select").value != None):

    def action_back(self) -> None:
        select_proc = self.query_one("#process_select")
        left = self.query_one("#select_cont")
        left.display = "block"
        self.query_one("#stage_proc_l").display = "none"
        self.query_one("#stage_proc_r").display = "none"
        self.call_after_refresh(select_proc.focus)

    def on_mount(self) -> None:
        self.query_one("#stage_proc_l").display = "none"
        self.query_one("#stage_proc_r").display = "none"
      
veritrakk().run()