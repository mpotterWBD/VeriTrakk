from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Label, Select, Rule, ContentSwitcher, Placeholder
from textual.binding import Binding
from textual.screen import Screen
from textual.containers import Container, Horizontal, VerticalScroll
from .storage import file_parser, number_of_files

FILES = file_parser()
NOF = number_of_files(FILES)

class MainScreen(Screen):
    TITLE = "WELCOME TO VERITRAKK"

    BINDINGS = [
        Binding("b", "back", "Back"),
    ]
    
    def compose(self)-> ComposeResult:
        yield Header()

        with Horizontal():
            with ContentSwitcher(initial="select_cont",id="ms_content_switcher"):
                with Container(id="select_cont"):   

                    options = [(x,x) for x in FILES]
                    yield Select(
                        options,
                        id="process_select",
                        compact=True,
                        prompt="Select",
                        allow_blank=True
                    )
                with Container(id="process_cont"):
                    yield Placeholder("PLACEHOLDER")
                         
        yield Footer()

    def action_back(self) -> None:
        self.query_one("#ms_content_switcher", ContentSwitcher).current = "select_cont"
        select = self.query_one("#process_select", Select).focus()
        select.clear()

    def on_mount(self) -> None:
        select_cont = self.query_one("#select_cont", Container)
        select_cont.border_title = "SELECT PROCESSES"
        select_cont.styles.height=NOF+4

        process_cont = self.query_one("#process_cont", Container)
        process_cont.border_title = "PROCESS DETAILS"

    def on_screen_resume(self) -> None:
        select = self.query_one("#process_select", Select)
        select.clear()

    def on_select_changed(self, event: Select.Changed) -> None:
        if(event.select.is_blank()):
            return
        if(event.select.id == "process_select"):
            self.query_one("#ms_content_switcher", ContentSwitcher).current = "process_cont"
    
class veritrakk(App):

    BINDINGS = [
        Binding("q", "quit", "Quit"),
    ]

    CSS_PATH = "veritrakk.tcss"

    SCREENS = {
        "main_screen": MainScreen,
    }

    def on_mount(self) -> None:
        self.push_screen(MainScreen())
      

app = veritrakk()
veritrakk().run()