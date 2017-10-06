import wxversion
wxversion.select("3.0")
import wx

import Images
import AccipyterConstants
import SuperListCtrl
import Torrent
import TorrentReader
import TorrentFileSelectWindow

class FileDropTarget(wx.FileDropTarget):
    def __init__(self, target):
        super(FileDropTarget, self).__init__()
        self.target = target

    def OnDropFiles(self, x, y, filenames):
        for fname in filenames:
            print fname

class PageOne(wx.Panel):
    def __init__(self, parent):
        wx.Panel.__init__(self, parent)
        t = wx.StaticText(self, -1, "This is a PageOne object", (20,20))

class AccipyterGUI(wx.Frame):

    def __init__(self):
        frame_style = wx.MAXIMIZE_BOX | wx.MINIMIZE_BOX | wx.RESIZE_BORDER | wx.SYSTEM_MENU | wx.CAPTION | wx.CLOSE_BOX
        super(AccipyterGUI, self).__init__(None, style=frame_style, title='Accipyter', size=(800,600))

        self.init_ui()
        self.Show()

    def init_ui(self):
        icon_bundle = wx.IconBundle()
        icon_bundle.AddIconFromFile(r'../resources/icon_512.ico', wx.BITMAP_TYPE_ANY)
        self.SetIcons(icon_bundle)

        self.main_panel = wx.Panel(parent=self)
        dropTarget = FileDropTarget(self.main_panel)
        self.main_panel.SetDropTarget(dropTarget)
        self.main_vsizer = wx.BoxSizer(wx.VERTICAL)

        toolbar = self.CreateToolBar()
        add_tool = toolbar.AddLabelTool(id=wx.ID_ANY, label='shit',bitmap=Images.plus_32.GetBitmap(), kind=wx.ITEM_DROPDOWN)
        add_torrent_menu = wx.Menu()
        add_torrent_menu.Append(text='from .torrent',id=AccipyterConstants.ADD_TORRENT_FROM_FILE_MENU_ID)
        add_torrent_menu.Append(text='from magnet link', id=AccipyterConstants.ADD_TORRENT_FROM_MAGNET_MENU_ID)
        add_torrent_menu.Bind(event=wx.EVT_MENU, handler=self.add_torrent_from_file, id=AccipyterConstants.ADD_TORRENT_FROM_FILE_MENU_ID)
        add_tool.SetDropdownMenu(add_torrent_menu)
        toolbar.AddTool(id=wx.ID_ANY, bitmap=Images.minus_32.GetBitmap())
        toolbar.AddTool(id=wx.ID_ANY, bitmap=Images.play_32.GetBitmap())
        toolbar.AddTool(id=wx.ID_ANY, bitmap=Images.pause_32.GetBitmap())
        toolbar.AddTool(id=wx.ID_ANY, bitmap=Images.gear_32.GetBitmap())
        toolbar.Realize()

        columns = ['Name', 'Size', 'Downloaded', 'Progress', 'Status', 'Time Remaining']
        self.sources_listctrl = SuperListCtrl.SuperListCtrl(parent=self.main_panel, columns=columns)

        details_notebook = wx.Notebook(parent=self.main_panel)
        pone = PageOne(details_notebook)
        details_notebook.InsertPage(page=pone,text='Files',n=0)

        self.main_vsizer.Add(self.sources_listctrl, flag=wx.EXPAND, proportion=1)
        self.main_vsizer.Add(details_notebook, flag=wx.EXPAND, proportion=1)

        self.main_panel.SetSizer(self.main_vsizer)
        self.main_vsizer.Fit(self)
        self.SetSize((800,600))

    def add_torrent_from_file(self, event):
        openFileDialog = wx.FileDialog(self, "Open torrent file", "", "", "Torrent files (*.torrent)|*.torrent", wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        if openFileDialog.ShowModal() == wx.ID_CANCEL:
            return

        torrent = Torrent.Torrent(openFileDialog.GetPath(),r'C:\Users\Andrew\Downloads')
        file_select_dialog = TorrentFileSelectWindow.TorrentFileSelectWindow(self, torrent)
        if file_select_dialog.ShowModal() == wx.ID_CANCEL:
            return

        size = 0
        selected_files = file_select_dialog.selected_files
        for file in selected_files:
            size += file['length']
        torrent_name = openFileDialog.GetPath().split('\\')[-1].replace('.torrent','')
        columns = [torrent_name, size, '-', '-', '-', '-']
        self.sources_listctrl.add_row(columns)

def main():
    app = wx.App()
    AccipyterGUI()
    app.MainLoop()


if __name__ == '__main__':
    main()
