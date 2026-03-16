from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Label, Select, Rule, ContentSwitcher, Placeholder, Tree
from textual.binding import Binding
from textual.screen import Screen
from textual.containers import Container, Horizontal, VerticalScroll, Vertical
from .storage import file_parser, number_of_files, file_reader

FILES = file_parser()
NOF = number_of_files(FILES)

class MainScreen(Screen):
    TITLE = "WELCOME TO VERITRAKK"

    BINDINGS = [
        Binding("up", "select_up"),
        Binding("down", "select_down"),
        Binding("right", "select_right"),
        Binding("left", "select_left"),
        Binding("b", "back", "Back"),
    
    ]

    def compose(self)-> ComposeResult:
        yield Header()

        with Vertical():

#TABS START
#--------------------------------------------------------------------------------------
            with Container(id="tab_placeholder"):
                yield Placeholder("SELECT TABS GO HERE")
#TABS END
#--------------------------------------------------------------------------------------

            with Horizontal():
                with Container(id="select_cont"):   

                        options = [(x,x) for x in FILES]
                        yield Select(
                            options,
                            id="process_select",
                            compact=True,
                            prompt="Select",
                            allow_blank=True
                        )

                with ContentSwitcher(initial="process_builder",id="ms_content_switcher"):
                    with Container(id="process_builder"):
                        yield Placeholder("PROCESS BUILDER GOES HERE")    

                    with Container(id="process_cont"):
                        self.tree_name = ""
                        prc_tree: Tree[str] = Tree("Process_Tree", id="process_tree")
                        prc_tree.root.expand()
                        prc_tree.guide_depth = 5
                        yield prc_tree

#CONTENTSWITCHER END
#--------------------------------------------------------------------------------------

        yield Footer()
   
    def action_back(self) -> None:
        self.query_one("#ms_content_switcher", ContentSwitcher).current = "process_builder"
        select = self.query_one("#process_select", Select).focus()
        select.clear()

        self.query_one("#process_tree").reset(self.tree_name)

    def action_select_down(self) -> None:
        tree = self.query_one("#process_tree")
        if self.query_one("#ms_content_switcher").current == "process_cont":
            tree.action_cursor_down()
    
    def action_select_up(self) -> None:
        tree = self.query_one("#process_tree")
        if self.query_one("#ms_content_switcher").current == "process_cont":
            tree.action_cursor_up()
    
    def action_select_right(self) -> None:
        tree = self.query_one("#process_tree")
        if self.query_one("#ms_content_switcher").current == "process_cont":
            node = tree.cursor_node
            node.label = node.label + "[SUCCESS]"
            node.label.stylize("green")
            node.set_label(node.label)
            

    def action_select_left(self) -> None:
        tree = self.query_one("#process_tree")
        if self.query_one("#ms_content_switcher").current == "process_cont":
            node = tree.cursor_node
            node.label.stylize("default")

    def on_mount(self) -> None:
        self.log("STUFF = ", file_reader("test_proc.prcss"))

        select_cont = self.query_one("#select_cont", Container)
        select_cont.border_title = "SELECT PROCESSES"
        

        process_cont = self.query_one("#process_cont", Container)
        process_cont.border_title = "PROCESS TREE"

        process_builder = self.query_one("#process_builder")
        process_builder.border_title = "PROCESS BUILDER"
        
    def on_screen_resume(self) -> None:
        select = self.query_one("#process_select", Select)
        select.clear()

    def on_select_changed(self, event: Select.Changed) -> None:
        self.select_data = self.query_one("#process_select").value
        self.log("SELECTED = ", self.select_data)
        tree = self.query_one("#process_tree")

        if self.select_data is Select.NULL:         #Handles select changes when in process and back is pressed
            return
        
        data = file_reader(self.select_data)
        
        tree.root.label = data[0]                   #Sets the first line in .prcss file as the main node
        data.remove(data[0])                        #Deletes the first line so all the other lines can be leaves

        for x in (data): 

            if x[0] == '<':
                current_node.add_leaf(x[1:])
                current_node.expand_all()
                
            else:
                current_node = tree.root.add(x)

        if(event.select.is_blank()):
            return
        
        if(event.select.id == "process_select"):
            print("OPENED PROCESS_CONT")
            self.query_one("#ms_content_switcher").current = "process_cont"
        
        self.query_one("#process_tree").focus()
    
class veritrakk(App):
    ENABLE_COMMAND_PALETTE = False
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