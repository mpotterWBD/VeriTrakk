from textual.app import App, ComposeResult
from textual.reactive import reactive
from textual.events import Key
from textual.widgets import Header, Footer, Label, Select, Rule, ContentSwitcher, Placeholder, Tree, Log, Markdown, Static, DirectoryTree, Tabs, Tab, TabbedContent
from textual.binding import Binding
from pathlib import Path
from textual.screen import Screen
from typing import Iterable
from pathlib import Path
from rich.text import Text
from textual.containers import Container, Horizontal, VerticalScroll, Vertical
from .storage import file_parser, number_of_files, file_reader, set_S, has_S, remove_S, file_parser_selected, save_root, has_child, read_root_and_file

FILES = []
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
        Binding("b", "back", "Home"),
    
    ]

    def compose(self)-> ComposeResult:
        yield Header(id="header")
        # self.query_one("header").tall = True

        with Vertical(id="main_panel"):

#TABS START
#--------------------------------------------------------------------------------------
            with Container (id="graphical_header"):
                yield Static(content=FIGLET,id="figlet")

            # with Container(id="tab_placeholder"):
            #     yield Placeholder("SELECT TABS GO HERE")
#TABS END
#--------------------------------------------------------------------------------------

            with Horizontal(id="data_panel"):
                with Vertical(id="left_panel"):
                    with ContentSwitcher(initial="or_cont",id="or_content_switcher"):
                        with Container(id="or_cont"):
                            
                            or_tab = Tabs(
                                Tab("OPEN", id="open"),
                                Tab("RESUME", id="resume"),
                                Tab("PROCESS BUILDER", id="processbuilder"),
                                id="or_tab"
)
                            # or_tab = Tabs("OPEN","RESUME","PROCESS BUILDER",id="or_tab")
                            
                            yield or_tab
                    
                    
                        with Container(id="file_and_select"):
                            with Container(id="select_cont"):   

                                options = []
                                yield Select(
                                options,
                                id="process_select",
                                compact=True,
                                prompt="Select",
                                allow_blank=True
                            )
                            with Container(id="file_cont"):
                                yield DirOnlyTree(Path.home(),id="file_tree")

                  

                with ContentSwitcher(initial="",id="ms_content_switcher"):
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

    # # def on_show(self) -> None:
    # #     self.query_one("#file_tree").root.expand()

    def on_tabs_tab_activated(self, event: Tabs.TabActivated) -> None:
        tab = self.query_one("#or_tab")
        resume_tab = self.query_one("#resume")
        try:
            if "resume" in tab.active:
                resume_tab.label = "RESUME" + " \\[" + str(read_root_and_file()[1]).replace(".prcss","") + "]"
            else:
                resume_tab.label = "RESUME"
        except IndexError:
            resume_tab.label = "RESUME \\[NONE]"

        


    def on_key(self, event: Key) -> None:
        tab = self.query_one("#or_tab")

        if event.key == "enter":
            # self.log("tab = ", tab.active)
            if "open" in tab.active:
                self.tab_selected = "open"
                tab.active = ""
                tree = self.query_one("#file_tree")
                self.query_one("#or_content_switcher").current = "file_and_select"
                tree.focus()
                tree.root.expand()
                tree.move_cursor(tree.root)
            elif "resume" in tab.active:
                self.tab_selected = "resume"
                tab.active = ""
                select = self.query_one("#process_select")
                self.on_select_changed(Select.Changed(self, value=select.value))
   
    def on_directory_tree_directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        select = self.query_one("#process_select")
        self.log("SELECTED PROCESS =",select.value)
        path = event.path
        self.root = path
        matches = list(path.glob("*.prcss"))
        if matches:
            files = file_parser_selected(path)
            nof = number_of_files(files)
            options = [(x, x) for x in files]
            select_cont = self.query_one("#select_cont")
            file_cont = self.query_one("#file_cont")
            select_cont.styles.height = 4 + nof
            file_cont.styles.height = "1fr"
            self.log("number of files = " + str(nof))
            self.query_one("#process_select", Select).set_options(options)
            self.query_one("#process_select", Select).focus()

            
    def action_back(self) -> None:
        self.query_one("#ms_content_switcher", ContentSwitcher).current = ""
        self.query_one("#or_content_switcher").current = "or_cont"
        self.query_one("#or_tab").focus()
        self.query_one("#or_tab").active = "open"
        self.query_one("#file_tree").root.collapse_all()

        select = self.query_one("#process_select", Select)
        select_cont = self.query_one("#select_cont")
        select.set_options([])
        select.clear()
        self.query_one("#process_tree").reset(self.tree_name)
        select_cont.styles.height = "7%"


    def action_select_down(self) -> None:
        tree = self.query_one("#process_tree")
        if self.query_one("#ms_content_switcher").current == "process_cont":
            tree.action_cursor_down()
    
    def action_select_up(self) -> None:
        tree = self.query_one("#process_tree")
        if self.query_one("#ms_content_switcher").current == "process_cont":
            tree.action_cursor_up()
    
    def action_select_right(self) -> None:
        succ_c = "[SUCCESS]    "
        succ_nc = "  [SUCCESS]    "
        tree = self.query_one("#process_tree")
        node = tree.cursor_node
        node_buff = node.label

        saved_f = read_root_and_file()
        tab = self.query_one("#or_tab")
        if "resume" in self.tab_selected:
            path = Path(saved_f[0].replace("\n",""))
            file = saved_f[1]
        else:
            path = self.root
            file = str(self.select_data)

        if self.query_one("#ms_content_switcher").current == "process_cont":

            #Applies to nodes with out success and nodes with no children
            if "[SUCCESS]" not in node_buff and len(node.children) == 0:
                set_S(str(node_buff), path, file)
                #Checks if node is a [>]
                if node.parent.parent:
                    node.label = succ_c + str(node_buff)
                else:
                    node.label = succ_nc + str(node_buff)
                    
                self.log(node.label)
                node.label.stylize("green")
                # node.set_label(node.label)

            #Auto collapeses parent when children are successful
            if node.parent:
                all_success = all("[SUCCESS]" in str(child.label) for child in node.parent.children)
                if all_success:
                    node.parent.collapse()
                    parent_label = str(node.parent.label).replace(succ_c, "").strip()
                    node.parent.set_label(Text(succ_c + parent_label, style="green"))
                    set_S(str(parent_label), path, file)
                    tree.move_cursor(node.parent)

            #Auto collapeses root when everything is successful
            if node.parent and node.parent.parent:
                parents_all_success = all("[SUCCESS]" in str(child.label) for child in node.parent.parent.children)
                if parents_all_success:
                    node.parent.parent.collapse()
                    parents_parent_label = str(node.parent.parent.label).replace(succ_c, "").strip()
                    node.parent.parent.set_label(Text(succ_c + parents_parent_label, style="green"))
                    set_S(str(parents_parent_label), path, file)
        
    def action_select_left(self) -> None:
        succ_c = "[SUCCESS]    "
        succ_nc = "  [SUCCESS]    "
        tree = self.query_one("#process_tree")
        node = tree.cursor_node
        node_buff = node.label

        saved_f = read_root_and_file()
        tab = self.query_one("#or_tab")
        if "resume" in self.tab_selected:
            path = Path(saved_f[0].replace("\n",""))
            file = saved_f[1]
        else:
            path = self.root
            file = str(self.select_data)

        if self.query_one("#ms_content_switcher").current == "process_cont":
            
            #Applies to nodes with success and nodes with no children
            if succ_c in node_buff and len(node.children) == 0:
                self.log("WE ARE EFFECTING CHILD WITH NO CHILD")
                self.log("node_buff = " + str(node_buff))
                
                #handles formatting based on if child has no children inside and has a parent or if just a child uner main root
                if succ_c in str(node_buff):
                    new_label = str(node_buff).replace(succ_c,"").strip()
                elif succ_nc in str(node_buff):
                    new_label = str(node_buff).replace(succ_nc,"").strip()
                
                self.log("to remove = " + "[S]|" + str(new_label))
                remove_S("[S]|" + str(new_label).strip(), path, file)
                node.label = new_label
                node.label.stylize("default")

            #Applies to nodes with success and nodes with children
            if node.parent:
                parent_label = str(node.parent.label).replace(succ_c, "").strip()
                remove_S("[S]|" + str(parent_label), path, file)
                node.parent.label = parent_label
                node.parent.label.stylize("default")

            #Applies to root node
            if node.parent and node.parent.parent:
                parents_parent_label = str(node.parent.parent.label).replace(succ_c, "").strip()
                remove_S("[S]|" + str(parents_parent_label), path, file)
                node.parent.parent.label = parents_parent_label
                node.parent.parent.label.stylize("default")
                
    def on_mount(self) -> None:
        self.title = "WELCOME TO VERITRAK"
        self.sub_title = "Powered by Westbound Designs"

        select_cont = self.query_one("#select_cont", Container)
        select_cont.border_title = "SELECT PROCESSES"
        
        process_cont = self.query_one("#process_cont", Container)
        process_cont.border_title = "PROCESS TREE"

        process_builder = self.query_one("#process_builder")
        process_builder.border_title = "PROCESS BUILDER"

        # self.call_after_refresh(self.query_one("#file_tree").root.expand)

        self.query_one("#or_tab").focus()
        
    def on_screen_resume(self) -> None:
        select = self.query_one("#process_select", Select)
        select.clear()

    def on_select_changed(self, event: Select.Changed) -> None:
        
        self.select_data = self.query_one("#process_select").value
        tab = self.query_one("#or_tab")

        tree = self.query_one("#process_tree")
        #Handles select changes when in process and back is pressed
        if "resume" in self.tab_selected:
            saved_f = read_root_and_file()
            path = Path(saved_f[0].replace("\n",""))
            self.log("root = ", saved_f[0].replace("\n",""), "file = ", saved_f[1])
            data = file_reader(path, saved_f[1])

        elif self.select_data is Select.NULL:         
            return
        
        else:
            save_root(str(self.root),str(self.select_data))
            data = file_reader(self.root, self.select_data)
        #Sets the first line in .prcss file as the main node
        tree.root.label = data[0]

        self.log("DATA = ", data)

        if "[S]" in tree.root.label:
            new_root_label = "[SUCCESS]    " + str(tree.root.label).replace("[S]|","")
            tree.root.label = new_root_label
            tree.root.label.stylize("green")
            tree.root.collapse()
        else:
            tree.root.expand()

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
                #Populates items with children
                if "[S]" in x and has_child(data,x):
                    current_node = tree.root.add_leaf("[SUCCESS]    " + x.replace("[S]|",""))
                    current_node.label.stylize("green")

                #Populates items without children
                elif "[S]" in x and not has_child(data,x):
                    current_node = tree.root.add_leaf("  [SUCCESS]    " + x.replace("[S]|",""))
                    current_node.label.stylize("green")

                else:
                    current_node = tree.root.add(x,allow_expand=False)
        
        if "resume" in self.tab_selected:
            self.query_one("#ms_content_switcher").current = "process_cont"
        
        elif(event.select.is_blank()):
            return
        
        elif(event.select.id == "process_select"):
            print("OPENED PROCESS_CONT")
            self.query_one("#ms_content_switcher").current = "process_cont"
        
        self.call_after_refresh(self.query_one("#process_tree").focus)
        
class DirOnlyTree(DirectoryTree):
    def on_show(self) -> None:
        self.root.expand()

    def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
        return [p for p in paths if p.is_dir()] 
    
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