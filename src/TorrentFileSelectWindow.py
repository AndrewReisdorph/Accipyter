import wx

import SuperListCtrl


class TorrentFileSelectWindow(wx.Dialog):

    def __init__(self, parent, torrent_obj):
        super(TorrentFileSelectWindow, self).__init__(parent=parent, style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.parent = parent
        self.torrent_obj = torrent_obj
        self.selected_files = []

        self.files_listctrl = None

        self.init_ui()

        self.add_files()

    def init_ui(self):
        main_panel = wx.Panel(parent=self)
        main_vsizer = wx.BoxSizer(wx.VERTICAL)
        buttons_hsizer = wx.BoxSizer(wx.HORIZONTAL)

        columns = ['Name', 'Size']
        self.files_listctrl = SuperListCtrl.SuperListCtrl(parent=main_panel, columns=columns, check_box=True)
        ok_button = wx.Button(parent=main_panel, label='OK')
        ok_button.Bind(event=wx.EVT_BUTTON, handler=self.on_button_ok)
        cancel_button = wx.Button(parent=main_panel, label='Cancel')
        cancel_button.Bind(event=wx.EVT_BUTTON, handler=self.on_button_cancel)

        buttons_hsizer.Add(ok_button)
        buttons_hsizer.Add(cancel_button)

        main_vsizer.Add(self.files_listctrl, flag=wx.EXPAND, proportion=1)
        main_vsizer.Add(buttons_hsizer)

        main_panel.SetSizer(main_vsizer)
        main_vsizer.Fit(self)
        self.SetSize((400, 300))

    def on_button_ok(self, event):
        for idx, file in enumerate(self.torrent_obj.files):
            if self.files_listctrl.IsChecked(idx):
                self.selected_files.append(file)

        self.EndModal(wx.ID_OK)

    def on_button_cancel(self, event):
        self.EndModal(wx.ID_CANCEL)

    def add_files(self):
        files = self.torrent_obj.files
        for idx, file_dict in enumerate(files):
            self.files_listctrl.add_row([file_dict['path'], file_dict['length']])
            self.files_listctrl.CheckItem(idx, True)
