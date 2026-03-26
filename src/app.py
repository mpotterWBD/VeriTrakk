from textual.app import App, ComposeResult
from textual.reactive import reactive
from textual.widgets import Header, Footer, Label, Select, Rule, ContentSwitcher, Placeholder, Tree, Log, Markdown, Static
from textual.binding import Binding
from textual.screen import Screen
from rich.text import Text
from textual.containers import Container, Horizontal, VerticalScroll, Vertical
from .storage import file_parser, number_of_files, file_reader, set_S, has_S, remove_S

FILES = file_parser()
NOF = number_of_files(FILES)

FIGLET = """
┓┏┏┓┳┓┳┏┳┓┳┓┏┓┓┏┓
┃┃┣ ┣┫┃ ┃ ┣┫┣┫┃┫ 
┗┛┗┛┛┗┻ ┻ ┛┗┛┗┛┗┛
"""

class MainScreen(Screen):
    # TITLE = "WELCOME TO VERITRAKK"
   

    BINDINGS = [
        Binding("up", "select_up"),
        Binding("down", "select_down"),
        Binding("right", "select_right"),
        Binding("left", "select_left"),
        Binding("b", "back", "Back"),
    
    ]

    def compose(self)-> ComposeResult:
        yield Header(id="header")
        # self.query_one("header").tall = True

        with Vertical():

#TABS START
#--------------------------------------------------------------------------------------
            with Container (id="graphical_header"):
                yield Static(content=FIGLET,id="figlet")
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
            node_buff = node.label
            # self.log("Label = ",node_buff)
            # self.log("file = ",self.select_data)
            self.log("node_buff=",node_buff)

            # applies only to nodes that are not successful and nodes that dont have children
            if "[SUCCESS]" not in node_buff and len(node.children) == 0:
                set_S(str(node_buff), str(self.select_data))
                node.label = "[SUCCESS]" + "    " + str(node_buff)
                self.log(node.label)
                node.label.stylize("green")
                node.set_label(node.label)

            # If the node is a parent, the node Collapses and appends [S] when children are all successful
            if node.parent:
                all_success = all("[SUCCESS]" in str(child.label) for child in node.parent.children)
                if all_success:
                    node.parent.collapse()
                    parent_label = str(node.parent.label).replace("[SUCCESS]", "").strip()
                    node.parent.set_label(Text("[SUCCESS]    " + parent_label, style="green"))
                    set_S(str(parent_label), str(self.select_data))

            if node.parent and node.parent.parent:
                parents_all_success = all("[SUCCESS]" in str(child.label) for child in node.parent.parent.children)
                if parents_all_success:
                    node.parent.parent.collapse()
                    parents_parent_label = str(node.parent.parent.label).replace("[SUCCESS]", "").strip()
                    node.parent.parent.set_label(Text("[SUCCESS]    " + parent_label, style="green"))
                    set_S(str(parents_parent_label), str(self.select_data))
        
            
    def action_select_left(self) -> None:
        tree = self.query_one("#process_tree")
        if self.query_one("#ms_content_switcher").current == "process_cont":
            node = tree.cursor_node
            node_buff = node.label
            #Only applies to nodes with success and nodes with no children
            if "[SUCCESS]" in node_buff and len(node.children) == 0:
                new_label = str(node_buff).replace("[SUCCESS]    ","")
                remove_S("[S]|" + str(new_label), str(self.select_data))
                node.label = new_label
                node.label.stylize("default")

            if node.parent:
                parent_label = str(node.parent.label).replace("[SUCCESS]", "").strip()
                remove_S("[S]|" + str(parent_label), str(self.select_data))
                node.parent.label = parent_label
                node.parent.label.stylize("default")

            if node.parent and node.parent.parent:
                parents_parent_label = str(node.parent.parent.label).replace("[SUCCESS]", "").strip()
                remove_S("[S]|" + str(parents_parent_label), str(self.select_data))
                node.parent.parent.label = parents_parent_label
                node.parent.parent.label.stylize("default")
                
                


    def on_mount(self) -> None:
        self.title = "WELCOME TO VERITRAK"
        self.sub_title = "Powered by Westbound Designs"

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
        #Handles select changes when in process and back is pressed
        if self.select_data is Select.NULL:         
            return
        
        data = file_reader(self.select_data)
        #Sets the first line in .prcss file as the main node
        tree.root.label = data[0]

        if "[S]" in tree.root.label:
            new_root_label = "[SUCCESS]    " + str(tree.root.label).replace("[S]|","")
            tree.root.label = new_root_label
            tree.root.label.stylize("green")

        #Deletes the first line so all the other lines can be leaves                   
        data.remove(data[0])                        

        #Populates Tree from file
        for x in (data): 
            if "[>]" in x:
                if "[S]" in x:
                    #Populates data that is successful and is a child
                    current_node.allow_expand = True
                    node_buffer = Text("[SUCCESS]    " + x.replace("[>]|","").replace("[S]|",""))
                    node_buffer.stylize("green")
                    current_node.add_leaf(node_buffer)
                    # current_node.label.stylize("green")
                else:
                    #Populates data that is not successful and is a child
                    current_node.allow_expand = True
                    current_node.add_leaf(x.replace("[>]|",""))
                    current_node.expand_all()
                
            else:
                #Store line into tree but removes status prefixes
                if "[S]" in x:
                    current_node = tree.root.add_leaf("[SUCCESS]    " + x.replace("[S]|",""))
                    current_node.label.stylize("green")
                else:
                    current_node = tree.root.add(x,allow_expand=False)

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