from textual.app import App, ComposeResult
from textual.reactive import reactive
from textual.events import Key
from textual.widgets import Header, Footer, Label, Select, Rule, ContentSwitcher, Placeholder, Tree, Log, Markdown, Static, DirectoryTree, Tabs, Tab, TabbedContent, Input
from textual.binding import Binding
from pathlib import Path
from textual.screen import Screen
from typing import Iterable
from pathlib import Path
import re
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
        Binding("b", "back", "Back"),
        Binding("ctrl+b", "unfocus_input", "Back"),
        Binding("f", "select_builder_directory", "Select Dir"),
        Binding("ctrl+a", "arm_builder_shift", "Shift", priority=True),
        Binding("s", "save_builder_process", "Save"),
        Binding("ctrl+s", "save_builder_process", "Save", priority=True),
        Binding("ctrl+t", "toggle_tags", "Tags"),
        Binding("ctrl+d", "delete_builder_node", "Delete", priority=True),
    
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
                        with ContentSwitcher(initial="builder_mode_select", id="builder_content_switcher"):
                            with Container(id="builder_mode_select"):
                                yield Tabs(
                                    Tab("NEW PROCESS", id="pb_new"),
                                    Tab("EDIT ACTIVE PROCESS", id="pb_edit"),
                                    id="builder_mode_tab",
                                )

                            with Container(id="builder_save_dir_select"):
                                yield Static("SELECT DIRECTORY TO SAVE TO\n\nUse UP and DOWN to highlight a folder in the left file tree.\nPress F to select that folder.", id="builder_save_dir_prompt")

                            with Vertical(id="builder_editor"):
                                yield Input(placeholder="Process / Sub Process", id="builder_name_input")
                                with Container(id="builder_tags_cont"):
                                    yield Tabs(
                                        Tab("SUB PROCESS", id="tag_subprocess"),
                                        Tab("+ ADD TAG", id="tag_placeholder"),
                                        id="builder_process_tags",
                                    )
                                builder_tree: Tree[str] = Tree("NEW PROCESS", id="builder_tree")
                                builder_tree.root.expand()
                                builder_tree.guide_depth = 5
                                builder_tree.root.add("Top Level Process", allow_expand=False)
                                builder_tree.root.add("Sub Process", allow_expand=False)
                                yield builder_tree

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

    def _show_process_builder_mode_select(self) -> None:
        self.tab_selected = "processbuilder"
        self.builder_save_dir = None
        self.query_one("#or_content_switcher").current = "or_cont"
        self.query_one("#ms_content_switcher").current = "process_builder"
        self.query_one("#builder_content_switcher", ContentSwitcher).current = "builder_mode_select"
        builder_mode_tab = self.query_one("#builder_mode_tab", Tabs)
        if not builder_mode_tab.active:
            builder_mode_tab.active = "pb_new"
        builder_mode_tab.focus()

    def _show_builder_save_directory_picker(self) -> None:
        self.query_one("#or_content_switcher").current = "file_and_select"
        select = self.query_one("#process_select", Select)
        select.set_options([])
        select.clear()
        select_cont = self.query_one("#select_cont")
        select_cont.styles.height = "7%"

        self.query_one("#builder_content_switcher", ContentSwitcher).current = "builder_save_dir_select"
        file_tree = self.query_one("#file_tree", Tree)
        file_tree.focus()
        file_tree.root.expand()
        file_tree.move_cursor(file_tree.root)

    def action_select_builder_directory(self) -> None:
        if self.query_one("#ms_content_switcher").current != "process_builder":
            return
        if self.query_one("#builder_content_switcher", ContentSwitcher).current != "builder_save_dir_select":
            return

        file_tree = self.query_one("#file_tree", Tree)
        node = file_tree.cursor_node
        if node is None:
            return

        directory_path = None
        node_data = getattr(node, "data", None)
        if node_data is not None:
            directory_path = getattr(node_data, "path", None)

        if directory_path is None:
            return

        self.builder_save_dir = Path(directory_path)
        self.query_one("#or_content_switcher").current = "or_cont"
        self._open_process_builder_editor("pb_new")

    def _get_active_process_name(self) -> str:
        try:
            saved_f = read_root_and_file()
            path = Path(saved_f[0].replace("\n", ""))
            file_name = saved_f[1].strip()
            if file_name:
                data = file_reader(path, file_name)
                if data:
                    return str(data[0]).replace("[S]|", "").strip()
                return Path(file_name).stem
        except (IndexError, FileNotFoundError, OSError):
            pass
        return "ACTIVE PROCESS"

    def _load_active_process_into_builder_tree(self) -> str:
        builder_tree = self.query_one("#builder_tree", Tree)
        try:
            saved_f = read_root_and_file()
            path = Path(saved_f[0].replace("\n", ""))
            file_name = saved_f[1].strip()
            if not file_name:
                raise FileNotFoundError

            data = file_reader(path, file_name)
            if not data:
                raise FileNotFoundError

            root_raw = str(data[0]).strip()
            root_is_complete = "[S]|" in root_raw
            root_label = root_raw.replace("[S]|", "").replace("[>]|", "").strip()
            root_display = f"[COMPLETE]    {root_label}" if root_is_complete else root_label
            builder_tree.reset(root_display)
            builder_tree.root.expand()

            current_node = builder_tree.root
            for line in data[1:]:
                raw_line = str(line).strip()
                if not raw_line:
                    continue

                is_complete = "[S]|" in raw_line
                is_child = "[>]|" in raw_line
                label = raw_line.replace("[S]|", "").replace("[>]|", "").strip()
                if not label:
                    continue

                display_label = f"[COMPLETE]    {label}" if is_complete else label

                if is_child:
                    current_node.allow_expand = True
                    current_node.add(display_label, allow_expand=False)
                else:
                    current_node = builder_tree.root.add(display_label, allow_expand=True)

            self._expand_tree_node_recursive(builder_tree.root)
            self._force_expand_builder_tree()
            self.call_after_refresh(self._force_expand_builder_tree)
            return root_display
        except (IndexError, FileNotFoundError, OSError):
            fallback_name = "ACTIVE PROCESS"
            builder_tree.reset(fallback_name)
            builder_tree.root.expand()
            return fallback_name

    def _expand_tree_node_recursive(self, node) -> None:
        if node.children:
            node.allow_expand = True
        node.expand()
        for child in node.children:
            self._expand_tree_node_recursive(child)

    def _force_expand_builder_tree(self) -> None:
        builder_tree = self.query_one("#builder_tree", Tree)
        self._expand_tree_node_recursive(builder_tree.root)

    def _open_process_builder_editor(self, mode: str) -> None:
        builder_tree = self.query_one("#builder_tree", Tree)
        input_widget = self.query_one("#builder_name_input", Input)
        self.query_one("#builder_content_switcher", ContentSwitcher).current = "builder_editor"
        self.builder_mode = mode
        self.builder_shift_armed = False

        if mode == "pb_edit":
            process_name = self._load_active_process_into_builder_tree()
        else:
            process_name = "NEW PROCESS"
            builder_tree.reset(process_name)
            builder_tree.root.expand()
            builder_tree.root.add("Top Level Process", allow_expand=False)
            builder_tree.root.add("Sub Process", allow_expand=False)

        input_widget.value = process_name
        input_widget.focus()
        builder_tree.move_cursor(builder_tree.root)
        if mode == "pb_edit":
            self._force_expand_builder_tree()
            self.call_after_refresh(self._force_expand_builder_tree)
            self.set_timer(0.05, self._force_expand_builder_tree)
        self._sync_builder_input()

    def action_delete_builder_node(self) -> None:
        if self.builder_tags_open:
            return
        if self.query_one("#ms_content_switcher").current != "process_builder":
            return
        if self.query_one("#builder_content_switcher", ContentSwitcher).current != "builder_editor":
            return

        builder_tree = self.query_one("#builder_tree", Tree)
        node = builder_tree.cursor_node
        if node is None or node is builder_tree.root:
            return

        root_label, model = self._capture_builder_model()

        if node.parent is builder_tree.root:
            top_index = list(builder_tree.root.children).index(node)
            if len(model) <= 1:
                self.notify("Cannot delete the only process item.")
                return
            # Promote children of deleted top-level node to top level after it
            children = model[top_index]["children"]
            model.pop(top_index)
            for i, child_label in enumerate(reversed(children)):
                model.insert(top_index, {"label": child_label, "children": []})
            new_top = min(top_index, len(model) - 1)
            cursor_path = ("top", new_top, None)
        else:
            parent = node.parent
            top_index = list(builder_tree.root.children).index(parent)
            child_index = list(parent.children).index(node)
            model[top_index]["children"].pop(child_index)
            # Move cursor to previous child or top-level parent
            if model[top_index]["children"]:
                new_child = max(0, child_index - 1)
                cursor_path = ("child", top_index, new_child)
            else:
                cursor_path = ("top", top_index, None)

        self._rebuild_builder_tree(root_label, model, cursor_path)
        self.call_after_refresh(lambda: self.call_after_refresh(lambda: (
            self._sync_builder_input(),
            self.query_one("#builder_name_input", Input).focus()
        )))

    def action_arm_builder_shift(self) -> None:
        if self.builder_tags_open:
            return
        if self.query_one("#ms_content_switcher").current != "process_builder":
            return
        if self.query_one("#builder_content_switcher", ContentSwitcher).current != "builder_editor":
            return

        self.builder_shift_armed = True
        self.notify("Shift armed: press UP or DOWN to insert a blank item.")

    def _capture_builder_model(self) -> tuple[str, list[dict[str, list[str]]]]:
        builder_tree = self.query_one("#builder_tree", Tree)
        root_label = str(builder_tree.root.label).strip()
        model: list[dict[str, list[str]]] = []
        for top_node in builder_tree.root.children:
            model.append(
                {
                    "label": str(top_node.label).strip(),
                    "children": [str(child.label).strip() for child in top_node.children],
                }
            )
        return root_label, model

    def _rebuild_builder_tree(self, root_label: str, model: list[dict[str, list[str]]], cursor_path: tuple[str, int, int | None] | None = None) -> None:
        builder_tree = self.query_one("#builder_tree", Tree)
        builder_tree.reset(root_label)
        builder_tree.root.expand()

        created_top_nodes = []
        for item in model:
            children = item["children"]
            top = builder_tree.root.add(item["label"], allow_expand=bool(children))
            created_top_nodes.append(top)
            for child_label in children:
                top.allow_expand = True
                top.add(child_label, allow_expand=False)

        self._force_expand_builder_tree()

        if cursor_path is not None:
            level, top_idx, child_idx = cursor_path
            target_node = None
            if level == "top" and 0 <= top_idx < len(created_top_nodes):
                target_node = created_top_nodes[top_idx]
            elif level == "child" and 0 <= top_idx < len(created_top_nodes):
                top = created_top_nodes[top_idx]
                if child_idx is not None and 0 <= child_idx < len(top.children):
                    target_node = top.children[child_idx]

            if target_node is not None:
                def _move(node=target_node):
                    builder_tree.move_cursor(node)
                self.call_after_refresh(_move)

    def _insert_blank_builder_node(self, direction: str) -> None:
        builder_tree = self.query_one("#builder_tree", Tree)
        node = builder_tree.cursor_node
        if node is None or node is builder_tree.root:
            self.builder_shift_armed = False
            return

        root_label, model = self._capture_builder_model()

        if node.parent is builder_tree.root:
            top_index = list(builder_tree.root.children).index(node)
            insert_index = top_index if direction == "up" else top_index + 1
            model.insert(insert_index, {"label": "", "children": []})
            cursor_path = ("top", insert_index, None)
        else:
            parent = node.parent
            top_index = list(builder_tree.root.children).index(parent)
            child_index = list(parent.children).index(node)
            insert_index = child_index if direction == "up" else child_index + 1
            model[top_index]["children"].insert(insert_index, "")
            cursor_path = ("child", top_index, insert_index)

        self._rebuild_builder_tree(root_label, model, cursor_path)
        self.builder_shift_armed = False

        def _after_insert():
            self._sync_builder_input()
            self.query_one("#builder_name_input", Input).focus()

        self.call_after_refresh(lambda: self.call_after_refresh(_after_insert))

    def _set_selected_builder_node_subprocess(self, make_subprocess: bool) -> None:
        builder_tree = self.query_one("#builder_tree", Tree)
        node = builder_tree.cursor_node
        if node is None or node is builder_tree.root:
            return

        root_label, model = self._capture_builder_model()

        if node.parent is builder_tree.root:
            top_index = list(builder_tree.root.children).index(node)
            if not make_subprocess:
                return
            if top_index == 0:
                self.notify("First top-level process can't be converted to sub process.")
                self._sync_builder_tag_checkbox(node)
                return

            moving_item = model.pop(top_index)
            parent_index = top_index - 1
            parent_children = model[parent_index]["children"]
            child_insert_at = len(parent_children)
            parent_children.append(moving_item["label"])
            parent_children.extend(moving_item["children"])
            cursor_path = ("child", parent_index, child_insert_at)
            self._rebuild_builder_tree(root_label, model, cursor_path)

        else:
            parent = node.parent
            top_index = list(builder_tree.root.children).index(parent)
            child_index = list(parent.children).index(node)
            if make_subprocess:
                return

            child_label = model[top_index]["children"].pop(child_index)
            insert_top_at = top_index + 1
            model.insert(insert_top_at, {"label": child_label, "children": []})
            cursor_path = ("top", insert_top_at, None)
            self._rebuild_builder_tree(root_label, model, cursor_path)

        self._sync_builder_input()
        self.query_one("#builder_name_input", Input).focus()

    def _sync_builder_tag_checkbox(self, node) -> None:
        tags_cont = self.query_one("#builder_tags_cont", Container)
        if node is None or node is self.query_one("#builder_tree", Tree).root:
            tags_cont.remove_class("tag-on")
            return
        is_subprocess = node.parent is not self.query_one("#builder_tree", Tree).root
        if is_subprocess:
            tags_cont.add_class("tag-on")
        else:
            tags_cont.remove_class("tag-on")

    def _strip_complete_prefix(self, label: str) -> tuple[str, bool]:
        if "[COMPLETE]" not in label:
            return label.strip(), False
        cleaned = label.replace("[COMPLETE]", "", 1).strip()
        return cleaned, True

    def _to_prcss_line(self, label: str, is_child: bool) -> str:
        clean_label, is_complete = self._strip_complete_prefix(label)
        prefix = ""
        if is_complete:
            prefix += "[S]|"
        if is_child:
            prefix += "[>]|"
        return f"{prefix}{clean_label}\n"

    def _sanitize_process_file_name(self, process_name: str) -> str:
        safe_name = re.sub(r'[<>:"/|?*]+', "_", process_name).strip()
        if not safe_name:
            safe_name = "new_process"
        return f"{safe_name}.prcss"

    def _get_builder_save_target(self) -> tuple[Path, str]:
        if self.builder_mode == "pb_edit":
            saved_f = read_root_and_file()
            return Path(saved_f[0].replace("\n", "")), saved_f[1].strip()

        if self.builder_save_dir is not None:
            save_dir = self.builder_save_dir
            builder_tree = self.query_one("#builder_tree", Tree)
            root_label, _ = self._strip_complete_prefix(str(builder_tree.root.label))
            file_name = self._sanitize_process_file_name(root_label)
            return save_dir, file_name

        try:
            saved_f = read_root_and_file()
            save_dir = Path(saved_f[0].replace("\n", ""))
            if not save_dir.exists():
                raise FileNotFoundError
        except (IndexError, FileNotFoundError, OSError):
            save_dir = Path.cwd() / "data"

        builder_tree = self.query_one("#builder_tree", Tree)
        root_label, _ = self._strip_complete_prefix(str(builder_tree.root.label))
        file_name = self._sanitize_process_file_name(root_label)
        return save_dir, file_name

    def action_save_builder_process(self) -> None:
        if self.builder_tags_open:
            return
        if self.query_one("#ms_content_switcher").current != "process_builder":
            return
        if self.query_one("#builder_content_switcher", ContentSwitcher).current != "builder_editor":
            return

        builder_tree = self.query_one("#builder_tree", Tree)
        output_lines = [self._to_prcss_line(str(builder_tree.root.label), is_child=False)]

        for top_level_node in builder_tree.root.children:
            output_lines.append(self._to_prcss_line(str(top_level_node.label), is_child=False))
            for child_node in top_level_node.children:
                output_lines.append(self._to_prcss_line(str(child_node.label), is_child=True))

        save_dir, file_name = self._get_builder_save_target()
        save_dir.mkdir(parents=True, exist_ok=True)
        with open(save_dir / file_name, "w") as f:
            f.writelines(output_lines)

        save_root(str(save_dir), file_name)
        self.notify(f"Saved: {save_dir / file_name}")

    def on_tabs_tab_activated(self, event: Tabs.TabActivated) -> None:
        if event.tabs.id == "builder_mode_tab":
            return

        if event.tabs.id == "builder_process_tags":
            return

        tab = self.query_one("#or_tab")
        resume_tab = self.query_one("#resume")
        try:
            if "resume" in tab.active:
                resume_tab.label = "RESUME" + " \\[" + str(read_root_and_file()[1]).replace(".prcss","") + "]"
            else:
                resume_tab.label = "RESUME"
        except IndexError:
            resume_tab.label = "RESUME \\[NONE]"

        if "open" in tab.active or "resume" in tab.active or "processbuilder" in tab.active:
            if self.query_one("#ms_content_switcher").current == "process_builder":
                self.query_one("#ms_content_switcher").current = ""

        


    def on_key(self, event: Key) -> None:
        # When the tags dialog is open, only ctrl+t and tag navigation is allowed.
        if self.builder_tags_open:
            if event.key == "ctrl+t":
                return  # let the binding system handle it
            if event.key in ("left", "right"):
                tabs = self.query_one("#builder_process_tags", Tabs)
                tab_ids = [t.id for t in tabs.query(Tab)]
                if tabs.active in tab_ids:
                    current_idx = tab_ids.index(tabs.active)
                    if event.key == "right":
                        new_idx = (current_idx + 1) % len(tab_ids)
                    else:
                        new_idx = (current_idx - 1) % len(tab_ids)
                    tabs.active = tab_ids[new_idx]
            elif event.key == "enter":
                tabs = self.query_one("#builder_process_tags", Tabs)
                if tabs.active == "tag_placeholder" or tabs.active is None:
                    event.stop()
                    return
                active_id = tabs.active
                if active_id in self.builder_staged_tags:
                    self.builder_staged_tags.discard(active_id)
                else:
                    self.builder_staged_tags.add(active_id)
                self._apply_staged_tag_visuals()
            event.stop()
            return

        if event.key != "enter":
            return

        tab = self.query_one("#or_tab")
        builder_mode_tab = self.query_one("#builder_mode_tab", Tabs)

        # Main tab actions execute only when that top-level tab is focused + Enter is pressed.
        if tab.has_focus and "open" in tab.active:
            self.tab_selected = "open"
            tab.active = ""
            tree = self.query_one("#file_tree")
            self.query_one("#or_content_switcher").current = "file_and_select"
            tree.focus()
            tree.root.expand()
            tree.move_cursor(tree.root)
            event.stop()
            return

        if tab.has_focus and "resume" in tab.active:
            self.tab_selected = "resume"
            tab.active = ""
            select = self.query_one("#process_select")
            self.on_select_changed(Select.Changed(self, value=select.value))
            event.stop()
            return

        if tab.has_focus and "processbuilder" in tab.active:
            self._show_process_builder_mode_select()
            event.stop()
            return

        # Builder mode selection executes on a separate Enter keypress.
        if self.query_one("#ms_content_switcher").current == "process_builder":
            if self.query_one("#builder_content_switcher", ContentSwitcher).current == "builder_mode_select" and builder_mode_tab.has_focus:
                mode = builder_mode_tab.active
                if mode:
                    if mode == "pb_new":
                        self._show_builder_save_directory_picker()
                    else:
                        self._open_process_builder_editor(mode)
                    event.stop()
   
    def on_directory_tree_directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        if self.query_one("#ms_content_switcher").current == "process_builder":
            if self.query_one("#builder_content_switcher", ContentSwitcher).current == "builder_save_dir_select":
                self.builder_save_dir = event.path
                self.notify(f"Save directory ready: {event.path}. Press F to confirm.")
                return

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

    def on_directory_tree_node_selected(self, event: DirectoryTree.NodeSelected) -> None:
        if self.query_one("#ms_content_switcher").current == "process_builder":
            if self.query_one("#builder_content_switcher", ContentSwitcher).current == "builder_save_dir_select":
                path = event.node.data.path
                self.builder_save_dir = path
                self.notify(f"Save directory ready: {path}. Press F to confirm.")
            return

    def action_unfocus_input(self) -> None:
        if self.query_one("#ms_content_switcher").current != "process_builder":
            return

        if self.query_one("#builder_content_switcher", ContentSwitcher).current != "builder_editor":
            return

        self._show_process_builder_mode_select()

            
    def check_action(self, action: str, parameters: tuple) -> bool | None:
        if action == "unfocus_input":
            try:
                return (
                    self.query_one("#ms_content_switcher").current == "process_builder"
                    and self.query_one("#builder_content_switcher", ContentSwitcher).current == "builder_editor"
                )
            except Exception:
                return False
        if action == "save_builder_process":
            try:
                return (
                    self.query_one("#ms_content_switcher").current == "process_builder"
                    and self.query_one("#builder_content_switcher", ContentSwitcher).current == "builder_editor"
                )
            except Exception:
                return False
        if action == "toggle_tags":
            try:
                return (
                    self.builder_tags_open
                    or self.query_one("#builder_name_input", Input).has_focus
                )
            except Exception:
                return False
        if action == "delete_builder_node":
            try:
                return self.query_one("#builder_name_input", Input).has_focus
            except Exception:
                return False
        if action == "arm_builder_shift":
            try:
                return self.query_one("#builder_name_input", Input).has_focus
            except Exception:
                return False
        if action == "select_builder_directory":
            try:
                return (
                    self.query_one("#ms_content_switcher").current == "process_builder"
                    and self.query_one("#builder_content_switcher", ContentSwitcher).current == "builder_save_dir_select"
                )
            except Exception:
                return False
        return True

    def action_back(self) -> None:
        if self.builder_tags_open:
            return
        self.builder_shift_armed = False
        if self.query_one("#ms_content_switcher", ContentSwitcher).current == "process_builder":
            builder_switcher = self.query_one("#builder_content_switcher", ContentSwitcher)
            if builder_switcher.current == "builder_editor" or builder_switcher.current == "builder_save_dir_select":
                builder_switcher.current = "builder_mode_select"
                self.query_one("#or_content_switcher").current = "or_cont"
                self.query_one("#builder_mode_tab", Tabs).focus()
                return

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


    def action_toggle_tags(self) -> None:
        if self.query_one("#ms_content_switcher").current != "process_builder":
            return
        if self.query_one("#builder_content_switcher", ContentSwitcher).current != "builder_editor":
            return
        self.builder_tags_open = not self.builder_tags_open
        tags_cont = self.query_one("#builder_tags_cont", Container)
        if self.builder_tags_open:
            # Sync staged state from the current node's actual state
            self.builder_staged_tags = set()
            builder_tree = self.query_one("#builder_tree", Tree)
            node = builder_tree.cursor_node
            if node and node is not builder_tree.root:
                if node.parent is not builder_tree.root:
                    self.builder_staged_tags.add("tag_subprocess")
            tags_cont.display = True
            self._apply_staged_tag_visuals()
            self.query_one("#builder_process_tags", Tabs).focus()
        else:
            # Apply staged tags to the node
            is_subprocess = "tag_subprocess" in self.builder_staged_tags
            self._set_selected_builder_node_subprocess(is_subprocess)
            self.builder_staged_tags = set()
            tags_cont.display = False
            self.query_one("#builder_name_input", Input).focus()

    def _apply_staged_tag_visuals(self) -> None:
        subprocess_tab = self.query_one("#tag_subprocess", Tab)
        if "tag_subprocess" in self.builder_staged_tags:
            subprocess_tab.add_class("tag-staged")
        else:
            subprocess_tab.remove_class("tag-staged")

    def action_select_down(self) -> None:
        if self.builder_tags_open:
            return
        tree = self.query_one("#process_tree")
        if self.query_one("#ms_content_switcher").current == "process_cont":
            tree.action_cursor_down()
        elif self.query_one("#ms_content_switcher").current == "process_builder" and self.query_one("#builder_content_switcher", ContentSwitcher).current == "builder_editor":
            if self.builder_shift_armed:
                self._insert_blank_builder_node("down")
                return
            builder_tree = self.query_one("#builder_tree", Tree)
            builder_tree.action_cursor_down()
            self._sync_builder_input()
            self.query_one("#builder_name_input", Input).focus()
        elif self.query_one("#ms_content_switcher").current == "process_builder" and self.query_one("#builder_content_switcher", ContentSwitcher).current == "builder_save_dir_select":
            file_tree = self.query_one("#file_tree", Tree)
            file_tree.action_cursor_down()
    
    def action_select_up(self) -> None:
        if self.builder_tags_open:
            return
        tree = self.query_one("#process_tree")
        if self.query_one("#ms_content_switcher").current == "process_cont":
            tree.action_cursor_up()
        elif self.query_one("#ms_content_switcher").current == "process_builder" and self.query_one("#builder_content_switcher", ContentSwitcher).current == "builder_editor":
            if self.builder_shift_armed:
                self._insert_blank_builder_node("up")
                return
            builder_tree = self.query_one("#builder_tree", Tree)
            builder_tree.action_cursor_up()
            self._sync_builder_input()
            self.query_one("#builder_name_input", Input).focus()
        elif self.query_one("#ms_content_switcher").current == "process_builder" and self.query_one("#builder_content_switcher", ContentSwitcher).current == "builder_save_dir_select":
            file_tree = self.query_one("#file_tree", Tree)
            file_tree.action_cursor_up()

    def _sync_builder_input(self) -> None:
        if self.query_one("#builder_content_switcher", ContentSwitcher).current != "builder_editor":
            return

        input_widget = self.query_one("#builder_name_input", Input)
        builder_tree = self.query_one("#builder_tree", Tree)
        node = builder_tree.cursor_node
        if node is None:
            return
        label_text = str(node.label).strip()
        input_widget.value = label_text
        input_widget.cursor_position = len(input_widget.value)
        builder_tree.set_class(label_text == "", "blank-focused")
        self._refresh_builder_blank_focus_visual(node)
        self._sync_builder_tag_checkbox(node)

    def _refresh_builder_blank_focus_visual(self, focused_node) -> None:
        builder_tree = self.query_one("#builder_tree", Tree)

        def _all_nodes():
            for top in builder_tree.root.children:
                yield top
                for child in top.children:
                    yield child

        for node in _all_nodes():
            label_text = str(node.label).strip()
            if label_text != "":
                continue

            if node is focused_node:
                node.set_label(Text(" ", style="black on #00aa00"))
            else:
                node.set_label("")

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "builder_name_input":
            return
        if self.query_one("#ms_content_switcher").current != "process_builder":
            return
        if self.query_one("#builder_content_switcher", ContentSwitcher).current != "builder_editor":
            return

        builder_tree = self.query_one("#builder_tree", Tree)
        node = builder_tree.cursor_node
        if node is None:
            return
        node.set_label(event.value)
        builder_tree.set_class(event.value.strip() == "", "blank-focused")
        self._refresh_builder_blank_focus_visual(node)

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        if self.query_one("#ms_content_switcher").current == "process_builder" and self.query_one("#builder_content_switcher", ContentSwitcher).current == "builder_editor":
            self._sync_builder_input()
            self.query_one("#builder_name_input", Input).focus()
    
    def action_select_right(self) -> None:
        if self.builder_tags_open:
            return
        if self.query_one("#ms_content_switcher").current != "process_cont":
            return

        succ_c = "[COMPLETE]    "
        succ_nc = "  [COMPLETE]    "
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

        #Applies to nodes with out COMPLETE and nodes with no children
        if "[COMPLETE]" not in node_buff and len(node.children) == 0:
            set_S(str(node_buff), path, file)
            #Checks if node is a [>]
            if node.parent.parent:
                node.label = succ_c + str(node_buff)
            else:
                node.label = succ_nc + str(node_buff)
                
            self.log(node.label)
            node.label.stylize("green")
            # node.set_label(node.label)

        #Auto collapeses parent when children are COMPLETEful
        if node.parent:
            all_complete = all("[COMPLETE]" in str(child.label) for child in node.parent.children)
            if all_complete:
                node.parent.collapse()
                parent_label = str(node.parent.label).replace(succ_c, "").strip()
                node.parent.set_label(Text(succ_c + parent_label, style="green"))
                set_S(str(parent_label), path, file)
                tree.move_cursor(node.parent)

        #Auto collapeses root when everything is complete
        if node.parent and node.parent.parent:
            parents_all_complete = all("[COMPLETE]" in str(child.label) for child in node.parent.parent.children)
            if parents_all_complete:
                node.parent.parent.collapse()
                parents_parent_label = str(node.parent.parent.label).replace(succ_c, "").strip()
                node.parent.parent.set_label(Text(succ_c + parents_parent_label, style="green"))
                set_S(str(parents_parent_label), path, file)
        
    def action_select_left(self) -> None:
        if self.builder_tags_open:
            return
        if self.query_one("#ms_content_switcher").current != "process_cont":
            return

        succ_c = "[COMPLETE]    "
        succ_nc = "  [COMPLETE ]    "
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

        #Applies to nodes with COMPLETE and nodes with no children
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

        #Applies to nodes with COMPLETE and nodes with children
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
        self.tab_selected = ""
        self.builder_mode = ""
        self.builder_save_dir = None
        self.builder_shift_armed = False
        self.builder_updating_tags = False
        self.builder_tags_open = False
        self.builder_staged_tags: set[str] = set()
        self.root = Path.home()
        self.select_data = Select.NULL

        self.title = "WELCOME TO VERITRAK"
        self.sub_title = "Powered by Westbound Designs"

        select_cont = self.query_one("#select_cont", Container)
        select_cont.border_title = "SELECT PROCESSES"
        
        process_cont = self.query_one("#process_cont", Container)
        process_cont.border_title = "PROCESS TREE"

        process_builder = self.query_one("#process_builder")
        process_builder.border_title = "PROCESS BUILDER"

        tags_cont = self.query_one("#builder_tags_cont", Container)
        tags_cont.border_title = "PROCESS TAGS"
        tags_cont.display = False

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
            new_root_label = "[COMPLETE]    " + str(tree.root.label).replace("[S]|","")
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
                    #Populates data that is COMPLETEful and is a child
                    current_node.allow_expand = True
                    node_buffer = Text("[COMPLETE]    " + x.replace("[>]|","").replace("[S]|",""))
                    node_buffer.stylize("green")
                    current_node.add_leaf(node_buffer)
                    # current_node.label.stylize("green")
                else:
                    #Populates data that is not complete and is a child
                    current_node.allow_expand = True
                    current_node.add_leaf(x.replace("[>]|",""))
                    current_node.expand_all()
                
            else:
                #Populates items with children
                if "[S]" in x and has_child(data,x):
                    current_node = tree.root.add_leaf("[COMPLETE]    " + x.replace("[S]|",""))
                    current_node.label.stylize("green")

                #Populates items without children
                elif "[S]" in x and not has_child(data,x):
                    current_node = tree.root.add_leaf("  [COMPLETE]    " + x.replace("[S]|",""))
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