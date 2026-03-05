from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Label, Select, Rule
from textual.binding import Binding
from textual.screen import Screen
from textual.containers import Container, Horizontal, VerticalScroll
from .storage import file_parser, number_of_files
# from storage import file_parser, number_of_files

FILES = file_parser()
NOF = number_of_files(FILES)

class MainScreen(Screen):
    TITLE = "WELCOME TO VERITRAKK"
    

    def compose(self)-> ComposeResult:
        yield Header()
        with Horizontal():
            
            select_cont = Container(id="select_cont")
            select_cont.border_title = "SELECT PROCESSES"

          
            with select_cont:

                options = [(x,x) for x in FILES]
                select_proc = Select(options,id="process_select",compact=True,prompt="Select",allow_blank=True)

                select_cont.styles.height=NOF+4
                yield select_proc
                 
        yield Footer()

    def on_screen_resume(self) -> None:
        select = self.query_one("#process_select", Select)
        select.clear()

   
     
        
class ProcessScreen(Screen):
    
    TITLE = "WELCOME TO VERITRAKK"

    BINDINGS = [
        Binding("b", "back", "Back"),
    ]
  
    def compose(self):
        yield Header(id="compose_header")
        with Horizontal():
            stage_proc_l = Container(id="stage_proc_l")
            stage_proc_r = Container(id="stage_proc_r")
            stage_proc_l.border_title = "PROCESS TREE"
            stage_proc_r.border_title = "PROCESS DETAILS"
            yield stage_proc_l
            yield stage_proc_r
        
        yield Footer()

    def action_back(self) -> None:
        self.app.pop_screen()

class veritrakk(App):

    CSS_PATH = "veritrakk.tcss"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
    ]

    SCREENS = {
        "main_screen": MainScreen,
        "process_screen": ProcessScreen,
    }

    def on_select_changed(self, event: Select.Changed) -> None:
        if(event.select.is_blank()):
            return
        if(event.select.id == "process_select"):
            self.app.push_screen("process_screen")

    def on_mount(self) -> None:
        
        self.push_screen(MainScreen())
      

app = veritrakk()
veritrakk().run()